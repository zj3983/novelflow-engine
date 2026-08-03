"""Filesystem paths and raw chapter artifact access."""

from __future__ import annotations

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

    def read_chapter(self, chapter_number: int, default: Any = None) -> Any:
        path = self.chapters_directory / f"{chapter_number:04d}.json"
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8-sig"))

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
