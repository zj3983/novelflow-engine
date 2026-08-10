"""Director context builder.

The director is the structural agent — it decides *what* should
happen next. The view it gets is therefore structural:
* the current volume and a few nearby chapter outlines,
* the previous chapter's summary and the active continuity
  ledger,
* active plot threads and unresolved foreshadowing,
* concise (identity + role + state) cards for characters that
  are in scope for the target chapter.

The director must *not* see craft-module text (those are the
writer's tools) or retired entities. Concise cards keep the
director's prompt focused on planning rather than prose cues.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .project_reader import ProjectContextReader


def _concise_character_card(card: dict[str, Any]) -> dict[str, Any]:
    return {
        key: card.get(key)
        for key in (
            "id",
            "name",
            "role",
            "location",
            "current_state",
            "lifecycle",
            "summary",
        )
        if key in card
    }


def _build_reader(project: Path, reader: ProjectContextReader | None) -> ProjectContextReader:
    if reader is not None:
        return reader
    return ProjectContextReader(project)


class DirectorContext(BaseModel):
    """The structural view the director sees."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = "director-context/v1"
    chapter_number: int
    volume: dict[str, Any]
    book_outline_summary: str
    nearby_outline: list[dict[str, Any]] = Field(default_factory=list)
    previous_chapter_summary: str = ""
    previous_chapter_tail: str = ""
    continuity_ledger: list[dict[str, Any]] = Field(default_factory=list)
    foreshadowing: list[dict[str, Any]] = Field(default_factory=list)
    character_cards: list[dict[str, Any]] = Field(default_factory=list)
    inventory: list[dict[str, Any]] = Field(default_factory=list)
    active_entity_names: list[str] = Field(default_factory=list)
    rewrite_guidance: str = ""


def build_director_context(
    *,
    project: Path,
    chapter_number: int,
    reader: ProjectContextReader | None = None,
    nearby_window: int = 2,
) -> DirectorContext:
    """Build the director's structural view for ``chapter_number``.

    The director sees the volume summary, a few nearby chapter
    outlines, the previous chapter's summary, the continuity
    ledger, unresolved foreshadowing, and concise character cards
    for the actors that are currently active. It does not see
    craft-module text, retired entities, or the full book
    outline.
    """
    project_root = Path(project).resolve()
    system_root = project_root / ".story-system"
    if not system_root.exists():
        raise ValueError(f"project_layout_missing: {system_root}")

    reader = _build_reader(system_root, reader)

    outline = reader.try_read_json("outline.json", kind="outline") or {}
    volume = reader.try_read_json("volume.json", kind="volume") or {}

    volume_range = volume.get("chapter_range") if isinstance(volume, dict) else None
    nearby: list[dict[str, Any]] = []
    for entry in outline.get("chapters") or []:
        if not isinstance(entry, dict):
            continue
        number = entry.get("number")
        if not isinstance(number, int):
            continue
        if isinstance(volume_range, list) and len(volume_range) == 2:
            if not (volume_range[0] - 1 <= number <= volume_range[1] + 1):
                continue
        if abs(number - chapter_number) > nearby_window:
            continue
        nearby.append(entry)
    nearby.sort(key=lambda item: item.get("number", 0))

    previous_chapter = None
    if chapter_number > 1:
        previous_path = f"chapters/{chapter_number - 1:04d}.json"
        previous_chapter = reader.try_read_json(previous_path, kind="chapter")
    previous_summary = ""
    if isinstance(previous_chapter, dict):
        previous_summary = str(previous_chapter.get("summary") or "")
    previous_tail = ""
    if isinstance(previous_chapter, dict):
        previous_tail = str(previous_chapter.get("tail") or "")

    continuity_ledger: list[dict[str, Any]] = []
    if isinstance(previous_chapter, dict):
        continuity_ledger = list(previous_chapter.get("continuity_ledger") or [])

    foreshadowing_payload = reader.try_read_json(
        "foreshadowing.json", kind="foreshadowing"
    ) or {}
    foreshadowing = list(foreshadowing_payload.get("unresolved") or [])

    inventory_payload = reader.try_read_json(
        "inventory.json", kind="inventory"
    ) or {}
    inventory_items = list(inventory_payload.get("items") or [])

    character_cards: list[dict[str, Any]] = []
    active_entity_names: list[str] = []
    characters_dir = system_root / "characters"
    if characters_dir.exists():
        for path in sorted(characters_dir.glob("*.json")):
            try:
                card = json_loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(card, dict):
                continue
            if card.get("lifecycle") != "active":
                continue
            character_cards.append(_concise_character_card(card))
            active_entity_names.append(str(card.get("name") or ""))

    return DirectorContext(
        chapter_number=chapter_number,
        volume=volume,
        book_outline_summary=str(outline.get("title") or ""),
        nearby_outline=nearby,
        previous_chapter_summary=previous_summary,
        previous_chapter_tail=previous_tail,
        continuity_ledger=continuity_ledger,
        foreshadowing=foreshadowing,
        character_cards=character_cards,
        inventory=inventory_items,
        active_entity_names=[name for name in active_entity_names if name],
    )


def json_loads(payload: str) -> Any:
    import json

    return json.loads(payload)


__all__ = ["DirectorContext", "build_director_context"]
