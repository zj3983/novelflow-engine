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

from packages.story_core.skill_packs import (
    resolve_enabled_skill_ids,
    resolve_enabled_skill_module_ids,
)

from ..agents.contracts import DirectorArtifact
from .project_reader import ProjectContextReader
from ..writer_character_context import (
    historical_writer_character_cards,
    writer_historical_chapter,
)


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
    # Project-level metadata. The writer prompt uses the title to
    # anchor voice and the genre to keep craft modules consistent.
    # These are generic; genre-specific rules stay in
    # ``world_rules`` and game-specific state stays in
    # ``character_cards`` (only when a character actually carries
    # one).
    project_title: str = ""
    genre: str = ""
    rewrite_guidance: str = ""
    previous_tail: str = ""
    continuity_facts: list[dict[str, Any]] = Field(default_factory=list)
    character_cards: list[dict[str, Any]] = Field(default_factory=list)
    entity_cards: list[dict[str, Any]] = Field(default_factory=list)
    world_rules: list[str] = Field(default_factory=list)
    craft_modules: list[dict[str, Any]] = Field(default_factory=list)
    enabled_skill_ids: list[str] = Field(default_factory=list)
    # Preserve legacy pack-level selection separately from explicit no-modules.
    enabled_skill_module_ids: list[str] | None = None
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

    # Project-level metadata is sourced from the canonical
    # ``project.json`` (which holds the title and the genre plugin
    # id). The legacy adapter does the same translation for
    # projects that have not yet migrated to ``.story-system/``;
    # ``_legacy_writer_context`` is responsible for the read.
    project_payload = reader.try_read_json("project.json", kind="project") or {}
    state_payload = reader.try_read_json("state.json", kind="state") or {}
    project_title = ""
    genre = ""
    if isinstance(project_payload, dict):
        project_title = str(project_payload.get("title") or "").strip()
        genre_id = project_payload.get("genre_plugin_id") or project_payload.get("genre")
        if isinstance(genre_id, str) and genre_id.strip():
            genre = genre_id.strip()

    referenced = _entity_referenced_names(director_artifact)
    scene_locations = {beat.location for beat in director_artifact.scene_beats}

    previous_chapter = (
        reader.try_read_json(
            f"chapters/{chapter_number - 1:04d}.json",
            kind="chapter",
        )
        or {}
        if chapter_number > 1
        else {}
    )
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
            if card.get("lifecycle") not in (None, "active"):
                continue
            name = str(card.get("name") or "")
            requirement_names = {
                str(req.name)
                for req in director_artifact.entity_requirements
                if req.kind == "character"
            }
            if name in requirement_names or name in referenced or not requirement_names:
                character_cards.append(card)

    # Replace the latest character mirrors with a chapter-bounded projection.
    # The canonical state file carries the replay sources; a characters/
    # directory card is used as the fallback source for migrated projects.
    replay_state = dict(state_payload) if isinstance(state_payload, dict) else {}
    state_characters = replay_state.get("characters")
    if not isinstance(state_characters, list) or not state_characters:
        replay_state["characters"] = [dict(card) for card in character_cards]
    elif not character_cards:
        # Some canonical projects keep character mirrors only in state.json.
        # Use the same scope filter as the directory-backed path, then apply
        # the historical projection below before exposing them to the writer.
        requirement_names = {
            str(req.name)
            for req in director_artifact.entity_requirements
            if req.kind == "character"
        }
        for raw in state_characters:
            if not isinstance(raw, dict) or raw.get("lifecycle") not in (None, "active"):
                continue
            name = str(raw.get("name") or "")
            if name and (name in requirement_names or name in referenced or not requirement_names):
                character_cards.append(dict(raw))
    else:
        known_state_names = {
            str(item.get("name") or "").strip()
            for item in state_characters
            if isinstance(item, dict)
        }
        replay_state["characters"] = [
            *state_characters,
            *[
                dict(card)
                for card in character_cards
                if str(card.get("name") or "").strip() not in known_state_names
            ],
        ]
    historical_cards = historical_writer_character_cards(
        replay_state,
        as_of_chapter=writer_historical_chapter(chapter_number),
    )
    historical_by_name = {
        str(card.get("name") or "").strip(): card
        for card in historical_cards
        if str(card.get("name") or "").strip()
    }
    character_cards = [
        historical_by_name[str(card.get("name") or "").strip()]
        for card in character_cards
        if str(card.get("name") or "").strip() in historical_by_name
    ]

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
        project_title=project_title,
        genre=genre,
        previous_tail=previous_tail,
        continuity_facts=continuity_facts,
        character_cards=character_cards,
        entity_cards=entity_cards,
        world_rules=world_rules,
        craft_modules=craft_modules,
        enabled_skill_ids=resolve_enabled_skill_ids(project_payload, state_payload),
        enabled_skill_module_ids=resolve_enabled_skill_module_ids(
            project_payload,
            state_payload,
        ),
        book_outline=None,
    )


__all__ = ["WriterContext", "build_writer_context"]
