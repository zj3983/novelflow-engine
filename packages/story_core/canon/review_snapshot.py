"""Read-only, chapter-bounded canon view for factual review.

The consistency model must never inspect the live project state blindly when
rewriting an older chapter: the live registry may already contain facts created
by later chapters. This module builds the review input as of the start of the
requested chapter (chapter_number - 1).

The builder prefers the durable continuity snapshot for the previous chapter.
If an older project has no continuity snapshot it can fall back to the saved
chapter's updated_story payload. Only when the target is not historical do we
fall back to the current writer context.

The result is intentionally a plain JSON-compatible dict. It is a read-only
projection; building it never mutates the registry or project files.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Iterable

from packages.story_core.continuity.store import ContinuityStore


SNAPSHOT_SCHEMA_VERSION = "canon-review-snapshot/v1"

_ESTABLISHED_LIFECYCLES = {"approved", "active", "retired"}
_ENTITY_INTRO_CHAPTER_KEYS = (
    "introduced_chapter",
    "first_chapter",
    "first_appearance",
    "created_chapter",
)
_HISTORICAL_VOLATILE_KEYS = {
    "location",
    "previous_location",
    "last_moved_chapter",
    "inventory",
    "status",
    "notes",
    "last_chapter",
    "current_state",
    "real_state",
    "game_state",
    "game_panel",
}


def _int_chapter(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        chapter = int(value)
    except (TypeError, ValueError):
        return None
    return chapter if chapter >= 0 else None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _project_current_chapter(project_root: Path) -> int:
    candidates = (
        project_root / ".webnovel" / "state.json",
        project_root / ".story-system" / "state.json",
    )
    values = [
        _int_chapter(_read_json(path).get("current_chapter"))
        for path in candidates
    ]
    return max((value for value in values if value is not None), default=0)


def _saved_chapter_state(project_root: Path, chapter_number: int) -> dict[str, Any]:
    if chapter_number <= 0:
        return {}
    payload = _read_json(
        project_root
        / ".story-system"
        / "chapters"
        / f"{chapter_number:04d}.json"
    )
    updated = payload.get("updated_story")
    if not isinstance(updated, dict):
        return {}
    current = _int_chapter(updated.get("current_chapter"))
    if current != chapter_number:
        return {}
    return deepcopy(updated)


def _bounded_state(
    *,
    project_root: Path,
    as_of_chapter: int,
    store: ContinuityStore,
) -> tuple[dict[str, Any], str, int | None]:
    if as_of_chapter <= 0:
        return {}, "chapter_start", 0

    if as_of_chapter in set(store.get_stale_chapters()):
        return {}, "stale", as_of_chapter

    snapshot = store.read_snapshot(as_of_chapter)
    if snapshot is not None and isinstance(snapshot.state_after, dict):
        state = deepcopy(snapshot.state_after)
        state_chapter = _int_chapter(state.get("current_chapter"))
        if state_chapter in {None, as_of_chapter}:
            return state, "continuity_snapshot", as_of_chapter

    saved = _saved_chapter_state(project_root, as_of_chapter)
    if saved:
        return saved, "chapter_updated_story", as_of_chapter
    return {}, "unavailable", None


def _normalize_fact(
    item: Any,
    *,
    default_field: str,
    default_source: str,
    as_of_chapter: int,
) -> dict[str, Any] | None:
    if isinstance(item, dict):
        chapter = _int_chapter(
            item.get("chapter_number")
            if "chapter_number" in item
            else item.get("chapter")
        )
        if chapter is not None and chapter > as_of_chapter:
            return None
        value = item.get("value")
        if value is None:
            value = (
                item.get("fact")
                or item.get("text")
                or item.get("summary")
                or item.get("message")
            )
        if value is None:
            value = {
                key: val
                for key, val in item.items()
                if key
                not in {
                    "chapter_number",
                    "chapter",
                    "source",
                    "source_sentence",
                    "evidence",
                }
            }
        source_sentence = str(
            item.get("source_sentence") or item.get("evidence") or ""
        ).strip()
        result = {
            "subject": str(item.get("subject") or "").strip(),
            "field": str(item.get("field") or default_field).strip(),
            "value": deepcopy(value),
            "source": str(item.get("source") or default_source).strip(),
        }
        if chapter is not None:
            result["chapter_number"] = chapter
        if source_sentence:
            result["evidence"] = source_sentence
        return result

    text = str(item or "").strip()
    if not text:
        return None
    return {
        "subject": "",
        "field": default_field,
        "value": text,
        "source": default_source,
    }


def _dedupe_dicts(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        try:
            marker = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            marker = repr(item)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(item)
    return result


def _state_continuity_facts(
    state: dict[str, Any],
    *,
    as_of_chapter: int,
    source_ref: str,
) -> list[dict[str, Any]]:
    raw: list[Any] = []
    if isinstance(state.get("continuity_facts"), list):
        raw.extend(state["continuity_facts"])
    ledger = state.get("progression_ledger")
    if isinstance(ledger, dict) and isinstance(ledger.get("continuity_ledger"), list):
        raw.extend(ledger["continuity_ledger"])

    result: list[dict[str, Any]] = []
    for item in raw:
        normalized = _normalize_fact(
            item,
            default_field="fact",
            default_source=source_ref,
            as_of_chapter=as_of_chapter,
        )
        if normalized is not None:
            result.append(normalized)
    return _dedupe_dicts(result)


def _state_world_facts(
    state: dict[str, Any],
    *,
    as_of_chapter: int,
    source_ref: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in state.get("world_facts") or []:
        normalized = _normalize_fact(
            item,
            default_field="world_fact",
            default_source=source_ref,
            as_of_chapter=as_of_chapter,
        )
        if normalized is not None:
            result.append(normalized)
    return _dedupe_dicts(result)


def _context_facts(
    items: Iterable[Any],
    *,
    as_of_chapter: int,
    source: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items:
        normalized = _normalize_fact(
            item,
            default_field="fact",
            default_source=source,
            as_of_chapter=as_of_chapter,
        )
        if normalized is not None:
            result.append(normalized)
    return _dedupe_dicts(result)


def _project_character(card: Any) -> dict[str, Any] | None:
    if not isinstance(card, dict):
        model_dump = getattr(card, "model_dump", None)
        if callable(model_dump):
            card = model_dump(mode="json")
    if not isinstance(card, dict):
        return None
    name = str(card.get("name") or card.get("display_name") or "").strip()
    if not name:
        return None

    keep = (
        "name",
        "aliases",
        "role",
        "character_tier",
        "importance",
        "narrative_function",
        "identity_profile",
        "current_life_profile",
        "current_state",
        "real_state",
        "game_state",
        "game_panel",
        "knowledge_boundary",
        "story_drive",
        "lifecycle_state",
    )
    projected = {
        key: deepcopy(card[key])
        for key in keep
        if key in card and card[key] not in (None, "", [], {})
    }
    projected["name"] = name
    return projected


def _entity_intro_chapter(entity: Any) -> int | None:
    extensions = getattr(entity, "extensions", None)
    if not isinstance(extensions, dict):
        return None
    for key in _ENTITY_INTRO_CHAPTER_KEYS:
        chapter = _int_chapter(extensions.get(key))
        if chapter is not None:
            return chapter
    return None


def _entity_projection(
    entity: Any,
    *,
    historical: bool,
    as_of_chapter: int,
    safe_historical_ids: set[str],
) -> dict[str, Any] | None:
    lifecycle = str(getattr(entity, "lifecycle", "") or "")
    if lifecycle not in _ESTABLISHED_LIFECYCLES:
        return None

    entity_id = str(getattr(entity, "entity_id", "") or "")
    intro = _entity_intro_chapter(entity)
    if historical and entity_id not in safe_historical_ids:
        if intro is None or intro > as_of_chapter:
            return None

    extensions = deepcopy(dict(getattr(entity, "extensions", {}) or {}))
    if historical:
        extensions = {
            key: value
            for key, value in extensions.items()
            if key not in _HISTORICAL_VOLATILE_KEYS
        }

    result = {
        "entity_id": entity_id,
        "kind": str(getattr(entity, "kind", "") or ""),
        "name": str(getattr(entity, "display_name", "") or ""),
        "aliases": list(getattr(entity, "aliases", ()) or ()),
        "lifecycle": lifecycle if not historical else "established",
        "attributes": extensions,
    }
    if intro is not None:
        result["introduced_chapter"] = intro
    return result


def _resolve_entity_name(registry: Any, entity_id: str) -> str:
    try:
        entity = registry.get(entity_id)
    except Exception:
        entity = None
    if entity is None:
        return entity_id
    return str(getattr(entity, "display_name", "") or entity_id)


def _bounded_relationships(
    registry: Any,
    *,
    as_of_chapter: int,
    stale_chapters: set[int],
    resolve_names: bool,
) -> tuple[list[dict[str, Any]], int, int, set[str]]:
    try:
        raw = list(registry.relationships())
    except Exception:
        raw = []
    result: list[dict[str, Any]] = []
    filtered_future = 0
    filtered_stale = 0
    safe_ids: set[str] = set()
    for edge in raw:
        if not isinstance(edge, dict):
            continue
        chapter = _int_chapter(edge.get("chapter_number"))
        if chapter is not None and chapter > as_of_chapter:
            filtered_future += 1
            continue
        if chapter is not None and chapter in stale_chapters:
            filtered_stale += 1
            continue
        subject_id = str(edge.get("subject_id") or "")
        object_id = str(edge.get("object_id") or "")
        if subject_id:
            safe_ids.add(subject_id)
        if object_id:
            safe_ids.add(object_id)
        item = deepcopy(edge)
        item["subject_name"] = (
            _resolve_entity_name(registry, subject_id)
            if resolve_names
            else subject_id
        )
        item["object_name"] = (
            _resolve_entity_name(registry, object_id)
            if resolve_names
            else object_id
        )
        result.append(item)
    return result, filtered_future, filtered_stale, safe_ids


def _bounded_timeline(
    registry: Any,
    *,
    as_of_chapter: int,
    stale_chapters: set[int],
) -> tuple[list[dict[str, Any]], int, int]:
    try:
        raw = list(registry.timeline())
    except Exception:
        raw = []
    result: list[dict[str, Any]] = []
    filtered_future = 0
    filtered_stale = 0
    for marker in raw:
        if not isinstance(marker, dict):
            continue
        chapter = _int_chapter(marker.get("chapter_number"))
        if chapter is not None and chapter > as_of_chapter:
            filtered_future += 1
            continue
        if chapter is not None and chapter in stale_chapters:
            filtered_stale += 1
            continue
        result.append(deepcopy(marker))
    return result, filtered_future, filtered_stale


def _bounded_registry_foreshadowing(
    registry: Any,
    *,
    as_of_chapter: int,
    stale_chapters: set[int],
) -> list[dict[str, Any]]:
    try:
        raw = list(registry.foreshadowing())
    except Exception:
        raw = []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        chapter = _int_chapter(item.get("chapter_number"))
        if chapter is not None and chapter > as_of_chapter:
            continue
        if chapter is not None and chapter in stale_chapters:
            continue
        result.append(deepcopy(item))
    return result


def build_canon_review_snapshot(
    *,
    project_root: str | Path,
    chapter_number: int,
    registry: Any,
    continuity_facts: Iterable[Any] = (),
    character_cards: Iterable[Any] = (),
    entity_cards: Iterable[Any] = (),
    world_rules: Iterable[Any] = (),
) -> dict[str, Any]:
    """Build the facts the consistency reviewer may treat as established.

    chapter_number is the chapter being generated or rewritten. The snapshot
    is therefore bounded at chapter_number - 1. A historical rewrite never
    falls back to live character/entity state when no bounded historical state
    is available; that is a deliberate degradation rather than a future leak.
    """

    root = Path(project_root)
    target = max(int(chapter_number), 1)
    as_of = max(target - 1, 0)
    store = ContinuityStore(root)
    snapshots = store.list_snapshots()
    stale_chapters = set(store.get_stale_chapters())
    latest_snapshot = max((item.chapter_number for item in snapshots), default=0)
    current_chapter = max(latest_snapshot, _project_current_chapter(root))
    historical = current_chapter > as_of

    state, state_source, source_chapter = _bounded_state(
        project_root=root,
        as_of_chapter=as_of,
        store=store,
    )
    bounded_available = bool(state) or as_of == 0
    unsafe_live_state = historical or state_source == "stale"

    source_ref = (
        f"{state_source}:{source_chapter:04d}"
        if source_chapter is not None
        else state_source
    )

    if state:
        characters = [
            projected
            for projected in (
                _project_character(card) for card in (state.get("characters") or [])
            )
            if projected is not None
        ]
        facts = _state_continuity_facts(
            state, as_of_chapter=as_of, source_ref=source_ref
        )
        world_facts = _state_world_facts(
            state, as_of_chapter=as_of, source_ref=source_ref
        )
    elif unsafe_live_state:
        characters = []
        facts = []
        world_facts = []
    else:
        characters = [
            projected
            for projected in (_project_character(card) for card in character_cards)
            if projected is not None
        ]
        facts = _context_facts(
            continuity_facts,
            as_of_chapter=as_of,
            source="writer_context",
        )
        world_facts = []

    if not unsafe_live_state:
        facts = _dedupe_dicts(
            [
                *facts,
                *_context_facts(
                    continuity_facts,
                    as_of_chapter=as_of,
                    source="writer_context",
                ),
            ]
        )

    (
        relationships,
        filtered_relationships,
        filtered_stale_relationships,
        _safe_entity_ids,
    ) = _bounded_relationships(
        registry,
        as_of_chapter=as_of,
        stale_chapters=stale_chapters,
        resolve_names=not unsafe_live_state,
    )
    timeline, filtered_timeline, filtered_stale_timeline = _bounded_timeline(
        registry,
        as_of_chapter=as_of,
        stale_chapters=stale_chapters,
    )

    entities: list[dict[str, Any]] = []
    if not unsafe_live_state:
        try:
            registry_entities = list(registry.list_all())
        except Exception:
            registry_entities = []
        for entity in registry_entities:
            projected = _entity_projection(
                entity,
                historical=False,
                as_of_chapter=as_of,
                safe_historical_ids=set(),
            )
            if projected is not None:
                entities.append(projected)

    if not unsafe_live_state:
        known = {
            (str(item.get("kind") or ""), str(item.get("name") or ""))
            for item in entities
        }
        for raw in entity_cards:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            kind = str(raw.get("kind") or "").strip()
            if not name or (kind, name) in known:
                continue
            entities.append(
                {
                    "entity_id": str(raw.get("id") or raw.get("entity_id") or ""),
                    "kind": kind,
                    "name": name,
                    "aliases": list(raw.get("aliases") or []),
                    "lifecycle": str(raw.get("lifecycle") or "active"),
                    "attributes": {
                        key: deepcopy(value)
                        for key, value in raw.items()
                        if key
                        not in {
                            "id",
                            "entity_id",
                            "kind",
                            "name",
                            "aliases",
                            "lifecycle",
                        }
                    },
                }
            )
            known.add((kind, name))

    bounded_world_rules = [
        str(item).strip()
        for item in world_rules
        if str(item or "").strip()
    ]
    if unsafe_live_state:
        bounded_world_rules = []

    state_foreshadowing = state.get("foreshadowing") if isinstance(state, dict) else None
    if isinstance(state_foreshadowing, list):
        foreshadowing = deepcopy(state_foreshadowing)
    else:
        foreshadowing = (
            []
            if unsafe_live_state
            else _bounded_registry_foreshadowing(
                registry,
                as_of_chapter=as_of,
                stale_chapters=stale_chapters,
            )
        )

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "chapter_number": target,
        "as_of_chapter": as_of,
        "state_source": state_source,
        "state_source_chapter": source_chapter,
        "historical_rewrite": historical,
        "stale_base_state": state_source == "stale",
        "bounded_state_available": bounded_available,
        "facts": _dedupe_dicts([*facts, *world_facts]),
        "world_rules": list(dict.fromkeys(bounded_world_rules)),
        "characters": characters,
        "entities": entities,
        "relationships": relationships,
        "timeline": timeline,
        "foreshadowing": foreshadowing,
        "diagnostics": {
            "latest_confirmed_chapter": current_chapter,
            "filtered_future_relationships": filtered_relationships,
            "filtered_stale_relationships": filtered_stale_relationships,
            "filtered_future_timeline": filtered_timeline,
            "filtered_stale_timeline": filtered_stale_timeline,
            "unsafe_live_state_omitted": bool(unsafe_live_state),
        },
    }


__all__ = ["SNAPSHOT_SCHEMA_VERSION", "build_canon_review_snapshot"]
