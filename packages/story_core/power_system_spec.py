from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from itertools import islice
import math
import re
from typing import Any

from packages.story_core.attribute_allocation import normalize_attribute_allocation_rule
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
    "attribute_allocation",
)
PATH_FIELDS = (
    "name",
    "role",
    "core_resource",
    "core_attributes",
    "weapons",
    "armor",
    "combat_loop",
    "strengths",
    "weaknesses",
    "skill_categories",
    "branches",
    "transfer_task",
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
    "core_attributes",
    "weapons",
    "armor",
    "strengths",
    "weaknesses",
    "skill_categories",
    "branches",
    "advancement",
)

_MAX_STRING = 240
_MAX_RAW_TEXT_SCAN = 4_096
_MAX_LIST = 64
_MAX_NUMBER = 1_000_000
_MAPPING_SCAN_CAP = 64
_GAME_MILESTONES = frozenset((1, 10, 20, 30, 60))
_GAME_CLASS_COUNT = 6
_PLACEHOLDER_CONTENT = frozenset(
    (
        "\u5f85\u5b9a",
        "\u5f85\u5b8c\u5584",
        "\u5f85\u8865\u5145",
        "\u5f85\u7ec6\u5316",
        "\u540e\u7eed\u8865\u5145",
        "\u540e\u7eed\u5b8c\u5584",
        "\u6682\u7f3a",
        "\u6682\u65e0",
        "\u7565",
        "\u540c\u4e0a",
        "\u7efc\u5408\u5b9e\u529b\u63d0\u5347",
        "todo",
        "tbd",
    )
)
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
    result: list[tuple[Any, Any]] = []
    try:
        iterator = iter(islice(value.items(), _MAPPING_SCAN_CAP))
        while True:
            try:
                result.append(next(iterator))
            except StopIteration:
                return result
            except Exception:
                return result
    except Exception:
        return result


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
    if not isinstance(value, str) or limit <= 0:
        return ""
    compact: list[str] = []
    emitted = 0
    pending_space = False
    try:
        characters = islice(value, _MAX_RAW_TEXT_SCAN)
        for character in characters:
            if not isinstance(character, str) or len(character) != 1:
                continue
            if str.isspace(character):
                pending_space = bool(compact)
                continue
            if not str.isprintable(character):
                continue
            if pending_space and emitted + 1 < limit:
                compact.append(" ")
                emitted += 1
            pending_space = False
            if emitted >= limit:
                break
            compact.append(character)
            emitted += 1
            if emitted >= limit:
                break
    except Exception:
        pass
    return "".join(compact).rstrip()


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
    return int(bounded) if isinstance(value, int) else float(bounded)


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
            elif field == "attribute_allocation":
                rule = normalize_attribute_allocation_rule(raw)
                if rule:
                    result[field] = rule
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
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", "_", value.casefold()).strip("_")


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
            "当前等级",
            "等级",
            "阶段",
            "境界",
            "修为",
        )
    ),
    "skills": frozenset(
        ("skill", "skills", "ability", "abilities", "power", "powers", "技能", "能力", "术法")
    ),
    "equipment": frozenset(
        ("equipment", "gear", "weapon", "weapons", "armor", "装备", "武器", "护甲", "法宝")
    ),
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
            "资源",
            "材料",
            "货币",
            "经验",
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
            "状态",
            "负面状态",
            "状态效果",
            "伤势",
        )
    ),
}


def _ledger_covers(keys: set[str], aliases: frozenset[str]) -> bool:
    return any(key in aliases for key in keys)


def _inferred_stage_level(stage: Mapping[str, Any]) -> int | None:
    if _has_key(stage, "level"):
        level = _mapping_get(stage, "level")
        return level if isinstance(level, int) and not isinstance(level, bool) else None
    text = " ".join(_text(_mapping_get(stage, field)) for field in ("name", "entry"))
    match = re.search(
        r"(?i:lv)\.?\s*(\d+)(?!\d)|(?<!\d)(\d+)\s*级",
        text,
    )
    if not match:
        return None
    return int(match.group(1) or match.group(2))


def _is_level_twenty_second_transfer(
    stage: Mapping[str, Any], *, specialization_fallback: bool = False
) -> bool:
    text = " ".join(_text(_mapping_get(stage, field)) for field in STAGE_FIELDS if field != "level")
    stage_name = _text(_mapping_get(stage, "name"))
    tied_to_specialization = _inferred_stage_level(stage) == 20 or (
        specialization_fallback and "专精" in stage_name
    )
    if not tied_to_specialization:
        return False
    return bool(
        re.search(
            r"第二次\s*转职|再次\s*转职|二次\s*转职|二转|第二职业\s*晋升|"
            r"(?i:second\s+(?:class\s+)?transfer)",
            text,
        )
    )


def _is_placeholder_content(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    token = re.sub(
        r"[\s,，。.!！?？:：;；、_()（）【】\[\]\"'“”‘’]+",
        "",
        value,
    ).casefold()
    return token in _PLACEHOLDER_CONTENT


def _contains_placeholder_content(value: Any) -> bool:
    if _is_placeholder_content(value):
        return True
    if isinstance(value, Mapping):
        return any(_contains_placeholder_content(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_placeholder_content(item) for item in value)
    return False


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
    if _contains_placeholder_content(normalized):
        violations.add("content.placeholder_or_low_information")

    stages = normalized.get("stages", [])
    if len(stages) < 3:
        violations.add("stages.minimum_count")
    for field in ("name", "entry", "change", "failure"):
        if any(not stage.get(field) for stage in stages):
            violations.add(f"stages.missing_{field}")
    levels = [
        level
        for stage in stages
        if (level := _inferred_stage_level(stage)) is not None
    ]
    if any(current <= previous for previous, current in zip(levels, levels[1:])):
        violations.add("stages.levels_not_increasing")

    paths = normalized.get("paths", [])
    if len(paths) < _minimum_path_count(selected):
        violations.add("paths.minimum_count")
    if any(not path.get("name") for path in paths):
        violations.add("paths.missing_name")
    path_names = [path["name"].casefold() for path in paths if path.get("name")]
    if len(path_names) != len(set(path_names)):
        violations.add("paths.duplicate_names")
    if any(
        len({branch.casefold() for branch in path.get("branches", [])}) < 2
        for path in paths
    ):
        violations.add("paths.distinct_branches")

    ledger = normalized.get("continuity_ledger", [])
    if len(ledger) < 4:
        violations.add("continuity_ledger.minimum_count")

    try:
        canonical_id = canonical_novel_type_id(novel_type_id)
    except Exception:
        canonical_id = "generic_webnovel"
    if canonical_id == "game_webnovel":
        ledger_keys = {_ledger_key(item) for item in ledger}
        for concept, aliases in _LEDGER_ALIASES.items():
            if not _ledger_covers(ledger_keys, aliases):
                violations.add(f"continuity_ledger.missing_{concept}")
        game_path_names = {path.get("name") for path in paths}
        if len(paths) < _GAME_CLASS_COUNT:
            violations.add("game.missing_classes")
        if len(game_path_names) != len(paths):
            violations.add("game.invalid_classes")
        milestones = tuple(_inferred_stage_level(stage) for stage in stages)
        expected_milestones = tuple(sorted(_GAME_MILESTONES))
        if milestones != expected_milestones:
            violations.add("game.invalid_milestones")
        if not _GAME_MILESTONES.issubset(milestones):
            violations.add("game.missing_milestones")
        detail_fields = (
            "role",
            "core_resource",
            "core_attributes",
            "combat_loop",
            "strengths",
            "weaknesses",
            "skill_categories",
            "branches",
            "transfer_task",
            "advancement",
        )
        for field in detail_fields:
            if any(_is_empty(path.get(field)) for path in paths):
                violations.add(f"game.path_missing_{field}")
        if any(not path.get("weapons") for path in paths):
            violations.add("game.path_missing_weapon_affinity")
        if any(not path.get("armor") for path in paths):
            violations.add("game.path_missing_armor_affinity")
        has_inferred_level = bool(levels)
        if any(
            _is_level_twenty_second_transfer(
                stage,
                specialization_fallback=not has_inferred_level and index == 2,
            )
            for index, stage in enumerate(stages)
        ):
            violations.add("game.level20_second_transfer")

    if missing or violations:
        raise PowerSystemValidationError(tuple(missing), tuple(violations))
    return deepcopy(normalized)
