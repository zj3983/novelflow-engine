from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import json
import math
import re
from typing import Any

from packages.story_core.novel_type_ids import canonical_novel_type_id
from packages.story_core.power_system_templates import POWER_SYSTEM_TEMPLATES


CANONICAL_FIELDS = (
    "name",
    "origin",
    "attributes",
    "paths",
    "stages",
    "skills",
    "equipment",
    "resources",
    "advancement",
    "costs",
    "counters",
    "boundaries",
    "social_impact",
    "visibility",
    "continuity_ledger",
)
PATH_FIELDS = (
    "name",
    "role",
    "core_resource",
    "weapons",
    "armor",
    "combat_loop",
    "strengths",
    "weaknesses",
    "branches",
    "advancement",
)
STAGE_FIELDS = ("name", "level", "entry", "change", "failure")
ATTRIBUTE_FIELDS = ("name", "effect")
TEXT_LIST_FIELDS = (
    "origin",
    "skills",
    "equipment",
    "resources",
    "advancement",
    "costs",
    "counters",
    "boundaries",
    "social_impact",
    "visibility",
    "continuity_ledger",
)
PATH_TEXT_LIST_FIELDS = (
    "weapons",
    "armor",
    "strengths",
    "weaknesses",
    "branches",
    "advancement",
)

_MAX_STRING = 240
_MAX_LIST = 64
_MAX_NUMBER = 1_000_000
_PROMPT_BUDGET = 5_000
_GAME_CLASSES = frozenset(("战士", "法师", "游侠", "盗贼", "牧师", "召唤师"))
_GAME_MILESTONES = frozenset((1, 10, 20, 30, 60))
_BASE_REQUIRED = frozenset(
    (
        "name",
        "attributes",
        "equipment",
        "advancement",
        "costs",
        "counters",
        "boundaries",
        "social_impact",
        "visibility",
    )
)


class PowerSystemValidationError(ValueError):
    """A stable, machine-readable power-system validation failure."""

    def __init__(
        self,
        missing_sections: Sequence[str] = (),
        violations: Sequence[str] = (),
    ) -> None:
        self.missing_sections = tuple(sorted(set(missing_sections)))
        self.violations = tuple(sorted(set(violations)))
        super().__init__(
            "invalid power system spec: "
            f"missing_sections={self.missing_sections}; violations={self.violations}"
        )


def _mapping_items(value: Any) -> list[tuple[Any, Any]]:
    if not isinstance(value, Mapping):
        return []
    try:
        return list(value.items())
    except Exception:
        return []


def _mapping_get(value: Any, key: str, default: Any = None) -> Any:
    if not isinstance(value, Mapping):
        return default
    try:
        return value.get(key, default)
    except Exception:
        return default


def _has_key(value: Any, key: str) -> bool:
    if not isinstance(value, Mapping):
        return False
    try:
        return key in value
    except Exception:
        return False


def _text(value: Any, limit: int = _MAX_STRING) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = "".join(
        " " if character.isspace() else character if character.isprintable() else ""
        for character in value
    )
    compact = " ".join(cleaned.split())
    return compact[:limit]


def _items(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return list(value[:_MAX_LIST])
    return []


def _text_list(value: Any, *, limit: int = _MAX_LIST, chars: int = _MAX_STRING) -> list[str]:
    result: list[str] = []
    for item in _items(value)[:limit]:
        compact = _text(item, chars)
        if compact:
            result.append(compact)
    return result


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return 0
    bounded = min(max(value, -_MAX_NUMBER), _MAX_NUMBER)
    return int(bounded) if isinstance(value, int) or bounded.is_integer() else bounded


def _normalize_record(value: Any, fields: Sequence[str]) -> dict[str, Any]:
    if not _mapping_items(value):
        return {}
    result: dict[str, Any] = {}
    for field in fields:
        if not _has_key(value, field):
            continue
        raw = _mapping_get(value, field)
        if field == "level":
            number = _number(raw)
            if number is not None:
                result[field] = number
        elif field in PATH_TEXT_LIST_FIELDS:
            result[field] = _text_list(raw)
        else:
            compact = _text(raw)
            if compact:
                result[field] = compact
    return result


def normalize_power_system_spec(value: Any) -> dict[str, Any]:
    """Return a bounded, canonical, JSON-safe copy of an untrusted specification."""

    if not isinstance(value, Mapping):
        return {}
    try:
        if not _mapping_items(value):
            return {}
        result: dict[str, Any] = {}
        for field in CANONICAL_FIELDS:
            if not _has_key(value, field):
                continue
            raw = _mapping_get(value, field)
            if field == "name":
                compact = _text(raw)
                if compact:
                    result[field] = compact
            elif field in TEXT_LIST_FIELDS:
                result[field] = _text_list(raw)
            elif field == "attributes":
                result[field] = [
                    record
                    for item in _items(raw)
                    if (record := _normalize_record(item, ATTRIBUTE_FIELDS))
                ][:_MAX_LIST]
            elif field == "paths":
                result[field] = [
                    _normalize_record(item, PATH_FIELDS)
                    for item in _items(raw)
                    if isinstance(item, Mapping)
                ][:_MAX_LIST]
            elif field == "stages":
                result[field] = [
                    _normalize_record(item, STAGE_FIELDS)
                    for item in _items(raw)
                    if isinstance(item, Mapping)
                ][:_MAX_LIST]
        return deepcopy(result)
    except Exception:
        return {}


def _selected_template(novel_type_id: str, template: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if template is not None and isinstance(template, Mapping):
        return template
    try:
        canonical_id = canonical_novel_type_id(novel_type_id)
    except Exception:
        canonical_id = "generic_webnovel"
    return POWER_SYSTEM_TEMPLATES.get(canonical_id, POWER_SYSTEM_TEMPLATES["generic_webnovel"])


def _required_sections(template: Mapping[str, Any]) -> set[str]:
    required = set(_BASE_REQUIRED)
    required.update(_text_list(_mapping_get(template, "required_sections")))
    return required.intersection(CANONICAL_FIELDS)


def _minimum_path_count(template: Mapping[str, Any]) -> int:
    value = _mapping_get(template, "minimum_path_count", 2)
    if isinstance(value, int) and not isinstance(value, bool):
        return min(max(value, 1), _MAX_LIST)
    return 2


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _ledger_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


_LEDGER_ALIASES = {
    "progression": frozenset(
        (
            "progression",
            "level",
            "levels",
            "current_level",
            "stage",
            "rank",
            "realm",
            "class_path",
        )
    ),
    "skills": frozenset(("skill", "skills", "ability", "abilities", "power", "powers")),
    "resources": frozenset(
        (
            "resource",
            "resources",
            "material",
            "materials",
            "currency",
            "energy",
            "mana",
            "experience",
        )
    ),
    "conditions": frozenset(
        (
            "condition",
            "conditions",
            "status",
            "statuses",
            "status_effect",
            "status_effects",
            "debuff",
            "debuffs",
        )
    ),
}


def _ledger_covers(keys: set[str], aliases: frozenset[str]) -> bool:
    return any(key in aliases for key in keys)


def _game_milestone(stage: Mapping[str, Any]) -> int | None:
    level = _mapping_get(stage, "level")
    if isinstance(level, (int, float)) and not isinstance(level, bool):
        return int(level)
    text = " ".join(_text(_mapping_get(stage, field)) for field in ("name", "entry"))
    match = re.search(r"(?i)(?:lv\.?\s*|等级\s*|)(60|30|20|10|1)(?!\d)\s*级?", text)
    return int(match.group(1)) if match else None


def _is_level_twenty_second_transfer(stage: Mapping[str, Any]) -> bool:
    text = " ".join(_text(_mapping_get(stage, field)) for field in STAGE_FIELDS if field != "level")
    if _game_milestone(stage) != 20 and not re.search(r"(?i)(?:lv\.?\s*20|20\s*级)", text):
        return False
    return bool(
        re.search(r"第二次\s*转职|二次\s*转职|(?i:second\s+(?:class\s+)?transfer)", text)
    )


def validate_power_system_spec(
    spec: Any,
    *,
    novel_type_id: str,
    template: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize and validate a project power-system specification."""

    normalized = normalize_power_system_spec(spec)
    selected = _selected_template(novel_type_id, template)
    missing = {
        section
        for section in _required_sections(selected)
        if _is_empty(normalized.get(section))
    }
    violations: set[str] = set()

    stages = normalized.get("stages", [])
    if len(stages) < 3:
        violations.add("stages.minimum_count")
    for field in ("name", "entry", "change", "failure"):
        if any(not stage.get(field) for stage in stages):
            violations.add(f"stages.missing_{field}")
    levels = [stage["level"] for stage in stages if "level" in stage]
    if any(current <= previous for previous, current in zip(levels, levels[1:])):
        violations.add("stages.levels_not_increasing")

    paths = normalized.get("paths", [])
    if len(paths) < _minimum_path_count(selected):
        violations.add("paths.minimum_count")
    if any(not path.get("name") for path in paths):
        violations.add("paths.missing_name")
    if any(len(set(path.get("branches", []))) < 2 for path in paths):
        violations.add("paths.distinct_branches")

    ledger = normalized.get("continuity_ledger", [])
    if len(ledger) < 4:
        violations.add("continuity_ledger.minimum_count")
    ledger_keys = {_ledger_key(item) for item in ledger}
    for concept, aliases in _LEDGER_ALIASES.items():
        if not _ledger_covers(ledger_keys, aliases):
            violations.add(f"continuity_ledger.missing_{concept}")

    try:
        canonical_id = canonical_novel_type_id(novel_type_id)
    except Exception:
        canonical_id = "generic_webnovel"
    if canonical_id == "game_webnovel":
        path_names = {path.get("name") for path in paths}
        if not _GAME_CLASSES.issubset(path_names):
            violations.add("game.missing_classes")
        milestones = {_game_milestone(stage) for stage in stages}
        if not _GAME_MILESTONES.issubset(milestones):
            violations.add("game.missing_milestones")
        detail_fields = (
            "role",
            "core_resource",
            "combat_loop",
            "strengths",
            "weaknesses",
            "branches",
        )
        for field in detail_fields:
            if any(_is_empty(path.get(field)) for path in paths):
                violations.add(f"game.path_missing_{field}")
        if any(not path.get("weapons") for path in paths):
            violations.add("game.path_missing_weapon_affinity")
        if any(not path.get("armor") for path in paths):
            violations.add("game.path_missing_armor_affinity")
        if any(_is_level_twenty_second_transfer(stage) for stage in stages):
            violations.add("game.level20_second_transfer")

    if missing or violations:
        raise PowerSystemValidationError(tuple(missing), tuple(violations))
    return deepcopy(normalized)


_CURRENCY_AMOUNT = re.compile(
    r"(?:[¥￥$]\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*(?:金币|银币|铜币|元|块钱|美元|人民币))"
)
_PERCENTAGE = re.compile(r"\d+(?:\.\d+)?\s*[%％]")


def _redact_exact_money(value: str) -> str:
    return _text(_PERCENTAGE.sub("", _CURRENCY_AMOUNT.sub("", value)))


def legacy_power_summary(spec: Any) -> list[str]:
    """Derive a concise legacy list without inventing absent information."""

    normalized = normalize_power_system_spec(spec)
    if not normalized:
        return []
    lines: list[str] = []
    name = normalized.get("name")
    if name:
        lines.append(f"力量体系：{name}。")

    def add_text_lines(label: str, values: list[str], cap: int = 2) -> None:
        for value in values[:cap]:
            redacted = _redact_exact_money(value)
            if redacted:
                lines.append(f"{label}：{redacted}。")

    add_text_lines("来源", normalized.get("origin", []))
    for stage in normalized.get("stages", [])[:5]:
        parts = [str(stage["level"]) if "level" in stage else "", stage.get("name", "")]
        text = " ".join(part for part in parts if part)
        if text:
            lines.append(f"阶段：{_redact_exact_money(text)}。")
    for path in normalized.get("paths", [])[:3]:
        path_name = path.get("name", "")
        branches = "、".join(path.get("branches", [])[:2])
        text = "；".join(part for part in (path_name, branches) if part)
        if text:
            lines.append(f"路线：{_redact_exact_money(text)}。")
    add_text_lines("资源", normalized.get("resources", []), 1)
    add_text_lines("代价", normalized.get("costs", []), 1)
    add_text_lines("边界", normalized.get("boundaries", []), 1)
    return lines[:16]


def _compact_prompt_value(value: Any, *, chars: int = 180, items: int = 8) -> Any:
    if isinstance(value, str):
        return _text(value, chars)
    if isinstance(value, list):
        return [_compact_prompt_value(item, chars=chars, items=items) for item in value[:items]]
    if isinstance(value, dict):
        return {
            key: _compact_prompt_value(item, chars=chars, items=items)
            for key, item in value.items()
        }
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return ""


def _stage_slice(stages: list[dict[str, Any]], hint: Any) -> list[dict[str, Any]]:
    if isinstance(hint, (int, float)) and not isinstance(hint, bool) and math.isfinite(hint):
        ordered = sorted(
            (stage for stage in stages if isinstance(stage.get("level"), (int, float))),
            key=lambda stage: stage["level"],
        )
        if not ordered:
            return stages[:3]
        eligible = [index for index, stage in enumerate(ordered) if stage["level"] <= hint]
        index = eligible[-1] if eligible else 0
        return ordered[index : index + 2]
    if isinstance(hint, str):
        needle = _text(hint).casefold()
        for index, stage in enumerate(stages):
            if needle and needle in stage.get("name", "").casefold():
                return stages[index : index + 2]
    return stages[:3]


def _path_slice(paths: list[dict[str, Any]], hint: Any) -> list[dict[str, Any]]:
    if isinstance(hint, str):
        needle = _text(hint).casefold()
        matches = [
            path
            for path in paths
            if needle
            and (
                needle in path.get("name", "").casefold()
                or any(needle in branch.casefold() for branch in path.get("branches", []))
            )
        ]
        if matches:
            return matches
    return [
        {key: deepcopy(path[key]) for key in ("name", "branches") if key in path}
        for path in paths
    ]


def _json_length(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False))


def _fit_prompt_budget(value: dict[str, Any]) -> dict[str, Any]:
    if _json_length(value) <= _PROMPT_BUDGET:
        return value
    compact = _compact_prompt_value(value, chars=96, items=4)
    if _json_length(compact) <= _PROMPT_BUDGET:
        return compact
    compact = _compact_prompt_value(value, chars=48, items=2)
    if _json_length(compact) <= _PROMPT_BUDGET:
        return compact
    return _compact_prompt_value(value, chars=24, items=1)


def power_system_prompt_slice(
    spec: Any,
    stage_hint: Any = None,
    path_hint: Any = None,
) -> dict[str, Any]:
    """Return a deterministic stage-aware prompt fragment under 5,000 JSON chars."""

    try:
        normalized = normalize_power_system_spec(spec)
        result: dict[str, Any] = {}
        for field in ("name", "origin", "boundaries", "costs", "counters", "continuity_ledger"):
            if field in normalized:
                result[field] = deepcopy(normalized[field])
        if "stages" in normalized:
            result["stages"] = deepcopy(_stage_slice(normalized["stages"], stage_hint))
        if "paths" in normalized:
            result["paths"] = deepcopy(_path_slice(normalized["paths"], path_hint))
        for field in ("skills", "resources", "equipment", "advancement"):
            if field in normalized:
                result[field] = _compact_prompt_value(normalized[field], chars=160, items=8)
        return deepcopy(_fit_prompt_budget(result))
    except Exception:
        return {}
