from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from packages.story_core.agent_base import compact_list, compact_text


def _compact_scalar(value: Any, *, max_chars: int = 400) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    if not isinstance(value, (str, int, float, bool)):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return compact_text(text, max_chars)


def _compact_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Iterable) and not isinstance(value, (dict, bytes, bytearray)):
        items = list(value)
    else:
        items = []
    cleaned = [
        str(item).strip()
        for item in items
        if isinstance(item, (str, int, float, bool)) and str(item).strip()
    ]
    return compact_list(cleaned)


def compact_trope_candidates(templates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for template in templates:
        if not isinstance(template, dict):
            continue
        template_id = _compact_scalar(template.get("id"))
        if not template_id or template_id in seen_ids:
            continue
        seen_ids.add(template_id)
        compacted.append(
            {
                "id": template_id,
                "name": _compact_scalar(template.get("name")),
                "trigger": _compact_scalar(template.get("trigger")),
                "beats": _compact_string_list(template.get("beats")),
                "payoff": _compact_scalar(template.get("payoff")),
                "avoid": _compact_string_list(template.get("avoid")),
            }
        )
    return deepcopy(compacted)


def merge_trope_templates(groups: Iterable[Iterable[dict[str, Any]]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for group in groups:
        for template in compact_trope_candidates(group):
            template_id = template["id"]
            if template_id in seen_ids:
                continue
            seen_ids.add(template_id)
            merged.append(template)
    return deepcopy(merged)


def resolve_trope_contract(
    templates: Iterable[dict[str, Any]],
    template_id: str,
    current_beat: str | None,
) -> dict[str, Any]:
    normalized_template_id = _compact_scalar(template_id)
    normalized_beat = _compact_scalar(current_beat, max_chars=80) if current_beat is not None else ""
    if not normalized_template_id or not normalized_beat:
        return {}
    for template in compact_trope_candidates(templates):
        if template["id"] != normalized_template_id:
            continue
        if normalized_beat not in template["beats"]:
            return {}
        return {
            "template_id": template["id"],
            "name": template["name"],
            "trigger": template["trigger"],
            "current_beat": normalized_beat,
            "payoff": template["payoff"],
            "avoid": deepcopy(template["avoid"]),
        }
    return {}


__all__ = [
    "compact_trope_candidates",
    "merge_trope_templates",
    "resolve_trope_contract",
]
