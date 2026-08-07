"""Writer context builder.

The writer is the operational agent — it decides *how* the
director-approved chapter is rendered. The view it gets is
therefore operational:
* the approved ``DirectorArtifact`` (ground truth for *what*
  happens),
* the previous chapter's tail (continuity handoff),
* full character cards for every actor named in the director
  artifact,
* active entity cards for locations in scope,
* scene-tagged world rules for the locations in the director
  artifact,
* only the craft modules that are enabled for the project.

The writer must *not* see the full book outline, retired
entities, unrelated character cards, or raw review history.
Keeping the view tight protects against the writer drifting
into structural decisions the director already made.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..agents.contracts import DirectorArtifact
from .project_reader import ProjectContextReader


def _entity_referenced_names(artifact: DirectorArtifact) -> set[str]:
    names: set[str] = set()
    for beat in artifact.scene_beats:
        names.add(str(beat.location))
    for requirement in artifact.entity_requirements:
        names.add(str(requirement.name))
    if artifact.opening_state:
        names.update(_extract_names(artifact.opening_state))
    if artifact.ending_state:
        names.update(_extract_names(artifact.ending_state))
    return {name for name in names if name}


def _extract_names(text: str) -> set[str]:
    # Heuristic: pick out non-trivial Chinese name tokens (length
    # 2-4, not in a stop list). This is intentionally simple — the
    # canonical name resolution will live in the canon registry
    # (Task 6); here we only need an approximate match to filter
    # the character / entity pool for the writer view.
    stop = {"主角", "配角", "妖物", "妖", "林", "山", "驿站", "宗门", "密林"}
    names: set[str] = set()
    cursor = 0
    while cursor < len(text):
        ch = text[cursor]
        if "\u4e00" <= ch <= "\u9fff":
            for length in (4, 3, 2):
                end = cursor + length
                if end <= len(text):
                    candidate = text[cursor:end]
                    if candidate in stop:
                        continue
                    if any("\u4e00" <= c <= "\u9fff" for c in candidate):
                        names.add(candidate)
                        break
        cursor += 1
    return names


def _resolve_world_rules(
    world_rules_payload: dict[str, Any] | None,
    locations: set[str],
) -> list[str]:
    if not isinstance(world_rules_payload, dict):
        return []
    rules: list[str] = []
    for rule in world_rules_payload.get("global") or []:
        text = str(rule).strip()
        if text and text not in rules:
            rules.append(text)
    by_scene = world_rules_payload.get("by_scene")
    if isinstance(by_scene, dict):
        for location in locations:
            for rule in by_scene.get(location) or []:
                text = str(rule).strip()
                if text and text not in rules:
                    rules.append(text)
    return rules


def _build_reader(project: Path, reader: ProjectContextReader | None) -> ProjectContextReader:
    if reader is not None:
        return reader
    return ProjectContextReader(project)


class WriterContext(BaseModel):
    """The operational view the writer sees."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = "writer-context/v1"
    chapter_number: int
    director_artifact: DirectorArtifact
    previous_tail: str = ""
    continuity_facts: list[dict[str, Any]] = Field(default_factory=list)
    character_cards: list[dict[str, Any]] = Field(default_factory=list)
    entity_cards: list[dict[str, Any]] = Field(default_factory=list)
    world_rules: list[str] = Field(default_factory=list)
    craft_modules: list[dict[str, Any]] = Field(default_factory=list)
    book_outline: dict[str, Any] | None = None


def build_writer_context(
    *,
    project: Path,
    chapter_number: int,
    director_artifact: DirectorArtifact,
    reader: ProjectContextReader | None = None,
) -> WriterContext:
    """Build the writer's operational view for ``chapter_number``.

    The writer always receives the approved director artifact
    verbatim. The previous chapter's tail and the continuity
    ledger give the writer a clean handoff. Character and entity
    cards are filtered to the scope declared by the director
    artifact; world rules are filtered to the locations the
    director put into the scene beats; craft modules are filtered
    to the ones the project has enabled.
    """
    project_root = Path(project).resolve()
    system_root = project_root / ".story-system"
    if not system_root.exists():
        raise ValueError(f"project_layout_missing: {system_root}")

    reader = _build_reader(system_root, reader)

    referenced = _entity_referenced_names(director_artifact)
    scene_locations = {beat.location for beat in director_artifact.scene_beats}

    previous_path = f"chapters/{max(chapter_number - 1, 1):04d}.json"
    previous_chapter = reader.try_read_json(previous_path, kind="chapter") or {}
    previous_tail = ""
    continuity_facts: list[dict[str, Any]] = []
    if isinstance(previous_chapter, dict):
        previous_tail = str(previous_chapter.get("tail") or "")
        continuity_facts = list(previous_chapter.get("continuity_ledger") or [])

    # Full character cards for actors in scope.
    character_cards: list[dict[str, Any]] = []
    characters_dir = system_root / "characters"
    if characters_dir.exists():
        for path in sorted(characters_dir.glob("*.json")):
            try:
                card = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(card, dict):
                continue
            if card.get("lifecycle") != "active":
                continue
            name = str(card.get("name") or "")
            requirement_names = {
                str(req.name)
                for req in director_artifact.entity_requirements
                if req.kind == "character"
            }
            if name in requirement_names or name in referenced or not requirement_names:
                character_cards.append(card)

    # Active entity cards for locations in scope, never retired.
    entity_cards: list[dict[str, Any]] = []
    entities_dir = system_root / "entities"
    if entities_dir.exists():
        for path in sorted(entities_dir.glob("*.json")):
            if not path.is_file():
                continue
            try:
                card = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(card, dict):
                continue
            if card.get("lifecycle") != "active":
                continue
            name = str(card.get("name") or "")
            requirement_names = {
                str(req.name)
                for req in director_artifact.entity_requirements
                if req.kind in ("location", "item", "equipment", "organization", "monster")
            }
            if name in requirement_names or name in scene_locations:
                entity_cards.append(card)

    # Scene-tagged world rules.
    world_rules_payload = reader.try_read_json(
        "world-rules.json", kind="world-rules"
    )
    world_rules = _resolve_world_rules(world_rules_payload, scene_locations)

    # Only enabled craft modules.
    craft_modules: list[dict[str, Any]] = []
    craft_dir = system_root / "craft-modules"
    if craft_dir.exists():
        for path in sorted(craft_dir.glob("*.json")):
            try:
                module = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(module, dict):
                continue
            if not bool(module.get("enabled_by_default", False)):
                continue
            if "writer" not in (module.get("stages") or []):
                continue
            craft_modules.append(module)

    return WriterContext(
        chapter_number=chapter_number,
        director_artifact=director_artifact,
        previous_tail=previous_tail,
        continuity_facts=continuity_facts,
        character_cards=character_cards,
        entity_cards=entity_cards,
        world_rules=world_rules,
        craft_modules=craft_modules,
        book_outline=None,
    )


__all__ = ["WriterContext", "build_writer_context"]
