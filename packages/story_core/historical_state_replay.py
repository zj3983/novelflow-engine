from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from packages.story_core.attribute_allocation import (
    normalize_attribute_allocation_rule,
    rebuild_attribute_progression,
)
from packages.story_core.foreshadowing import (
    canonicalize_foreshadowing_ledger,
    normalize_foreshadowing_text,
    reconcile_foreshadowing,
)
from packages.story_core.models import ForeshadowingState, StoryState


_EVENT_CONTAINER_KEYS = (
    "history",
    "state_history",
    "state_changes",
    "changes",
    "recent_changes",
    "snapshots",
    "events",
)
_BASELINE_KEYS = ("baseline", "initial", "initial_state")
_EVENT_META_KEYS = {
    "chapter",
    "chapter_number",
    "as_of_chapter",
    "fact",
    "summary",
    "evidence",
    "source",
    "confidence",
    "line",
    "scene_line",
    "state_line",
    "namespace",
    "updated_chapter",
    "last_appearance_chapter",
    "last_update_chapter",
    "first_appearance_chapter",
}
_STATE_EVENT_PAYLOAD_KEYS = ("current", "state", "delta", "state_delta", "value")
_STATE_NAMESPACE_KEYS = ("current_state", "real_state", "game_state")
_PROGRESSION_EVENT_KEYS = (
    "events",
    "history",
    "progression_history",
    "level_history",
    "changes",
    "snapshots",
)
_EQUIPMENT_MUTABLE_FIELDS = (
    "current_owner",
    "current_location",
    "durability",
    "status",
)
_PROGRESSION_HISTORY_FIELDS = (
    "attribute_point_awards",
    "attribute_allocations",
)


@dataclass(frozen=True)
class HistoricalCharacterState:
    """Read-only, chapter-bounded character projection.

    The projection intentionally contains only values supported by explicit
    chapter-tagged evidence.  Fields that exist only on the latest character
    mirror are omitted and listed in ``unknown_fields`` instead.
    """

    character_name: str
    as_of_chapter: int
    profile: dict[str, Any]
    current_state: dict[str, Any]
    real_state: dict[str, Any]
    game_state: dict[str, Any]
    relationships: list[dict[str, Any]]
    progression: dict[str, Any]
    equipment: list[dict[str, Any]]
    evidence: dict[str, dict[str, Any]]
    unknown_fields: tuple[str, ...] = ()

    @property
    def location(self) -> Any:
        return self.current_state.get("location")

    @property
    def current_emotion(self) -> Any:
        return self.current_state.get("emotion") or self.current_state.get("current_emotion")

    @property
    def current_goal(self) -> Any:
        return self.current_state.get("current_goal") or self.current_state.get("goal")

    @property
    def immediate_problem(self) -> Any:
        return self.current_state.get("immediate_problem")

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_name": self.character_name,
            "as_of_chapter": self.as_of_chapter,
            "profile": deepcopy(self.profile),
            "current_state": deepcopy(self.current_state),
            "real_state": deepcopy(self.real_state),
            "game_state": deepcopy(self.game_state),
            "relationships": deepcopy(self.relationships),
            "progression": deepcopy(self.progression),
            "equipment": deepcopy(self.equipment),
            "evidence": deepcopy(self.evidence),
            "unknown_fields": list(self.unknown_fields),
        }


def _replay_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                dumped = model_dump(mode="python")
                return dict(dumped) if isinstance(dumped, Mapping) else {}
            except TypeError:
                pass
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="python")
            return dict(dumped) if isinstance(dumped, Mapping) else {}
        except TypeError:
            return {}
    return {}


def _chapter_number(value: Any, *, allow_zero: bool = True) -> int | None:
    if isinstance(value, bool) or isinstance(value, float) and not value.is_integer():
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < (0 if allow_zero else 1):
        return None
    return number


def _event_chapter(event: Mapping[str, Any], *, default: int | None = None) -> int | None:
    for key in ("chapter", "chapter_number", "as_of_chapter"):
        if key in event:
            return _chapter_number(event.get(key))
    return default


def _event_value(event: Mapping[str, Any]) -> dict[str, Any]:
    for key in _STATE_EVENT_PAYLOAD_KEYS:
        value = event.get(key)
        if isinstance(value, Mapping):
            return {
                str(item_key): deepcopy(item_value)
                for item_key, item_value in value.items()
                if str(item_key) not in _EVENT_META_KEYS
                and item_value not in (None, "")
            }
    direct = {
        str(key): deepcopy(value)
        for key, value in event.items()
        if str(key) not in _EVENT_META_KEYS
        and str(key) not in _STATE_EVENT_PAYLOAD_KEYS
        and value not in (None, "")
    }
    return direct


def _event_list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    if isinstance(value, Mapping):
        if "chapter" not in value and "chapter_number" not in value and "as_of_chapter" not in value:
            keyed = []
            for key, item in value.items():
                chapter = _chapter_number(key)
                if chapter is None or not isinstance(item, Mapping):
                    keyed = []
                    break
                keyed.append({"chapter": chapter, **dict(item)})
            if keyed:
                return keyed
        return [value]
    return []


def _explicit_events(
    container: Any,
    *,
    source: str,
    include_baseline: bool = True,
    allowed_keys: Sequence[str] = _EVENT_CONTAINER_KEYS,
) -> list[tuple[int, int, dict[str, Any], str]]:
    """Collect structured events without interpreting prose fields."""

    payload = _replay_payload(container)
    collected: list[tuple[int, int, dict[str, Any], str]] = []
    sequence = 0

    if include_baseline:
        for key in _BASELINE_KEYS:
            baseline = payload.get(key)
            if not isinstance(baseline, Mapping):
                continue
            event = dict(baseline)
            event.setdefault("chapter", 0)
            values = _event_value(event)
            chapter = _event_chapter(event)
            if values and chapter is not None:
                collected.append((chapter, sequence, values, f"{source}.{key}"))
                sequence += 1

    for key in allowed_keys:
        if key not in payload:
            continue
        for item in _event_list(payload.get(key)):
            if not isinstance(item, Mapping):
                continue
            chapter = _event_chapter(item)
            values = _event_value(item)
            if chapter is None or not values:
                continue
            collected.append((chapter, sequence, values, f"{source}.{key}"))
            sequence += 1

    # A namespace may itself be a list of fully structured events.
    if isinstance(container, Sequence) and not isinstance(container, (str, bytes, bytearray)):
        for item in container:
            if not isinstance(item, Mapping):
                continue
            chapter = _event_chapter(item)
            values = _event_value(item)
            if chapter is None or not values:
                continue
            collected.append((chapter, sequence, values, source))
            sequence += 1
    return collected


def _record_evidence(
    evidence: dict[str, dict[str, Any]],
    path: str,
    value: Any,
    chapter: int,
    source: str,
) -> None:
    evidence[path] = {
        "value": deepcopy(value),
        "chapter": chapter,
        "source": source,
    }


def _replay_events(
    events: Sequence[tuple[int, int, dict[str, Any], str]],
    *,
    as_of_chapter: int,
    path_prefix: str,
    evidence: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for chapter, sequence, values, source in sorted(events, key=lambda item: (item[0], item[1])):
        del sequence
        if chapter > as_of_chapter:
            continue
        for key, value in values.items():
            if value is None:
                continue
            normalized_key = str(key).strip()
            if not normalized_key:
                continue
            result[normalized_key] = deepcopy(value)
            _record_evidence(
                evidence,
                f"{path_prefix}.{normalized_key}",
                value,
                chapter,
                source,
            )
    return result


def _stable_profile(character: Mapping[str, Any]) -> dict[str, Any]:
    # current_life_profile and story_drive contain immediate_problem and
    # immediate_goal respectively; they are latest-facing, not stable.
    profile: dict[str, Any] = {}
    for key in (
        "role",
        "importance",
        "narrative_function",
        "character_tier",
        "story_function",
        "character_type",
        "core_motivation",
        "behavior_logic",
        "interaction_mode",
        "identity_profile",
        "background_profile",
        "performance_profile",
        "npc_profile",
        "personality_portrait",
        "traits",
    ):
        if key in character and character.get(key) not in (None, "", [], {}):
            profile[key] = deepcopy(character[key])
    if "importance" not in profile and profile.get("character_tier") not in (None, ""):
        profile["importance"] = deepcopy(profile["character_tier"])
    if "narrative_function" not in profile and profile.get("story_function") not in (None, ""):
        profile["narrative_function"] = deepcopy(profile["story_function"])
    return profile


def _state_events(
    character: Mapping[str, Any],
    namespace: str,
) -> list[tuple[int, int, dict[str, Any], str]]:
    events: list[tuple[int, int, dict[str, Any], str]] = []
    container = character.get(namespace)
    events.extend(
        _explicit_events(
            container,
            source=f"character.{namespace}",
        )
    )
    if namespace == "current_state":
        for key in ("state_changes", "state_history", "state_events"):
            if key in character:
                events.extend(
                    _explicit_events(
                        character.get(key),
                        source=f"character.{key}",
                        allowed_keys=(),
                    )
                )
    else:
        direct_key = f"{namespace}_changes"
        if direct_key in character:
            events.extend(
                _explicit_events(
                    character.get(direct_key),
                    source=f"character.{direct_key}",
                    allowed_keys=(),
                )
            )
    return events


def _raw_current_fields(container: Any) -> set[str]:
    payload = _replay_payload(container)
    current = payload.get("current")
    if isinstance(current, Mapping):
        return {
            str(key)
            for key in current
            if str(key) not in _EVENT_META_KEYS
        }
    return set()


def _relationship_edges(story: Mapping[str, Any], character_name: str) -> list[Mapping[str, Any]]:
    raw = story.get("relationship_graph")
    edges: list[Mapping[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            names = {
                str(item.get("source") or "").strip(),
                str(item.get("target") or "").strip(),
            }
            if character_name not in names:
                continue
            pair = tuple(sorted(names))
            if len(pair) == 2 and pair not in seen_pairs:
                edges.append(item)
                seen_pairs.add(pair)
    character = next(
        (
            item
            for item in story.get("characters", [])
            if isinstance(item, Mapping) and str(item.get("name") or "").strip() == character_name
        ),
        None,
    )
    if isinstance(character, Mapping):
        relations = character.get("relationships")
        if isinstance(relations, Mapping):
            relations = [
                {**dict(value), "target": value.get("target") or key, "source": character_name}
                for key, value in relations.items()
                if isinstance(value, Mapping)
            ]
        elif isinstance(relations, Sequence) and not isinstance(relations, (str, bytes, bytearray)):
            relations = [
                {**dict(value), "source": value.get("source") or character_name}
                for value in relations
                if isinstance(value, Mapping)
            ]
        else:
            relations = []
        for relation in relations:
            names = {
                str(relation.get("source") or "").strip(),
                str(relation.get("target") or "").strip(),
            }
            pair = tuple(sorted(names))
            if len(pair) == 2 and pair not in seen_pairs:
                edges.append(relation)
                seen_pairs.add(pair)
    return edges


def _replay_relationships(
    story: Mapping[str, Any],
    character_name: str,
    *,
    as_of_chapter: int,
    evidence: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for edge in _relationship_edges(story, character_name):
        changes = [
            item for item in _event_list(edge.get("changes")) if isinstance(item, Mapping)
        ]
        changes_with_values: list[tuple[int, int, dict[str, Any], str]] = []
        for sequence, change in enumerate(changes):
            chapter = _event_chapter(change)
            if chapter is None:
                continue
            values = {
                key: deepcopy(change[key])
                for key in ("trust", "tension", "current_state", "relation_type", "bond", "status")
                if key in change and change.get(key) is not None
            }
            if values:
                changes_with_values.append(
                    (chapter, sequence, values, "relationship_graph.changes")
                )
        first_chapter = _chapter_number(edge.get("first_chapter"))
        known_chapters = [item[0] for item in changes_with_values]
        if first_chapter is not None and first_chapter > as_of_chapter:
            continue
        if first_chapter in (None, 0) and known_chapters and min(known_chapters) > as_of_chapter:
            continue
        if first_chapter is None and not known_chapters:
            first_chapter = 0

        values: dict[str, Any] = {}
        for field in ("relation_type", "bond"):
            value = edge.get(field)
            if value not in (None, "") and not changes_with_values:
                values[field] = deepcopy(value)
        relation_evidence: dict[str, dict[str, Any]] = {}
        for chapter, sequence, change_values, source in sorted(
            changes_with_values, key=lambda item: (item[0], item[1])
        ):
            del sequence
            if chapter > as_of_chapter:
                continue
            for field, value in change_values.items():
                values[field] = deepcopy(value)
                relation_evidence[field] = {
                    "value": deepcopy(value),
                    "chapter": chapter,
                    "source": source,
                }
        # A top-level score is usable only when it is explicitly anchored to
        # a chapter and no change history contradicts that boundary.
        if not changes_with_values:
            last_changed = _chapter_number(edge.get("last_changed_chapter"))
            if last_changed is not None and last_changed > 0 and last_changed <= as_of_chapter:
                for field in ("trust", "tension"):
                    if edge.get(field) not in (None, ""):
                        values[field] = deepcopy(edge[field])
        source_name = str(edge.get("source") or character_name).strip()
        target_name = str(edge.get("target") or "").strip()
        if not target_name:
            continue
        identifier = str(edge.get("id") or f"{source_name}:{target_name}")
        output = {
            "id": identifier,
            "source": source_name,
            "target": target_name,
            **values,
        }
        if relation_evidence:
            output["evidence"] = relation_evidence
            for field, item in relation_evidence.items():
                evidence[f"relationships.{identifier}.{field}"] = deepcopy(item)
        projected.append(output)
    return sorted(projected, key=lambda item: (str(item.get("id") or ""), str(item.get("target") or "")))


def _progression_events(ledger: Mapping[str, Any]) -> list[tuple[int, int, dict[str, Any], str]]:
    protagonist = ledger.get("protagonist")
    source = "progression_ledger.protagonist"
    container = protagonist if isinstance(protagonist, Mapping) else ledger
    events = _explicit_events(
        container,
        source=source,
        allowed_keys=_PROGRESSION_EVENT_KEYS,
    )
    if isinstance(ledger.get("events"), Sequence):
        if container is ledger:
            return events
        events.extend(
            _explicit_events(
                ledger.get("events"),
                source="progression_ledger.events",
                allowed_keys=(),
            )
        )
    return events


def _is_protagonist_character(character: Mapping[str, Any]) -> bool:
    role = str(character.get("role") or "").strip().casefold()
    tier = str(character.get("character_tier") or "").strip().casefold()
    return role in {"protagonist", "主角"} or tier in {"protagonist", "主角"}


def _replay_progression(
    story: Mapping[str, Any],
    character: Mapping[str, Any],
    *,
    as_of_chapter: int,
    evidence: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not _is_protagonist_character(character):
        return {}
    raw_ledger = story.get("progression_ledger")
    ledger = raw_ledger if isinstance(raw_ledger, Mapping) else {}
    result = _replay_events(
        _progression_events(ledger),
        as_of_chapter=as_of_chapter,
        path_prefix="progression",
        evidence=evidence,
    )
    protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), Mapping) else {}
    for field in _PROGRESSION_HISTORY_FIELDS:
        history = protagonist.get(field)
        if not isinstance(history, Sequence) or isinstance(history, (str, bytes, bytearray)):
            continue
        bounded: list[tuple[int, int, dict[str, Any]]] = []
        for sequence, item in enumerate(history):
            if not isinstance(item, Mapping):
                continue
            chapter = _event_chapter(item)
            if chapter is None or chapter > as_of_chapter:
                continue
            bounded.append((chapter, sequence, deepcopy(dict(item))))
            _record_evidence(
                evidence,
                f"progression.{field}.{sequence}",
                item,
                chapter,
                f"progression_ledger.protagonist.{field}",
            )
        if bounded:
            result[field] = [
                item
                for _, _, item in sorted(bounded, key=lambda value: (value[0], value[1]))
            ]
    return result


def _equipment_events(card: Mapping[str, Any]) -> list[tuple[int, int, dict[str, Any], str]]:
    events = _explicit_events(
        card,
        source="equipment_card",
        allowed_keys=("history", "state_history", "state_changes", "changes", "snapshots", "events"),
    )
    aliases = {
        "current_owner": ("current_owner", "owner"),
        "current_location": ("current_location", "location"),
        "durability": ("durability",),
        "status": ("status",),
    }
    normalized: list[tuple[int, int, dict[str, Any], str]] = []
    for chapter, sequence, values, source in events:
        canonical = {
            field: deepcopy(values[key])
            for field, keys in aliases.items()
            for key in keys
            if key in values and values[key] not in (None, "")
        }
        if canonical:
            normalized.append((chapter, sequence, canonical, source))
    for sequence, item in enumerate(_event_list(card.get("evidence"))):
        if not isinstance(item, Mapping):
            continue
        chapter = _event_chapter(item)
        if chapter is None:
            continue
        values = _event_value(item)
        canonical = {
            field: deepcopy(values[key])
            for field, keys in aliases.items()
            for key in keys
            if key in values and values[key] not in (None, "")
        }
        if canonical:
            normalized.append((chapter, sequence, canonical, "equipment_card.evidence"))
    return normalized


def _replay_equipment(
    story: Mapping[str, Any],
    character_name: str,
    *,
    as_of_chapter: int,
    evidence: dict[str, dict[str, Any]],
    unknown_fields: set[str],
) -> list[dict[str, Any]]:
    raw_cards = story.get("equipment_cards")
    if not isinstance(raw_cards, Sequence) or isinstance(raw_cards, (str, bytes, bytearray)):
        return []
    projected: list[dict[str, Any]] = []
    for raw_card in raw_cards:
        if not isinstance(raw_card, Mapping):
            continue
        card = dict(raw_card)
        events = _equipment_events(card)
        dated_evidence = [
            _chapter_number(item.get("chapter"), allow_zero=False)
            for item in _event_list(card.get("evidence"))
            if isinstance(item, Mapping)
        ]
        dated_evidence = [item for item in dated_evidence if item is not None]
        first = _chapter_number(card.get("first_appearance_chapter"), allow_zero=False)
        if first is None:
            event_chapters = [item[0] for item in events if item[0] > 0]
            first = min([*dated_evidence, *event_chapters], default=None)
        if first is None or first > as_of_chapter:
            continue
        last_update = _chapter_number(card.get("last_update_chapter"), allow_zero=False)
        bounded_values: dict[str, tuple[Any, int, str]] = {}
        for chapter, sequence, values, source in sorted(events, key=lambda item: (item[0], item[1])):
            del sequence
            if chapter > as_of_chapter:
                continue
            for field in _EQUIPMENT_MUTABLE_FIELDS:
                if field in values and values[field] is not None:
                    bounded_values[field] = (deepcopy(values[field]), chapter, source)

        # Existence and first appearance do not identify a holder.  Attach a
        # card only after an explicit owner event (or an explicitly dated
        # current card) matches the queried character.
        owner = bounded_values.get("current_owner")
        if owner is None and (
            last_update is not None
            and last_update <= as_of_chapter
            and card.get("current_owner") not in (None, "")
        ):
            owner = (
                deepcopy(card["current_owner"]),
                last_update,
                "equipment_card.current",
            )
        if owner is None or str(owner[0]).strip() != character_name:
            continue
        output: dict[str, Any] = {}
        for field in (
            "id",
            "name",
            "equipment_type",
            "slot",
            "rarity",
            "required_level",
            "class_restrictions",
            "base_attributes",
            "special_effects",
            "skills",
            "first_appearance_chapter",
        ):
            value = card.get(field)
            if value not in (None, "", [], {}):
                output[field] = deepcopy(value)
        output.setdefault("first_appearance_chapter", first)
        for field in _EQUIPMENT_MUTABLE_FIELDS:
            if field in bounded_values:
                value, chapter, source = bounded_values[field]
                output[field] = value
                _record_evidence(evidence, f"equipment.{output.get('id', output.get('name', ''))}.{field}", value, chapter, source)
            elif last_update is not None and last_update <= as_of_chapter and card.get(field) not in (None, ""):
                value = deepcopy(card[field])
                output[field] = value
                _record_evidence(
                    evidence,
                    f"equipment.{output.get('id', output.get('name', ''))}.{field}",
                    value,
                    last_update,
                    "equipment_card.current",
                )
            elif card.get(field) not in (None, ""):
                unknown_fields.add(f"equipment.{output.get('id', output.get('name', ''))}.{field}")
        projected.append(output)
    return sorted(projected, key=lambda item: (str(item.get("id") or ""), str(item.get("name") or "")))


def _get_character_state(
    story_state: StoryState | Mapping[str, Any],
    character_name: str,
    as_of_chapter: int,
    *,
    allow_zero: bool,
) -> HistoricalCharacterState:
    """Return the character state at the end of ``as_of_chapter``.

    Only explicit, chapter-tagged state deltas are replayed.  The latest
    values on a character card, panel, ledger, relationship edge, or item
    card are never used as an earlier answer without a chapter anchor.
    """

    if isinstance(as_of_chapter, bool) or not isinstance(as_of_chapter, int):
        target = None
    else:
        target = _chapter_number(as_of_chapter, allow_zero=allow_zero)
    if target is None:
        boundary_label = "non-negative integer" if allow_zero else "positive integer"
        raise ValueError(f"as_of_chapter must be a {boundary_label}")
    story = _replay_payload(story_state)
    wanted = str(character_name or "").strip()
    characters = story.get("characters")
    character = next(
        (
            _replay_payload(item)
            for item in characters
            if isinstance(item, Mapping)
            and str(item.get("name") or "").strip() == wanted
        ),
        None,
    ) if isinstance(characters, Sequence) and not isinstance(characters, (str, bytes, bytearray)) else None
    if not wanted or character is None:
        raise KeyError(f"character_not_found:{wanted or character_name}")

    evidence: dict[str, dict[str, Any]] = {}
    unknown_fields: set[str] = set()
    states: dict[str, dict[str, Any]] = {}
    for namespace in _STATE_NAMESPACE_KEYS:
        states[namespace] = _replay_events(
            _state_events(character, namespace),
            as_of_chapter=target,
            path_prefix=namespace,
            evidence=evidence,
        )
        for field in _raw_current_fields(character.get(namespace)):
            if field not in states[namespace]:
                unknown_fields.add(f"{namespace}.{field}")

    for field in ("current_emotion", "location", "goals"):
        if character.get(field) not in (None, "", [], {}):
            unknown_fields.add(field)

    progression = _replay_progression(
        story,
        character,
        as_of_chapter=target,
        evidence=evidence,
    )
    ledger = story.get("progression_ledger")
    if _is_protagonist_character(character) and isinstance(ledger, Mapping):
        protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), Mapping) else ledger
        if isinstance(protagonist, Mapping):
            for field in ("level", "skills", "attributes", "inventory", "currency", "quests"):
                if protagonist.get(field) not in (None, "", [], {}):
                    if field not in progression:
                        unknown_fields.add(f"progression.{field}")

    relationships = _replay_relationships(
        story,
        wanted,
        as_of_chapter=target,
        evidence=evidence,
    )
    equipment = _replay_equipment(
        story,
        wanted,
        as_of_chapter=target,
        evidence=evidence,
        unknown_fields=unknown_fields,
    )
    return HistoricalCharacterState(
        character_name=wanted,
        as_of_chapter=target,
        profile=_stable_profile(character),
        current_state=states["current_state"],
        real_state=states["real_state"],
        game_state=states["game_state"],
        relationships=relationships,
        progression=progression,
        equipment=equipment,
        evidence=evidence,
        unknown_fields=tuple(sorted(unknown_fields)),
    )


def get_character_state(
    story_state: StoryState | Mapping[str, Any],
    character_name: str,
    as_of_chapter: int,
) -> HistoricalCharacterState:
    """Return a positive-chapter historical state projection."""

    return _get_character_state(
        story_state,
        character_name,
        as_of_chapter,
        allow_zero=False,
    )


def get_character_state_for_writer(
    story_state: StoryState | Mapping[str, Any],
    character_name: str,
    as_of_chapter: int,
) -> HistoricalCharacterState:
    """Return a writer boundary projection, including the chapter-zero baseline."""

    return _get_character_state(
        story_state,
        character_name,
        as_of_chapter,
        allow_zero=True,
    )


class HistoricalStateReplayMixin:
    @staticmethod
    def _protagonist_ledger(state: dict[str, Any], *, chapter_number: int) -> dict[str, Any]:
        ledger = state.get("progression_ledger")
        protagonist = ledger.get("protagonist") if isinstance(ledger, dict) else None
        if not isinstance(protagonist, dict):
            raise ValueError(f"attribute_rebase_missing_protagonist:{chapter_number}")
        return protagonist

    @staticmethod
    def _replace_attribute_slice(state: dict[str, Any], attribute_slice: dict[str, Any]) -> None:
        fields = (
            "attributes",
            "unallocated_attribute_points",
            "attribute_point_awards",
            "attribute_allocations",
        )
        ledger = dict(state.get("progression_ledger") or {})
        protagonist = dict(ledger.get("protagonist") or {})
        for field in fields:
            protagonist[field] = deepcopy(attribute_slice[field])
        ledger["protagonist"] = protagonist
        state["progression_ledger"] = ledger

        for raw_character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(raw_character, dict):
                continue
            role = str(raw_character.get("role") or "").strip().casefold()
            tier = str(raw_character.get("character_tier") or "").strip().casefold()
            if role not in {"protagonist", "主角"} and tier != "protagonist":
                continue
            game_state = dict(raw_character.get("game_state") or {})
            current = dict(game_state.get("current") or {})
            panel = dict(raw_character.get("game_panel") or {})
            for field in fields:
                current[field] = deepcopy(attribute_slice[field])
                panel[field] = deepcopy(attribute_slice[field])
            game_state["current"] = current
            game_state.setdefault("recent_changes", [])
            raw_character["game_state"] = game_state
            raw_character["game_panel"] = panel

    @staticmethod
    def _parse_foreshadowing_ledger(raw_ledger: Any) -> list[ForeshadowingState]:
        if not isinstance(raw_ledger, (list, tuple)):
            return []
        parsed: list[ForeshadowingState] = []
        for item in raw_ledger:
            try:
                parsed.append(ForeshadowingState.model_validate(item))
            except ValidationError:
                continue
        return parsed

    @staticmethod
    def _foreshadowing_chapter_number(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            chapter_number = int(value)
        except (TypeError, ValueError):
            return None
        return chapter_number if chapter_number > 0 else None

    def _project_foreshadowing_history(
        self,
        existing_ledger: Any,
        chapters: list[dict[str, Any]],
        *,
        evidence_complete: bool,
        manual_ledger: Any = None,
    ) -> tuple[
        list[dict[str, Any]],
        dict[int, list[dict[str, Any]]],
        list[dict[str, Any]],
    ]:
        existing = self._parse_foreshadowing_ledger(existing_ledger)
        manual = self._parse_foreshadowing_ledger(manual_ledger)
        if not manual and manual_ledger is None:
            manual = [entry for entry in existing if entry.payoff_plan.strip()]
        manual_keys = {
            normalize_foreshadowing_text(entry.text) for entry in manual
        }
        if evidence_complete:
            pending_terminal = [
                entry
                for entry in canonicalize_foreshadowing_ledger([*existing, *manual])
                if entry.status == "resolved" and entry.resolved_chapter is not None
            ]
            ledger = canonicalize_foreshadowing_ledger(
                [
                    *[
                        entry
                        for entry in manual
                        if entry.status != "resolved" or entry.resolved_chapter is None
                    ],
                    *[
                        entry
                        for entry in existing
                        if (
                            entry.status == "expired"
                            or (entry.status == "resolved" and entry.resolved_chapter is None)
                        )
                        and normalize_foreshadowing_text(entry.text) not in manual_keys
                    ],
                ]
            )
        else:
            pending_terminal = []
            ledger = canonicalize_foreshadowing_ledger([*existing, *manual])

        by_chapter: dict[int, list[dict[str, Any]]] = {}
        for chapter in sorted(
            chapters,
            key=lambda item: self._foreshadowing_chapter_number(
                item.get("chapter_number")
            ) or 0,
        ):
            chapter_number = self._foreshadowing_chapter_number(
                chapter.get("chapter_number")
            )
            if chapter_number is None:
                continue
            summary = self._chapter_summary_payload(chapter)
            due_terminal = [
                entry
                for entry in pending_terminal
                if int(entry.resolved_chapter or 0) <= chapter_number
            ]
            if due_terminal:
                pending_terminal = [
                    entry for entry in pending_terminal if entry not in due_terminal
                ]
            ledger = reconcile_foreshadowing(
                [*ledger, *due_terminal],
                chapter_number=chapter_number,
                unresolved_threads=summary["unresolved_threads"],
                resolved_threads=summary["resolved_threads"],
            )
            by_chapter[chapter_number] = [entry.model_dump() for entry in ledger]

        if pending_terminal:
            ledger = reconcile_foreshadowing(
                [*ledger, *pending_terminal],
                chapter_number=max(by_chapter, default=0),
                unresolved_threads=[],
            )
        final = [entry.model_dump() for entry in ledger]
        manual_final = [
            entry.model_dump()
            for entry in ledger
            if normalize_foreshadowing_text(entry.text) in manual_keys
        ]
        return final, by_chapter, manual_final

    def _historical_foreshadowing_for_rewrite(
        self,
        replacement_chapter: dict[str, Any],
    ) -> dict[str, Any] | None:
        raw_global = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        if not isinstance(raw_global, dict):
            return None
        target_chapter = self._foreshadowing_chapter_number(
            replacement_chapter.get("chapter_number")
        )
        current_chapter = self._foreshadowing_chapter_number(
            raw_global.get("current_chapter")
        )
        if (
            target_chapter is None
            or current_chapter is None
            or target_chapter >= current_chapter
        ):
            return None

        chapters_by_number = {target_chapter: replacement_chapter}
        available_numbers = {
            number for number in self.chapter_numbers() if number <= current_chapter
        }
        for chapter_number in sorted(available_numbers):
            if chapter_number > current_chapter or chapter_number == target_chapter:
                continue
            try:
                saved_chapter = self._read_json(
                    self.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
                    {},
                )
            except (OSError, ValueError):
                continue
            saved_chapter_number = (
                self._foreshadowing_chapter_number(saved_chapter.get("chapter_number"))
                if isinstance(saved_chapter, dict)
                else None
            )
            if saved_chapter_number == chapter_number:
                chapters_by_number[chapter_number] = saved_chapter

        expected_numbers = set(range(1, current_chapter + 1))
        summaries_complete = all(
            isinstance(chapter.get("chapter_summary"), dict)
            and isinstance(chapter["chapter_summary"].get("unresolved_threads"), list)
            for chapter in chapters_by_number.values()
        )
        evidence_complete = (
            expected_numbers == set(chapters_by_number)
            and summaries_complete
        )
        final_ledger, by_chapter, manual_ledger = self._project_foreshadowing_history(
            raw_global.get("foreshadowing"),
            list(chapters_by_number.values()),
            evidence_complete=evidence_complete,
            manual_ledger=raw_global.get("manual_foreshadowing"),
        )
        return {
            "final": final_ledger,
            "manual": manual_ledger,
            "by_chapter": by_chapter,
            "chapters": chapters_by_number,
            "evidence_complete": evidence_complete,
        }

    def _prepare_historical_attribute_rebase(
        self,
        chapter: dict[str, Any],
        updated_story: Any,
    ) -> tuple[dict[str, Any], dict[Path, Any]] | None:
        target_chapter = int(chapter.get("chapter_number") or 0)
        raw_global = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        if not isinstance(raw_global, dict):
            return None
        current_chapter = int(raw_global.get("current_chapter") or 0)
        if target_chapter >= current_chapter:
            return None

        project = self.project()
        blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        power_system = blueprint.get("power_system_spec") if isinstance(blueprint.get("power_system_spec"), dict) else {}
        rule = normalize_attribute_allocation_rule(power_system.get("attribute_allocation"))
        if not rule:
            return None

        target_state = self._validated_runtime_state(updated_story, raw_global)
        if target_state is None or int(target_state.get("current_chapter") or 0) != target_chapter:
            raise ValueError(f"attribute_rebase_invalid_target_snapshot:{target_chapter}")
        prepared_chapter = self._hydrate_chapter_display_fields(deepcopy(chapter), target_state)
        target_state = self._sync_state_after_chapter(deepcopy(target_state), prepared_chapter)
        target_state = self._sync_ledger_from_chapter_body(target_state, prepared_chapter)
        target_state["current_chapter"] = target_chapter
        target_protagonist = self._protagonist_ledger(target_state, chapter_number=target_chapter)

        future_chapters: list[tuple[int, Path, dict[str, Any]]] = []
        future_protagonists: list[tuple[int, dict[str, Any]]] = []
        for chapter_number in range(target_chapter + 1, current_chapter + 1):
            path = self.story_system_dir / "chapters" / f"{chapter_number:04d}.json"
            raw_chapter = self._read_json(path)
            if not isinstance(raw_chapter, dict):
                raise ValueError(f"attribute_rebase_missing_future_chapter:{chapter_number}")
            snapshot = raw_chapter.get("updated_story")
            snapshot_chapter = snapshot.get("current_chapter") if isinstance(snapshot, dict) else None
            if (
                not isinstance(snapshot, dict)
                or isinstance(snapshot_chapter, bool)
                or not isinstance(snapshot_chapter, int)
                or snapshot_chapter != chapter_number
            ):
                raise ValueError(f"attribute_rebase_invalid_future_snapshot:{chapter_number}")
            protagonist = self._protagonist_ledger(snapshot, chapter_number=chapter_number)
            future_chapters.append((chapter_number, path, deepcopy(raw_chapter)))
            future_protagonists.append((chapter_number, protagonist))

        rebuilt = rebuild_attribute_progression(
            rule,
            target_chapter,
            target_protagonist,
            future_protagonists,
        )
        self._replace_attribute_slice(target_state, rebuilt[target_chapter])
        prepared_chapter["updated_story"] = target_state
        prepared_chapter["chapter_summary"] = self._chapter_summary_payload(prepared_chapter)

        payloads: dict[Path, Any] = {}
        for chapter_number, path, future_chapter in future_chapters:
            snapshot = deepcopy(future_chapter["updated_story"])
            self._replace_attribute_slice(snapshot, rebuilt[chapter_number])
            StoryState.model_validate(snapshot)
            future_chapter["updated_story"] = snapshot
            payloads[path] = future_chapter

        rebuilt_global = deepcopy(raw_global)
        self._replace_attribute_slice(rebuilt_global, rebuilt[current_chapter])
        StoryState.model_validate(target_state)
        StoryState.model_validate(rebuilt_global)
        payloads[self.webnovel_dir / "state.json"] = rebuilt_global
        return prepared_chapter, payloads

    def _chapter_summary_payload(self, chapter: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        summary = dict(chapter.get("chapter_summary") or {})
        title = str(chapter.get("chapter_title") or summary.get("chapter_title") or f"Chapter {chapter_number}")
        summary_text = self._compact_text(summary.get("summary"), 320)
        if self._is_placeholder_text(summary_text):
            chapter_intent = chapter.get("chapter_intent") or {}
            summary_text = self._first_mapping_text(
                chapter_intent.get("primary_conflict")
                if isinstance(chapter_intent, dict)
                else {},
                ("summary", "collision", "goal", "conflict"),
            )
        if self._is_placeholder_text(summary_text):
            summary_text = self._compact_text(
                (chapter.get("event_plan") or {}).get("summary"),
                320,
            )
        if self._is_placeholder_text(summary_text):
            summary_text = self._compact_text(chapter.get("body"), 320)
        raw_facts = summary.get("facts") if isinstance(summary.get("facts"), list) else []
        facts = [
            self._compact_text(item, 220)
            for item in raw_facts
            if str(item).strip() and not self._is_placeholder_text(item)
        ]
        if summary_text and not facts:
            facts = [summary_text]
        event_beat = self._coerce_summary_mapping(
            summary.get("event_beat") or chapter.get("event_beat"),
            label="event_beat",
        )
        next_focus = ""
        for candidate in (
            summary.get("next_focus"),
            chapter.get("next_outline"),
            (chapter.get("event_plan") or {}).get("next_focus"),
            self._first_mapping_text(
                event_beat,
                ("turn", "pivot", "hook", "result", "change", "next"),
            ),
            (chapter.get("chapter_intent") or {}).get("next_focus"),
        ):
            compact = self._compact_text(candidate, 220)
            if compact and not self._is_placeholder_text(compact):
                next_focus = compact
                break
        cadence = str(
            summary.get("cadence") or chapter.get("cadence") or "measured"
        ).strip()
        if cadence not in {"urgent", "measured", "breathing"}:
            cadence = "measured"
        return {
            "chapter_number": chapter_number,
            "chapter_title": title,
            "cadence": cadence,
            "summary": summary_text or f"Chapter {chapter_number}.",
            "facts": facts[:8],
            "unresolved_threads": [
                self._compact_text(item, 220)
                for item in (summary.get("unresolved_threads") if isinstance(summary.get("unresolved_threads"), list) else [])
                if str(item).strip()
            ][:8],
            "resolved_threads": [
                self._compact_text(item, 220)
                for item in (summary.get("resolved_threads") if isinstance(summary.get("resolved_threads"), list) else [])
                if str(item).strip()
            ][:8],
            "next_focus": next_focus,
            "primary_conflict": self._coerce_summary_mapping(
                summary.get("primary_conflict") or chapter.get("conflict_summary", {}).get("primary_conflict"),
                label="primary_conflict",
            ),
            "secondary_conflict": self._coerce_summary_mapping(
                summary.get("secondary_conflict") or chapter.get("conflict_summary", {}).get("secondary_conflict"),
                label="secondary_conflict",
            ),
            "event_beat": event_beat,
        }
