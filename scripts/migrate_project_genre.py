from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.storage import SQLiteStoryStore


XIANXIA_DEFAULT_TERMS = ("渡劫", "飞升", "长生求道", "灵根")
STALE_GAME_LEDGER_MARKERS = (
    "game_id",
    "player",
    "guild",
    "copper",
    "newbie",
    "service_counter",
    "chaos_seed",
    "交易行",
    "玩家",
    "公会",
    "铜币",
    "掉落",
    "背包",
    "游戏",
)
DEFAULT_TENDENCY_MARKERS = (
    "默认",
    "必须",
    "主线",
    "后续",
    "围绕",
    "重点",
    "方向",
    "突出",
    "体现",
)
NEGATION_MARKERS = ("不要", "不得", "禁止", "避免", "并非", "不是", "没有", "不写")


class GenreMigrationError(RuntimeError):
    def __init__(self, message: str, backup_path: Path) -> None:
        self.backup_path = backup_path
        super().__init__(f"{message}; backup_path={backup_path}")


def _text_quality(text: str) -> int:
    cjk = sum("\u4e00" <= char <= "\u9fff" for char in text)
    controls = sum(ord(char) < 32 and char not in "\n\r\t" for char in text)
    suspicious = sum(0x80 <= ord(char) <= 0xFF for char in text)
    return cjk * 3 - controls * 8 - suspicious


def repair_gbk_mojibake(value: Any) -> Any:
    """Repair reversible text produced by decoding GBK bytes as Latin-1."""
    if isinstance(value, dict):
        return {key: repair_gbk_mojibake(item) for key, item in value.items()}
    if isinstance(value, list):
        return [repair_gbk_mojibake(item) for item in value]
    if not isinstance(value, str):
        return value
    try:
        repaired = value.encode("latin1").decode("gbk")
        reversible = repaired.encode("gbk").decode("latin1") == value
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    if not reversible or _text_quality(repaired) <= _text_quality(value):
        return value
    return repaired


def _chapter_hashes(history: list[Any]) -> dict[int, str]:
    return {
        int(bundle.chapter_number): hashlib.sha256(
            f"{bundle.chapter_title}\0{bundle.body}".encode("utf-8")
        ).hexdigest()
        for bundle in history
    }


def _combined_hash(chapter_hashes: dict[int, str]) -> str:
    payload = json.dumps(chapter_hashes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _backup_database(store: SQLiteStoryStore, backup_dir: Path | None = None) -> Path:
    db_path = Path(store._db_path).resolve()
    target_dir = (backup_dir or db_path.parent / "backups").resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = target_dir / f"stories-before-genre-migration-{timestamp}.db"
    source = store._conn()
    source.commit()
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
    return backup_path


def _restore_database(store: SQLiteStoryStore, backup_path: Path) -> None:
    source = sqlite3.connect(backup_path)
    destination = store._conn()
    try:
        source.backup(destination)
        destination.commit()
    finally:
        source.close()


def _looks_like_unestablished_default(text: str, removable_terms: set[str]) -> bool:
    if any(marker in text for marker in NEGATION_MARKERS):
        return False
    return any(term in text for term in removable_terms) and any(
        marker in text for marker in DEFAULT_TENDENCY_MARKERS
    )


def _prune_default_tendencies(
    value: Any,
    removable_terms: set[str],
    protected_terms: set[str] | None = None,
) -> Any:
    protected_terms = protected_terms or set()
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            is_protected = isinstance(item, str) and any(term in item for term in protected_terms)
            if (
                isinstance(item, str)
                and not is_protected
                and _looks_like_unestablished_default(item, removable_terms)
            ):
                continue
            cleaned[key] = _prune_default_tendencies(item, removable_terms, protected_terms)
        return cleaned
    if isinstance(value, list):
        return [
            _prune_default_tendencies(item, removable_terms, protected_terms)
            for item in value
            if not (
                isinstance(item, str)
                and not any(term in item for term in protected_terms)
                and _looks_like_unestablished_default(item, removable_terms)
            )
        ]
    return value


def _repair_project_configuration(project: Any) -> None:
    for field_name in (
        "world_blueprint",
        "author_constraints",
        "character_profiles",
        "seed_outline",
        "world_summary",
        "current_focus",
    ):
        setattr(project, field_name, repair_gbk_mojibake(getattr(project, field_name)))


def _prune_stale_game_ledger(runtime_ledger: Any, canonical_ledger: Any) -> dict[str, Any]:
    runtime = dict(runtime_ledger) if isinstance(runtime_ledger, dict) else {}
    canonical = canonical_ledger if isinstance(canonical_ledger, dict) else {}
    cleaned: dict[str, Any] = {}
    for key, value in runtime.items():
        if key in canonical:
            cleaned[key] = value
            continue
        payload = json.dumps({key: value}, ensure_ascii=False).lower()
        if value in (None, {}, []) or any(marker in payload for marker in STALE_GAME_LEDGER_MARKERS):
            continue
        cleaned[key] = value
    return cleaned


def _apply_migration(
    *,
    store: SQLiteStoryStore,
    project: Any,
    record: Any,
    target_genre: str,
    repair_mojibake: bool = False,
    backup_path: Path,
) -> dict[str, Any]:
    before_genres = project.world_blueprint.get("genre_plugin_ids", [])
    before_genre = str(before_genres[0]) if before_genres else str(record.story.genre or "")
    before_hashes = _chapter_hashes(record.history)
    before_count = len(record.history)
    established_text = "\n".join(
        f"{bundle.chapter_title}\n{bundle.body}" for bundle in record.history
    )
    established_terms = {term for term in XIANXIA_DEFAULT_TERMS if term in established_text}
    removable_terms = set(XIANXIA_DEFAULT_TERMS) - established_terms

    if repair_mojibake:
        _repair_project_configuration(project)
    project.world_blueprint = dict(project.world_blueprint or {})
    if target_genre == "xuanhuan" and removable_terms:
        project.author_constraints = _prune_default_tendencies(
            project.author_constraints, removable_terms, established_terms
        )
        project.world_blueprint = _prune_default_tendencies(
            project.world_blueprint, removable_terms, established_terms
        )
    project.world_blueprint["genre_plugin_ids"] = [target_genre]
    store.update_project(project)

    synced = store.sync_project_context(project.project_id)
    if synced is None:
        raise RuntimeError(f"failed to synchronize active story: {project.active_story_id}")
    if target_genre == "xuanhuan":
        if removable_terms:
            synced.story.writing_lessons = _prune_default_tendencies(
                synced.story.writing_lessons, removable_terms, established_terms
            )
            synced.story.world_facts = _prune_default_tendencies(
                synced.story.world_facts, removable_terms, established_terms
            )
        canonical_ledger = project.world_blueprint.get("progression_ledger", {})
        synced.story.progression_ledger = _prune_stale_game_ledger(
            synced.story.progression_ledger,
            canonical_ledger,
        )
        store._save_record(store._conn(), synced)

    migrated = store.get(project.active_story_id)
    if migrated is None:
        raise RuntimeError(f"active story disappeared: {project.active_story_id}")
    if migrated.story.genre != target_genre:
        raise RuntimeError(
            f"story genre did not synchronize: {migrated.story.genre!r} != {target_genre!r}"
        )

    after_hashes = _chapter_hashes(migrated.history)
    after_count = len(migrated.history)
    if before_count != after_count or before_hashes != after_hashes:
        raise RuntimeError(f"chapter content changed; restore from backup: {backup_path}")

    return {
        "before_genre": before_genre,
        "target_genre": target_genre,
        "chapter_count": before_count,
        "before_body_sha256": _combined_hash(before_hashes),
        "after_body_sha256": _combined_hash(after_hashes),
        "backup_path": str(backup_path),
    }


def migrate_project_genre(
    *,
    store: SQLiteStoryStore,
    project_id: str,
    target_genre: str,
    repair_mojibake: bool = False,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    project = store.get_project(project_id)
    if project is None:
        raise KeyError(f"project not found: {project_id}")
    if not project.active_story_id:
        raise RuntimeError(f"project has no active story: {project_id}")
    record = store.get(project.active_story_id)
    if record is None:
        raise RuntimeError(f"active story not found: {project.active_story_id}")

    backup_path = _backup_database(store, backup_dir)
    try:
        return _apply_migration(
            store=store,
            project=project,
            record=record,
            target_genre=target_genre,
            repair_mojibake=repair_mojibake,
            backup_path=backup_path,
        )
    except Exception as exc:
        try:
            _restore_database(store, backup_path)
        except Exception as restore_exc:
            raise GenreMigrationError(
                f"migration failed and backup restore also failed: {restore_exc}",
                backup_path,
            ) from exc
        raise GenreMigrationError(
            f"migration failed and database was restored: {exc}",
            backup_path,
        ) from exc


def main(argv: list[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Safely migrate a novel project genre.")
    parser.add_argument("project_id")
    parser.add_argument("--target-genre", required=True)
    parser.add_argument("--repair-gbk-mojibake", action="store_true")
    args = parser.parse_args(argv)

    result = migrate_project_genre(
        store=SQLiteStoryStore(),
        project_id=args.project_id,
        target_genre=args.target_genre,
        repair_mojibake=args.repair_gbk_mojibake,
    )
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
