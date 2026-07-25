from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
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
            ("匿名担保交易已完成", "已进入独立官方兑换页面"),
            ("担保交易平台", "交易行与官方兑换渠道"),
            ("持牌担保平台", "官方兑换渠道"),
            ("担保订单编号", "官方兑换流水编号"),
            ("担保订单号", "官方兑换流水号"),
            ("稀有资产担保", "交易行成交与官方兑换"),
            ("担保稀有资产", "兑换稀有资产"),
            ("担保交易已完成", "已进入独立官方兑换页面"),
            ("买家确认收购", "求购单已成交"),
            ("担保名单", "官方兑换记录"),
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
    "出售",
    "成交",
    "持牌虚拟资产担保平台",
    "担保交易平台",
    "担保平台",
    "担保订单",
    "担保交割",
    "稀有资产担保",
)
_PROMPT_CLAUSE_SEPARATOR = re.compile(r"([。；！？!?\n]+)")
_PROMPT_SOFT_CLAUSE_SEPARATOR = re.compile(r"([，,]+)")
_ORDER_STATUS_APPRAISAL_PATTERN = re.compile(
    r"订单状态变成\s*(?:[“‘\"']\s*)?鉴定中(?:\s*[”’\"'])?"
)
_ANONYMOUS_SUBMIT_ACTION_PATTERN = re.compile(
    r"(?P<action>点下|点击|选择|按下)\s*匿名提交(?!反馈|投诉|意见|举报)"
)
_LEGACY_TRADE_WINDOW_ACTION_PATTERN = re.compile(
    r"(?P<actor>夜烬|他)(?P<middle>[^。！？!?\n]{0,40}?)(?P<action>点下|点击|选择|按下)\s*匿名提交"
    r"(?!反馈|投诉|意见|举报)"
)
_LEGACY_LISTING_NET_PATTERN = re.compile(
    r"【担保净到账\s*[:：]?\s*(?P<amount>\d+(?:\.\d+)?)\s*元[。.]?】"
)
_LEGACY_ACTUAL_NET_PATTERN = re.compile(
    r"【净到账\s*[:：]?\s*(?P<amount>\d+(?:\.\d+)?)\s*元[。.]?】"
)
_LEGACY_TRADE_STATUS_PATTERN = re.compile(
    r"(?P<item>裂纹狼心从背包中消失，)?"
    r"订单状态变成\s*(?:[“‘\"']\s*)?鉴定中(?:\s*[”’\"'])?[。.]?"
)
_ADJACENT_LEGACY_TRADE_RESULTS_PATTERN = re.compile(
    r"【\s*买家确认收购[。.]?\s*】\s*"
    r"【\s*(?:匿名)?担保交易已完成[。.]?\s*】"
)
_LEGACY_SAMPLE_WAIT_RESULT_PATTERN = re.compile(
    r"夜烬盯着订单页面，食指轻轻敲着膝盖。屏幕终于一跳。\s*"
    r"【样本符合求购要求。】"
)
_PARAGRAPH_BREAK_PATTERN = re.compile(r"(?:\r?\n[\t ]*){2,}")
_CHAPTER_SCOPE_MARKER = re.compile(
    r"第\s*(?P<chinese>[零〇一二两三四五六七八九十百千万\d]+)\s*章"
    r"|(?:[\"']?chapter_number[\"']?)\s*[:：]\s*[\"']?(?P<json>\d+)[\"']?"
    r"|(?P<current>本章)"
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
    rf"(?:{'|'.join(re.escape(term) for term in _LEGACY_PROMPT_FLOW_TERMS)})(?P<terminal>[。！？!?])?"
)
_FORBIDDEN_CURRENCY_NAME = "\u4eba\u6c11\u5e01"
_NUMBERED_FORBIDDEN_CURRENCY = re.compile(
    rf"(?P<amount>(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万点]+))\s*{_FORBIDDEN_CURRENCY_NAME}"
)


@dataclass(frozen=True)
class EconomyBoundaryViolation:
    code: str
    issue: str
    revision: str


_ECONOMY_PARAGRAPH_SPLIT = re.compile(r"(?:\r?\n\s*){2,}")
_ECONOMY_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;])")
_MARKET_SCENE_TERMS = (
    "交易行",
    "拍卖行",
    "拍卖物",
    "求购单",
    "求购成交",
    "立即出售",
)
_REAL_SETTLEMENT_TERMS = ("现实账户", "现实结算")
_APPRAISAL_ACTION_TERMS = ("提交鉴定", "送去鉴定", "交给鉴定师", "送去验货", "平台验货", "安排验货")
_IDENTIFIED_STATE_TERMS = ("已识别", "已经识别", "正式名称", "用途：", "用途:", "【名称：", "【名称:")
_FUNDED_ORDER_TERMS = (
    "资金已冻结",
    "资金已经冻结",
    "资金冻结",
    "已付款",
    "已经付款",
    "游戏币已冻结",
    "游戏币已经冻结",
    "游戏币冻结",
)
_COMPLETED_ORDER_TERMS = ("立即出售", "显示成交", "已经成交", "已成交", "成交后", "成交以后")
_BUYER_RECONFIRM_PATTERNS = (
    re.compile(r"(?:仍|还|继续)?\s*(?:等待|等)买家(?:再次)?确认"),
    re.compile(r"买家再次确认"),
)


def _asserted_action(text: str, action: str) -> bool:
    start = 0
    while True:
        index = text.find(action, start)
        if index < 0:
            return False
        prefix = text[max(0, index - 6) : index]
        if not any(marker in prefix for marker in ("不", "无需", "不用", "没有", "未曾", "不再")):
            return True
        start = index + len(action)


def _has_direct_market_settlement(text: str) -> bool:
    for paragraph in _ECONOMY_PARAGRAPH_SPLIT.split(text):
        for sentence in _ECONOMY_SENTENCE_SPLIT.split(paragraph):
            market_positions = [sentence.find(term) for term in _MARKET_SCENE_TERMS if term in sentence]
            reality_positions = [sentence.find(term) for term in _REAL_SETTLEMENT_TERMS if term in sentence]
            if not market_positions or not reality_positions:
                continue
            market = min(market_positions)
            reality = min(position for position in reality_positions if position >= 0)
            exchange = sentence.find("官方兑换", market, reality)
            direct = any(term in sentence[market : reality + 8] for term in ("直接", "所得", "款项", "转入", "打进"))
            if reality > market and exchange < 0 and direct:
                return True
    return False


def _has_reappraised_identified_item(text: str) -> bool:
    for paragraph in _ECONOMY_PARAGRAPH_SPLIT.split(text):
        appraisal = any(_asserted_action(paragraph, action) for action in _APPRAISAL_ACTION_TERMS)
        if not appraisal:
            continue
        if "裂纹狼心" in paragraph or any(term in paragraph for term in _IDENTIFIED_STATE_TERMS):
            return True
    return False


def _has_buyer_reconfirmation_after_funded_sale(text: str) -> bool:
    for paragraph in _ECONOMY_PARAGRAPH_SPLIT.split(text):
        if "求购单" not in paragraph:
            continue
        funded_positions = [paragraph.find(term) for term in _FUNDED_ORDER_TERMS if term in paragraph]
        completed_positions = [paragraph.find(term) for term in _COMPLETED_ORDER_TERMS if term in paragraph]
        confirm_positions = [
            match.start()
            for pattern in _BUYER_RECONFIRM_PATTERNS
            for match in pattern.finditer(paragraph)
        ]
        if funded_positions and completed_positions and confirm_positions:
            funded = min(funded_positions)
            completed = min(position for position in completed_positions if position >= 0)
            confirm = min(confirm_positions)
            if funded < completed < confirm:
                return True
    return False


def detect_economy_boundary_violations(body: str) -> tuple[EconomyBoundaryViolation, ...]:
    """Find only explicit market, appraisal and exchange boundary violations."""

    violations: list[EconomyBoundaryViolation] = []
    if _has_direct_market_settlement(body):
        violations.append(
            EconomyBoundaryViolation(
                code="market_direct_reality_settlement",
                issue="交易行成交所得被直接写入现实账户，交易与现实兑换混成了一步。",
                revision="交易行只进游戏钱包；现实收益必须在离开交易行后走独立官方兑换。",
            )
        )
    if _has_reappraised_identified_item(body):
        violations.append(
            EconomyBoundaryViolation(
                code="identified_item_reappraised",
                issue="已显示正式名称、用途或已识别状态的物品又被送去鉴定或验货。",
                revision="已识别物不重复鉴定；只有明确标为未鉴定的物品才交给鉴定师。",
            )
        )
    if _has_buyer_reconfirmation_after_funded_sale(body):
        violations.append(
            EconomyBoundaryViolation(
                code="funded_order_waits_for_buyer",
                issue="已有资金冻结或已付款的求购单成交后，仍在等待买家再次确认。",
                revision="资金冻结的求购单应立即成交，成交后游戏币直接进入游戏钱包，不再等待买家确认。",
            )
        )
    if _FORBIDDEN_CURRENCY_NAME in body:
        violations.append(
            EconomyBoundaryViolation(
                code="forbidden_currency_name",
                issue="正文使用了禁止出现的完整现实货币名称。",
                revision="删除完整现实货币名称；交易行只进游戏钱包，现实收益走独立官方兑换。",
            )
        )
    return tuple(violations)

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


def _normalize_anonymous_submit_soft_clauses(value: str) -> str:
    parts = _PROMPT_SOFT_CLAUSE_SEPARATOR.split(value)
    for index in range(0, len(parts), 2):
        clause = parts[index]
        if "匿名提交" in clause and _has_first_chapter_transaction_marker(clause):
            parts[index] = clause.replace("匿名提交", "立即出售")
    return "".join(parts)


def _normalize_local_transaction_terms(clause: str) -> str:
    normalized = _ORDER_STATUS_APPRAISAL_PATTERN.sub("求购单显示已成交", clause)
    return (
        normalized.replace("提交鉴定", "立即出售")
        .replace("鉴定求购", "求购单")
        .replace("鉴定中", "已成交")
    )


def _normalize_legacy_trade_window(
    value: str,
    expected_amount: str,
    actual_amount: str,
) -> str:
    normalized = _LEGACY_LISTING_NET_PATTERN.sub("", value)
    normalized = _LEGACY_TRADE_WINDOW_ACTION_PATTERN.sub(
        lambda match: (
            f"{match.group('actor')}{match.group('middle')}{match.group('action')}立即出售"
        ),
        normalized,
        count=1,
    )
    has_wallet_result = "游戏币已进入钱包" in normalized

    def replace_status(match: re.Match[str]) -> str:
        item = match.group("item") or ""
        wallet = "" if has_wallet_result else "【游戏币已进入钱包。】"
        return f"{item}求购单显示已成交。【成交价：按求购单标价。】{wallet}"

    normalized = _LEGACY_TRADE_STATUS_PATTERN.sub(replace_status, normalized, count=1)
    wallet_end = normalized.find("【游戏币已进入钱包。】")
    sample_result = _LEGACY_SAMPLE_WAIT_RESULT_PATTERN.search(normalized)
    if wallet_end >= 0 and sample_result is not None and wallet_end < sample_result.start():
        wallet_end += len("【游戏币已进入钱包。】")
        bridge = normalized[wallet_end : sample_result.start()].replace(
            "等待的半分钟里，村口",
            "交易完成以后，村口",
            1,
        )
        normalized = normalized[:wallet_end] + bridge + normalized[sample_result.start() :]
    normalized = _LEGACY_SAMPLE_WAIT_RESULT_PATTERN.sub("", normalized, count=1)
    exchange_step = (
        "他随后打开独立的官方兑换页面。"
        "【兑换价：当前官方报价。】"
        "【可用额度：足够完成本次兑换。】"
        "【手续费：已计入预计到账。】"
        f"【预计到账：{expected_amount}元。】"
        "他确认兑换。"
    )
    normalized = _ADJACENT_LEGACY_TRADE_RESULTS_PATTERN.sub(
        exchange_step,
        normalized,
        count=1,
    )
    normalized = _LEGACY_ACTUAL_NET_PATTERN.sub(
        f"【现实账户到账{actual_amount}元。】",
        normalized,
        count=1,
    )
    return normalized


def _listing_has_trade_paragraph_context(
    value: str,
    listing_start: int,
    lower_bound: int,
) -> bool:
    paragraphs: list[tuple[int, int, str]] = []
    paragraph_start = lower_bound
    for separator in _PARAGRAPH_BREAK_PATTERN.finditer(value, lower_bound):
        text = value[paragraph_start : separator.start()]
        if text.strip():
            paragraphs.append((paragraph_start, separator.start(), text))
        paragraph_start = separator.end()
    tail = value[paragraph_start:]
    if tail.strip():
        paragraphs.append((paragraph_start, len(value), tail))

    for index, (start, end, text) in enumerate(paragraphs):
        if not start <= listing_start < end:
            continue
        candidates = [text]
        if index > 0:
            candidates.append(paragraphs[index - 1][2])
        return any(
            marker in paragraph
            for paragraph in candidates
            for marker in ("求购单", "求购", "裂纹狼心")
        )
    return False


def _normalize_legacy_trade_windows(value: str) -> str:
    parts: list[str] = []
    cursor = 0
    search_from = 0
    while action := _LEGACY_TRADE_WINDOW_ACTION_PATTERN.search(value, search_from):
        actual = _LEGACY_ACTUAL_NET_PATTERN.search(value, action.end())
        if actual is None:
            break
        status = _LEGACY_TRADE_STATUS_PATTERN.search(value, action.end(), actual.start())
        results = (
            _ADJACENT_LEGACY_TRADE_RESULTS_PATTERN.search(value, status.end(), actual.start())
            if status is not None
            else None
        )
        next_action = (
            _LEGACY_TRADE_WINDOW_ACTION_PATTERN.search(value, action.end(), status.start())
            if status is not None
            else None
        )
        if status is None or results is None or next_action is not None:
            search_from = action.end()
            continue
        listing_candidates = tuple(
            _LEGACY_LISTING_NET_PATTERN.finditer(
                value,
                max(cursor, action.start() - 2000),
                action.start(),
            )
        )
        listing = listing_candidates[-1] if listing_candidates else None
        if listing is None or not _listing_has_trade_paragraph_context(
            value,
            listing.start(),
            cursor,
        ):
            search_from = action.end()
            continue
        expected_amount = listing.group("amount")
        actual_amount = actual.group("amount")
        parts.append(value[cursor : listing.start()])
        parts.append(
            _normalize_legacy_trade_window(
                value[listing.start() : actual.end()],
                expected_amount,
                actual_amount,
            )
        )
        cursor = actual.end()
        search_from = cursor
    if not parts:
        return value
    parts.append(value[cursor:])
    return "".join(parts)


def _next_sentence_has_transaction_marker(parts: list[str], index: int) -> bool:
    if index + 2 >= len(parts):
        return False
    separator = parts[index + 1]
    if not separator or separator[0] not in "。！？!?":
        return False
    return _has_first_chapter_transaction_marker(parts[index + 2])


def _normalize_clause_scoped_terms(value: str) -> str:
    parts = _PROMPT_CLAUSE_SEPARATOR.split(value)
    for index in range(0, len(parts), 2):
        clause = _normalize_anonymous_submit_soft_clauses(parts[index])
        if _next_sentence_has_transaction_marker(parts, index):
            clause = _ANONYMOUS_SUBMIT_ACTION_PATTERN.sub(
                lambda match: f"{match.group('action')}立即出售",
                clause,
            )
        if _has_first_chapter_transaction_marker(clause):
            clause = _normalize_local_transaction_terms(clause)
        parts[index] = clause
    return "".join(parts)


def _normalize_legacy_economy_prompt_segment(value: str) -> str:
    inserted_flow = False

    def replace_flow(_match: re.Match[str]) -> str:
        nonlocal inserted_flow
        terminal = _match.groupdict().get("terminal")
        if inserted_flow:
            replacement = "交易与兑换流程"
        else:
            inserted_flow = True
            replacement = " ".join(_OPENING_MARKET_EXCHANGE_FLOW)
        if terminal:
            replacement = replacement.rstrip("。！？!?") + terminal
        return replacement

    normalized = _normalize_legacy_trade_windows(value)
    normalized = _normalize_clause_scoped_terms(normalized)
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
    if match.group("current"):
        return 1
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


def _normalize_legacy_economy_scoped_text(value: str) -> str:
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


def _future_chapter_json_spans(value: str) -> tuple[tuple[int, int], ...]:
    stack: list[int] = []
    candidates: list[tuple[int, int]] = []
    in_string = False
    escaped = False
    for index, char in enumerate(value):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            stack.append(index)
        elif char == "}" and stack:
            candidates.append((stack.pop(), index + 1))

    protected: list[tuple[int, int]] = []
    for start, end in candidates:
        try:
            payload = json.loads(value[start:end])
            chapter_number = int(payload.get("chapter_number")) if isinstance(payload, dict) else 0
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if chapter_number >= 2:
            protected.append((start, end))

    merged: list[tuple[int, int]] = []
    for start, end in sorted(protected):
        if merged and start < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _normalize_json_string_scopes(value: str) -> str:
    parts: list[str] = []
    cursor = 0
    start: int | None = None
    escaped = False
    for index, char in enumerate(value):
        if start is None:
            if char == '"':
                parts.append(_normalize_legacy_economy_scoped_text(value[cursor:index]))
                start = index
            continue
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            lookahead = index + 1
            while lookahead < len(value) and value[lookahead].isspace():
                lookahead += 1
            token = value[start : index + 1]
            parts.append(
                token
                if lookahead < len(value) and value[lookahead] == ":"
                else _normalize_legacy_economy_scoped_text(token)
            )
            cursor = index + 1
            start = None
    if start is not None:
        parts.append(_normalize_legacy_economy_scoped_text(value[start:]))
    else:
        parts.append(_normalize_legacy_economy_scoped_text(value[cursor:]))
    return "".join(parts)


def _normalize_legacy_economy_prompt_text(value: str) -> str:
    protected = _future_chapter_json_spans(value)
    if not protected:
        return _normalize_json_string_scopes(value)

    parts: list[str] = []
    cursor = 0
    for start, end in protected:
        parts.append(_normalize_json_string_scopes(value[cursor:start]))
        parts.append(value[start:end])
        cursor = end
    parts.append(_normalize_json_string_scopes(value[cursor:]))
    return "".join(parts)


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
