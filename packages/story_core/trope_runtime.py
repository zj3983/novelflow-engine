from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from packages.story_core.agent_base import compact_list, compact_text

_MAX_TROPE_ID_CHARS = 120


def _normalize_scalar(value: Any) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    if not isinstance(value, (str, int, float, bool)):
        return ""
    return str(value).strip()


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Iterable) and not isinstance(value, (dict, bytes, bytearray)):
        items = list(value)
    else:
        items = []
    return [
        str(item).strip()
        for item in items
        if isinstance(item, (str, int, float, bool)) and str(item).strip()
    ]


def _normalize_template(template: Any) -> dict[str, Any] | None:
    if not isinstance(template, dict):
        return None
    template_id = _normalize_scalar(template.get("id"))
    if not template_id or len(template_id) > _MAX_TROPE_ID_CHARS:
        return None
    return {
        "id": template_id,
        "name": _normalize_scalar(template.get("name")),
        "trigger": _normalize_scalar(template.get("trigger")),
        "beats": _normalize_string_list(template.get("beats")),
        "payoff": _normalize_scalar(template.get("payoff")),
        "avoid": _normalize_string_list(template.get("avoid")),
    }


def compact_trope_candidates(templates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for template in templates:
        normalized = _normalize_template(template)
        if normalized is None or normalized["id"] in seen_ids:
            continue
        seen_ids.add(normalized["id"])
        compacted.append(
            {
                "id": normalized["id"],
                "name": compact_text(normalized["name"], 400),
                "trigger": compact_text(normalized["trigger"], 400),
                "beats": compact_list(normalized["beats"]),
                "payoff": compact_text(normalized["payoff"], 400),
                "avoid": compact_list(normalized["avoid"]),
            }
        )
    return deepcopy(compacted)


def merge_trope_templates(groups: Iterable[Iterable[dict[str, Any]]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for group in groups:
        for template in group:
            normalized = _normalize_template(template)
            if normalized is None or normalized["id"] in seen_ids:
                continue
            seen_ids.add(normalized["id"])
            merged.append(deepcopy(normalized))
    return deepcopy(merged)


def resolve_trope_contract(
    templates: Iterable[dict[str, Any]],
    template_id: str,
    current_beat: str | None,
) -> dict[str, Any]:
    normalized_template_id = _normalize_scalar(template_id)
    if not normalized_template_id or len(normalized_template_id) > _MAX_TROPE_ID_CHARS:
        return {}
    normalized_beat = _normalize_scalar(current_beat)
    for template in templates:
        normalized = _normalize_template(template)
        if normalized is None or normalized["id"] != normalized_template_id:
            continue
        if normalized_beat and normalized_beat not in normalized["beats"]:
            return {}
        return {
            "template_id": normalized["id"],
            "name": normalized["name"],
            "trigger": normalized["trigger"],
            "current_beat": normalized_beat,
            "payoff": normalized["payoff"],
            "avoid": deepcopy(normalized["avoid"]),
        }
    return {}


__all__ = [
    "compact_trope_candidates",
    "merge_trope_templates",
    "resolve_trope_contract",
]
