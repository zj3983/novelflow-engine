from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
import json
import math
import re
from typing import Any

from packages.story_core.power_system_spec import _text, normalize_power_system_spec


_PROMPT_BUDGET = 5_000

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
