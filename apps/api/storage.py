from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

from packages.story_core.engine import ChapterBundle, StoryEngine
from packages.story_core.models import NovelOutline, NovelStatus, StoryState, WorldBible


# SQLite database path: next to this file, or override via env var
_DB_PATH = os.environ.get(
    "STORY_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stories.db"),
)


def _get_db_path() -> str:
    return _DB_PATH


def _ensure_db_dir(db_path: str) -> None:
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _init_db(db_path: str) -> sqlite3.Connection:
    _ensure_db_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stories (
            story_id TEXT PRIMARY KEY,
            story_state TEXT NOT NULL,
            initial_state TEXT NOT NULL,
            parent_story_id TEXT,
            branched_from_chapter INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chapter_bundles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            story_id TEXT NOT NULL,
            chapter_number INTEGER NOT NULL,
            bundle_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (story_id) REFERENCES stories(story_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_chapter_bundles_story
            ON chapter_bundles(story_id, chapter_number);
        CREATE INDEX IF NOT EXISTS idx_stories_parent
            ON stories(parent_story_id);
        CREATE TABLE IF NOT EXISTS novel_outlines (
            story_id TEXT PRIMARY KEY,
            outline_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (story_id) REFERENCES stories(story_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS world_bibles (
            story_id TEXT PRIMARY KEY,
            world_bible_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (story_id) REFERENCES stories(story_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS novel_statuses (
            story_id TEXT PRIMARY KEY,
            status_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (story_id) REFERENCES stories(story_id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    return conn


# Thread-local storage for DB connections
_local = threading.local()


def _get_conn(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or _get_db_path()
    if not hasattr(_local, "connections"):
        _local.connections = {}
    if path not in _local.connections:
        conn = _init_db(path)
        _local.connections[path] = conn
    return _local.connections[path]


@dataclass
class StoryRecord:
    story: StoryState
    initial_story: StoryState
    history: list[ChapterBundle] = field(default_factory=list)
    parent_story_id: str | None = None
    branched_from_chapter: int | None = None


class SQLiteStoryStore:
    """SQLite-backed persistent story store.

    Replaces InMemoryStoryStore. Keeps the same public API so
    API routes and tests require no changes.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _get_db_path()

    def _conn(self) -> sqlite3.Connection:
        return _get_conn(self._db_path)

    # ── helpers ──────────────────────────────────────────────

    def _serialize_story(self, story: StoryState) -> str:
        return story.model_dump_json()

    def _deserialize_story(self, json_str: str) -> StoryState:
        return StoryState.model_validate_json(json_str)

    def _serialize_bundle(self, bundle: ChapterBundle) -> str:
        return bundle.model_dump_json()

    def _deserialize_bundle(self, json_str: str) -> ChapterBundle:
        return ChapterBundle.model_validate_json(json_str)

    def _load_history(self, conn: sqlite3.Connection, story_id: str) -> list[ChapterBundle]:
        cursor = conn.execute(
            "SELECT bundle_json FROM chapter_bundles WHERE story_id = ? ORDER BY chapter_number",
            (story_id,),
        )
        return [self._deserialize_bundle(row[0]) for row in cursor.fetchall()]

    def _save_record(self, conn: sqlite3.Connection, record: StoryRecord) -> None:
        # Use UPDATE to avoid ON DELETE CASCADE wiping chapter_bundles.
        # INSERT only if the row doesn't exist yet (e.g. after create).
        conn.execute(
            """
            UPDATE stories
            SET story_state = ?, initial_state = ?, parent_story_id = ?,
                branched_from_chapter = ?, updated_at = CURRENT_TIMESTAMP
            WHERE story_id = ?
            """,
            (
                self._serialize_story(record.story),
                self._serialize_story(record.initial_story),
                record.parent_story_id,
                record.branched_from_chapter,
                record.story.story_id,
            ),
        )
        if conn.total_changes == 0:
            # Row didn't exist yet — insert it
            conn.execute(
                """
                INSERT INTO stories
                    (story_id, story_state, initial_state, parent_story_id,
                     branched_from_chapter, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    record.story.story_id,
                    self._serialize_story(record.story),
                    self._serialize_story(record.initial_story),
                    record.parent_story_id,
                    record.branched_from_chapter,
                ),
            )
        conn.commit()

    def _save_bundle(self, conn: sqlite3.Connection, story_id: str, bundle: ChapterBundle) -> None:
        conn.execute(
            """
            INSERT INTO chapter_bundles (story_id, chapter_number, bundle_json)
            VALUES (?, ?, ?)
            """,
            (story_id, bundle.chapter_number, self._serialize_bundle(bundle)),
        )
        conn.commit()

    # ── public API ───────────────────────────────────────────

    def create(self, story: StoryState) -> StoryRecord:
        conn = self._conn()
        record = StoryRecord(
            story=story,
            initial_story=story.model_copy(deep=True),
        )
        self._save_record(conn, record)
        return record

    def get(self, story_id: str) -> StoryRecord | None:
        conn = self._conn()
        cursor = conn.execute(
            "SELECT story_state, initial_state, parent_story_id, branched_from_chapter FROM stories WHERE story_id = ?",
            (story_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return StoryRecord(
            story=self._deserialize_story(row[0]),
            initial_story=self._deserialize_story(row[1]),
            history=self._load_history(conn, story_id),
            parent_story_id=row[2],
            branched_from_chapter=row[3],
        )

    def list(self) -> list[StoryRecord]:
        conn = self._conn()
        cursor = conn.execute(
            "SELECT story_id FROM stories ORDER BY created_at"
        )
        records: list[StoryRecord] = []
        for (story_id,) in cursor.fetchall():
            record = self.get(story_id)
            if record is not None:
                records.append(record)
        return records

    def rename(self, story_id: str, new_story_id: str) -> StoryRecord:
        conn = self._conn()
        record = self.get(story_id)
        if record is None:
            raise KeyError(story_id)

        # Check new ID doesn't exist
        cursor = conn.execute("SELECT 1 FROM stories WHERE story_id = ?", (new_story_id,))
        if cursor.fetchone():
            raise ValueError("story_exists")

        # Update parent references in children
        conn.execute(
            "UPDATE stories SET parent_story_id = ? WHERE parent_story_id = ?",
            (new_story_id, story_id),
        )

        # Update story_id in all fields
        record.story.story_id = new_story_id
        record.initial_story.story_id = new_story_id
        for bundle in record.history:
            bundle.updated_story.story_id = new_story_id
        record.parent_story_id = new_story_id if record.parent_story_id == story_id else record.parent_story_id

        # Insert with new ID
        self._save_record(conn, record)

        # Delete old
        conn.execute("DELETE FROM stories WHERE story_id = ?", (story_id,))
        conn.execute("DELETE FROM chapter_bundles WHERE story_id = ?", (story_id,))
        conn.commit()

        return record

    def delete(self, story_id: str) -> StoryRecord:
        conn = self._conn()
        record = self.get(story_id)
        if record is None:
            raise KeyError(story_id)
        if record.parent_story_id is None:
            raise ValueError("cannot_delete_root")

        # Check for children
        cursor = conn.execute(
            "SELECT 1 FROM stories WHERE parent_story_id = ? LIMIT 1",
            (story_id,),
        )
        if cursor.fetchone():
            raise ValueError("story_has_children")

        conn.execute("DELETE FROM stories WHERE story_id = ?", (story_id,))
        conn.execute("DELETE FROM chapter_bundles WHERE story_id = ?", (story_id,))
        conn.commit()
        return record

    def generate_next(self, story_id: str, engine: StoryEngine) -> ChapterBundle:
        conn = self._conn()
        record = self.get(story_id)
        if record is None:
            raise KeyError(story_id)

        bundle = engine.generate_next_chapter(record.story)

        # Update story state
        record.story = bundle.updated_story
        record.history.append(bundle)

        # Persist
        self._save_record(conn, record)
        self._save_bundle(conn, story_id, bundle)

        return bundle

    def rollback_last(self, story_id: str) -> StoryRecord:
        conn = self._conn()
        record = self.get(story_id)
        if record is None:
            raise KeyError(story_id)

        if record.history:
            # Delete last bundle from DB
            last_chapter = record.history[-1].chapter_number
            conn.execute(
                "DELETE FROM chapter_bundles WHERE story_id = ? AND chapter_number = ?",
                (story_id, last_chapter),
            )

            record.history.pop()
            if record.history:
                record.story = record.history[-1].updated_story.model_copy(deep=True)
            else:
                record.story = record.initial_story.model_copy(deep=True)

            self._save_record(conn, record)
            conn.commit()

        return record

    def branch_from(self, story_id: str, new_story_id: str, from_chapter: int) -> StoryRecord:
        conn = self._conn()

        # Check new ID doesn't exist
        cursor = conn.execute("SELECT 1 FROM stories WHERE story_id = ?", (new_story_id,))
        if cursor.fetchone():
            raise ValueError("story_exists")

        record = self.get(story_id)
        if record is None:
            raise KeyError(story_id)

        if from_chapter < 0 or from_chapter > len(record.history):
            raise IndexError(from_chapter)

        if from_chapter == 0:
            branch_story = record.initial_story.model_copy(deep=True)
            branch_history: list[ChapterBundle] = []
        else:
            branch_history = [bundle.model_copy(deep=True) for bundle in record.history[:from_chapter]]
            branch_story = branch_history[-1].updated_story.model_copy(deep=True)

        branch_story.story_id = new_story_id
        for bundle in branch_history:
            bundle.updated_story.story_id = new_story_id

        branch_record = StoryRecord(
            story=branch_story,
            initial_story=record.initial_story.model_copy(deep=True),
            history=branch_history,
            parent_story_id=story_id,
            branched_from_chapter=from_chapter,
        )
        branch_record.initial_story.story_id = new_story_id

        # Persist branch
        self._save_record(conn, branch_record)
        for bundle in branch_history:
            self._save_bundle(conn, new_story_id, bundle)

        return branch_record

    def freeze_character(self, story_id: str, character_name: str) -> StoryRecord:
        conn = self._conn()
        record = self.get(story_id)
        if record is None:
            raise KeyError(story_id)

        for character in record.story.characters:
            if character.name == character_name:
                character.frozen = True
                character.lifecycle_state = "frozen"
                self._save_record(conn, record)
                return record

        raise KeyError(character_name)


    # ── outline persistence ──────────────────────────────────

    def save_outline(self, story_id: str, outline: NovelOutline) -> None:
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO novel_outlines (story_id, outline_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(story_id) DO UPDATE SET
                outline_json = excluded.outline_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (story_id, outline.model_dump_json()),
        )
        conn.commit()

    def get_outline(self, story_id: str) -> NovelOutline | None:
        conn = self._conn()
        cursor = conn.execute(
            "SELECT outline_json FROM novel_outlines WHERE story_id = ?",
            (story_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return NovelOutline.model_validate_json(row[0])

    def delete_outline(self, story_id: str) -> bool:
        conn = self._conn()
        cursor = conn.execute("DELETE FROM novel_outlines WHERE story_id = ?", (story_id,))
        conn.commit()
        return cursor.rowcount > 0

    # ── world bible persistence ──────────────────────────────

    def save_world_bible(self, story_id: str, world_bible: WorldBible) -> None:
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO world_bibles (story_id, world_bible_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(story_id) DO UPDATE SET
                world_bible_json = excluded.world_bible_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (story_id, world_bible.model_dump_json()),
        )
        conn.commit()

    def get_world_bible(self, story_id: str) -> WorldBible | None:
        conn = self._conn()
        cursor = conn.execute(
            "SELECT world_bible_json FROM world_bibles WHERE story_id = ?",
            (story_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return WorldBible.model_validate_json(row[0])

    def delete_world_bible(self, story_id: str) -> bool:
        conn = self._conn()
        cursor = conn.execute("DELETE FROM world_bibles WHERE story_id = ?", (story_id,))
        conn.commit()
        return cursor.rowcount > 0

    # ── novel status persistence ─────────────────────────────

    def save_novel_status(self, story_id: str, novel_status: NovelStatus) -> None:
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO novel_statuses (story_id, status_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(story_id) DO UPDATE SET
                status_json = excluded.status_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (story_id, novel_status.model_dump_json()),
        )
        conn.commit()

    def get_novel_status(self, story_id: str) -> NovelStatus | None:
        conn = self._conn()
        cursor = conn.execute(
            "SELECT status_json FROM novel_statuses WHERE story_id = ?",
            (story_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return NovelStatus.model_validate_json(row[0])

    def update_novel_status_after_chapter(self, story_id: str, chapter_number: int, word_count: int) -> NovelStatus | None:
        """Auto-update novel status after a chapter is generated."""
        conn = self._conn()
        status = self.get_novel_status(story_id)
        if status is None:
            return None
        status.total_chapters_written = chapter_number
        status.last_written_chapter = chapter_number
        status.total_word_count += word_count
        status.updated_at = ""
        self.save_novel_status(story_id, status)
        return status


# Backward-compatible alias: existing code imports InMemoryStoryStore
# and expects the same interface. SQLiteStoryStore is a drop-in replacement.
InMemoryStoryStore = SQLiteStoryStore
