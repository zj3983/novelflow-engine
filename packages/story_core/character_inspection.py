"""Author-facing, read-only character history inspection.

This module deliberately does not persist a timeline.  Every result is
aggregated from the structured state, progression, equipment, relationship,
knowledge, and memory records that already belong to the story.  The
consistency checker uses the same historical replay boundary as the writer:
the start of chapter ``N`` is the end of chapter ``N - 1``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha1
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from packages.story_core.historical_state_replay import (
    _EVENT_META_KEYS,
    _PROGRESSION_EVENT_KEYS,
    _STATE_NAMESPACE_KEYS,
    _event_chapter,
    _event_list,
    _event_value,
    _explicit_events,
    _equipment_events,
    _is_protagonist_character,
    _relationship_edges,
    _replay_payload,
    _state_events,
    get_character_state_for_writer,
)
from packages.story_core.models import KnowledgeFact


TimelineCategory = Literal[
    "state",
    "location",
    "emotion",
    "relationship",
    "progression",
    "skill",
    "equipment",
    "knowledge",
    "appearance",
]


class CharacterTimelineEvent(BaseModel):
    """One normalized, explicitly evidenced character history event."""

    event_id: str = Field(min_length=1)
    chapter_number: int = Field(ge=0)
    character_name: str = Field(min_length=1)
    category: TimelineCategory
    title: str = Field(min_length=1)
    summary: str = ""
    before: Any = None
    after: Any = None
    source: str = Field(min_length=1)
    source_id: str = ""
    confidence: str = "confirmed"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CharacterPlanContext(BaseModel):
    """Small structured input accepted by the deterministic warning engine."""

    character_name: str = ""
    location: str | None = None
    skills_used: list[Any] = Field(default_factory=list)
    equipment_used: list[Any] = Field(default_factory=list)
    knowledge_fact_ids: list[str] = Field(default_factory=list)
    knowledge_facts: list[str] = Field(default_factory=list)
    relationship_expectations: Any = Field(default_factory=list)


class ConsistencyWarning(BaseModel):
    """A deterministic warning about a structured plan at a chapter boundary."""

    code: str = Field(min_length=1)
    severity: Literal["error", "warning", "info"] = "warning"
    character_name: str = Field(min_length=1)
    target_chapter: int = Field(ge=1)
    message: str = Field(min_length=1)
    expected: Any = None
    observed: Any = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    source: str = ""
    suggestion: str = ""


@dataclass
class _Candidate:
    chapter_number: int
    sequence: int
    category: str
    title: str
    summary: str
    before: Any
    after: Any
    source: str
    source_id: str
    confidence: str = "confirmed"
    metadata: dict[str, Any] = field(default_factory=dict)
    source_rank: int = 99
    dedupe_key: tuple[Any, ...] = ()


@dataclass(frozen=True)
class _EquipmentObservation:
    card_id: str
    name: str
    aliases: tuple[str, ...]
    chapter_number: int
    sequence: int
    source_id: str
    previous: dict[str, Any]
    current: dict[str, Any]


_SOURCE_RANK = {
    # Dedicated ledgers/history win when the same structured fact was copied
    # into a character state mirror or a chapter index.
    "progression_ledger": 10,
    "knowledge_ledger": 10,
    "character_state": 20,
    "relationship_graph": 30,
    "equipment_history": 30,
    "memory_index": 40,
}

_FIELD_ORDER = {
    "location": 10,
    "current_location": 10,
    "emotion": 20,
    "current_emotion": 20,
    "mood": 20,
    "level": 30,
    "skills": 40,
    "skill": 40,
    "skill_name": 40,
}

_STATE_META_KEYS = {
    *_EVENT_META_KEYS,
    "character",
    "character_name",
    "actor",
    "owner",
}

_PROGRESSION_META_KEYS = {
    *_EVENT_META_KEYS,
    "character",
    "character_name",
    "actor",
    "source_character",
}

_SKILL_KEYS = (
    "skills",
    "skill",
    "skill_name",
    "skills_added",
    "skills_acquired",
    "learned_skill",
    "learned_skills",
)

_PROGRESSION_VALUE_KEYS = {
    "attributes",
    "class_path",
    "exp",
    "hp",
    "mp",
    "currency",
    "inventory",
    "quests",
    "realm",
    "cultivation",
    "cultivation_realm",
}

_RELATIONSHIP_FIELDS = (
    "trust",
    "tension",
    "current_state",
    "relation_type",
    "bond",
    "status",
)

_EQUIPMENT_FIELDS = ("current_owner", "current_location", "durability", "status")
_MISSING = object()


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


def _story_payload(story_state: Any) -> dict[str, Any]:
    payload = _mapping(story_state)
    # Keep the helper friendly to a future StoryState extension that carries
    # these fields as model attributes, without mutating the input model.
    for key in ("relationship_graph",):
        if key not in payload:
            value = getattr(story_state, key, _MISSING)
            if value is not _MISSING:
                payload[key] = value
    return payload


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(value)


def _display(value: Any) -> str:
    if value is None:
        return "未知"
    if isinstance(value, Mapping):
        return "；".join(
            f"{key}：{_display(item)}"
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if item not in (None, "", [], {})
        ) or "未知"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "、".join(_display(item) for item in value) or "未知"
    return _text(value) or "未知"


def _transition_summary(label: str, before: Any, after: Any) -> str:
    if before is _MISSING or before is None:
        return f"{label}：{_display(after)}"
    return f"{label}：{_display(before)} → {_display(after)}"


def _chapter(value: Any, *, allow_zero: bool = True) -> int | None:
    if isinstance(value, bool) or isinstance(value, float) and not value.is_integer():
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < (0 if allow_zero else 1):
        return None
    return number


def _query_boundary(value: Any, *, label: str, allow_zero: bool = True) -> int:
    number = _chapter(value, allow_zero=allow_zero)
    if number is None:
        minimum = 0 if allow_zero else 1
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return number


def _character(payload: Mapping[str, Any], character_name: str) -> dict[str, Any]:
    wanted = _text(character_name)
    characters = payload.get("characters")
    if isinstance(characters, Sequence) and not isinstance(characters, (str, bytes, bytearray)):
        for item in characters:
            card = _mapping(item)
            if _text(card.get("name")) == wanted:
                return card
    raise KeyError(f"character_not_found:{wanted or character_name}")


def _clean_event_values(values: Mapping[str, Any], *, meta_keys: set[str]) -> dict[str, Any]:
    return {
        str(key): deepcopy(value)
        for key, value in values.items()
        if str(key) not in meta_keys and value not in (None, "")
    }


def _ordered_keys(values: Mapping[str, Any]) -> list[str]:
    return sorted(values, key=lambda key: (_FIELD_ORDER.get(key, 100), str(key)))


def _skill_name(value: Any) -> str:
    if isinstance(value, Mapping):
        for key in ("skill_id", "id", "name", "skill", "title"):
            text = _text(value.get(key))
            if text:
                return text
        return ""
    return _text(value)


def _skill_values(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        for key in ("learned", "acquired", "added", "skills", "active", "items"):
            if key in value:
                return _skill_values(value.get(key))
        name = _skill_name(value)
        return [name] if name else []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result: list[str] = []
        for item in value:
            name = _skill_name(item)
            if name and name not in result:
                result.append(name)
        return result
    name = _skill_name(value)
    return [name] if name else []


def _actor_matches(values: Mapping[str, Any], wanted: str) -> bool:
    for key in ("character", "character_name", "actor", "source_character"):
        if key in values and _text(values.get(key)) not in {"", wanted, "*"}:
            return False
    return True


def _has_actor_reference(values: Mapping[str, Any]) -> bool:
    return any(
        key in values and _text(values.get(key))
        for key in ("character", "character_name", "actor", "source_character")
    )


def _make_candidate(
    *,
    chapter_number: int,
    sequence: int,
    category: str,
    title: str,
    before: Any,
    after: Any,
    source: str,
    source_id: str,
    summary: str | None = None,
    confidence: str = "confirmed",
    metadata: Mapping[str, Any] | None = None,
    dedupe_key: tuple[Any, ...] = (),
) -> _Candidate:
    return _Candidate(
        chapter_number=chapter_number,
        sequence=sequence,
        category=category,
        title=title,
        summary=summary or _transition_summary(title, before, after),
        before=deepcopy(None if before is _MISSING else before),
        after=deepcopy(after),
        source=source,
        source_id=source_id,
        confidence=confidence or "confirmed",
        metadata=deepcopy(dict(metadata or {})),
        source_rank=_SOURCE_RANK[source],
        dedupe_key=dedupe_key,
    )


def _state_candidates(payload: Mapping[str, Any], wanted: str) -> list[_Candidate]:
    character = _character(payload, wanted)
    collected: list[tuple[int, int, int, dict[str, Any], str, str]] = []
    for namespace_index, namespace in enumerate(_STATE_NAMESPACE_KEYS):
        events = _state_events(character, namespace)
        for chapter_number, sequence, values, source_id in events:
            collected.append(
                (
                    chapter_number,
                    namespace_index * 1_000_000 + sequence,
                    namespace_index,
                    _clean_event_values(values, meta_keys=set(_EVENT_META_KEYS)),
                    namespace,
                    source_id,
                )
            )

    candidates: list[_Candidate] = []
    previous: dict[str, Any] = {}
    known_skills: dict[str, list[str]] = {}
    for chapter_number, sequence, namespace_index, values, namespace, source_id in sorted(
        collected,
        key=lambda item: (item[0], item[1], item[5]),
    ):
        del namespace_index
        for key in _ordered_keys(values):
            if key in _STATE_META_KEYS:
                continue
            value = values[key]
            field_key = f"{namespace}.{key}"
            if key in _SKILL_KEYS:
                current_skills = known_skills.setdefault(namespace, [])
                for skill in _skill_values(value):
                    if skill in current_skills:
                        continue
                    current_skills.append(skill)
                    candidates.append(
                        _make_candidate(
                            chapter_number=chapter_number,
                            sequence=sequence * 100 + len(current_skills),
                            category="skill",
                            title="获得技能",
                            before=None,
                            after=skill,
                            source="character_state",
                            source_id=f"{source_id}.{key}",
                            metadata={"namespace": namespace, "field": key, "skill": skill},
                            dedupe_key=("skill", _text(skill).casefold()),
                        )
                    )
                continue

            previous_value = previous.get(field_key, _MISSING)
            previous[field_key] = deepcopy(value)
            if previous_value is not _MISSING and previous_value == value:
                continue
            if key in {"location", "current_location"}:
                category = "location"
                title = "位置变化"
            elif key in {"emotion", "current_emotion", "mood"}:
                category = "emotion"
                title = "情绪变化"
            elif key == "level":
                category = "progression"
                title = "等级变化"
            else:
                category = "state"
                title = "状态变化"
            candidates.append(
                _make_candidate(
                    chapter_number=chapter_number,
                    sequence=sequence * 100,
                    category=category,
                    title=title,
                    before=previous_value,
                    after=value,
                    source="character_state",
                    source_id=f"{source_id}.{key}",
                    metadata={"namespace": namespace, "field": key},
                    dedupe_key=("state", namespace, key),
                )
            )
    return candidates


def _named_progression_container(value: Any, wanted: str) -> Any:
    if isinstance(value, Mapping):
        direct = value.get(wanted)
        if isinstance(direct, Mapping):
            return direct
        for item in value.values():
            card = _mapping(item)
            if _text(card.get("name") or card.get("character_name")) == wanted:
                return card
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            card = _mapping(item)
            if _text(card.get("name") or card.get("character_name")) == wanted:
                return card
    return None


def _progression_events_for_character(payload: Mapping[str, Any], wanted: str) -> list[tuple[int, int, dict[str, Any], str]]:
    ledger = _mapping(payload.get("progression_ledger"))
    if not ledger:
        return []
    character = _character(payload, wanted)
    containers: list[tuple[str, Any]] = []
    protagonist = ledger.get("protagonist")
    if _is_protagonist_character(character):
        if isinstance(protagonist, Mapping):
            containers.append(("progression_ledger.protagonist", protagonist))
        else:
            containers.append(("progression_ledger", ledger))
    else:
        for key in (wanted, "characters", "by_character", "character_progression"):
            container = _named_progression_container(ledger.get(key), wanted) if key != wanted else ledger.get(key)
            if isinstance(container, Mapping):
                containers.append((f"progression_ledger.{key}.{wanted}", container))
    events: list[tuple[int, int, dict[str, Any], str]] = []
    seen_sources: set[tuple[int, int, str]] = set()
    for source, container in containers:
        for chapter_number, sequence, values, source_id in _explicit_events(
            container,
            source=source,
            allowed_keys=_PROGRESSION_EVENT_KEYS,
        ):
            if not _actor_matches(values, wanted):
                continue
            identity = (chapter_number, sequence, source_id)
            if identity in seen_sources:
                continue
            seen_sources.add(identity)
            events.append((chapter_number, sequence, dict(values), source_id))
        mapping = _mapping(container)
        for history_key in ("attribute_point_awards", "attribute_allocations"):
            history = mapping.get(history_key)
            if not isinstance(history, Sequence) or isinstance(history, (str, bytes, bytearray)):
                continue
            for history_sequence, item in enumerate(history):
                item_mapping = _mapping(item)
                chapter_number = _event_chapter(item_mapping)
                values = _event_value(item_mapping)
                if chapter_number is None or not values or not _actor_matches(values, wanted):
                    continue
                events.append(
                    (
                        chapter_number,
                        10_000 + history_sequence,
                        values,
                        f"{source}.{history_key}.{history_sequence}",
                    )
                )

    global_events = ledger.get("events")
    if isinstance(global_events, Sequence) and not isinstance(global_events, (str, bytes, bytearray)):
        for chapter_number, sequence, values, source_id in _explicit_events(
            global_events,
            source="progression_ledger.events",
            allowed_keys=(),
        ):
            # An unscoped global event can be safely attributed to the
            # protagonist fallback, but must not satisfy another character's
            # timeline.  Non-protagonists need an explicit actor reference.
            if not _is_protagonist_character(character) and not _has_actor_reference(values):
                continue
            if _actor_matches(values, wanted):
                events.append((chapter_number, 20_000 + sequence, dict(values), source_id))
    return sorted(events, key=lambda item: (item[0], item[1], item[3]))


def _transition_value(values: Mapping[str, Any], key: str, previous: Any) -> tuple[Any, Any]:
    before = previous
    for candidate in (f"{key}_before", f"previous_{key}", f"old_{key}"):
        if candidate in values:
            before = values[candidate]
            break
    after = values.get(key, _MISSING)
    for candidate in (f"{key}_after", f"new_{key}"):
        if candidate in values:
            after = values[candidate]
            break
    return before, after


def _progression_candidates(payload: Mapping[str, Any], wanted: str) -> list[_Candidate]:
    events = _progression_events_for_character(payload, wanted)
    candidates: list[_Candidate] = []
    previous: dict[str, Any] = {}
    known_skills: list[str] = []
    for chapter_number, sequence, raw_values, source_id in events:
        values = _clean_event_values(raw_values, meta_keys=_PROGRESSION_META_KEYS)
        if not values:
            continue
        level_before, level_after = _transition_value(values, "level", previous.get("level", _MISSING))
        if level_after is not _MISSING:
            previous["level"] = deepcopy(level_after)
            if level_before is _MISSING or level_before != level_after:
                candidates.append(
                    _make_candidate(
                        chapter_number=chapter_number,
                        sequence=sequence * 100,
                        category="progression",
                        title="等级变化",
                        before=level_before,
                        after=level_after,
                        source="progression_ledger",
                        source_id=f"{source_id}.level",
                        metadata={"field": "level"},
                        dedupe_key=("progression", "level"),
                    )
                )

        for key in _SKILL_KEYS:
            if key not in values:
                continue
            for skill in _skill_values(values[key]):
                if skill in known_skills:
                    continue
                known_skills.append(skill)
                candidates.append(
                    _make_candidate(
                        chapter_number=chapter_number,
                        sequence=sequence * 100 + len(known_skills),
                        category="skill",
                        title="获得技能",
                        before=None,
                        after=skill,
                        source="progression_ledger",
                        source_id=f"{source_id}.{key}",
                        metadata={"field": key, "skill": skill},
                        dedupe_key=("skill", _text(skill).casefold()),
                    )
                )

        for key in _ordered_keys(values):
            if key in {"level", *_SKILL_KEYS} or key in {
                "level_before",
                "level_after",
                "previous_level",
                "old_level",
                "new_level",
            }:
                continue
            if key not in _PROGRESSION_VALUE_KEYS:
                continue
            before = previous.get(key, _MISSING)
            after = values[key]
            previous[key] = deepcopy(after)
            if before is not _MISSING and before == after:
                continue
            candidates.append(
                _make_candidate(
                    chapter_number=chapter_number,
                    sequence=sequence * 100 + 50,
                    category="progression",
                    title="成长状态变化",
                    before=before,
                    after=after,
                    source="progression_ledger",
                    source_id=f"{source_id}.{key}",
                    metadata={"field": key},
                    dedupe_key=("progression", key),
                )
            )
    return candidates


def _equipment_cards(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_cards = payload.get("equipment_cards")
    if isinstance(raw_cards, Sequence) and not isinstance(raw_cards, (str, bytes, bytearray)):
        return [_mapping(item) for item in raw_cards if _mapping(item)]
    return []


def _equipment_observations(payload: Mapping[str, Any]) -> list[_EquipmentObservation]:
    observations: list[_EquipmentObservation] = []
    for card_index, card in enumerate(_equipment_cards(payload)):
        name = _text(card.get("name"))
        if not name:
            continue
        card_id = _text(card.get("id")) or name
        aliases_value = card.get("aliases")
        aliases = tuple(
            _text(item)
            for item in aliases_value
            if _text(item)
        ) if isinstance(aliases_value, Sequence) and not isinstance(aliases_value, (str, bytes, bytearray)) else ()
        events = list(_equipment_events(card))
        last_update = _chapter(card.get("last_update_chapter"), allow_zero=False)
        current_owner = _text(card.get("current_owner"))
        if current_owner and last_update is not None:
            # Match historical replay's explicitly dated current-card
            # fallback, while keeping an undated latest owner unknown.
            events.append((last_update, 1_000_000, {"current_owner": current_owner}, "equipment_card.current"))
        state: dict[str, Any] = {}
        for chapter_number, sequence, values, source in sorted(
            events,
            key=lambda item: (item[0], item[1], item[3]),
        ):
            previous = deepcopy(state)
            current = deepcopy(state)
            for key in _EQUIPMENT_FIELDS:
                if key in values and values[key] not in (None, ""):
                    current[key] = deepcopy(values[key])
            if current == previous:
                continue
            source_id = f"equipment_cards[{card_index}].{source}.{sequence}"
            observations.append(
                _EquipmentObservation(
                    card_id=card_id,
                    name=name,
                    aliases=aliases,
                    chapter_number=chapter_number,
                    sequence=card_index * 1_000_000 + sequence,
                    source_id=source_id,
                    previous=previous,
                    current=current,
                )
            )
            state = current
    return sorted(
        observations,
        key=lambda item: (item.chapter_number, item.sequence, item.source_id),
    )


def _equipment_candidates(payload: Mapping[str, Any], wanted: str) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for observation in _equipment_observations(payload):
        before_owner = _text(observation.previous.get("current_owner"))
        after_owner = _text(observation.current.get("current_owner"))
        owner_changed = before_owner != after_owner and (before_owner or after_owner)
        metadata_base = {
            "equipment_id": observation.card_id,
            "equipment_name": observation.name,
            "owner_before": before_owner or None,
            "owner_after": after_owner or None,
        }
        if owner_changed:
            if after_owner == wanted:
                candidates.append(
                    _make_candidate(
                        chapter_number=observation.chapter_number,
                        sequence=observation.sequence,
                        category="equipment",
                        title="获得装备",
                        before=None,
                        after=observation.name,
                        source="equipment_history",
                        source_id=f"{observation.source_id}.current_owner",
                        metadata={**metadata_base, "field": "current_owner", "owner": wanted},
                        dedupe_key=("equipment", observation.card_id, "acquire", wanted),
                    )
                )
            if before_owner == wanted:
                candidates.append(
                    _make_candidate(
                        chapter_number=observation.chapter_number,
                        sequence=observation.sequence + 1,
                        category="equipment",
                        title="失去装备",
                        before=observation.name,
                        after=None,
                        source="equipment_history",
                        source_id=f"{observation.source_id}.current_owner",
                        metadata={**metadata_base, "field": "current_owner", "owner": wanted},
                        dedupe_key=("equipment", observation.card_id, "lose", wanted),
                    )
                )

        if after_owner != wanted:
            continue
        for field_name in ("current_location", "durability", "status"):
            before = observation.previous.get(field_name, _MISSING)
            after = observation.current.get(field_name, _MISSING)
            if after is _MISSING or (before is not _MISSING and before == after):
                continue
            title = {
                "current_location": "装备位置变化",
                "durability": "装备耐久变化",
                "status": "装备状态变化",
            }[field_name]
            candidates.append(
                _make_candidate(
                    chapter_number=observation.chapter_number,
                    sequence=observation.sequence + 10,
                    category="equipment",
                    title=title,
                    before=before,
                    after=after,
                    source="equipment_history",
                    source_id=f"{observation.source_id}.{field_name}",
                    metadata={**metadata_base, "field": field_name, "owner": wanted},
                    dedupe_key=("equipment", observation.card_id, field_name),
                )
            )
    return candidates


def _equipment_identifier(item: Any) -> str:
    if isinstance(item, Mapping):
        for key in ("id", "name", "equipment_id", "equipment_name"):
            text = _text(item.get(key))
            if text:
                return text
        return ""
    return _text(item)


def _equipment_matches(observation: _EquipmentObservation, identifier: str) -> bool:
    wanted = identifier.casefold()
    return wanted in {
        observation.card_id.casefold(),
        observation.name.casefold(),
        *(item.casefold() for item in observation.aliases),
    }


def _equipment_owner_at(
    payload: Mapping[str, Any],
    identifier: str,
    boundary: int,
) -> dict[str, Any] | None:
    matches = [item for item in _equipment_observations(payload) if _equipment_matches(item, identifier)]
    if not matches:
        return None
    latest_by_card: dict[str, _EquipmentObservation] = {}
    for item in matches:
        if item.chapter_number > boundary or "current_owner" not in item.current:
            continue
        previous = latest_by_card.get(item.card_id)
        if previous is None or (item.chapter_number, item.sequence) > (previous.chapter_number, previous.sequence):
            latest_by_card[item.card_id] = item
    if not latest_by_card:
        return None
    owners = [
        item
        for item in latest_by_card.values()
        if _text(item.current.get("current_owner"))
    ]
    if not owners:
        return None
    selected = sorted(owners, key=lambda item: (item.chapter_number, item.sequence, item.card_id))[-1]
    return {
        "owner": _text(selected.current.get("current_owner")),
        "chapter": selected.chapter_number,
        "source": selected.source_id,
    }


def _knowledge_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("knowledge_ledger")
    if isinstance(raw, Mapping):
        values = [raw] if "fact_id" in raw else list(raw.values())
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        values = list(raw)
    else:
        values = []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in values:
        try:
            record = KnowledgeFact.model_validate(item).model_dump(mode="python")
        except (TypeError, ValueError):
            continue
        fact_id = _text(record.get("fact_id"))
        if not fact_id or fact_id in seen:
            continue
        seen.add(fact_id)
        records.append(record)
    return sorted(
        records,
        key=lambda item: (_chapter(item.get("learned_chapter")) or 0, _text(item.get("fact_id"))),
    )


def _knowledge_visible(record: Mapping[str, Any], wanted: str) -> bool:
    known_by = record.get("known_by")
    names = {
        _text(item)
        for item in known_by
        if _text(item)
    } if isinstance(known_by, Sequence) and not isinstance(known_by, (str, bytes, bytearray)) else set()
    return wanted in names or "*" in names or (record.get("visibility") == "public" and not names)


def _knowledge_candidates(payload: Mapping[str, Any], wanted: str) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for sequence, record in enumerate(_knowledge_records(payload)):
        if not _knowledge_visible(record, wanted):
            continue
        learned = _chapter(record.get("learned_chapter"))
        if learned is None:
            continue
        fact_id = _text(record.get("fact_id"))
        fact = _text(record.get("fact"))
        title = "认知更新" if _text(record.get("supersedes")) else "得知信息"
        candidates.append(
            _make_candidate(
                chapter_number=learned,
                sequence=sequence * 2,
                category="knowledge",
                title=title,
                before=None,
                after=fact,
                source="knowledge_ledger",
                source_id=fact_id,
                confidence=_text(record.get("certainty")) or "confirmed",
                metadata={
                    "fact_id": fact_id,
                    "visibility": record.get("visibility"),
                    "known_by": deepcopy(record.get("known_by") or []),
                    "supersedes": _text(record.get("supersedes")) or None,
                },
                dedupe_key=("knowledge", fact_id, "learned"),
            )
        )
        invalidated = _chapter(record.get("invalidated_chapter"))
        if invalidated is not None:
            candidates.append(
                _make_candidate(
                    chapter_number=invalidated,
                    sequence=sequence * 2 + 1,
                    category="knowledge",
                    title="知识失效",
                    before=fact,
                    after=None,
                    source="knowledge_ledger",
                    source_id=f"{fact_id}.invalidated",
                    confidence=_text(record.get("certainty")) or "confirmed",
                    metadata={"fact_id": fact_id, "event": "invalidated"},
                    dedupe_key=("knowledge", fact_id, "invalidated"),
                )
            )
    return candidates


def _relationship_candidates(payload: Mapping[str, Any], wanted: str) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    edges = sorted(
        _relationship_edges(payload, wanted),
        key=lambda item: (
            _text(item.get("id")),
            _text(item.get("source")),
            _text(item.get("target")),
        ),
    )
    for edge_index, edge in enumerate(edges):
        edge_id = _text(edge.get("id")) or f"{_text(edge.get('source'))}:{_text(edge.get('target'))}"
        source_name = _text(edge.get("source"))
        target_name = _text(edge.get("target"))
        other = target_name if source_name == wanted else source_name
        changes = [item for item in _event_list(edge.get("changes")) if isinstance(item, Mapping)]
        previous: dict[str, Any] = {}
        if changes:
            dated_changes = [
                (change_index, change, _event_chapter(change))
                for change_index, change in enumerate(changes)
            ]
            for change_index, change, chapter_number in sorted(
                dated_changes,
                key=lambda item: (item[2] is None, item[2] if item[2] is not None else 0, item[0]),
            ):
                if chapter_number is None:
                    continue
                values = {
                    key: deepcopy(change[key])
                    for key in _RELATIONSHIP_FIELDS
                    if key in change and change.get(key) is not None
                }
                if not values:
                    summary = _text(change.get("summary"))
                    if not summary:
                        continue
                    values = {"summary": summary}
                for field_name in _ordered_keys(values):
                    value = values[field_name]
                    before = previous.get(field_name, _MISSING)
                    previous[field_name] = deepcopy(value)
                    if before is not _MISSING and before == value:
                        continue
                    title = {
                        "trust": "信任变化",
                        "tension": "紧张变化",
                        "current_state": "关系状态变化",
                        "relation_type": "关系类型变化",
                        "bond": "关系变化",
                        "status": "关系状态变化",
                        "summary": "关系变化",
                    }.get(field_name, "关系变化")
                    candidates.append(
                        _make_candidate(
                            chapter_number=chapter_number,
                            sequence=edge_index * 1_000_000 + change_index * 100 + _FIELD_ORDER.get(field_name, 90),
                            category="relationship",
                            title=title,
                            before=before,
                            after=value,
                            source="relationship_graph",
                            source_id=f"relationship_graph.{edge_id}.changes.{change_index}.{field_name}",
                            summary=(
                                f"与{other}：{_transition_summary(title, before, value)}"
                                if field_name != "summary"
                                else f"与{other}：{value}"
                            ),
                            metadata={"relationship_id": edge_id, "target": other, "field": field_name},
                            dedupe_key=("relationship", edge_id, field_name),
                        )
                    )
            continue

        first_chapter = _chapter(edge.get("first_chapter"), allow_zero=False)
        if first_chapter is not None:
            for field_name in ("relation_type", "bond"):
                value = edge.get(field_name)
                if value in (None, ""):
                    continue
                candidates.append(
                    _make_candidate(
                        chapter_number=first_chapter,
                        sequence=edge_index * 1_000_000 + _FIELD_ORDER.get(field_name, 90),
                        category="relationship",
                        title="关系建立",
                        before=None,
                        after=value,
                        source="relationship_graph",
                        source_id=f"relationship_graph.{edge_id}.initial.{field_name}",
                        summary=f"与{other}：关系建立（{_display(value)}）",
                        metadata={"relationship_id": edge_id, "target": other, "field": field_name},
                        dedupe_key=("relationship", edge_id, field_name),
                    )
                )
        last_changed = _chapter(edge.get("last_changed_chapter"), allow_zero=False)
        if last_changed is not None:
            for field_name in ("trust", "tension", "current_state", "status"):
                value = edge.get(field_name)
                if value in (None, ""):
                    continue
                candidates.append(
                    _make_candidate(
                        chapter_number=last_changed,
                        sequence=edge_index * 1_000_000 + 100 + _FIELD_ORDER.get(field_name, 90),
                        category="relationship",
                        title="关系状态变化",
                        before=None,
                        after=value,
                        source="relationship_graph",
                        source_id=f"relationship_graph.{edge_id}.current.{field_name}",
                        summary=f"与{other}：关系状态变化为{_display(value)}",
                        metadata={"relationship_id": edge_id, "target": other, "field": field_name},
                        dedupe_key=("relationship", edge_id, field_name),
                    )
                )
    return candidates


def _appearance_candidates(payload: Mapping[str, Any], wanted: str) -> list[_Candidate]:
    records = payload.get("memory_index")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        return []
    found: list[tuple[int, int, Mapping[str, Any]]] = []
    for index, raw in enumerate(records):
        record = _mapping(raw)
        chapter_number = _chapter(record.get("chapter_number"), allow_zero=False)
        names = record.get("characters")
        if chapter_number is None or not isinstance(names, Sequence) or isinstance(names, (str, bytes, bytearray)):
            continue
        if wanted in {_text(item) for item in names}:
            found.append((chapter_number, index, record))
    found.sort(key=lambda item: (item[0], item[1]))
    candidates: list[_Candidate] = []
    for position, (chapter_number, index, record) in enumerate(found):
        title = "首次出场" if position == 0 else "出场记录"
        candidates.append(
            _make_candidate(
                chapter_number=chapter_number,
                sequence=index,
                category="appearance",
                title=title,
                before=None,
                after=wanted,
                source="memory_index",
                source_id=f"memory_index.{index}",
                summary=f"{title}：{wanted}",
                metadata={"memory_index_chapter": chapter_number},
                dedupe_key=("appearance", chapter_number),
            )
        )
    return candidates


def _candidate_key(candidate: _Candidate) -> tuple[Any, ...]:
    return (
        candidate.chapter_number,
        candidate.category,
        _canonical(candidate.dedupe_key),
        _canonical(candidate.after),
    )


def _finalize_candidates(candidates: Sequence[_Candidate], wanted: str) -> list[CharacterTimelineEvent]:
    selected: dict[tuple[Any, ...], _Candidate] = {}
    for candidate in candidates:
        key = _candidate_key(candidate)
        current = selected.get(key)
        if current is None or (
            candidate.source_rank,
            candidate.sequence,
            candidate.source_id,
        ) < (
            current.source_rank,
            current.sequence,
            current.source_id,
        ):
            selected[key] = candidate

    ordered = sorted(
        selected.values(),
        key=lambda item: (
            item.chapter_number,
            item.sequence,
            item.source_rank,
            item.source_id,
            item.category,
        ),
    )
    result: list[CharacterTimelineEvent] = []
    for candidate in ordered:
        event_seed = _canonical(
            {
                "character_name": wanted,
                "chapter_number": candidate.chapter_number,
                "category": candidate.category,
                "dedupe_key": candidate.dedupe_key,
                "before": candidate.before,
                "after": candidate.after,
            }
        )
        event_id = f"character-event-{sha1(event_seed.encode('utf-8')).hexdigest()[:16]}"
        result.append(
            CharacterTimelineEvent(
                event_id=event_id,
                chapter_number=candidate.chapter_number,
                character_name=wanted,
                category=candidate.category,
                title=candidate.title,
                summary=candidate.summary,
                before=candidate.before,
                after=candidate.after,
                source=candidate.source,
                source_id=candidate.source_id,
                confidence=candidate.confidence,
                metadata=candidate.metadata,
            )
        )
    return result


def get_character_timeline(
    story_state: Any,
    character_name: str,
    *,
    start_chapter: int | None = None,
    end_chapter: int | None = None,
) -> list[CharacterTimelineEvent]:
    """Aggregate a character's explicit structured history in one pass.

    Missing or undated latest-card fields are intentionally absent.  The
    function never reads chapter prose and never mutates ``story_state``.
    """

    payload = _story_payload(story_state)
    wanted = _text(character_name)
    _character(payload, wanted)
    start = 0 if start_chapter is None else _query_boundary(start_chapter, label="start_chapter")
    end = None if end_chapter is None else _query_boundary(end_chapter, label="end_chapter")
    if end is not None and start > end:
        raise ValueError("start_chapter must be <= end_chapter")

    candidates = [
        *_state_candidates(payload, wanted),
        *_progression_candidates(payload, wanted),
        *_equipment_candidates(payload, wanted),
        *_knowledge_candidates(payload, wanted),
        *_relationship_candidates(payload, wanted),
        *_appearance_candidates(payload, wanted),
    ]
    events = _finalize_candidates(candidates, wanted)
    return [
        item
        for item in events
        if item.chapter_number >= start and (end is None or item.chapter_number <= end)
    ]


def _context_payload(planned_context: Any, wanted: str) -> dict[str, Any]:
    if planned_context is None:
        return {}
    context = _mapping(planned_context)
    if not context:
        raise ValueError("planned_context must be an object")
    context_name = _text(context.get("character_name"))
    if context_name and context_name != wanted:
        raise ValueError("planned_context character_name does not match character")
    return context


def _items(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return list(value)
    return []


def _planned_names(context: Mapping[str, Any], *keys: str) -> list[str]:
    result: list[str] = []
    for key in keys:
        for raw in _items(context.get(key)):
            value = _skill_name(raw) if isinstance(raw, Mapping) and ("skill" in raw or "skill_id" in raw) else _equipment_identifier(raw) if isinstance(raw, Mapping) else _text(raw)
            if value and value not in result:
                result.append(value)
    return result


def _planned_skills(context: Mapping[str, Any]) -> list[str]:
    values = _planned_names(context, "skills_used")
    if not values and "skills" in context:
        values = _planned_names(context, "skills")
    return values


def _planned_equipment(context: Mapping[str, Any]) -> list[str]:
    values = _planned_names(context, "equipment_used")
    if not values and "equipment" in context:
        values = _planned_names(context, "equipment")
    return values


def _historical_location(historical: Any) -> tuple[Any, dict[str, Any]]:
    for namespace in ("current_state", "game_state", "real_state"):
        state = getattr(historical, namespace, {})
        if not isinstance(state, Mapping):
            continue
        for field_name in ("location", "current_location"):
            if state.get(field_name) not in (None, ""):
                evidence_key = f"{namespace}.{field_name}"
                return state[field_name], getattr(historical, "evidence", {}).get(evidence_key, {})
    return None, {}


def _historical_skills(historical: Any) -> set[str]:
    values: list[str] = []
    for container in (
        getattr(historical, "progression", {}),
        getattr(historical, "game_state", {}),
    ):
        if not isinstance(container, Mapping):
            continue
        for key in ("skills", "skill", "learned_skills"):
            values.extend(_skill_values(container.get(key)))
    return {item.casefold() for item in values if item}


def _future_skill_events(
    payload: Mapping[str, Any],
    wanted: str,
    boundary: int,
    skills: Sequence[str],
) -> dict[str, CharacterTimelineEvent]:
    wanted_keys = {skill.casefold() for skill in skills if skill}
    if not wanted_keys:
        return {}
    matching: dict[str, CharacterTimelineEvent] = {}
    for item in get_character_timeline(payload, wanted):
        key = _text(item.after).casefold()
        if (
            item.category == "skill"
            and item.chapter_number > boundary
            and key in wanted_keys
            and key not in matching
        ):
            matching[key] = item
    return matching


def _relationship_expectations(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        if any(key in value for key in ("target", "character", "trust", "trust_min", "tension", "status")):
            return [dict(value)]
        result: list[dict[str, Any]] = []
        for target, expectation in value.items():
            item = _mapping(expectation)
            if item:
                result.append({"target": target, **item})
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


def _other_relationship(edge: Mapping[str, Any], wanted: str) -> str:
    source = _text(edge.get("source"))
    target = _text(edge.get("target"))
    return target if source == wanted else source


def _relationship_warning_value(expectation: Mapping[str, Any], field_name: str) -> tuple[Any, str] | None:
    aliases = {
        "trust": ("trust", "trust_min", "min_trust", "trust_gte", "trust_at_least"),
        "tension": ("tension", "tension_min", "min_tension", "tension_gte", "tension_at_least"),
    }
    for key in aliases.get(field_name, (field_name,)):
        if key in expectation:
            return expectation[key], key
    return None


def check_character_consistency(
    story_state: Any,
    character_name: str,
    *,
    target_chapter: int,
    planned_context: Any = None,
) -> list[ConsistencyWarning]:
    """Check a structured plan against state at the start of a chapter.

    Unknown historical values intentionally produce no warning.  A warning is
    emitted only when an explicit future event proves that a requested skill
    or fact is unavailable, or when an explicit historical value contradicts
    the plan.
    """

    payload = _story_payload(story_state)
    wanted = _text(character_name)
    _character(payload, wanted)
    target = _query_boundary(target_chapter, label="target_chapter", allow_zero=False)
    boundary = target - 1
    context = _context_payload(planned_context, wanted)
    if not context:
        return []

    historical = get_character_state_for_writer(payload, wanted, boundary)
    warnings: list[ConsistencyWarning] = []

    expected_location = context.get("location")
    if expected_location not in (None, ""):
        observed_location, evidence = _historical_location(historical)
        if observed_location not in (None, "") and _text(observed_location) != _text(expected_location):
            warnings.append(
                ConsistencyWarning(
                    code="LOCATION_MISMATCH",
                    character_name=wanted,
                    target_chapter=target,
                    message=f"第{target}章计划位置与历史位置不一致。",
                    expected=expected_location,
                    observed=observed_location,
                    evidence=evidence or {"boundary": boundary},
                    source="character_state",
                    suggestion="确认计划是否包含明确的移动事件，或改用历史位置。",
                )
            )

    historical_skills = _historical_skills(historical)
    planned_skills = _planned_skills(context)
    future_skill_events = _future_skill_events(payload, wanted, boundary, planned_skills)
    for skill in planned_skills:
        if skill.casefold() in historical_skills:
            continue
        future_event = future_skill_events.get(skill.casefold())
        if future_event is None:
            continue
        warnings.append(
            ConsistencyWarning(
                code="SKILL_NOT_YET_ACQUIRED",
                character_name=wanted,
                target_chapter=target,
                message=f"第{target}章计划使用技能“{skill}”，但历史记录显示该技能尚未获得。",
                expected=skill,
                observed={"acquired_chapter": future_event.chapter_number},
                evidence={
                    "event_id": future_event.event_id,
                    "source": future_event.source,
                    "source_id": future_event.source_id,
                },
                source="progression_ledger",
                suggestion=f"将使用时间移至第{future_event.chapter_number}章之后，或补充明确的获得事件。",
            )
        )

    for equipment in _planned_equipment(context):
        owner = _equipment_owner_at(payload, equipment, boundary)
        if owner is None or owner.get("owner") in {"", wanted}:
            continue
        warnings.append(
            ConsistencyWarning(
                code="EQUIPMENT_NOT_OWNED",
                character_name=wanted,
                target_chapter=target,
                message=f"第{target}章计划使用“{equipment}”，但历史所有者不是该角色。",
                expected={"equipment": equipment, "owner": wanted},
                observed={"owner": owner["owner"], "chapter": owner["chapter"]},
                evidence={"source": owner.get("source", ""), "boundary": boundary},
                source="equipment_history",
                suggestion="确认装备转移是否已经发生，或改为当前历史所有者。",
            )
        )

    records = _knowledge_records(payload)
    by_id = {_text(item.get("fact_id")): item for item in records}
    fact_ids = _planned_names(context, "knowledge_fact_ids")
    fact_texts = _planned_names(context, "knowledge_facts")
    if not fact_ids and not fact_texts and "knowledge" in context:
        fact_ids = _planned_names(context, "knowledge")
    selected_records: list[dict[str, Any]] = []
    for fact_id in fact_ids:
        record = by_id.get(fact_id)
        if record is not None and record not in selected_records:
            selected_records.append(record)
    for fact_text in fact_texts:
        for record in records:
            if _text(record.get("fact")) == fact_text and _knowledge_visible(record, wanted) and record not in selected_records:
                selected_records.append(record)
    for record in selected_records:
        if not _knowledge_visible(record, wanted):
            # Do not expose or infer another character's private fact.
            continue
        learned = _chapter(record.get("learned_chapter"))
        reveal = _chapter(record.get("reveal_chapter"))
        available_from = max(item for item in (learned, reveal) if item is not None) if any(item is not None for item in (learned, reveal)) else None
        if available_from is None or available_from <= boundary:
            continue
        fact_id = _text(record.get("fact_id"))
        warnings.append(
            ConsistencyWarning(
                code="KNOWLEDGE_NOT_YET_LEARNED",
                character_name=wanted,
                target_chapter=target,
                message=f"第{target}章计划使用的信息尚未对该角色可用。",
                expected=fact_id,
                observed={"available_chapter": available_from},
                evidence={
                    "fact_id": fact_id,
                    "learned_chapter": learned,
                    "reveal_chapter": reveal,
                    "visibility": record.get("visibility"),
                },
                source="knowledge_ledger",
                suggestion=f"将引用时间移至第{available_from}章之后，或先安排明确的信息揭示。",
            )
        )

    relationships = getattr(historical, "relationships", [])
    for expectation in _relationship_expectations(context.get("relationship_expectations")):
        target_name = _text(expectation.get("target") or expectation.get("character"))
        if not target_name:
            continue
        edge = next(
            (
                item
                for item in relationships
                if isinstance(item, Mapping) and _other_relationship(item, wanted) == target_name
            ),
            None,
        )
        if edge is None:
            continue
        mismatch: tuple[str, Any, Any, str] | None = None
        for field_name in ("trust", "tension", "status", "relation_type", "bond", "current_state"):
            requested = _relationship_warning_value(expectation, field_name)
            if requested is None or edge.get(field_name) in (None, ""):
                continue
            expected_value, requested_key = requested
            observed_value = edge.get(field_name)
            if field_name in {"trust", "tension"}:
                try:
                    mismatch_found = float(observed_value) < float(expected_value)
                except (TypeError, ValueError):
                    continue
            else:
                mismatch_found = _text(observed_value) != _text(expected_value)
            if mismatch_found:
                mismatch = (field_name, expected_value, observed_value, requested_key)
                break
        if mismatch is None:
            continue
        field_name, expected_value, observed_value, requested_key = mismatch
        relationship_id = _text(edge.get("id"))
        evidence = edge.get("evidence") if isinstance(edge.get("evidence"), Mapping) else {}
        warnings.append(
            ConsistencyWarning(
                code="RELATIONSHIP_STATE_MISMATCH",
                character_name=wanted,
                target_chapter=target,
                message=f"第{target}章计划假定与{target_name}的关系状态超出历史边界。",
                expected={"target": target_name, requested_key: expected_value},
                observed=observed_value,
                evidence={"relationship_id": relationship_id, "boundary": boundary, "fields": evidence},
                source="relationship_graph",
                suggestion="按第{0}章时的关系状态调整计划，或先安排关系变化。".format(target),
            )
        )

    return sorted(
        warnings,
        key=lambda item: (item.code, _canonical(item.expected), _canonical(item.observed)),
    )


__all__ = [
    "CharacterPlanContext",
    "CharacterTimelineEvent",
    "ConsistencyWarning",
    "check_character_consistency",
    "get_character_timeline",
]
