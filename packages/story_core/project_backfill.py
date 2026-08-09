"""Read-only evidence extraction for long-running file projects."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from packages.story_core.file_project_store import FileProjectStore


@dataclass(frozen=True)
class ChapterEvidence:
    chapter_number: int
    title: str
    body_hash: str
    body: str
    summary: str
    timeline: tuple[Mapping[str, Any], ...]
    character_updates: tuple[Mapping[str, Any], ...]
    foreshadowing: tuple[Mapping[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "chapter_number": self.chapter_number,
            "title": self.title,
            "body_hash": self.body_hash,
            "body": self.body,
            "summary": self.summary,
            "timeline": _thaw(self.timeline),
            "character_updates": _thaw(self.character_updates),
            "foreshadowing": _thaw(self.foreshadowing),
        }


@dataclass(frozen=True)
class ProjectEvidenceIndex:
    project_root: Path
    chapters: tuple[ChapterEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_root": str(self.project_root),
            "chapters": [chapter.to_dict() for chapter in self.chapters],
        }


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_thaw(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


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


def _frozen_entries(values: tuple[dict[str, Any], ...]) -> tuple[Mapping[str, Any], ...]:
    return tuple(_freeze(item) for item in values)


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
    store: FileProjectStore,
    chapter_number: int,
    chapter: Mapping[str, Any],
) -> Path | None:
    body_path = chapter.get("body_path")
    if isinstance(body_path, str) and body_path.strip():
        path = project_root / body_path
        if path.is_file():
            return path

    title = str(chapter.get("chapter_title") or chapter.get("title") or "").strip()
    resolved = store.chapter_store.paths(chapter_number, title)["markdown"]
    if resolved.is_file():
        return resolved

    matches = sorted(store.chapter_store.markdown_directory.glob(f"{chapter_number:04d}*.md"))
    return matches[0] if len(matches) == 1 else None


def _body_hash(
    project_root: Path,
    store: FileProjectStore,
    chapter_number: int,
    chapter: Mapping[str, Any],
) -> str:
    markdown_path = _canonical_markdown_path(
        project_root,
        store,
        chapter_number,
        chapter,
    )
    if markdown_path is not None:
        return sha256(markdown_path.read_bytes()).hexdigest()
    body = chapter.get("body")
    return sha256(body.encode("utf-8")).hexdigest() if isinstance(body, str) else ""


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
        body_hash = _body_hash(root, store, chapter_number, chapter)
        if body_hash:
            hashes[chapter_number] = body_hash
    return hashes


def _character_snapshot(chapter: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    updated_story = _mapping(chapter.get("updated_story"))
    characters = _dict_entries(updated_story.get("characters"))
    return {
        str(character.get("name") or "").strip(): character
        for character in characters
        if str(character.get("name") or "").strip()
    }


def _actual_character_evidence(
    chapter: Mapping[str, Any],
    previous_snapshot: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    chapter_summary = _mapping(chapter.get("chapter_summary"))
    state_delta = _mapping(chapter.get("state_delta"))
    explicit = _first_entries(
        chapter.get("character_updates"),
        chapter_summary.get("character_updates"),
        state_delta.get("character_updates"),
    )

    snapshot = _character_snapshot(chapter)
    changed = tuple(
        {
            "source": "updated_story.characters",
            "name": name,
            "character": character,
        }
        for name, character in snapshot.items()
        if previous_snapshot.get(name) != character
    )

    known_names = sorted(set(snapshot) | set(previous_snapshot))
    facts = chapter_summary.get("facts")
    confirmed_facts: list[dict[str, Any]] = []
    for fact in facts if isinstance(facts, (list, tuple)) else ():
        if not isinstance(fact, str):
            continue
        matched_names = [name for name in known_names if name in fact]
        if matched_names:
            confirmed_facts.append(
                {
                    "source": "chapter_summary.facts",
                    "name": matched_names[0],
                    "names": matched_names,
                    "fact": fact,
                }
            )
    return (*explicit, *changed, *confirmed_facts)


def _chapter_evidence(
    store: FileProjectStore,
    chapter_number: int,
    hashes: Mapping[int, str],
    previous_character_snapshot: Mapping[str, Mapping[str, Any]],
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

    markdown_path = _canonical_markdown_path(store.root, store, chapter_number, chapter)
    body = (
        markdown_path.read_text(encoding="utf-8-sig")
        if markdown_path is not None
        else str(chapter.get("body") or "")
    )

    return ChapterEvidence(
        chapter_number=chapter_number,
        title=str(chapter.get("chapter_title") or chapter.get("title") or "").strip(),
        body_hash=hashes.get(chapter_number, ""),
        body=body,
        summary=_summary(chapter),
        timeline=_frozen_entries(timeline),
        character_updates=_frozen_entries(
            _actual_character_evidence(chapter, previous_character_snapshot)
        ),
        foreshadowing=_frozen_entries(
            _first_entries(
                chapter.get("foreshadowing"),
                chapter.get("foreshadowing_updates"),
                chapter_summary.get("foreshadowing"),
                state_delta.get("foreshadowing"),
            )
        ),
    )


def build_evidence_index(project_root: Path) -> ProjectEvidenceIndex:
    root = Path(project_root).resolve()
    store = FileProjectStore(root)
    hashes = chapter_hashes(root)
    chapters: list[ChapterEvidence] = []
    previous_character_snapshot: dict[str, dict[str, Any]] = {}
    for chapter_number in store.chapter_numbers():
        chapter = store.chapter_store.read_chapter(chapter_number, default={})
        chapter_mapping = chapter if isinstance(chapter, Mapping) else {}
        chapters.append(
            _chapter_evidence(
                store,
                chapter_number,
                hashes,
                previous_character_snapshot,
            )
        )
        snapshot = _character_snapshot(chapter_mapping)
        if snapshot:
            previous_character_snapshot = snapshot
    return ProjectEvidenceIndex(project_root=root, chapters=tuple(chapters))


__all__ = [
    "ChapterEvidence",
    "ProjectEvidenceIndex",
    "build_evidence_index",
    "chapter_hashes",
]
