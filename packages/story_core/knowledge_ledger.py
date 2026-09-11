"""Deterministic, character-scoped knowledge facts.

The ledger is intentionally separate from world truth and free-form memory.
Only an explicit ``known_by`` entry (or an explicit public marker) makes a
fact available to a character at a chapter boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from packages.story_core.models import KnowledgeFact, StoryState


def _payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="python")
        except TypeError:
            dumped = model_dump()
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def _boundary(value: Any, *, allow_zero: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("as_of_chapter must be a non-negative integer")
    if value < (0 if allow_zero else 1):
        label = "non-negative integer" if allow_zero else "positive integer"
        raise ValueError(f"as_of_chapter must be a {label}")
    return value


def _raw_records(story_state: StoryState | Mapping[str, Any]) -> list[Any]:
    ledger = _payload(story_state).get("knowledge_ledger")
    if isinstance(ledger, Mapping):
        if "fact_id" in ledger:
            return [ledger]
        return list(ledger.values())
    if isinstance(ledger, Sequence) and not isinstance(ledger, (str, bytes, bytearray)):
        return list(ledger)
    return []


def _relationship_records(story_state: StoryState | Mapping[str, Any]) -> list[dict[str, Any]]:
    """Adapt only explicitly dated relationship knowledge into read records.

    RelationshipEdge.source_knowledge and target_knowledge are accumulated
    current notes.  Their list position does not establish when a character
    learned a fact, so plain strings are deliberately ignored here.  A
    mapping may opt into the historical ledger only by carrying its own
    ``learned_chapter``/``chapter`` evidence.
    """

    graph = _payload(story_state).get("relationship_graph")
    if not isinstance(graph, Sequence) or isinstance(graph, (str, bytes, bytearray)):
        return []
    records: list[dict[str, Any]] = []
    for edge in graph:
        if not isinstance(edge, Mapping):
            continue
        source = str(edge.get("source") or "").strip()
        target = str(edge.get("target") or "").strip()
        if not source or not target:
            continue
        edge_id = str(edge.get("id") or f"{source}:{target}").strip()
        for side, character, field in (
            ("source", source, "source_knowledge"),
            ("target", target, "target_knowledge"),
        ):
            facts = edge.get(field)
            if not isinstance(facts, Sequence) or isinstance(facts, (str, bytes, bytearray)):
                continue
            for index, fact in enumerate(facts):
                if not isinstance(fact, Mapping):
                    continue
                text = str(fact.get("fact") or fact.get("text") or fact.get("value") or "").strip()
                raw_learned = fact.get("learned_chapter")
                if raw_learned in (None, ""):
                    raw_learned = fact.get("chapter", fact.get("chapter_number"))
                if isinstance(raw_learned, bool):
                    continue
                try:
                    learned = int(raw_learned)
                except (TypeError, ValueError):
                    continue
                if learned < 0 or not text:
                    continue
                records.append(
                    {
                        "fact_id": f"relationship:{edge_id}:{side}:{index}",
                        "fact": text,
                        "learned_chapter": learned,
                        "known_by": [character],
                        "source": f"relationship:{edge_id}",
                        "certainty": fact.get("certainty", "certain"),
                        "visibility": fact.get("visibility", "private"),
                        "reveal_chapter": fact.get("reveal_chapter"),
                        "invalidated_chapter": fact.get("invalidated_chapter"),
                        "tags": ["relationship", *(
                            [str(tag) for tag in fact.get("tags", [])]
                            if isinstance(fact.get("tags"), Sequence)
                            and not isinstance(fact.get("tags"), (str, bytes, bytearray))
                            else []
                        )],
                    }
                )
    return records


def _normalized_records(story_state: StoryState | Mapping[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_fact_ids: set[str] = set()
    for raw in [*_raw_records(story_state), *_relationship_records(story_state)]:
        try:
            record = KnowledgeFact.model_validate(raw)
        except (TypeError, ValidationError):
            continue
        item = record.model_dump(mode="python")
        fact_id = str(item.get("fact_id") or "")
        if fact_id in seen_fact_ids:
            continue
        seen_fact_ids.add(fact_id)
        item["known_by"] = [
            str(name).strip()
            for name in item.get("known_by", [])
            if str(name).strip()
        ]
        records.append(item)
    return records


def _is_known_by(record: Mapping[str, Any], character_name: str) -> bool:
    known_by = record.get("known_by")
    if not isinstance(known_by, Sequence) or isinstance(known_by, (str, bytes, bytearray)):
        return False
    names = {str(item).strip() for item in known_by if str(item).strip()}
    return character_name in names or "*" in names or (
        record.get("visibility") == "public" and not names
    )


def _available_at(record: Mapping[str, Any], as_of_chapter: int) -> bool:
    try:
        learned = int(record.get("learned_chapter", 0))
    except (TypeError, ValueError):
        return False
    reveal = record.get("reveal_chapter")
    if learned > as_of_chapter:
        return False
    if reveal not in (None, ""):
        try:
            if int(reveal) > as_of_chapter:
                return False
        except (TypeError, ValueError):
            return False
    invalidated = record.get("invalidated_chapter")
    if invalidated not in (None, ""):
        try:
            if int(invalidated) <= as_of_chapter:
                return False
        except (TypeError, ValueError):
            return False
    return True


def get_character_knowledge(
    story_state: StoryState | Mapping[str, Any],
    character_name: str,
    as_of_chapter: int,
) -> list[dict[str, Any]]:
    """Return only explicitly known, chapter-available active facts."""

    target = _boundary(as_of_chapter)
    wanted = str(character_name or "").strip()
    if not wanted:
        raise KeyError("character_not_found:")
    selected = [
        deepcopy(record)
        for record in _normalized_records(story_state)
        if _available_at(record, target) and _is_known_by(record, wanted)
    ]
    return sorted(
        selected,
        key=lambda item: (
            int(item.get("learned_chapter") or 0),
            str(item.get("fact_id") or ""),
            str(item.get("fact") or ""),
        ),
    )


def _ledger_target(story_state: StoryState | MutableMapping[str, Any]) -> list[Any]:
    if isinstance(story_state, MutableMapping):
        ledger = story_state.get("knowledge_ledger")
        if not isinstance(ledger, list):
            ledger = []
            story_state["knowledge_ledger"] = ledger
        return ledger
    ledger = getattr(story_state, "knowledge_ledger", None)
    if not isinstance(ledger, list):
        ledger = []
        setattr(story_state, "knowledge_ledger", ledger)
    return ledger


def apply_knowledge_updates(
    story_state: StoryState | MutableMapping[str, Any],
    updates: Any,
    *,
    chapter_number: int | None = None,
) -> list[dict[str, Any]]:
    """Commit explicit structured knowledge events without extracting prose."""

    if chapter_number is not None:
        _boundary(chapter_number, allow_zero=False)
    if not isinstance(updates, Sequence) or isinstance(updates, (str, bytes, bytearray)):
        return []
    ledger = _ledger_target(story_state)
    committed: list[dict[str, Any]] = []
    for raw in updates:
        item = _payload(raw)
        if not item:
            continue
        if item.get("learned_chapter") in (None, ""):
            if chapter_number is None:
                continue
            item["learned_chapter"] = chapter_number
        known_by = item.get("known_by")
        if isinstance(known_by, str):
            item["known_by"] = [known_by]
        try:
            record = KnowledgeFact.model_validate(item)
        except (TypeError, ValidationError):
            continue
        normalized = record.model_dump(mode="json")
        if (
            chapter_number is not None
            and int(normalized["learned_chapter"]) > chapter_number
        ):
            # A commit for chapter N cannot introduce a fact learned in a
            # future chapter; callers should submit that event at its own
            # chapter boundary.
            continue
        fact_id = normalized["fact_id"]
        existing_index = next(
            (
                index
                for index, current in enumerate(ledger)
                if isinstance(current, Mapping)
                and str(current.get("fact_id") or "") == fact_id
            ),
            None,
        )
        if existing_index is None:
            ledger.append(deepcopy(normalized))
        else:
            merged = dict(ledger[existing_index]) if isinstance(ledger[existing_index], Mapping) else {}
            merged.update(normalized)
            ledger[existing_index] = merged
        committed.append(deepcopy(normalized))
    return committed


def add_knowledge_fact(
    story_state: StoryState | MutableMapping[str, Any],
    *,
    fact_id: str,
    fact: str,
    known_by: Sequence[str],
    source: str = "",
    learned_chapter: int | None = None,
    certainty: str = "certain",
    visibility: str = "private",
    reveal_chapter: int | None = None,
    invalidated_chapter: int | None = None,
    supersedes: str = "",
    tags: Sequence[str] = (),
) -> dict[str, Any] | None:
    """Convenience wrapper for an explicit chapter-commit event."""

    committed = apply_knowledge_updates(
        story_state,
        [
            {
                "fact_id": fact_id,
                "fact": fact,
                "known_by": list(known_by),
                "source": source,
                "learned_chapter": learned_chapter,
                "certainty": certainty,
                "visibility": visibility,
                "reveal_chapter": reveal_chapter,
                "invalidated_chapter": invalidated_chapter,
                "supersedes": supersedes,
                "tags": list(tags),
            }
        ],
        chapter_number=learned_chapter,
    ) if learned_chapter is not None else []
    return committed[0] if committed else None


__all__ = [
    "KnowledgeFact",
    "add_knowledge_fact",
    "apply_knowledge_updates",
    "get_character_knowledge",
]
