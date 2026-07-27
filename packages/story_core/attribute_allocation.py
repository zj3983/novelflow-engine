from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from itertools import islice
import re
from typing import Any


_MAX_BASE_ATTRIBUTES = 16
_MAX_ATTRIBUTE_NAME = 120
_MAX_RESPEC_RULE = 240
_MAX_RAW_TEXT_SCAN = 4_096
_MAX_STARTING_LEVEL = 1_000_000
_MAX_LEVEL_DIGITS = len(str(_MAX_STARTING_LEVEL))
_MAX_LEVEL_UP_SPAN = 1_000
_LEVEL_PATTERN = re.compile(r"^(?:lv\.\s*)?(\d+)(?:\s*\u7ea7)?$", re.IGNORECASE)
_ATTRIBUTE_POINT_HANDLING_TOKENS = ("属性点", "加点", "配点", "保留点数", "分配属性")
_ATTRIBUTE_POINT_NEGATIONS = ("不要", "禁止", "不得", "避免", "无需")
_ATTRIBUTE_ACTION_FIELDS = ("turn", "pivot", "ordered_actions", "chapter_satisfaction", "state_delta")
_ATTRIBUTE_SCENE_FIELDS = ("purpose", "must_show", "state_delta")
_ATTRIBUTE_IGNORED_FIELDS = {
    "attribute_allocation_decision",
    "chapter_end_hook",
    "next_focus",
    "next_hook",
    "must_not_write",
    "avoid",
}


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


def parse_level(value: Any) -> int | None:
    """Parse an existing numeric or display level into a positive integer."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 < value <= _MAX_STARTING_LEVEL else None
    if not isinstance(value, str):
        return None
    match = _LEVEL_PATTERN.fullmatch(value.strip())
    if not match:
        return None
    digits = match.group(1)
    if len(digits) > _MAX_LEVEL_DIGITS:
        return None
    try:
        level = int(digits)
    except (ValueError, OverflowError):
        return None
    return level if 0 < level <= _MAX_STARTING_LEVEL else None


def attribute_allocation_rule_from_story(story: Any) -> dict[str, Any]:
    """Return the normalized structured allocation rule configured on a story."""

    world_context = story.get("world_context") if isinstance(story, Mapping) else getattr(story, "world_context", None)
    if not isinstance(world_context, Mapping):
        return {}
    power_system_spec = world_context.get("power_system_spec")
    if not isinstance(power_system_spec, Mapping):
        return {}
    return normalize_attribute_allocation_rule(power_system_spec.get("attribute_allocation"))


def _valid_unallocated_points(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _unallocated_points(value: Any) -> int:
    return _valid_unallocated_points(value) or 0


def current_protagonist_level(ledger: Any, starting_level: int) -> int:
    """Read the current protagonist level from nested or legacy flat ledgers."""

    if not isinstance(ledger, Mapping):
        return starting_level
    protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), Mapping) else {}
    return parse_level(protagonist.get("level")) or parse_level(ledger.get("level")) or starting_level


def current_unallocated_attribute_points(ledger: Any) -> int:
    """Read unallocated points from nested or legacy flat ledgers."""

    if not isinstance(ledger, Mapping):
        return 0
    protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), Mapping) else {}
    protagonist_points = _valid_unallocated_points(protagonist.get("unallocated_attribute_points"))
    if protagonist_points is not None:
        return protagonist_points
    return _unallocated_points(ledger.get("unallocated_attribute_points"))


def planned_level_target(plan: Any) -> int | None:
    """Read an explicit level target from the current chapter plan only."""

    if not isinstance(plan, Mapping):
        return None

    def protagonist_level(state_delta: Any) -> int | None:
        if not isinstance(state_delta, Mapping):
            return None
        protagonist = state_delta.get("protagonist")
        if not isinstance(protagonist, Mapping):
            return None
        return parse_level(protagonist.get("level")) or (
            parse_level(protagonist.get("panel", {}).get("level"))
            if isinstance(protagonist.get("panel"), Mapping)
            else None
        )

    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), Mapping) else {}
    levels = [
        parse_level(event_plan.get("attribute_allocation_level_target")),
        parse_level(event_plan.get("level")),
        protagonist_level(event_plan.get("state_delta")),
        protagonist_level(plan.get("state_delta")),
    ]
    scene_cards = plan.get("scene_cards")
    if isinstance(scene_cards, list):
        levels.extend(
            protagonist_level(card.get("state_delta"))
            for card in scene_cards[:6]
            if isinstance(card, Mapping)
        )
    levels = [level for level in levels if level is not None]
    return max(levels) if levels else None


def plan_handles_attribute_points(plan: Any) -> bool:
    """Return whether the current chapter explicitly handles existing attribute points."""

    if not isinstance(plan, Mapping):
        return False

    def has_handling_signal(value: Any) -> bool:
        def text_handles_points(text: str) -> bool:
            for token in _ATTRIBUTE_POINT_HANDLING_TOKENS:
                start = text.find(token)
                while start >= 0:
                    prefix = text[max(0, start - 8) : start]
                    if not any(negation in prefix for negation in _ATTRIBUTE_POINT_NEGATIONS):
                        return True
                    start = text.find(token, start + len(token))
            return False

        pending = [value]
        seen: set[int] = set()
        while pending:
            current = pending.pop()
            if isinstance(current, str):
                if text_handles_points(current):
                    return True
                continue
            if isinstance(current, Mapping):
                identity = id(current)
                if identity in seen:
                    continue
                seen.add(identity)
                for key, nested in current.items():
                    field_name = key.casefold() if isinstance(key, str) else ""
                    if field_name in _ATTRIBUTE_IGNORED_FIELDS or "future" in field_name:
                        continue
                    if isinstance(key, str) and text_handles_points(key):
                        return True
                    pending.append(nested)
                continue
            if isinstance(current, list):
                identity = id(current)
                if identity in seen:
                    continue
                seen.add(identity)
                pending.extend(current)
        return False

    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), Mapping) else {}
    sources = [event_plan.get(field) for field in _ATTRIBUTE_ACTION_FIELDS]
    scene_cards = plan.get("scene_cards")
    if isinstance(scene_cards, list):
        for card in scene_cards[:6]:
            if isinstance(card, Mapping):
                sources.extend(card.get(field) for field in _ATTRIBUTE_SCENE_FIELDS)
    return any(has_handling_signal(value) for value in sources)


def validate_attribute_allocation_decision(
    decision: Any,
    rule: Mapping[str, Any],
    available_points: Any,
) -> dict[str, Any]:
    """Return one canonical chapter allocation decision, or an empty mapping."""

    normalized_rule = normalize_attribute_allocation_rule(rule)
    available = _unallocated_points(available_points)
    if not normalized_rule or not isinstance(decision, Mapping):
        return {}
    mode = _compact_text(decision.get("mode"), 16).casefold()
    remaining = decision.get("remaining")
    if isinstance(remaining, bool) or not isinstance(remaining, int) or remaining < 0:
        return {}
    if mode == "carry":
        if "allocations" in decision or not normalized_rule["allow_carry"] or remaining != available:
            return {}
        reason = _compact_text(decision.get("reason"), _MAX_RESPEC_RULE)
        if not reason:
            return {}
        return {"mode": "carry", "remaining": remaining, "reason": reason}
    if mode != "allocate":
        return {}
    allocations = decision.get("allocations")
    if not isinstance(allocations, Mapping) or not allocations:
        return {}
    normalized_allocations: dict[str, int] = {}
    for name, points in allocations.items():
        if (
            not isinstance(name, str)
            or name not in normalized_rule["base_attributes"]
            or isinstance(points, bool)
            or not isinstance(points, int)
            or points <= 0
        ):
            return {}
        normalized_allocations[name] = points
    spent = sum(normalized_allocations.values())
    if spent > available or remaining != available - spent:
        return {}
    result = {"mode": "allocate", "allocations": normalized_allocations, "remaining": remaining}
    reason = _compact_text(decision.get("reason"), _MAX_RESPEC_RULE)
    if reason:
        result["reason"] = reason
    return result


def attribute_allocation_context(story: Any, plan: Any | None = None) -> dict[str, Any]:
    """Build a read-only, writer-safe view of free attribute allocation state."""

    rule = attribute_allocation_rule_from_story(story)
    if not rule:
        return {}
    ledger = story.get("progression_ledger") if isinstance(story, Mapping) else getattr(story, "progression_ledger", None)
    ledger = ledger if isinstance(ledger, Mapping) else {}
    protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), Mapping) else {}
    raw_attributes = protagonist.get("attributes")
    attributes = deepcopy(dict(raw_attributes)) if isinstance(raw_attributes, Mapping) else deepcopy(rule["base_attributes"])
    available = current_unallocated_attribute_points(ledger)
    allocations = protagonist.get("attribute_allocations")
    latest_allocations = (
        [deepcopy(item) for item in allocations if isinstance(item, Mapping)][-3:]
        if isinstance(allocations, list)
        else []
    )
    context: dict[str, Any] = {
        "mode": rule["mode"],
        "points_per_level": rule["points_per_level"],
        "starting_level": rule["starting_level"],
        "attributes": attributes,
        "available_points": available,
        "latest_allocations": latest_allocations,
    }
    event_plan = plan.get("event_plan") if isinstance(plan, Mapping) and isinstance(plan.get("event_plan"), Mapping) else {}
    current_level = current_protagonist_level(ledger, rule["starting_level"])
    target_level = planned_level_target(plan)
    expected_points = available + max(0, (target_level or current_level) - current_level) * rule["points_per_level"]
    decision = validate_attribute_allocation_decision(
        event_plan.get("attribute_allocation_decision"), rule, expected_points
    )
    if decision:
        context["chapter_decision"] = decision
    return context


def award_attribute_points(
    ledger: dict[str, Any],
    rule: Mapping[str, Any],
    previous_level: Any,
    current_level: Any,
    chapter_number: int | None,
) -> None:
    """Grant each unrecorded level-up award exactly once to the protagonist ledger."""

    normalized_rule = normalize_attribute_allocation_rule(rule)
    if not normalized_rule or not isinstance(ledger, dict):
        return
    current = parse_level(current_level)
    if current is None:
        return
    starting_level = normalized_rule["starting_level"]
    previous = parse_level(previous_level)
    from_level = max(previous if previous is not None else starting_level, starting_level)
    if current <= from_level or current - from_level > _MAX_LEVEL_UP_SPAN:
        return

    protagonist = ledger.get("protagonist")
    source_protagonist = protagonist if isinstance(protagonist, dict) else {}
    awards = source_protagonist.get("attribute_point_awards")
    awards = deepcopy(awards) if isinstance(awards, list) else []
    awarded_levels = {
        parse_level(award.get("level"))
        for award in awards
        if isinstance(award, Mapping) and parse_level(award.get("level")) is not None
    }
    points = normalized_rule["points_per_level"]
    new_awards = [
        {"level": level, "points": points, "chapter": chapter_number}
        for level in range(from_level + 1, current + 1)
        if level not in awarded_levels
    ]
    if not new_awards:
        return
    if not isinstance(protagonist, dict):
        protagonist = {}
        ledger["protagonist"] = protagonist
    if "attributes" not in protagonist:
        protagonist["attributes"] = deepcopy(normalized_rule["base_attributes"])
    protagonist["attribute_point_awards"] = [*awards, *new_awards]
    protagonist["unallocated_attribute_points"] = _unallocated_points(
        protagonist.get("unallocated_attribute_points")
    ) + sum(award["points"] for award in new_awards)


def apply_attribute_allocation(
    ledger: dict[str, Any],
    directive: Any,
    rule: Mapping[str, Any],
    chapter_number: int | None,
) -> bool:
    """Validate and atomically apply one free-attribute allocation directive."""

    normalized_rule = normalize_attribute_allocation_rule(rule)
    if not normalized_rule or not isinstance(ledger, dict) or not isinstance(directive, Mapping):
        return False
    allocations = directive.get("allocations")
    if not isinstance(allocations, Mapping) or not allocations:
        return False

    protagonist = ledger.get("protagonist")
    source_protagonist = protagonist if isinstance(protagonist, dict) else {}
    source_attributes = source_protagonist.get("attributes")
    if "attributes" in source_protagonist and not isinstance(source_attributes, Mapping):
        return False
    attributes = (
        deepcopy(dict(source_attributes))
        if isinstance(source_attributes, Mapping)
        else deepcopy(normalized_rule["base_attributes"])
    )
    normalized_allocations: dict[str, int] = {}
    for name, points in allocations.items():
        if (
            not isinstance(name, str)
            or name not in normalized_rule["base_attributes"]
            or isinstance(points, bool)
            or not isinstance(points, int)
            or points <= 0
        ):
            return False
        if name not in attributes:
            attributes[name] = normalized_rule["base_attributes"][name]
        if isinstance(attributes[name], bool) or not isinstance(attributes[name], int):
            return False
        normalized_allocations[name] = points

    reason = directive.get("reason", "")
    if not isinstance(reason, str):
        return False
    existing_allocations = source_protagonist.get("attribute_allocations")
    allocation_history = deepcopy(existing_allocations) if isinstance(existing_allocations, list) else []
    duplicate = next(
        (
            item
            for item in allocation_history
            if isinstance(item, Mapping)
            and item.get("chapter") == chapter_number
            and item.get("allocations") == normalized_allocations
        ),
        None,
    )
    remaining = directive.get("remaining")
    if duplicate is not None:
        return remaining is None or (
            isinstance(remaining, int)
            and not isinstance(remaining, bool)
            and remaining == duplicate.get("remaining")
        )

    available = _unallocated_points(source_protagonist.get("unallocated_attribute_points"))
    spent = sum(normalized_allocations.values())
    calculated_remaining = available - spent
    if calculated_remaining < 0:
        return False
    if remaining is not None and (
        isinstance(remaining, bool)
        or not isinstance(remaining, int)
        or remaining != calculated_remaining
    ):
        return False

    updated_protagonist = deepcopy(source_protagonist)
    updated_protagonist["attributes"] = attributes
    for name, points in normalized_allocations.items():
        updated_protagonist["attributes"][name] += points
    updated_protagonist["unallocated_attribute_points"] = calculated_remaining
    updated_protagonist["attribute_allocations"] = [
        *allocation_history,
        {
            "chapter": chapter_number,
            "allocations": normalized_allocations,
            "remaining": calculated_remaining,
            "reason": reason,
        },
    ]
    ledger["protagonist"] = updated_protagonist
    return True
