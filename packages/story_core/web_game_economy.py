from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_MARKET_RULES: tuple[str, ...] = (
    "交易行只用游戏币交易。",
    "卖家可挂单，也可选择现有求购单。",
    "系统核对物品ID、数量和可交易状态，匹配后立即成交，游戏币进入游戏钱包。",
)

_EXCHANGE_RULES: tuple[str, ...] = (
    "官方兑换渠道独立于交易行，只兑换已进入游戏钱包的游戏币。",
    "确认兑换价、额度、手续费和预计到账后，款项进入现实账户。",
    "现实款项只能通过独立官方兑换渠道进入现实账户。",
)

_APPRAISAL_RULES: tuple[str, ...] = (
    "仅未鉴定物品可交给鉴定师。",
    "已识别物品不重复鉴定。",
)

_OPENING_MARKET_EXCHANGE_FLOW: tuple[str, ...] = (
    "在交易行选择已冻结游戏币的现有求购单，立即出售已识别裂纹狼心，游戏币进入游戏钱包。",
    "离开交易行，进入独立官方兑换页面。",
    "确认兑换价、额度、手续费和预计到账。",
    "现实账户到账后处理急账。",
)

_LEGACY_PROMPT_FLOW_TERMS: tuple[str, ...] = (
    "裂纹狼心提交鉴定后，系统给出一条求购匹配",
    "交易行直接现实结算",
    "买家再次确认",
    "平台验货",
    "封存交割",
    "匿名交割",
    "提交鉴定",
    "鉴定中",
    "鉴定求购",
    "担保订单",
    "担保交易",
    "现实结算",
)
_LEGACY_PROMPT_FLOW_PATTERN = re.compile(
    "|".join(re.escape(term) for term in _LEGACY_PROMPT_FLOW_TERMS)
)
_FORBIDDEN_CURRENCY_NAME = "人民币"
_NUMBERED_FORBIDDEN_CURRENCY = re.compile(
    rf"(?P<amount>(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万点]+))\s*{_FORBIDDEN_CURRENCY_NAME}"
)

_LEGACY_OPENING_MARKERS: tuple[str, ...] = (
    "第一章必须通过裂纹狼心担保交易",
    "第一章必须解决现实急账",
    "第一章通过裂纹狼心担保交易解决",
    "第一章的裂纹狼心担保交易",
    "第一章已经通过担保交易解决现实急账",
    "第一章已通过担保交易解决现实急账",
    "第一章允许完成裂纹狼心担保交易",
)

_ECONOMY_DENIAL = re.compile(
    r"(?:不(?:得|再|允许|能|应|必)?|禁止|严禁|不可|无需|无须|拒绝)"
    r"[^，。；;！？!?\n]{0,8}(?:交易|卖出|兑换)"
)
_PURPOSE_LINK_DENIAL_PATTERN = r"(?:并非|并不(?:是)?|不是|不)(?:用于|用来|为了)"
_OUTCOME_DENIAL_PATTERN = r"(?:并不能|不能|无法|不)"
_FLOW_PURPOSE_DENIAL = re.compile(
    r"(?:卖出裂纹狼心|交易成交)"
    rf"{_PURPOSE_LINK_DENIAL_PATTERN}(?:官方)?兑换"
    r"|官方兑换(?:渠道)?"
    rf"(?:{_PURPOSE_LINK_DENIAL_PATTERN}|{_OUTCOME_DENIAL_PATTERN})"
    r"(?:解决|处理)现实急账"
)
_NUMBERED_CHAPTER = re.compile(r"第(?:[一二三四五六七八九十百千万零〇两\d]+|[Nn])章")
_CLAUSE_SPLIT = re.compile(r"[\n。；;]+")


def market_rules() -> tuple[str, ...]:
    return _MARKET_RULES


def exchange_rules() -> tuple[str, ...]:
    return _EXCHANGE_RULES


def appraisal_rules() -> tuple[str, ...]:
    return _APPRAISAL_RULES


def opening_market_exchange_flow_lines() -> tuple[str, ...]:
    """Return the canonical writer-facing opening flow in scene order."""

    return _OPENING_MARKET_EXCHANGE_FLOW


def _normalize_legacy_economy_prompt_text(value: str) -> str:
    inserted_flow = False

    def replace_flow(_match: re.Match[str]) -> str:
        nonlocal inserted_flow
        if inserted_flow:
            return "交易与兑换流程"
        inserted_flow = True
        return " ".join(_OPENING_MARKET_EXCHANGE_FLOW)

    normalized = _LEGACY_PROMPT_FLOW_PATTERN.sub(replace_flow, value)
    normalized = _NUMBERED_FORBIDDEN_CURRENCY.sub(
        lambda match: f"{match.group('amount')}元",
        normalized,
    )
    return normalized.replace(_FORBIDDEN_CURRENCY_NAME, "现实货币")


def normalize_legacy_economy_prompt_value(value: Any) -> Any:
    """Return a prompt-safe copy while leaving stored project data unchanged."""

    if isinstance(value, str):
        return _normalize_legacy_economy_prompt_text(value)
    if isinstance(value, Mapping):
        return {
            normalize_legacy_economy_prompt_value(key): normalize_legacy_economy_prompt_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize_legacy_economy_prompt_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(normalize_legacy_economy_prompt_value(item) for item in value)
    if isinstance(value, set):
        return {normalize_legacy_economy_prompt_value(item) for item in value}
    return value


def _text_entries(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(text for item in value.values() for text in _text_entries(item))
    if isinstance(value, (list, tuple)):
        return tuple(text for item in value for text in _text_entries(item))
    return ()


def _is_first_chapter(marker: str) -> bool:
    return marker[1:-1] in ("一", "1")


def _scoped_clauses(text: str) -> tuple[tuple[bool | None, str], ...]:
    scoped: list[tuple[bool | None, str]] = []
    current_scope: bool | None = None
    for clause in _CLAUSE_SPLIT.split(text):
        clause = clause.strip()
        if not clause:
            continue
        markers = tuple(_NUMBERED_CHAPTER.finditer(clause))
        if not markers:
            if current_scope is None and "本章" in clause:
                current_scope = True
            scoped.append((current_scope, clause))
            continue
        prefix = clause[: markers[0].start()].strip()
        if prefix:
            prefix_scope = (
                True if current_scope is None and "本章" in prefix else current_scope
            )
            scoped.append((prefix_scope, prefix))
        for index, marker in enumerate(markers):
            current_scope = _is_first_chapter(marker.group())
            end = markers[index + 1].start() if index + 1 < len(markers) else len(clause)
            scoped.append((current_scope, clause[marker.start() : end].strip()))
    return tuple(scoped)


def _first_chapter_ranges(text: str) -> tuple[str, ...]:
    ranges: list[str] = []
    current: list[str] = []
    for is_first_chapter, clause in _scoped_clauses(text):
        if is_first_chapter:
            current.append(clause)
        elif current:
            ranges.append("\n".join(current))
            current = []
    if current:
        ranges.append("\n".join(current))
    return tuple(ranges)


def _ordered_new_chain(text: str) -> tuple[int, int, int] | None:
    for transaction in re.finditer(r"卖出裂纹狼心|交易成交", text):
        exchange = text.find("官方兑换", transaction.end())
        if exchange < 0:
            continue
        urgency = text.find("现实急账", exchange + len("官方兑换"))
        if urgency >= 0:
            return transaction.start(), exchange, urgency
    return None


def _first_chapter_range_authorized(text: str) -> bool:
    denial_matches = tuple(_ECONOMY_DENIAL.finditer(text))
    current_denials = tuple(
        match for match in denial_matches if not match.group().endswith("担保交易")
    )
    new_chain = _ordered_new_chain(text)
    purpose_denial = _FLOW_PURPOSE_DENIAL.search(text)
    # A complete replacement chain is independent of the retired legacy flow.
    if new_chain is not None and not current_denials and purpose_denial is None:
        return True
    # Read compatibility only. New prompt rules must never emit legacy markers.
    legacy_contract = any(marker in text for marker in _LEGACY_OPENING_MARKERS)
    return legacy_contract and not denial_matches


def first_chapter_market_exchange_authorized(
    event_plan: dict[str, Any] | None = None,
    world_facts: list[str] | None = None,
) -> bool:
    entries = (
        *_text_entries(event_plan or {}),
        *(str(item) for item in (world_facts or [])),
    )
    return any(
        _first_chapter_range_authorized(chapter_range)
        for entry in entries
        for chapter_range in _first_chapter_ranges(entry)
    )
