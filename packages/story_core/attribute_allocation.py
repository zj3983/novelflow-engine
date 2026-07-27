from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from itertools import islice
from typing import Any


_MAX_BASE_ATTRIBUTES = 16
_MAX_ATTRIBUTE_NAME = 120
_MAX_RESPEC_RULE = 240
_MAX_RAW_TEXT_SCAN = 4_096
_MAX_STARTING_LEVEL = 1_000_000


def _compact_text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or limit <= 0:
        return ""
    result: list[str] = []
    pending_space = False
    try:
        for character in islice(value, _MAX_RAW_TEXT_SCAN):
            if not character.isprintable():
                continue
            if character.isspace():
                pending_space = bool(result)
                continue
            if pending_space and len(result) < limit - 1:
                result.append(" ")
            pending_space = False
            if len(result) >= limit:
                break
            result.append(character)
            if len(result) >= limit:
                break
    except Exception:
        return ""
    return "".join(result).rstrip()


def _positive_integer(value: Any, *, maximum: int | None = None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    if maximum is not None and value > maximum:
        return None
    return value


def _base_attributes(value: Any) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        items = list(islice(value.items(), _MAX_BASE_ATTRIBUTES + 1))
    except Exception:
        return None
    if not items or len(items) > _MAX_BASE_ATTRIBUTES:
        return None

    result: dict[str, int] = {}
    for name, points in items:
        compact_name = _compact_text(name, _MAX_ATTRIBUTE_NAME)
        if not compact_name or compact_name in result:
            return None
        if isinstance(points, bool) or not isinstance(points, int) or not 0 <= points <= 10_000:
            return None
        result[compact_name] = points
    return result


def normalize_attribute_allocation_rule(value: Any) -> dict[str, Any]:
    """Return a bounded canonical free-attribute rule, or an empty mapping."""

    if not isinstance(value, Mapping):
        return {}
    try:
        mode = _compact_text(value.get("mode"), 16).casefold()
        points_per_level = _positive_integer(value.get("points_per_level"), maximum=100)
        starting_level = _positive_integer(
            value.get("starting_level"), maximum=_MAX_STARTING_LEVEL
        )
        base_attributes = _base_attributes(value.get("base_attributes"))
        allow_carry = value.get("allow_carry")
        respec_rule = _compact_text(value.get("respec_rule"), _MAX_RESPEC_RULE)
    except Exception:
        return {}

    if (
        mode != "free"
        or points_per_level is None
        or starting_level is None
        or base_attributes is None
        or not isinstance(allow_carry, bool)
        or not respec_rule
    ):
        return {}
    return deepcopy(
        {
            "mode": "free",
            "points_per_level": points_per_level,
            "starting_level": starting_level,
            "base_attributes": base_attributes,
            "allow_carry": allow_carry,
            "respec_rule": respec_rule,
        }
    )
