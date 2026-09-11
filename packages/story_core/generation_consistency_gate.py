"""Deterministic consistency gate for pre-generation chapter plans.

The gate is deliberately small and advisory-first.  It projects only the
structured fields already present in a Director/legacy plan into the
Phase 2C character consistency checker.  It never reads prose, calls a
model, repairs state, or writes an audit record.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from packages.story_core.character_inspection import (
    CharacterPlanContext,
    ConsistencyWarning,
    check_character_consistency,
)


GenerationGateStatus = Literal["clear", "warnings", "blocking"]


class GenerationConsistencyGate(BaseModel):
    """Result of checking one structured chapter plan."""

    schema_version: Literal["generation-consistency-gate/v1"] = (
        "generation-consistency-gate/v1"
    )
    target_chapter: int = Field(ge=1)
    status: GenerationGateStatus
    warnings: list[ConsistencyWarning] = Field(default_factory=list)
    checked_characters: list[str] = Field(default_factory=list)
    checked_at_boundary: int = Field(ge=0)
    override_applied: bool = False

    @property
    def blocking_warnings(self) -> list[ConsistencyWarning]:
        return [item for item in self.warnings if item.severity == "error"]


class ConsistencyGateRequired(RuntimeError):
    """Raised before Writer execution when an author decision is required."""

    def __init__(self, gate: GenerationConsistencyGate) -> None:
        self.gate = gate
        super().__init__(
            f"generation_consistency_override_required:{gate.target_chapter}"
        )


_NAME_KEYS = ("name", "character_name", "actor", "character")
_PARTICIPANT_KEYS = (
    "cast",
    "characters",
    "participants",
    "involved_characters",
    "character_names",
    "actors",
    "cast_list",
)
_LOCATION_KEYS = ("location", "current_location", "planned_location", "plan_location")
_SKILL_KEYS = ("skills_used", "planned_skills", "skills")
_EQUIPMENT_KEYS = (
    "equipment_used",
    "planned_equipment",
    "equipment",
    "items_used",
)
_KNOWLEDGE_ID_KEYS = ("knowledge_fact_ids", "fact_ids")
_KNOWLEDGE_TEXT_KEYS = ("knowledge_facts", "facts")
_RELATIONSHIP_KEYS = (
    "relationship_expectations",
    "relationship_requirements",
    "relationships",
)
_BLOCKING_CODES = frozenset(
    {
        "SKILL_NOT_YET_ACQUIRED",
        "KNOWLEDGE_NOT_YET_LEARNED",
        "EQUIPMENT_NOT_OWNED",
    }
)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="python")
        except TypeError:
            dumped = model_dump()
        if isinstance(dumped, Mapping):
            return {str(key): item for key, item in dumped.items()}
    return {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(value)


def _items(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    return []


def _append_unique(target: list[Any], values: Any) -> None:
    candidates = _items(values)
    if not candidates and values not in (None, "", [], {}):
        candidates = [values]
    seen = {_canonical(item) for item in target}
    for item in candidates:
        if item in (None, "", [], {}):
            continue
        marker = _canonical(item)
        if marker in seen:
            continue
        target.append(deepcopy(item))
        seen.add(marker)


def _name(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in _NAME_KEYS:
            found = _text(value.get(key))
            if found:
                return found
        return ""
    return _text(value)


def _entry_items(value: Any) -> list[tuple[str, dict[str, Any]]]:
    """Normalize an explicit actor collection without reading free text."""

    if isinstance(value, Mapping):
        if any(key in value for key in _NAME_KEYS):
            return [(_name(value), _mapping(value))]
        result: list[tuple[str, dict[str, Any]]] = []
        for key, raw in value.items():
            actor = _text(key)
            if not actor:
                continue
            item = _mapping(raw)
            if item:
                item.setdefault("character_name", actor)
            else:
                item = {"character_name": actor}
            result.append((actor, item))
        return result
    result = []
    for raw in _items(value):
        item = _mapping(raw)
        actor = _name(item)
        if actor:
            result.append((actor, item))
        elif isinstance(raw, str) and raw.strip():
            result.append((raw.strip(), {"character_name": raw.strip()}))
    return result


def _field_value(entry: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in entry and entry[key] not in (None, "", [], {}):
            return entry[key]
    return None


def _merge_entry(context: dict[str, Any], entry: Mapping[str, Any]) -> None:
    nested = _mapping(entry.get("context") or entry.get("plan_context"))
    sources = [entry]
    if nested:
        sources.append(nested)
    for source in sources:
        if context.get("location") in (None, ""):
            location = _field_value(source, _LOCATION_KEYS)
            if location not in (None, ""):
                context["location"] = deepcopy(location)
        for key in _SKILL_KEYS:
            if key in source:
                _append_unique(context["skills_used"], source[key])
        for key in _EQUIPMENT_KEYS:
            if key in source:
                _append_unique(context["equipment_used"], source[key])
        for key in _KNOWLEDGE_ID_KEYS:
            if key in source:
                _append_unique(context["knowledge_fact_ids"], source[key])
        for key in _KNOWLEDGE_TEXT_KEYS:
            if key in source:
                _append_unique(context["knowledge_facts"], source[key])
        for key in _RELATIONSHIP_KEYS:
            if key in source:
                _append_unique(context["relationship_expectations"], source[key])


def _scene_participants(card: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any]]] = []
    for key in _PARTICIPANT_KEYS:
        if key in card:
            for actor, entry in _entry_items(card[key]):
                # Carry the scene's explicit location to a participant, but
                # retain the participant entry's values when it supplies a
                # more specific structured field.
                result.append((actor, {**dict(card), **entry}))
    # A singular, explicitly named actor is also a safe association.  A
    # scene-card title/name is intentionally not considered an actor.
    for key in ("actor", "character_name"):
        actor = _text(card.get(key))
        if actor:
            result.append((actor, card))
    return result


def _dedupe_contexts(contexts: dict[str, dict[str, Any]]) -> list[CharacterPlanContext]:
    return [
        CharacterPlanContext.model_validate({"character_name": name, **payload})
        for name, payload in contexts.items()
    ]


def map_plan_to_character_contexts(
    plan: Any,
) -> list[CharacterPlanContext]:
    """Project explicit plan participation into Phase 2C contexts.

    No value is extracted from ``action``, ``result``, ``summary``, or any
    other prose field.  Director entity requirements are usable for a sole
    character participant because the association is structurally
    unambiguous; with multiple participants, unscoped entities are omitted.
    """

    payload = _mapping(plan)
    contexts: dict[str, dict[str, Any]] = {}

    def ensure(actor: str) -> dict[str, Any]:
        name = _text(actor)
        if not name:
            return {}
        return contexts.setdefault(
            name,
            {
                "location": None,
                "skills_used": [],
                "equipment_used": [],
                "knowledge_fact_ids": [],
                "knowledge_facts": [],
                "relationship_expectations": [],
            },
        )

    for key in ("character_moves", "action_briefs", "character_plans", "actor_plans"):
        for actor, entry in _entry_items(payload.get(key)):
            _merge_entry(ensure(actor), entry)

    scene_actors: list[tuple[str, dict[str, Any]]] = []
    for card in _items(payload.get("scene_cards")):
        scene = _mapping(card)
        if not scene:
            continue
        for actor, entry in _scene_participants(scene):
            scene_actors.append((actor, entry))
            _merge_entry(ensure(actor), entry)

    for key in ("cast", "participants", "involved_characters", "character_names"):
        for actor, entry in _entry_items(payload.get(key)):
            _merge_entry(ensure(actor), entry)

    requirements = [
        _mapping(item)
        for item in _items(payload.get("entity_requirements"))
        if _mapping(item)
    ]
    requirement_actors = [
        _text(item.get("name"))
        for item in requirements
        if _text(item.get("kind")).casefold() == "character" and _text(item.get("name"))
    ]
    for actor in requirement_actors:
        ensure(actor)

    # ``DirectorArtifact`` scene beats do not carry an actor field.  A sole
    # character requirement is the only deterministic association available.
    actor_names = list(contexts)
    if len(actor_names) == 1:
        sole = ensure(actor_names[0])
        locations = [
            _text(_mapping(beat).get("location"))
            for beat in _items(payload.get("scene_beats"))
            if _text(_mapping(beat).get("location"))
        ]
        distinct_locations = list(dict.fromkeys(locations))
        if sole.get("location") in (None, "") and len(distinct_locations) == 1:
            sole["location"] = distinct_locations[0]
        for requirement in requirements:
            kind = _text(requirement.get("kind")).casefold()
            entity_name = _text(requirement.get("name"))
            if not entity_name or kind == "character":
                continue
            if kind == "technique":
                _append_unique(sole["skills_used"], entity_name)
            elif kind == "equipment":
                _append_unique(sole["equipment_used"], entity_name)

    # Keep this variable explicit: it documents that scene participation was
    # collected only from structured cast fields, never inferred from prose.
    del scene_actors
    return _dedupe_contexts(contexts)


def _merge_structured_values(primary: Any, fallback: Any) -> Any:
    """Merge historical source data with project metadata without mutation."""

    if isinstance(primary, Mapping) and isinstance(fallback, Mapping):
        merged = deepcopy(dict(primary))
        for key, value in fallback.items():
            if key not in merged:
                merged[str(key)] = deepcopy(value)
            elif isinstance(merged.get(key), Mapping) and isinstance(value, Mapping):
                merged[str(key)] = _merge_structured_values(merged[key], value)
            elif isinstance(merged.get(key), list) and isinstance(value, list):
                values = deepcopy(merged[key])
                seen = {_canonical(item) for item in values}
                for item in value:
                    marker = _canonical(item)
                    if marker not in seen:
                        values.append(deepcopy(item))
                        seen.add(marker)
                merged[str(key)] = values
        return merged
    if isinstance(primary, list) and isinstance(fallback, list):
        values = deepcopy(primary)
        seen = {_canonical(item) for item in values}
        for item in fallback:
            marker = _canonical(item)
            if marker not in seen:
                values.append(deepcopy(item))
                seen.add(marker)
        return values
    return deepcopy(primary if primary not in (None, "", [], {}) else fallback)


def _source_payload(source: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(source, (str, Path)):
        from packages.story_core.file_project_store import FileProjectStore

        store = FileProjectStore(Path(source))
        return deepcopy(store.state()), deepcopy(store.project())
    state_method = getattr(source, "state", None)
    project_method = getattr(source, "project", None)
    if callable(state_method):
        state = _mapping(state_method())
        project = _mapping(project_method()) if callable(project_method) else {}
        return deepcopy(state), deepcopy(project)
    payload = _mapping(source)
    nested_state = _mapping(payload.get("state"))
    nested_project = _mapping(payload.get("project"))
    if nested_state:
        return deepcopy(nested_state), deepcopy(nested_project)
    return deepcopy(payload), {}


def build_character_inspection_payload(
    source: Any,
    *,
    fallback_root: Any | None = None,
) -> dict[str, Any]:
    """Build a read-only checker payload, optionally from a project root.

    ``source`` is normally the historical ``StoryState`` prepared for the
    target chapter.  ``fallback_root`` contributes future-dated ledger
    records needed to identify a requested fact that is acquired later, but
    the source's historical values remain authoritative on conflicts.
    """

    state, project = _source_payload(source)
    if fallback_root is not None:
        fallback_state, fallback_project = _source_payload(fallback_root)
        state = _merge_structured_values(state, fallback_state)
        project = _merge_structured_values(project, fallback_project)

    payload = deepcopy(state)
    relationship_graph = project.get("relationship_graph")
    if not isinstance(relationship_graph, list) or not relationship_graph:
        relationship_graph = payload.get("relationship_graph") or []
    payload["relationship_graph"] = deepcopy(relationship_graph)

    blueprint = project.get("world_blueprint")
    blueprint_cards = blueprint.get("equipment_cards") if isinstance(blueprint, Mapping) else []
    existing_cards = payload.get("equipment_cards")
    cards: list[dict[str, Any]] = []
    seen_cards: set[str] = set()
    for raw in [
        *(_items(existing_cards)),
        *(_items(blueprint_cards)),
    ]:
        card = _mapping(raw)
        if not card:
            continue
        identity = _text(card.get("id") or card.get("name")).casefold()
        if not identity:
            continue
        if identity in seen_cards:
            index = next(
                (index for index, item in enumerate(cards) if _text(item.get("id") or item.get("name")).casefold() == identity),
                None,
            )
            if index is not None:
                cards[index] = _merge_structured_values(cards[index], card)
            continue
        seen_cards.add(identity)
        cards.append(deepcopy(card))
    payload["equipment_cards"] = cards
    return payload


def evaluate_generation_consistency(
    source: Any,
    plan: Any,
    *,
    target_chapter: int,
    fallback_root: Any | None = None,
    override: bool = False,
) -> GenerationConsistencyGate:
    """Evaluate all explicitly participating, historically known characters."""

    target = int(target_chapter)
    if target < 1:
        raise ValueError("target_chapter must be an integer >= 1")
    payload = build_character_inspection_payload(source, fallback_root=fallback_root)
    available = {
        _text(_mapping(item).get("name"))
        for item in _items(payload.get("characters"))
        if _text(_mapping(item).get("name"))
    }
    contexts = map_plan_to_character_contexts(plan)
    checked_characters = [
        context.character_name
        for context in contexts
        if context.character_name in available
    ]
    warnings: list[ConsistencyWarning] = []
    for context in contexts:
        if context.character_name not in available:
            # New explicitly planned characters have no historical record;
            # unknown history is silent by Phase 2C contract.
            continue
        warnings.extend(
            check_character_consistency(
                payload,
                context.character_name,
                target_chapter=target,
                planned_context=context,
            )
        )

    normalized: list[ConsistencyWarning] = []
    for warning in warnings:
        if warning.code in _BLOCKING_CODES:
            normalized.append(warning.model_copy(update={"severity": "error"}))
        else:
            normalized.append(warning.model_copy(update={"severity": "warning"}))
    normalized.sort(
        key=lambda item: (
            item.character_name,
            item.code,
            _canonical(item.expected),
            _canonical(item.observed),
        )
    )
    status: GenerationGateStatus = (
        "blocking"
        if any(item.severity == "error" for item in normalized)
        else "warnings"
        if normalized
        else "clear"
    )
    return GenerationConsistencyGate(
        target_chapter=target,
        status=status,
        warnings=normalized,
        checked_characters=checked_characters,
        checked_at_boundary=target - 1,
        override_applied=bool(override and normalized),
    )


def require_generation_consistency(
    source: Any,
    plan: Any,
    *,
    target_chapter: int,
    fallback_root: Any | None = None,
    override: bool = False,
) -> GenerationConsistencyGate:
    """Evaluate and pause before Writer unless the author explicitly overrides."""

    gate = evaluate_generation_consistency(
        source,
        plan,
        target_chapter=target_chapter,
        fallback_root=fallback_root,
        override=override,
    )
    if gate.status != "clear" and not override:
        raise ConsistencyGateRequired(gate)
    return gate


run_generation_consistency_gate = evaluate_generation_consistency


__all__ = [
    "ConsistencyGateRequired",
    "GenerationConsistencyGate",
    "GenerationGateStatus",
    "build_character_inspection_payload",
    "evaluate_generation_consistency",
    "map_plan_to_character_contexts",
    "require_generation_consistency",
    "run_generation_consistency_gate",
]
