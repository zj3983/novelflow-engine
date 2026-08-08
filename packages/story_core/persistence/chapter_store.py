"""Filesystem paths and raw chapter artifact access.

After the Markdown-canonical migration the chapter JSON only stores
metadata (``body_path`` + ``body_sha256``) and the prose lives in
the sibling ``chapters/NNNN-{title}.md`` file. This module owns the
metadata read / write path, the Markdown hydration, and the legacy
JSON-only fallback for chapters written before the migration.

The body itself is *not* duplicated in the metadata: keeping a
single source of truth keeps diffs and edits friendly and lets the
workbench surface a hash mismatch if the user (or another tool)
edits the Markdown file outside the pipeline.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


class ChapterStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.story_system_directory = self.root / ".story-system"
        self.chapters_directory = self.story_system_directory / "chapters"
        self.reviews_directory = self.story_system_directory / "reviews"
        self.markdown_directory = self.root / "chapters"

    @staticmethod
    def markdown_name(chapter_number: int, title: str) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|]+', "", str(title or "")).strip()
        suffix = f"-{cleaned}" if cleaned else ""
        return f"{chapter_number:04d}{suffix}.md"

    def paths(self, chapter_number: int, title: str) -> dict[str, Path]:
        return {
            "json": self.chapters_directory / f"{chapter_number:04d}.json",
            "review": self.reviews_directory / f"{chapter_number:04d}.json",
            "markdown": self.markdown_directory / self.markdown_name(chapter_number, title),
        }

    def remove_markdowns(self, chapter_number: int) -> None:
        if not self.markdown_directory.exists():
            return
        for path in self.markdown_directory.glob(f"{chapter_number:04d}*.md"):
            path.unlink()

    def chapter_numbers(self) -> list[int]:
        if not self.chapters_directory.exists():
            return []
        numbers: list[int] = []
        for path in self.chapters_directory.glob("*.json"):
            try:
                numbers.append(int(path.stem))
            except ValueError:
                continue
        return sorted(set(numbers))

    def has_chapters(self) -> bool:
        return bool(self.chapter_numbers())

    def read_chapter(
        self,
        chapter_number: int,
        default: Any = None,
        *,
        include_body: bool = True,
    ) -> Any:
        """Read a chapter's metadata.

        ``include_body`` defaults to ``True``: the returned dict
        contains a hydrated ``body`` field. Pass ``False`` to keep
        the response metadata-only — useful for list endpoints
        that touch every chapter.
        """
        path = self.chapters_directory / f"{chapter_number:04d}.json"
        if not path.exists():
            return default
        chapter = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(chapter, dict):
            return chapter
        if include_body and "body" not in chapter:
            hydrated = self._hydrate_body_from_markdown(chapter)
            if hydrated is not None:
                chapter = {**chapter, "body": hydrated}
        return chapter

    def read_chapter_body(self, chapter_number: int) -> str | None:
        """Return the chapter body, hydrated from Markdown when possible.

        Falls back to the legacy ``body`` field when no Markdown
        file is referenced; returns ``None`` when the chapter does
        not exist.
        """
        chapter = self.read_chapter(chapter_number, default=None, include_body=True)
        if isinstance(chapter, dict):
            body = chapter.get("body")
            return body if isinstance(body, str) else None
        return None

    def detect_markdown_mismatch(self, chapter_number: int) -> dict[str, Any] | None:
        """Compare the recorded SHA-256 to the actual Markdown content.

        Returns a small dict describing the mismatch, or ``None``
        when the hashes agree (or the chapter is legacy and the
        comparison is not applicable).
        """
        path = self.chapters_directory / f"{chapter_number:04d}.json"
        if not path.exists():
            return None
        chapter = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(chapter, dict):
            return None
        body_path_value = chapter.get("body_path")
        expected = chapter.get("body_sha256")
        if not body_path_value or not expected:
            return None
        markdown_path = self.root / str(body_path_value)
        if not markdown_path.is_file():
            return {
                "expected_sha256": expected,
                "actual_sha256": None,
                "body_path": body_path_value,
                "reason": "markdown_missing",
            }
        actual = hashlib.sha256(markdown_path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        if actual == expected:
            return None
        return {
            "expected_sha256": expected,
            "actual_sha256": actual,
            "body_path": body_path_value,
            "reason": "markdown_modified",
        }

    def _hydrate_body_from_markdown(self, chapter: dict[str, Any]) -> str | None:
        body_path_value = chapter.get("body_path")
        expected_sha = chapter.get("body_sha256")
        if not body_path_value or not expected_sha:
            return None
        markdown_path = self.root / str(body_path_value)
        if not markdown_path.is_file():
            return None
        text = markdown_path.read_text(encoding="utf-8")
        actual_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if actual_sha != expected_sha:
            # Hash mismatch: prefer the on-disk content (it might
            # have been intentionally edited) but signal the
            # mismatch via ``detect_markdown_mismatch`` for callers
            # that need to surface it.
            return text
        return text

    def read_review(self, chapter_number: int, default: Any = None) -> Any:
        path = self.reviews_directory / f"{chapter_number:04d}.json"
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def read_records(self, *, ignore_errors: bool = False) -> list[tuple[int, dict[str, Any]]]:
        records: list[tuple[int, dict[str, Any]]] = []
        for number in self.chapter_numbers():
            try:
                chapter = self.read_chapter(number, {})
            except (OSError, ValueError, json.JSONDecodeError):
                if not ignore_errors:
                    raise
                chapter = {}
            records.append((number, chapter if isinstance(chapter, dict) else {}))
        return records


__all__ = ["ChapterStore"]
