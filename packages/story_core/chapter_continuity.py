from __future__ import annotations

from typing import Any


FACT_PRIORITY = ["已发生剧情", "本章计划", "静态人物设定", "后续旧稿"]


def _chapter_number(chapter: dict[str, Any] | None) -> int | None:
    if not isinstance(chapter, dict):
        return None
    try:
        number = int(chapter.get("chapter_number") or 0)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _body_slice(chapter: dict[str, Any] | None, *, limit: int, tail: bool) -> str:
    if not isinstance(chapter, dict):
        return ""
    body = str(chapter.get("body") or "").strip()
    if not body:
        return ""
    if len(body) <= limit:
        return body
    return body[-limit:] if tail else body[:limit]


def _summary_items(chapter: dict[str, Any] | None, key: str, *, limit: int) -> list[str]:
    if not isinstance(chapter, dict):
        return []
    summary = chapter.get("chapter_summary")
    if not isinstance(summary, dict):
        return []
    values = summary.get(key)
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def build_continuity_interface(
    target_chapter: int,
    *,
    previous: dict[str, Any] | None,
    next_chapter: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build transient adjacent-chapter context for one generation run."""

    if target_chapter < 1:
        raise ValueError("target_chapter_must_be_positive")

    result: dict[str, Any] = {}
    previous_number = _chapter_number(previous)
    previous_tail = _body_slice(previous, limit=1000, tail=True)
    previous_facts = _summary_items(previous, "facts", limit=10)
    previous_threads = _summary_items(previous, "unresolved_threads", limit=6)
    if previous_number is not None:
        result["previous_chapter_number"] = previous_number
    if previous_tail:
        result["previous_tail"] = previous_tail
    if previous_facts:
        result["previous_facts"] = previous_facts
    if previous_threads:
        result["previous_threads"] = previous_threads

    next_number = _chapter_number(next_chapter)
    next_opening = _body_slice(next_chapter, limit=700, tail=False)
    if next_number is not None:
        result["next_chapter_number"] = next_number
    if next_opening:
        result["next_opening"] = next_opening

    if result:
        result["fact_priority"] = list(FACT_PRIORITY)
    return result
