"""Normalize static worldbuilding and evolving story continuity.

Legacy file projects mixed stable rules, current state, chapter facts and
chapter summaries in ``world_facts`` and ``world_blueprint``.  This module is
the compatibility boundary that separates those concerns before they reach
the writer or the workbench.
"""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import json
import re
from typing import Any, Iterable


DYNAMIC_BLUEPRINT_FIELDS = frozenset({"current_arc", "continuity_state", "time_state"})
_CHAPTER_FACT_PREFIX = re.compile(r"^第\s*(\d+)\s*章事实\s*[：:]\s*(.+)$")
_CHAPTER_SUMMARY_PREFIX = re.compile(r"^第\s*\d+\s*章摘要\s*[：:]", re.DOTALL)
_STATIC_FACT_PREFIX = re.compile(
    r"^(?:小说类型|世界摘要|世界前提|世界背景|世界规则|力量体系|成长规则|经济体系|"
    r"任务体系|阵营规则|面板规则|现实桥接|当前焦点|卷规划|卷核心目标)\s*[：:]"
)
_MAX_CONTINUITY_FACT_CHARS = 320


@dataclass(frozen=True)
class NormalizedWorldContext:
    static_blueprint: dict[str, Any]
    world_snapshot: dict[str, Any]
    continuity_facts: list[dict[str, Any]]


def normalize_world_context(
    *,
    blueprint: Any,
    state: Any,
    current_focus: Any = "",
) -> NormalizedWorldContext:
    world = deepcopy(blueprint) if isinstance(blueprint, dict) else {}
    story_state = state if isinstance(state, dict) else {}
    static_blueprint = {
        key: value for key, value in world.items() if key not in DYNAMIC_BLUEPRINT_FIELDS
    }

    world_snapshot = deepcopy(story_state.get("world_snapshot"))
    if not isinstance(world_snapshot, dict):
        world_snapshot = {}
    for key in ("current_arc", "time_state"):
        value = world.get(key)
        if _has_content(value) and not _has_content(world_snapshot.get(key)):
            world_snapshot[key] = deepcopy(value)
    focus = str(current_focus or story_state.get("current_focus") or "").strip()
    if focus and not str(world_snapshot.get("current_focus") or "").strip():
        world_snapshot["current_focus"] = focus

    facts: list[dict[str, Any]] = []
    facts.extend(_fact_records(story_state.get("continuity_facts")))
    continuity = world.get("continuity_state")
    if isinstance(continuity, dict):
        facts.extend(_fact_records(continuity.get("running_facts")))
        facts.extend(_chapter_fact_records(continuity.get("chapter_facts")))

    static_values = _flatten_text(static_blueprint)
    facts.extend(_legacy_world_fact_records(story_state.get("world_facts"), static_values))

    return NormalizedWorldContext(
        static_blueprint=static_blueprint,
        world_snapshot=world_snapshot,
        continuity_facts=_dedupe_fact_records(facts),
    )


def append_continuity_facts(
    existing: Any,
    *,
    chapter_number: int,
    facts: Iterable[str],
) -> list[dict[str, Any]]:
    records = _fact_records(existing)
    by_key = {_fact_key(item["text"]): item for item in records}
    order = [_fact_key(item["text"]) for item in records]
    for value in facts:
        text = _clean_fact_text(value)
        if not _is_continuity_fact(text):
            continue
        key = _fact_key(text)
        if key in by_key:
            by_key[key]["updated_chapter"] = max(
                int(by_key[key].get("updated_chapter") or 0), chapter_number
            )
            continue
        by_key[key] = _record(text, chapter_number, chapter_number)
        order.append(key)
    return [by_key[key] for key in order]


def relevant_continuity_facts(
    facts: Any,
    *,
    query_terms: Iterable[str] = (),
    limit: int = 12,
) -> list[dict[str, Any]]:
    records = _dedupe_fact_records(_fact_records(facts))
    terms = [str(term).strip().casefold() for term in query_terms if str(term).strip()]

    def score(item: dict[str, Any]) -> tuple[int, int, int]:
        text = str(item.get("text") or "").casefold()
        matches = sum(1 for term in terms if term in text)
        return (
            matches,
            int(item.get("updated_chapter") or 0),
            int(item.get("source_chapter") or 0),
        )

    if terms:
        records.sort(key=lambda item: score(item)[0], reverse=True)
    else:
        records.sort(key=lambda item: score(item)[1:], reverse=True)
    return records[: max(0, int(limit))]


def _legacy_world_fact_records(values: Any, static_values: set[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for value in values if isinstance(values, list) else []:
        if isinstance(value, dict):
            records.extend(_fact_records([value]))
            continue
        raw = str(value or "").strip()
        if not raw or _CHAPTER_SUMMARY_PREFIX.match(raw):
            continue
        match = _CHAPTER_FACT_PREFIX.match(raw)
        chapter = int(match.group(1)) if match else 0
        text = _clean_fact_text(match.group(2) if match else raw)
        if _STATIC_FACT_PREFIX.match(raw) or _is_static_duplicate(text, static_values):
            continue
        if _is_continuity_fact(text):
            records.append(_record(text, chapter, chapter))
    return records


def _chapter_fact_records(values: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for value in values if isinstance(values, list) else []:
        if not isinstance(value, dict):
            records.extend(_fact_records([value]))
            continue
        chapter = int(value.get("chapter_number") or value.get("chapter") or 0)
        nested = value.get("facts")
        if isinstance(nested, list):
            for fact in nested:
                text = _clean_fact_text(fact)
                if _is_continuity_fact(text):
                    records.append(_record(text, chapter, chapter))
        else:
            text = _clean_fact_text(value.get("text") or value.get("fact"))
            if _is_continuity_fact(text):
                records.append(_record(text, chapter, chapter))
    return records


def _fact_records(values: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for value in values if isinstance(values, list) else []:
        if isinstance(value, str):
            text = _clean_fact_text(value)
            if _is_continuity_fact(text):
                records.append(_record(text, 0, 0))
            continue
        if not isinstance(value, dict):
            continue
        text = _clean_fact_text(value.get("text") or value.get("fact"))
        if not _is_continuity_fact(text):
            continue
        source = int(value.get("source_chapter") or value.get("chapter_number") or 0)
        updated = int(value.get("updated_chapter") or source)
        records.append(
            {
                "text": text,
                "source_chapter": source,
                "status": str(value.get("status") or "active"),
                "updated_chapter": updated,
            }
        )
    return records


def _dedupe_fact_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in records:
        text = _clean_fact_text(item.get("text"))
        if not _is_continuity_fact(text):
            continue
        key = _fact_key(text)
        candidate = {
            "text": text,
            "source_chapter": int(item.get("source_chapter") or 0),
            "status": str(item.get("status") or "active"),
            "updated_chapter": int(item.get("updated_chapter") or item.get("source_chapter") or 0),
        }
        current = by_key.get(key)
        if current is None:
            by_key[key] = candidate
            order.append(key)
            continue
        current_source = int(current.get("source_chapter") or 0)
        candidate_source = int(candidate.get("source_chapter") or 0)
        if not current_source and candidate_source:
            current["source_chapter"] = candidate_source
        current["updated_chapter"] = max(
            int(current.get("updated_chapter") or 0),
            int(candidate.get("updated_chapter") or 0),
        )
        if candidate["status"] != "active":
            current["status"] = candidate["status"]
    return [by_key[key] for key in order]


def _record(text: str, source_chapter: int, updated_chapter: int) -> dict[str, Any]:
    return {
        "text": text,
        "source_chapter": int(source_chapter),
        "status": "active",
        "updated_chapter": int(updated_chapter),
    }


def _clean_fact_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _fact_key(text: str) -> str:
    return re.sub(r"[\s，。！？；：、,.!?;:]", "", text).casefold()


def _is_continuity_fact(text: str) -> bool:
    if not text or len(text) > _MAX_CONTINUITY_FACT_CHARS:
        return False
    normalized = text.strip().casefold()
    if normalized in {
        "continue",
        "manual draft",
        "manual rewrite",
        "manual chapter",
        "chapter-progress",
    }:
        return False
    if re.match(
        r"^(?:\u7b2c\s*\d+\s*\u7ae0\s*(?:\u4e8b\u5b9e|\u6458\u8981)|chapter\s*\d+\s*(?:fact|summary))\s*[:\uff1a]\s*continue\s*$",
        normalized,
        re.IGNORECASE,
    ):
        return False
    if _CHAPTER_SUMMARY_PREFIX.match(text) or _STATIC_FACT_PREFIX.match(text):
        return False
    return True


def _flatten_text(value: Any) -> set[str]:
    values: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            values.update(_flatten_text(item))
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            values.update(_flatten_text(item))
    elif isinstance(value, str):
        text = _clean_fact_text(value)
        if text:
            values.add(_fact_key(text))
    return values


def _is_static_duplicate(text: str, static_values: set[str]) -> bool:
    key = _fact_key(text)
    return bool(key and key in static_values)


def _has_content(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    try:
        return bool(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError):
        return bool(value)


__all__ = [
    "DYNAMIC_BLUEPRINT_FIELDS",
    "NormalizedWorldContext",
    "append_continuity_facts",
    "normalize_world_context",
    "relevant_continuity_facts",
]
