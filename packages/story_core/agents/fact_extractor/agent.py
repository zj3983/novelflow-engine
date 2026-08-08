"""Deterministic + model-backed fact extraction.

The extractor answers one question: *what facts did this chapter
introduce that should be reflected in the project canon?*

Strategy (per the migration plan):

1. **Deterministic first** — explicit numeric state ("还剩三枚金币"),
   named ownership ("林昭把玉佩塞进口袋"), and explicit location
   movement ("林昭抵达驿站") are caught by regex. Confidence is
   ``1.0`` because the prose literally states the change.
2. **Model-backed fallback** — ambiguous relationships, knowledge
   changes, and foreshadowing require a model call. The
   ``FactExtractorRuntime`` is a swappable boundary; production
   uses the gateway; tests can inject a canned double.
3. **Reference validation** — every entity / task / foreshadowing id
   referenced by the proposed delta is checked against the candidate
   canon view. Unknown ids are flagged ``orphan`` so the workbench
   can warn the user before confirmation.

A failing model call must not poison the deterministic extraction;
it is wrapped in ``try / except`` and produces an empty model delta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from packages.story_core.continuity.delta import (
    ContinuityDelta,
    ForeshadowingChange,
    InventoryChange,
    LocationMovement,
    RelationshipChange,
)


# --- Sentence splitter ---------------------------------------------------------

# Chinese full stop, Chinese exclamation/question marks, English period.
# The extractor works on a per-sentence basis so a confidence / source
# trace points at the sentence that triggered the fact.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?\.])")


def _split_sentences(body: str) -> list[str]:
    if not body:
        return []
    parts = [segment.strip() for segment in _SENTENCE_SPLIT_RE.split(body)]
    return [part for part in parts if part]


# --- Patterns ------------------------------------------------------------------
#
# Each pattern maps a Chinese-language cue to a fact. They are
# intentionally narrow: the deterministic layer is allowed to miss
# things; the model layer will catch the rest.

# "林昭还剩三枚金币" / "林昭仅剩三枚金币" → resulting_quantity
# The numeric pattern accepts both Arabic (\d+) and Chinese
# (一二三四五六七八九十百千万零) numerals because Chinese fiction
# rarely uses Arabic digits. The Chinese-to-int conversion lives in
# ``_chinese_to_int`` below so the rest of the pipeline sees an int.
_NUMERIC_STATE_RE = re.compile(
    r"(?P<entity>[一-龥]{2,8}?)[^\n。！？!?\.]{0,8}?(?:还剩|仅剩|还|仅|只|剩)"
    r"(?P<count>(?:\d+|[一二三四五六七八九十百千万零]+))"
    r"\s*[枚个只把块张支条颗本把]"
    r"\s*的?\s*"
    r"(?P<item>[一-龥]{2,8}?)"
    r"(?=[。！？!?\.\s]|$)"
)


_CHINESE_DIGIT_MAP = {
    "零": 0, "一": 1, "二": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _chinese_to_int(text: str) -> int | None:
    """Best-effort Chinese numeral → int.

    Handles single digits (``三`` → 3) and the common compound forms
    (``十三`` → 13, ``二十`` → 20, ``两百`` → 200). Anything weirder
    returns ``None`` so the caller can decide to drop the fact rather
    than guess.
    """
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if all(ch in _CHINESE_DIGIT_MAP or ch in "十百千万" for ch in text):
        # Walk with a tiny state machine.
        total = 0
        current = 0
        for ch in text:
            if ch in _CHINESE_DIGIT_MAP:
                current = _CHINESE_DIGIT_MAP[ch]
            elif ch == "十":
                # "十" alone = 10, "二十" = 20, "十三" = 13
                if current == 0:
                    current = 1
                total += current * 10
                current = 0
            elif ch in "百千":
                multiplier = {"百": 100, "千": 1000}[ch]
                if current == 0:
                    current = 1
                total += current * multiplier
                current = 0
            elif ch == "万":
                if current == 0:
                    current = 1
                total += current * 10000
                current = 0
        total += current
        return total
    return None

# "林昭从包裹里取出一把生锈的铁剑" → +1 acquisition
_TAKE_ITEM_RE = re.compile(
    r"(?P<entity>[一-龥]{2,8}?)"
    r"[^\n。！？!?\.]{0,12}?"
    r"(?:取出|拿出|拾起|拿起|获得|收到|收下|得到|取了|捡起)"
    r"[^\n。！？!?\.]{0,12}?"
    r"(?P<item>[一-龥]{2,8}?)"
    r"(?=[。！？!?\.\s]|$)"
)

# "苏婉把旧玉佩塞进了行李底" / "苏婉失去了一支笔" → -1 loss
# The item group is greedy so it absorbs the full noun phrase (e.g.
# "旧玉佩") before the verb. The non-greedy variant truncated the
# noun at two characters; the verb acts as a natural terminator here
# so greedy + verb-anchored is the right shape.
_LOSE_ITEM_RE = re.compile(
    r"(?P<entity>[一-龥]{2,8}?)"
    r"[^\n。！？!?\.]{0,12}?"
    r"(?:把|将)?"
    r"(?P<item>[一-龥]{2,8})"
    r"[^\n。！？!?\.]{0,8}?"
    r"(?:失去|丢失|交出|送出|卖掉|用掉|消耗|塞进|藏进|扔掉)"
)

# "林昭才赶到了驿站" / "林昭走进客栈" → to_location
# The entity group is greedy and the to_location uses non-greedy +
# boundary anchor so a sentence like "天黑后，林昭才赶到了驿站。"
# matches "林昭" rather than the leading temporal phrase.
_LOCATION_MOVE_RE = re.compile(
    r"(?P<entity>[一-龥]{2,8})"
    r"[^\n。！？!?\.]{0,16}?"
    r"(?:抵达|到达|来到|赶到|进入|走进|走入|回|返回|抵达了|到达了|来到了)"
    r"(?P<location>[一-龥]{2,8}?)"
    r"(?=[。！？!?\.\s]|$)"
)

# "把 X 交给 Y" / "X 塞给 Y" → implied transfer (logged as relationship
# in the model layer; the deterministic layer only records the inventory
# change for the source).
_TRANSFER_VERB_RE = re.compile(
    r"(?P<source>[一-龥]{2,8})\s*把\s*(?P<item>[一-龥]{2,8})\s*"
    r"(?:交给|塞给|递给|送到|给了)\s*(?P<target>[一-龥]{2,8})"
)


# --- Types ---------------------------------------------------------------------

class FactExtractorRuntime(Protocol):
    """Anything that can answer an ambiguous-fact extraction call.

    Production wires the gateway; tests inject a canned double. The
    request shape is intentionally loose (it is whatever the
    orchestrator / gateway already uses); the runtime is responsible
    for prompt construction and response parsing.
    """

    def complete(self, request: Any) -> Any: ...


@dataclass
class FactExtractorContext:
    """Everything the extractor needs to run.

    ``body`` is the chapter text. ``canon_view`` is a small index of
    the project's known entities keyed by id / kind / alias. The
    director artifact and continuity facts are optional because the
    deterministic layer does not need them; the model layer will
    consume them when present.
    """

    body: str
    chapter_number: int
    director_artifact: Any = None
    canon_view: dict[str, Any] = field(default_factory=dict)
    continuity_facts: list[dict[str, Any]] = field(default_factory=list)


# --- Helpers -------------------------------------------------------------------

def _resolve_entity_id(name: str, canon_view: dict[str, Any]) -> str | None:
    """Return the canonical id for ``name`` if it appears in the view."""
    if not name or not canon_view:
        return None
    aliases = canon_view.get("by_alias") or {}
    matches = aliases.get(name)
    if matches:
        return matches[0]
    by_id = canon_view.get("by_id") or {}
    for entity_id, record in by_id.items():
        if not isinstance(record, dict):
            continue
        if record.get("canonical_name") == name:
            return entity_id
        if name in (record.get("aliases") or []):
            return entity_id
    return None


def _record_orphan(name: str) -> dict[str, Any]:
    return {"kind": "entity", "id": name, "status": "orphan", "name": name}


def _record_valid(name: str, entity_id: str) -> dict[str, Any]:
    return {
        "kind": "entity",
        "id": entity_id,
        "name": name,
        "status": "valid",
    }


# --- Deterministic passes ------------------------------------------------------

def _known_entity_names(canon_view: dict[str, Any]) -> list[str]:
    """Return canonical names + aliases, longest first.

    Longer names are tried first so "林昭之子" wins over "林昭" when
    both are present in the canon view.
    """
    by_id = canon_view.get("by_id") or {}
    names: set[str] = set()
    for record in by_id.values():
        if isinstance(record, dict):
            if record.get("canonical_name"):
                names.add(record["canonical_name"])
            for alias in record.get("aliases") or []:
                if alias:
                    names.add(alias)
    return sorted(names, key=len, reverse=True)


def _find_entity_in_sentence(
    sentence: str, canon_view: dict[str, Any]
) -> list[tuple[str, str]]:
    """Return ``(name, entity_id)`` for every known entity in sentence.

    Longest match wins per position so a name like "林昭之子" is not
    shadowed by the shorter "林昭".
    """
    names = _known_entity_names(canon_view)
    by_id = canon_view.get("by_id") or {}
    found: list[tuple[int, int, str, str]] = []
    for name in names:
        start = 0
        while True:
            idx = sentence.find(name, start)
            if idx < 0:
                break
            record = by_id.get(_resolve_entity_id(name, canon_view) or "")
            if record is None:
                start = idx + 1
                continue
            found.append((idx, idx + len(name), name, record.get("canonical_name", name)))
            start = idx + 1
    if not found:
        return []
    found.sort()
    # Resolve overlaps: keep the longest match starting at each
    # position. Adjacent matches with the same name are merged.
    resolved: list[tuple[int, int, str, str]] = []
    for match in found:
        if resolved and match[0] < resolved[-1][1]:
            continue  # overlap; keep earlier (longer or earlier-start) match
        resolved.append(match)
    by_alias = canon_view.get("by_alias") or {}
    out: list[tuple[str, str]] = []
    for _, _, name, _ in resolved:
        entity_id = _resolve_entity_id(name, canon_view)
        if entity_id is not None:
            out.append((name, entity_id))
    return out


def _deterministic_inventory(context: FactExtractorContext) -> list[InventoryChange]:
    """Catch explicit numeric state, named gains, and named losses.

    The deterministic layer is *known-entity driven*: it first looks
    up which canon entities are mentioned in each sentence, then
    applies the verb patterns after each entity. This avoids the
    regex-engine trap of matching a leading temporal phrase
    ("天黑后，") as a fake entity.
    """
    canon_view = context.canon_view
    changes: list[InventoryChange] = []
    for sentence in _split_sentences(context.body):
        for name, entity_id in _find_entity_in_sentence(sentence, canon_view):
            # Numeric state has the highest precision; check it first.
            match = _NUMERIC_STATE_RE.search(sentence)
            if match and _resolve_entity_id(match.group("entity"), canon_view) == entity_id:
                count = _chinese_to_int(match.group("count"))
                if count is not None:
                    changes.append(
                        InventoryChange(
                            chapter_number=context.chapter_number,
                            source_sentence=sentence,
                            confidence=1.0,
                            entity_id=entity_id,
                            item=match.group("item"),
                            delta=0,
                            resulting_quantity=count,
                        )
                    )
                    continue
            match = _LOSE_ITEM_RE.search(sentence)
            if match and _resolve_entity_id(match.group("entity"), canon_view) == entity_id:
                changes.append(
                    InventoryChange(
                        chapter_number=context.chapter_number,
                        source_sentence=sentence,
                        confidence=1.0,
                        entity_id=entity_id,
                        item=match.group("item"),
                        delta=-1,
                    )
                )
                continue
            match = _TAKE_ITEM_RE.search(sentence)
            if match and _resolve_entity_id(match.group("entity"), canon_view) == entity_id:
                changes.append(
                    InventoryChange(
                        chapter_number=context.chapter_number,
                        source_sentence=sentence,
                        confidence=1.0,
                        entity_id=entity_id,
                        item=match.group("item"),
                        delta=1,
                    )
                )
    return changes


def _deterministic_locations(context: FactExtractorContext) -> list[LocationMovement]:
    canon_view = context.canon_view
    moves: list[LocationMovement] = []
    for sentence in _split_sentences(context.body):
        for name, entity_id in _find_entity_in_sentence(sentence, canon_view):
            # Use a fresh, entity-name anchored regex for the location
            # so the leading "天黑后，" never shadows the real subject.
            anchored = re.compile(
                re.escape(name)
                + r"[^\n。！？!?\.]{0,16}?"
                + r"(?:赶到了|抵达了|到达了|来到了|抵达|到达|来到|赶到|进入|走进|走入|回|返回)"
                + r"(?P<location>[一-龥]{2,8}?)"
                + r"(?=[。！？!?\.\s]|$)"
            )
            match = anchored.search(sentence)
            if not match:
                continue
            moves.append(
                LocationMovement(
                    chapter_number=context.chapter_number,
                    source_sentence=sentence,
                    confidence=1.0,
                    entity_id=entity_id,
                    to_location=match.group("location"),
                )
            )
    return moves


# --- Reference validation ------------------------------------------------------

def _collect_referenced_names(
    context: FactExtractorContext,
) -> list[tuple[str, str]]:
    """Return ``(name, role)`` pairs for every entity the prose mentions.

    Two passes run:

    1. *Known-entity pass* — every canon name that appears in the body.
    2. *Orphan pass* — short Chinese phrases at sentence start that
       *look* like a name (2-4 characters) but are not in the canon
       view. These are flagged so the workbench can prompt the user
       to either accept them as new canon entities or ignore them.

    The role is ``"subject"`` for the canonical scan and the implicit
    actor in the orphan scan; transfer targets are tagged separately
    so the workbench can render them as object spans.
    """
    canon_view = context.canon_view
    pairs: list[tuple[str, str]] = []
    for sentence in _split_sentences(context.body):
        for name, _ in _find_entity_in_sentence(sentence, canon_view):
            pairs.append((name, "subject"))
        transfer = _TRANSFER_VERB_RE.search(sentence)
        if transfer:
            source = transfer.group("source")
            target = transfer.group("target")
            for name in (source, target):
                if name and (name, "subject") not in pairs and (
                    name,
                    "transfer",
                ) not in pairs:
                    pairs.append((name, "transfer"))
        # Orphan pass: short Chinese names at the start of a sentence
        # (or after a comma) that the canon does not yet know about.
        for match in _CANDIDATE_NAME_RE.finditer(sentence):
            name = match.group("name")
            if any(name == existing for existing, _ in pairs):
                continue
            pairs.append((name, "subject"))
    return pairs


# A loose "looks like a name" pattern: 2-4 CJK ideographs at the
# start of a sentence or right after a comma. It deliberately
# produces false positives so the workbench can prompt the user
# to confirm; the user is the final arbiter of canon.
_CANDIDATE_NAME_RE = re.compile(
    r"(?:^|[，,。！？!?\s])(?P<name>[一-龥]{2,4})"
)


def _validate_references(
    context: FactExtractorContext,
    referenced: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    canon_view = context.canon_view
    report: list[dict[str, Any]] = []
    for name, role in referenced:
        entity_id = _resolve_entity_id(name, canon_view)
        entry = (
            _record_valid(name, entity_id)
            if entity_id is not None
            else _record_orphan(name)
        )
        entry["role"] = role
        report.append(entry)
    return report


# --- Model-backed pass ---------------------------------------------------------

def _safe_model_extract(
    context: FactExtractorContext,
    runtime: FactExtractorRuntime | None,
) -> tuple[list[RelationshipChange], list[ForeshadowingChange]]:
    """Call the model runtime and parse the ambiguous-fact response.

    Returns empty lists when no runtime is wired or when the runtime
    raises — the deterministic layer is the source of truth.
    """
    if runtime is None:
        return [], []
    try:
        response = runtime.complete(
            {
                "stage": "fact_extractor",
                "chapter_number": context.chapter_number,
                "body": context.body,
                "director_artifact": context.director_artifact,
                "canon_view": context.canon_view,
            }
        )
    except Exception:
        return [], []
    payload = response if isinstance(response, dict) else getattr(response, "payload", {}) or {}
    relationships: list[RelationshipChange] = []
    for item in payload.get("relationship_changes") or []:
        try:
            relationships.append(
                RelationshipChange(
                    chapter_number=context.chapter_number,
                    source_sentence=str(item.get("source_sentence") or ""),
                    confidence=float(item.get("confidence") or 0.5),
                    subject_id=str(item.get("subject_id") or ""),
                    predicate=str(item.get("predicate") or ""),
                    object_id=str(item.get("object_id") or ""),
                    polarity=item.get("polarity") or "added",
                )
            )
        except Exception:
            continue
    foreshadowing: list[ForeshadowingChange] = []
    for item in payload.get("foreshadowing_changes") or []:
        try:
            foreshadowing.append(
                ForeshadowingChange(
                    chapter_number=context.chapter_number,
                    source_sentence=str(item.get("source_sentence") or ""),
                    confidence=float(item.get("confidence") or 0.5),
                    foreshadowing_id=str(item.get("foreshadowing_id") or ""),
                    action=item.get("action") or "planted",
                    detail=str(item.get("detail") or ""),
                )
            )
        except Exception:
            continue
    return relationships, foreshadowing


# --- Public agent --------------------------------------------------------------

class FactExtractor:
    """The single entry point for assembling a ``ContinuityDelta``."""

    def __init__(self, *, runtime: FactExtractorRuntime | None = None) -> None:
        self._runtime = runtime

    def extract(self, context: FactExtractorContext) -> ContinuityDelta:
        delta = ContinuityDelta(chapter_number=context.chapter_number)
        delta.inventory_changes.extend(_deterministic_inventory(context))
        delta.location_movements.extend(_deterministic_locations(context))

        relationships, foreshadowing = _safe_model_extract(context, self._runtime)
        delta.relationship_changes.extend(relationships)
        delta.foreshadowing_changes.extend(foreshadowing)

        referenced = _collect_referenced_names(context)
        delta.reference_validation = _validate_references(context, referenced)
        return delta


def build_default_extractor(
    *, runtime: FactExtractorRuntime | None = None
) -> FactExtractor:
    """Return a default extractor instance for the orchestrator.

    ``runtime`` is optional so the orchestrator can opt out of model
    calls entirely (tests, dry runs, deterministic-only smoke runs).
    """
    return FactExtractor(runtime=runtime)
