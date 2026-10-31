"""Director context builder.

The director is the structural agent — it decides *what* should
happen next. The view it gets is therefore structural:
* the current volume and a few nearby chapter outlines,
* the previous chapter's summary and the active continuity
  ledger,
* active plot threads and unresolved foreshadowing,
* concise decision slices (identity + current state + bounded
  drive/personality/performance/relationship fields) for
  characters that are in scope for the target chapter.

The director must *not* see craft-module text (those are the
writer's tools), retired entities, or private secrets. Bounded
slices keep the director's prompt focused on planning rather than
prose cues.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..outline_rolling import rolling_chapter_to_outline_entry
from .project_reader import ProjectContextReader


def _plain_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _bounded_items(value: Any, limit: int = 3) -> list[Any]:
    if isinstance(value, list):
        return value[:limit]
    if value in (None, ""):
        return []
    return [value]


def _project_relationships(card: dict[str, Any]) -> list[dict[str, Any]]:
    raw = card.get("relationships")
    if raw is None:
        raw = card.get("relationship_notes")

    entries: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            entry = _plain_dict(value)
            entry.setdefault("target", str(key))
            entries.append(entry)
    elif isinstance(raw, list):
        entries = [_plain_dict(item) for item in raw]

    def score(entry: dict[str, Any]) -> tuple[float, float]:
        try:
            tension = float(entry.get("tension") or 0.0)
        except (TypeError, ValueError):
            tension = 0.0
        try:
            trust = float(entry.get("trust") or 0.0)
        except (TypeError, ValueError):
            trust = 0.0
        return tension, trust

    projected: list[dict[str, Any]] = []
    for entry in sorted(entries, key=score, reverse=True)[:3]:
        target = str(entry.get("target") or entry.get("name") or "").strip()
        if not target:
            continue
        projected.append(
            {
                "target": target,
                "trust": entry.get("trust", 0.0),
                "tension": entry.get("tension", 0.0),
                "bond": str(
                    entry.get("bond")
                    or entry.get("relation_type")
                    or entry.get("type")
                    or entry.get("current_attitude")
                    or ""
                ),
            }
        )
    return projected


def _concise_character_card(card: dict[str, Any]) -> dict[str, Any]:
    """Project identity into a bounded, decision-oriented director slice.

    The source cards have several legacy shapes. Normalize only the fields
    needed to choose actions and scene pressure; private secrets, memories,
    and full personality/profile payloads stay out of the director context.
    """
    drive = _plain_dict(card.get("story_drive"))
    personality = _plain_dict(
        card.get("personality") or card.get("personality_portrait")
    )
    psychology = _plain_dict(personality.get("psychology"))
    behavior = _plain_dict(personality.get("behavior"))
    performance = _plain_dict(
        card.get("performance") or card.get("performance_profile")
    )

    projected: dict[str, Any] = {
        "id": card.get("id"),
        "lifecycle": card.get("lifecycle") or card.get("lifecycle_state"),
        "summary": card.get("summary"),
        "relationship_notes": [dict(note) for note in (card.get("relationship_notes") or [])[:3] if isinstance(note, dict)],
        "name": card.get("name", ""),
        "role": card.get("role", ""),
        "narrative_function": (
            card.get("narrative_function")
            or card.get("story_function")
            or card.get("chapter_role")
            or ""
        ),
        "location": card.get("location", ""),
        "current_state": card.get("current_state", ""),
        "story_drive": {
            "immediate_goal": drive.get("immediate_goal", ""),
            "motivation": drive.get("motivation", ""),
            "main_conflict_reason": drive.get("main_conflict_reason", ""),
        },
        "personality": {
            "desire": personality.get("desire") or psychology.get("desire", ""),
            "fear": personality.get("fear") or psychology.get("fear", ""),
            "pressure_mode": personality.get("pressure_mode")
            or behavior.get("pressure_mode", ""),
            "conflict_response": personality.get("conflict_response")
            or behavior.get("conflict_response", ""),
        },
        "performance": {
            "speech_style": performance.get("speech_style", ""),
            "action_style": performance.get("action_style", ""),
            "decision_rules": _bounded_items(performance.get("decision_rules")),
            "reveal_limits": _bounded_items(performance.get("reveal_limits")),
        },
        "relationships": _project_relationships(card),
    }

    # Keep the small legacy identity envelope because existing artifact
    # consumers use it for display and lifecycle filtering.
    if "id" in card:
        projected["id"] = card["id"]
    if "lifecycle" in card or "lifecycle_state" in card:
        projected["lifecycle"] = card.get("lifecycle", card.get("lifecycle_state"))
    if "summary" in card:
        projected["summary"] = card["summary"]
    elif isinstance(card.get("current_state"), dict):
        current = card["current_state"]
        current_state = current.get("current") if isinstance(current.get("current"), dict) else current
        if isinstance(current_state, dict) and current_state.get("summary"):
            projected["summary"] = current_state["summary"]
    return projected


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
    character_intents: list[dict[str, Any]] = Field(default_factory=list)
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
    ledger, unresolved foreshadowing, and decision-oriented character
    slices for the actors that are currently active. It does not see
    craft-module text, retired entities, private secrets, or the full
    book outline.
    """
    project_root = Path(project).resolve()
    system_root = project_root / ".story-system"
    if not system_root.exists():
        raise ValueError(f"project_layout_missing: {system_root}")

    reader = _build_reader(system_root, reader)

    outline = reader.try_read_json("outline.json", kind="outline") or {}
    rolling_outline = reader.try_read_json(
        "outline-generation/rolling_outline.json", kind="outline"
    ) or {}
    volume = reader.try_read_json("volume.json", kind="volume") or {}

    volume_range = volume.get("chapter_range") if isinstance(volume, dict) else None
    outline_by_number: dict[int, dict[str, Any]] = {}
    for entry in outline.get("chapters") or []:
        if not isinstance(entry, dict):
            continue
        number = entry.get("number")
        if isinstance(number, int):
            outline_by_number[number] = entry
    for payload in rolling_outline.get("chapters") or []:
        adapted = rolling_chapter_to_outline_entry(
            payload, base_entry=outline_by_number.get(payload.get("chapter_number"))
            if isinstance(payload, dict) else None,
        )
        number = adapted.get("number")
        if isinstance(number, int):
            outline_by_number[number] = adapted

    nearby: list[dict[str, Any]] = []
    for entry in outline_by_number.values():
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
            lifecycle = card.get("lifecycle") or card.get("lifecycle_state") or "active"
            if lifecycle != "active":
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
