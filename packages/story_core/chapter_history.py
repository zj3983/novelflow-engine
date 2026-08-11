"""Pure helpers for chapter-number keyed story history."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping, Sequence


def replace_chapter_record(
    items: Sequence[Any],
    entry: Mapping[str, Any],
    *,
    limit: int = 120,
) -> list[Any]:
    """Replace one chapter record, order structured rows, and retain the tail."""

    record = dict(entry)
    chapter_number = record.get("chapter_number")
    filtered = [
        item
        for item in items
        if not (
            (isinstance(item, dict) and item.get("chapter_number") == chapter_number)
            or (
                isinstance(item, str)
                and chapter_number is not None
                and re.match(
                    rf"^\s*chapter\s+{int(chapter_number)}\s*:",
                    item,
                    re.IGNORECASE,
                )
            )
        )
    ]
    filtered.append(record)
    filtered.sort(
        key=lambda item: (
            int(item.get("chapter_number") or 0)
            if isinstance(item, dict)
            else 0
        )
    )
    return filtered[-limit:]


def apply_chapter_history(
    state: Mapping[str, Any],
    chapter_summary: Mapping[str, Any],
    *,
    limit: int = 240,
) -> dict[str, Any]:
    """Return a copied story payload advanced by one normalized chapter summary."""

    updated = deepcopy(dict(state))
    summary = dict(chapter_summary)
    chapter_number = summary.get("chapter_number")
    summary_text = str(summary.get("summary") or "")
    next_focus = str(summary.get("next_focus") or "")

    updated["current_chapter"] = chapter_number
    updated["chapter_summaries"] = replace_chapter_record(
        list(updated.get("chapter_summaries") or []),
        summary,
        limit=limit,
    )
    updated["timeline"] = replace_chapter_record(
        list(updated.get("timeline") or []),
        {
            "chapter_number": chapter_number,
            "summary": summary_text,
            "impact": next_focus or summary_text,
        },
        limit=limit,
    )
    return updated
