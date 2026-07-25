from __future__ import annotations

import re
from collections.abc import Callable, Mapping
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

_LEGACY_SPECIFIC_PROMPT_REPLACEMENTS: tuple[tuple[str, str], ...] = tuple(
    sorted(
        (
            ("持牌虚拟资产担保平台", "官方兑换渠道"),
            ("匿名担保交易已完成", "求购单已成交，官方兑换完成"),
            ("担保交易平台", "交易行与官方兑换渠道"),
            ("持牌担保平台", "官方兑换渠道"),
            ("担保订单编号", "官方兑换流水编号"),
            ("担保订单号", "官方兑换流水号"),
            ("稀有资产担保", "交易行成交与官方兑换"),
            ("担保稀有资产", "兑换稀有资产"),
            ("担保交易已完成", "求购单已成交，官方兑换完成"),
            ("买家确认收购", "求购单已成交"),
            ("担保名单", "官方兑换记录"),
            ("担保净到账", "官方兑换净到账"),
            ("担保到账", "官方兑换到账"),
            ("担保交割", "交易行成交与官方兑换"),
            ("担保订单", "官方兑换流水"),
            ("担保平台", "官方兑换渠道"),
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)
_FIRST_CHAPTER_TRANSACTION_MARKERS: tuple[str, ...] = (
    "裂纹狼心",
    "交易行",
    "求购单",
    "订单状态",
    "订单",
    "出售",
    "成交",
    "持牌虚拟资产担保平台",
    "担保交易平台",
    "担保平台",
    "担保订单",
    "担保交割",
    "稀有资产担保",
)
_PROMPT_CLAUSE_SEPARATOR = re.compile(r"([，。；！？!?：:\n]+)")
_CLAUSE_SCOPED_LEGACY_FLOW_TERMS: tuple[str, ...] = (
    "提交鉴定",
    "鉴定中",
    "鉴定求购",
)
_CLAUSE_SCOPED_LEGACY_FLOW_PATTERN = re.compile(
    "|".join(re.escape(term) for term in _CLAUSE_SCOPED_LEGACY_FLOW_TERMS)
)
_CHAPTER_SCOPE_MARKER = re.compile(
    r"第\s*(?P<chinese>[零〇一二两三四五六七八九十百千万\d]+)\s*章"
    r"|(?:[\"']?chapter_number[\"']?)\s*[:：]\s*[\"']?(?P<json>\d+)[\"']?"
)

_LEGACY_PROMPT_FLOW_TERMS: tuple[str, ...] = (
    "裂纹狼心提交鉴定后，系统给出一条求购匹配",
    "交易行直接现实结算",
    "买家再次确认",
    "平台验货",
    "封存交割",
    "匿名交割",
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


def _has_first_chapter_transaction_marker(clause: str) -> bool:
    return any(term in clause for term in _FIRST_CHAPTER_TRANSACTION_MARKERS)


def _normalize_clause_scoped_terms(
    value: str,
    replace_flow: Callable[[re.Match[str]], str],
) -> str:
    parts = _PROMPT_CLAUSE_SEPARATOR.split(value)
    for index in range(0, len(parts), 2):
        clause = parts[index]
        if not _has_first_chapter_transaction_marker(clause):
            continue
        clause = clause.replace("匿名提交", "立即出售")
        parts[index] = _CLAUSE_SCOPED_LEGACY_FLOW_PATTERN.sub(replace_flow, clause)
    return "".join(parts)


def _normalize_legacy_economy_prompt_segment(value: str) -> str:
    inserted_flow = False

    def replace_flow(_match: re.Match[str]) -> str:
        nonlocal inserted_flow
        if inserted_flow:
            return "交易与兑换流程"
        inserted_flow = True
        return " ".join(_OPENING_MARKET_EXCHANGE_FLOW)

    normalized = _normalize_clause_scoped_terms(value, replace_flow)
    for legacy, current in _LEGACY_SPECIFIC_PROMPT_REPLACEMENTS:
        normalized = normalized.replace(legacy, current)
    normalized = _LEGACY_PROMPT_FLOW_PATTERN.sub(replace_flow, normalized)
    normalized = _NUMBERED_FORBIDDEN_CURRENCY.sub(
        lambda match: f"{match.group('amount')}元",
        normalized,
    )
    normalized = normalized.replace(_FORBIDDEN_CURRENCY_NAME, "现实货币")
    return normalized


def _chapter_scope_number(match: re.Match[str]) -> int:
    raw = str(match.group("json") or match.group("chinese") or "").strip()
    if raw.isdigit():
        return int(raw)
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = 0
    section = 0
    number = 0
    for char in raw:
        if char in digits:
            number = digits[char]
            continue
        unit = units.get(char)
        if unit is None:
            return 0
        if unit == 10000:
            section += number
            total += (section or 1) * unit
            section = 0
            number = 0
        else:
            section += (number or 1) * unit
            number = 0
    return total + section + number


def _normalize_legacy_economy_prompt_line(value: str) -> str:
    markers = list(_CHAPTER_SCOPE_MARKER.finditer(value))
    if not markers:
        return _normalize_legacy_economy_prompt_segment(value)

    parts = [_normalize_legacy_economy_prompt_segment(value[: markers[0].start()])]
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(value)
        segment = value[marker.start() : end]
        parts.append(
            _normalize_legacy_economy_prompt_segment(segment)
            if _chapter_scope_number(marker) == 1
            else segment
        )
    return "".join(parts)


def _normalize_legacy_economy_prompt_text(value: str) -> str:
    return "".join(
        _normalize_legacy_economy_prompt_line(line)
        for line in value.splitlines(keepends=True)
    )


def normalize_legacy_economy_prompt_value(
    value: Any,
    *,
    game_context: bool,
    chapter_number: int,
) -> Any:
    """Return a prompt-safe copy while leaving stored project data unchanged."""

    if not game_context or int(chapter_number or 0) != 1:
        return value
    if isinstance(value, str):
        return _normalize_legacy_economy_prompt_text(value)
    if isinstance(value, Mapping):
        scoped_chapter = value.get("chapter_number")
        try:
            if scoped_chapter is not None and int(scoped_chapter) >= 2:
                return value
        except (TypeError, ValueError):
            pass
        items = [
            (
                key,
                normalize_legacy_economy_prompt_value(
                    item,
                    game_context=game_context,
                    chapter_number=chapter_number,
                ),
            )
            for key, item in value.items()
        ]
        if isinstance(value, dict):
            return type(value)(items)
        try:
            return type(value)(items)
        except (TypeError, ValueError):
            return value
    if isinstance(value, list):
        return [
            normalize_legacy_economy_prompt_value(
                item,
                game_context=game_context,
                chapter_number=chapter_number,
            )
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            normalize_legacy_economy_prompt_value(
                item,
                game_context=game_context,
                chapter_number=chapter_number,
            )
            for item in value
        )
    if isinstance(value, set):
        return {
            normalize_legacy_economy_prompt_value(
                item,
                game_context=game_context,
                chapter_number=chapter_number,
            )
            for item in value
        }
    if isinstance(value, frozenset):
        return frozenset(
            normalize_legacy_economy_prompt_value(
                item,
                game_context=game_context,
                chapter_number=chapter_number,
            )
            for item in value
        )
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
