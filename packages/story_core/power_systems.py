from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from itertools import islice
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
_PROMPT_BUDGET = 5_000
_GAME_MILESTONES = frozenset((1, 10, 20, 30, 60))
_GAME_CLASS_COUNT = 6
_PLACEHOLDER_CONTENT = frozenset(
    (
        "\u5f85\u5b9a",
        "\u7565",
        "\u540c\u4e0a",
        "\u7efc\u5408\u5b9e\u529b\u63d0\u5347",
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
    ledger_keys = {_ledger_key(item) for item in ledger}
    for concept, aliases in _LEDGER_ALIASES.items():
        if not _ledger_covers(ledger_keys, aliases):
            violations.add(f"continuity_ledger.missing_{concept}")

    try:
        canonical_id = canonical_novel_type_id(novel_type_id)
    except Exception:
        canonical_id = "generic_webnovel"
    if canonical_id == "game_webnovel":
        game_path_names = {path.get("name") for path in paths}
        if len(paths) < _GAME_CLASS_COUNT:
            violations.add("game.missing_classes")
        if (
            len(paths) != _GAME_CLASS_COUNT
            or len(game_path_names) != _GAME_CLASS_COUNT
        ):
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


_FORMATTED_NUMBER = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_UNAMBIGUOUS_CURRENCY_UNIT = r"(?:金币|银币|铜币|块钱|美元|人民币)"
_UNAMBIGUOUS_CURRENCY_AMOUNT = re.compile(
    rf"(?:"
    rf"(?:RMB|CNY|[¥￥$])\s*{_FORMATTED_NUMBER}\s*[百千万亿]?"
    rf"|{_FORMATTED_NUMBER}\s*[百千万亿]?\s*{_UNAMBIGUOUS_CURRENCY_UNIT}"
    rf"|{_UNAMBIGUOUS_CURRENCY_UNIT}\s*{_FORMATTED_NUMBER}\s*[百千万亿]?"
    rf")",
    re.IGNORECASE,
)
_AMBIGUOUS_YUAN_AMOUNT = re.compile(
    rf"(?:{_FORMATTED_NUMBER}\s*[百千万亿]?\s*元|元\s*{_FORMATTED_NUMBER}\s*[百千万亿]?)"
)
_PERCENTAGE = re.compile(rf"{_FORMATTED_NUMBER}\s*[%％]")
_FINANCIAL_SEMANTIC_TERMS = (
    "支付",
    "购买",
    "价格",
    "售价",
    "定价",
    "费用",
    "手续费",
    "费率",
    "税",
    "佣金",
    "折扣",
    "利息",
    "收益率",
    "提现",
    "到账",
    "交易",
    "交易费",
    "收入",
    "成本",
    "租金",
    "余额",
    "人民币",
    "RMB",
    "门票",
    "需要",
    "需",
    "花费",
    "花",
    "值",
    "缴纳",
)
_POWER_RESOURCE_SEMANTIC_TERMS = (
    "获得",
    "恢复",
    "消耗",
    "收集",
    "凝聚",
    "炼化",
    "突破",
    "提升",
    "注入",
    "吸收",
)
_GAMEPLAY_SEMANTIC_TERMS = (
    "暴击",
    "抗性",
    "伤害",
    "命中",
    "闪避",
    "速度",
    "生命",
    "法力",
    "冷却",
    "加成",
)
_POWER_RESOURCE_SUFFIX_STARTS = "核魂丹婴力气神灵素晶初始"
_POSTFIX_FINANCIAL_NOUN = re.compile(
    r"^\s*(?:作为|的|为|作)?\s*(?:手续费|交易费|费率|佣金|利息|收益率|税)"
)
_POSTFIX_FINANCIAL_SCAN = 12
_CLAUSE_BOUNDARIES = "，,。；;！？!?\n"
_SEMANTIC_CONTEXT_WINDOW = 24


def _semantic_bounds(value: str, start: int, end: int) -> tuple[int, int]:
    lower = max(0, start - _SEMANTIC_CONTEXT_WINDOW)
    upper = min(len(value), end + _SEMANTIC_CONTEXT_WINDOW)
    left_edges = [
        position + 1
        for boundary in _CLAUSE_BOUNDARIES
        if (position := value.rfind(boundary, lower, start)) >= 0
    ]
    right_edges = [
        position
        for boundary in _CLAUSE_BOUNDARIES
        if (position := value.find(boundary, end, upper)) >= 0
    ]
    return max(left_edges, default=lower), min(right_edges, default=upper)


def _nearest_preceding_semantic_distance(
    value: str,
    *,
    start: int,
    end: int,
    terms: Sequence[str],
) -> int | None:
    lower, _ = _semantic_bounds(value, start, end)
    nearest: int | None = None
    for term in terms:
        search_from = lower
        while (position := value.find(term, search_from, start)) >= 0:
            term_end = position + len(term)
            if term_end <= start:
                distance = start - term_end
                nearest = distance if nearest is None else min(nearest, distance)
            search_from = position + 1
    return nearest


def _nearest_following_semantic_distance(
    value: str,
    *,
    start: int,
    end: int,
    terms: Sequence[str],
) -> int | None:
    _, upper = _semantic_bounds(value, start, end)
    nearest: int | None = None
    for term in terms:
        search_from = end
        while (position := value.find(term, search_from, upper)) >= 0:
            distance = position - end
            nearest = distance if nearest is None else min(nearest, distance)
            search_from = position + 1
    return nearest


def _redact_ambiguous_yuan(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        financial_distance = _nearest_preceding_semantic_distance(
            value,
            start=match.start(),
            end=match.end(),
            terms=_FINANCIAL_SEMANTIC_TERMS,
        )
        resource_distance = _nearest_preceding_semantic_distance(
            value,
            start=match.start(),
            end=match.end(),
            terms=_POWER_RESOURCE_SEMANTIC_TERMS,
        )
        _, upper = _semantic_bounds(value, match.start(), match.end())
        suffix = value[match.end() : upper].lstrip()
        has_power_suffix = suffix.startswith(tuple(_POWER_RESOURCE_SUFFIX_STARTS))
        if resource_distance is not None and (
            financial_distance is None or resource_distance < financial_distance
        ):
            return match.group(0)
        if has_power_suffix:
            return match.group(0)
        return ""

    return _AMBIGUOUS_YUAN_AMOUNT.sub(replace, value)


def _redact_financial_percentages(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        postfix = value[match.end() : match.end() + _POSTFIX_FINANCIAL_SCAN]
        if _POSTFIX_FINANCIAL_NOUN.match(postfix):
            return ""
        financial_distance = _nearest_preceding_semantic_distance(
            value,
            start=match.start(),
            end=match.end(),
            terms=_FINANCIAL_SEMANTIC_TERMS,
        )
        gameplay_distance = _nearest_preceding_semantic_distance(
            value,
            start=match.start(),
            end=match.end(),
            terms=_GAMEPLAY_SEMANTIC_TERMS,
        )
        if financial_distance is not None or gameplay_distance is not None:
            if financial_distance is not None and (
                gameplay_distance is None or financial_distance <= gameplay_distance
            ):
                return ""
            return match.group(0)

        financial_distance = _nearest_following_semantic_distance(
            value,
            start=match.start(),
            end=match.end(),
            terms=_FINANCIAL_SEMANTIC_TERMS,
        )
        gameplay_distance = _nearest_following_semantic_distance(
            value,
            start=match.start(),
            end=match.end(),
            terms=_GAMEPLAY_SEMANTIC_TERMS,
        )
        if financial_distance is not None and (
            gameplay_distance is None or financial_distance <= gameplay_distance
        ):
            return ""
        return match.group(0)

    return _PERCENTAGE.sub(replace, value)


def _redact_exact_money(value: str) -> str:
    without_currency = _UNAMBIGUOUS_CURRENCY_AMOUNT.sub("", value)
    without_yuan = _redact_ambiguous_yuan(without_currency)
    return _text(_redact_financial_percentages(without_yuan))


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
        matches: list[tuple[int, int, int, int, dict[str, Any]]] = []
        if needle:
            for path_index, path in enumerate(paths):
                aliases = [path.get("name", ""), *path.get("branches", [])]
                for alias_index, alias in enumerate(aliases):
                    candidate = _text(alias).casefold()
                    if not candidate or not (needle in candidate or candidate in needle):
                        continue
                    matches.append(
                        (
                            int(candidate == needle),
                            len(candidate),
                            -path_index,
                            -alias_index,
                            path,
                        )
                    )
        if matches:
            return [max(matches, key=lambda item: item[:4])[4]]
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
