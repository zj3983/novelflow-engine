"""Read-only evidence extraction for long-running file projects."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from packages.story_core.file_project_store import FileProjectStore


@dataclass(frozen=True)
class ChapterEvidence:
    chapter_number: int
    title: str
    body_hash: str
    body: str
    summary: str
    timeline: tuple[dict[str, Any], ...]
    character_updates: tuple[dict[str, Any], ...]
    foreshadowing: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ProjectEvidenceIndex:
    project_root: Path
    chapters: tuple[ChapterEvidence, ...]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _dict_entries(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _first_entries(*values: Any) -> tuple[dict[str, Any], ...]:
    for value in values:
        entries = _dict_entries(value)
        if entries:
            return entries
    return ()


def _chapter_timeline(value: Any, chapter_number: int) -> tuple[dict[str, Any], ...]:
    entries = _dict_entries(value)
    scoped = tuple(
        entry
        for entry in entries
        if entry.get("chapter_number") in (None, chapter_number, str(chapter_number))
    )
    return scoped


def _summary(chapter: Mapping[str, Any]) -> str:
    chapter_summary = chapter.get("chapter_summary")
    if isinstance(chapter_summary, str):
        return chapter_summary.strip()
    summary = _mapping(chapter_summary).get("summary") or chapter.get("summary")
    return str(summary or "").strip()


def _canonical_markdown_path(
    project_root: Path,
    chapter: Mapping[str, Any],
) -> Path | None:
    body_path = chapter.get("body_path")
    if not isinstance(body_path, str) or not body_path.strip():
        return None
    path = project_root / body_path
    return path if path.is_file() else None


def chapter_hashes(project_root: Path) -> dict[int, str]:
    """Return SHA-256 hashes of canonical Markdown chapter bytes."""

    root = Path(project_root).resolve()
    store = FileProjectStore(root)
    hashes: dict[int, str] = {}
    for chapter_number in store.chapter_numbers():
        chapter = store.chapter_store.read_chapter(
            chapter_number,
            default={},
            include_body=False,
        )
        if not isinstance(chapter, Mapping):
            continue
        markdown_path = _canonical_markdown_path(root, chapter)
        if markdown_path is not None:
            hashes[chapter_number] = sha256(markdown_path.read_bytes()).hexdigest()
    return hashes


def _chapter_evidence(
    store: FileProjectStore,
    chapter_number: int,
    hashes: Mapping[int, str],
) -> ChapterEvidence:
    chapter = store.chapter_store.read_chapter(chapter_number, default={})
    if not isinstance(chapter, Mapping):
        chapter = {}
    chapter_summary = _mapping(chapter.get("chapter_summary"))
    state_delta = _mapping(chapter.get("state_delta"))
    updated_story = _mapping(chapter.get("updated_story"))
    timeline = _first_entries(
        chapter.get("timeline"),
        chapter_summary.get("timeline"),
        state_delta.get("timeline"),
    ) or _chapter_timeline(updated_story.get("timeline"), chapter_number)

    return ChapterEvidence(
        chapter_number=chapter_number,
        title=str(chapter.get("chapter_title") or chapter.get("title") or "").strip(),
        body_hash=hashes.get(chapter_number, ""),
        body=str(chapter.get("body") or ""),
        summary=_summary(chapter),
        timeline=timeline,
        character_updates=_first_entries(
            chapter.get("character_updates"),
            chapter_summary.get("character_updates"),
            state_delta.get("character_updates"),
        ),
        foreshadowing=_first_entries(
            chapter.get("foreshadowing"),
            chapter.get("foreshadowing_updates"),
            chapter_summary.get("foreshadowing"),
            state_delta.get("foreshadowing"),
        ),
    )


def build_evidence_index(project_root: Path) -> ProjectEvidenceIndex:
    root = Path(project_root).resolve()
    store = FileProjectStore(root)
    hashes = chapter_hashes(root)
    chapters = tuple(
        _chapter_evidence(store, chapter_number, hashes)
        for chapter_number in store.chapter_numbers()
    )
    return ProjectEvidenceIndex(project_root=root, chapters=chapters)


__all__ = [
    "ChapterEvidence",
    "ProjectEvidenceIndex",
    "build_evidence_index",
    "chapter_hashes",
]
