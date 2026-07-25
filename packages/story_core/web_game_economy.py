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


@dataclass(frozen=True)
class _EconomyUnit:
    text: str
    paragraph_index: int
    sentence_index: int
    start: int


@dataclass(frozen=True)
class _ItemMention:
    item: str
    identified: bool | None
    unit_index: int
    position: int


@dataclass(frozen=True)
class _AppraisalAction:
    item: str
    unit_index: int
    position: int


@dataclass(frozen=True)
class _OrderEvent:
    paragraph_index: int
    position: int
    owner: str | None
    label: str | None
    referential: bool


_ECONOMY_PARAGRAPH_BREAK = re.compile(r"(?:\r?\n[\t ]*){2,}")
_ECONOMY_SENTENCE = re.compile(r"[^。！？!?；;\r\n]+[。！？!?；;]?")
_MARKET_SCENE_TERMS = (
    "交易行",
    "拍卖行",
    "拍卖物",
    "求购",
    "求购单",
    "求购成交",
    "立即出售",
)
_REAL_SETTLEMENT_TERMS = ("现实账户", "现实结算", "现实到账")
_MARKET_TRANSACTION_SOURCE_TERMS = (
    "成交款",
    "成交所得",
    "交易所得",
    "拍卖所得",
    "求购所得",
    "求购成交所得",
    "卖出所得",
)
_MARKET_MONEY_TO_REALITY_PATTERN = re.compile(
    r"(?P<reference>这笔款项|那笔款项|这笔款|这笔钱|那笔钱|款项|(?<![一-龥A-Za-z0-9])钱)"
    r"(?P<link>[^。！？!?；;\r\n]{0,24}?)"
    r"(?:直接\s*)?(?:转入|打进|进入|到账)[^。！？!?；;\r\n]{0,8}现实账户"
)
_MONEY_SOURCE_REBINDING = re.compile(
    r"^(?:(?:是|来自)(?P<description>[^。！？!?；;\r\n]{1,18})"
    r"|由(?P<actor>[^，,。！？!?；;\r\n]{1,16})(?:支付|归还|发放))"
)
_MARKET_PAYMENT_ACTOR_PATTERN = re.compile(r"(?:交易行|拍卖行|求购平台|交易平台|拍卖平台)")
_MARKET_SALES_SOURCE_PATTERN = re.compile(
    r"(?:卖(?:出)?|出售|售出)[^，,。！？!?；;\r\n]{0,12}(?:所得|赚来|收入|款)"
    r"|(?:成交|交易|拍卖|求购)[^，,。！？!?；;\r\n]{0,12}(?:所得|赚来|收入|款)"
)
_SOURCE_NEGATION_PATTERN = re.compile(r"(?:不是|并非|不属于|并不是)\s*$")
_INDEPENDENT_SETTLEMENT_SOURCE_TERMS = (
    "工资",
    "薪水",
    "薪资",
    "奖金",
    "退款",
    "报销",
    "项目尾款",
    "旧工资",
)
_MARKET_COMPLETION_TERMS = ("成交", "卖出", "出售")
_DIRECT_SETTLEMENT_TERMS = ("直接", "进入", "转入", "打进", "到账", "现实结算")
_DIRECT_SETTLEMENT_DENIAL = re.compile(
    r"(?:没有|不需要|不必|无需|不用|不会|不能|并非|不是|不再|不应|不得|不可能)"
    r"\s*(?:(?:被|由)\s*(?:交易行|拍卖行|平台|系统)?\s*)?"
    r"(?:再|继续|要求)?\s*(?:直接)?(?:进入|转入|打进|到账|现实结算)"
)
_COMPLETED_EXCHANGE_PATTERN = re.compile(
    r"(?:确认(?:了)?兑换(?!价)|兑换(?:已经|已)?(?:成功|完成)|(?:成功|完成)(?:了)?官方兑换|"
    r"确认[^。！？!?；;\r\n]{0,24}(?:兑换价|额度|手续费|预计到账))"
)
_NEGATED_EXCHANGE_PATTERN = re.compile(
    r"(?:没有|并未|未|不需要|不必|无需|不用|不会|不能|尚未|无法)"
    r"[^。！？!?；;\r\n]{0,12}(?:使用|完成|确认)?[^。！？!?；;\r\n]{0,8}官方兑换"
    r"|官方兑换[^。！？!?；;\r\n]{0,12}(?:不可用|未开放|失败|尚未确认|没有完成)"
)
_LOCAL_ACTION_NEGATION = re.compile(
    r"(?:没有|并未|未|不需要|不必|无需|无须|不用|不会|不能|不再)"
    r"[^，,。！？!?；;\r\n]{0,14}$"
)
_ORDER_CLAUSE_BREAK = re.compile(r"[，,、]")
_NAME_PANEL_PATTERN = re.compile(r"【名称\s*[:：]\s*(?P<item>[^】]{1,20})】")
_ITEM_USE_PATTERN = re.compile(
    r"(?P<item>[一-龥A-Za-z0-9·]{2,20})(?:的)?用途(?:是|为|写着|标为|[:：])"
)
_ITEM_IDENTIFIED_PATTERN = re.compile(
    r"(?P<item>[一-龥A-Za-z0-9·]{2,20})(?:已识别|已经识别|已显示正式名称|已经显示正式名称)"
)
_INLINE_IDENTIFIED_ITEM_PATTERN = re.compile(
    r"(?:已经|已)识别的(?P<item>[一-龥A-Za-z0-9·]{1,20}?)(?=提交鉴定|送去鉴定|送去验货|交给鉴定师)"
)
_ITEM_UNIDENTIFIED_PATTERNS = (
    re.compile(r"(?P<item>[一-龥A-Za-z0-9·]{1,20})(?:仍是|仍为|还是|标为|显示为)?未鉴定"),
    re.compile(r"未鉴定的(?P<item>[一-龥A-Za-z0-9·]{1,20})"),
)
_CURRENT_ITEM_PATTERNS = (
    re.compile(r"(?:拿起|取出|看向|查看)(?:一件|一块|一颗|一个)?(?P<item>[一-龥A-Za-z0-9·]{1,16})"),
    re.compile(
        r"(?:换成|换上|改拿|转向)(?:了)?(?:一把|一柄|一件|一块|一颗|一个)?"
        r"(?P<item>[一-龥A-Za-z0-9·]{1,16})"
    ),
    re.compile(r"当前(?:查看|拿着)的是(?P<item>[一-龥A-Za-z0-9·]{1,16})"),
)
_APPRAISAL_ACTION_PATTERNS = (
    re.compile(
        r"把(?P<item>[一-龥A-Za-z0-9·]{1,20}?)(?:交给鉴定师|提交鉴定|送去鉴定|送去验货)"
    ),
    re.compile(r"送(?P<item>[一-龥A-Za-z0-9·]{1,20}?)去鉴定"),
    re.compile(
        r"(?:^|[，、：\s])(?P<item>[一-龥A-Za-z0-9·]{1,20}?)(?:提交鉴定|送去鉴定|送去验货)"
    ),
)
_ITEM_PRONOUNS = {"它", "这件物品", "这个物品", "这件装备", "这颗材料", "这块材料", "这件材料"}
_IMPLICIT_ITEM_REFERENCE = "<implicit-item>"
_APPRAISAL_ACTION_TERMS = ("提交鉴定", "送去鉴定", "送去验货", "平台验货")
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
_COMPLETED_ORDER_TERMS = ("立即出售", "显示成交", "已经成交", "已成交", "成交后", "成交以后", "成交")
_BUYER_RECONFIRM_PATTERN = re.compile(r"(?:等待|等)买家(?:再次)?确认|买家再次确认")
_NEGATED_WAIT_MARKERS = (
    "没有",
    "不需要",
    "不必",
    "无需",
    "无须",
    "不用",
    "不会",
    "不能",
    "并非",
    "不是",
    "不再",
)
_FUNDED_ORDER_PATTERN = re.compile(
    r"求购单(?:里|里的|中|中的|其中|其中的)?"
    r"[^，。！？!?；;]{0,8}?(?:资金|游戏币)(?:已经|已)?(?:被)?冻结(?:了)?"
)
_FUNDED_MONEY_PATTERN = re.compile(
    r"(?:资金|游戏币)(?:已经|已|随后)?(?:被)?冻结(?:了)?"
)
_ORDER_POSSESSIVE_OWNER_PATTERN = re.compile(
    r"(?:^|[，、：；。！？!?\s])\s*(?P<owner>[一-龥A-Za-z0-9·]{1,8}?)的"
    r"(?:(?:第[一二三四五六七八九十百\d]+(?:条|张))?"
    r"(?:普通)?(?:求购单|订单)|[A-Z]单(?:求购)?)"
)
_ORDER_PLAYER_OWNER_PATTERN = re.compile(r"(?P<owner>[甲乙丙丁戊己庚辛壬癸A-Z])玩家")
_ORDER_NARRATED_OWNER_PATTERN = re.compile(
    r"(?:看见|发现|查看|得知|注意到)\s*(?P<owner>[一-龥A-Za-z0-9·]{1,8}?)的"
    r"(?:(?:第[一二三四五六七八九十百\d]+(?:条|张))?"
    r"(?:普通)?(?:求购单|订单)|[A-Z]单(?:求购)?)"
)
_ORDER_HOLDER_OWNER_PATTERN = re.compile(
    r"(?:^|[，、：；。！？!?\s])\s*(?P<owner>[一-龥A-Za-z0-9·]{1,8}?)"
    r"(?=有一张(?:求购单|订单))"
)
_ORDER_WAITING_OWNER_PATTERN = re.compile(
    r"(?:^|[，、：；。！？!?\s])\s*"
    r"(?P<owner>(?!(?:[一-龥A-Za-z0-9·]{0,7})(?:订单|求购|系统|页面|界面|成交|要求|仍需|还需))"
    r"[一-龥A-Za-z0-9·]{1,8}?)"
    r"(?=(?:(?:还在|仍在|正在)?等待)买家(?:再次)?确认)"
)
_ORDER_LABEL_PATTERNS = (
    (
        "number",
        re.compile(r"(?:求购单|订单)(?:号|编号)[:：#-]?(?P<label>[A-Z0-9甲乙丙丁戊己庚辛壬癸-]+)"),
    ),
    (
        "ordinal",
        re.compile(r"第(?P<label>[一二三四五六七八九十百\d]+)(?:条|张)(?:求购单|订单)"),
    ),
    ("code", re.compile(r"(?P<label>[A-Z])单(?:求购)?")),
    ("code", re.compile(r"(?P<label>[甲乙丙丁戊己庚辛壬癸A-Z])(?:号)?(?:求购单|订单)")),
    ("code", re.compile(r"(?:求购单|订单)(?P<label>[甲乙丙丁戊己庚辛壬癸A-Z]\d*)")),
)
_ORDER_REFERENCE_PATTERN = re.compile(
    r"(?:该(?:求购单|订单|玩家)|这张(?:求购单|订单)?|同一(?:求购单|订单))"
)


def _economy_units(text: str) -> tuple[_EconomyUnit, ...]:
    units: list[_EconomyUnit] = []
    paragraph_start = 0
    paragraph_index = 0
    breaks = (*_ECONOMY_PARAGRAPH_BREAK.finditer(text), None)
    for paragraph_break in breaks:
        paragraph_end = paragraph_break.start() if paragraph_break else len(text)
        paragraph = text[paragraph_start:paragraph_end]
        sentence_index = 0
        for sentence in _ECONOMY_SENTENCE.finditer(paragraph):
            raw = sentence.group()
            stripped = raw.strip()
            if not stripped:
                continue
            leading = len(raw) - len(raw.lstrip())
            units.append(
                _EconomyUnit(
                    text=stripped,
                    paragraph_index=paragraph_index,
                    sentence_index=sentence_index,
                    start=paragraph_start + sentence.start() + leading,
                )
            )
            sentence_index += 1
        if paragraph_break is None:
            break
        paragraph_start = paragraph_break.end()
        paragraph_index += 1
    return tuple(units)


def _is_market_completion(unit: _EconomyUnit) -> bool:
    return any(term in unit.text for term in _MARKET_SCENE_TERMS) and any(
        term in unit.text for term in _MARKET_COMPLETION_TERMS
    )


def _term_is_negated(text: str, index: int) -> bool:
    return _SOURCE_NEGATION_PATTERN.search(text[max(0, index - 8) : index]) is not None


def _has_asserted_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(
        not _term_is_negated(text, match.start())
        for term in terms
        for match in re.finditer(re.escape(term), text)
    )


def _has_independent_settlement_source(text: str) -> bool:
    return _has_asserted_term(text, _INDEPENDENT_SETTLEMENT_SOURCE_TERMS)


def _has_market_money_reference(text: str) -> bool:
    for match in _MARKET_MONEY_TO_REALITY_PATTERN.finditer(text):
        link = match.group("link").strip()
        reference = match.group("reference")
        rebinding = _MONEY_SOURCE_REBINDING.search(link)
        if rebinding is None:
            if _has_independent_settlement_source(link) and not _has_asserted_term(
                link, _MARKET_TRANSACTION_SOURCE_TERMS
            ):
                continue
            return True
        source = rebinding.group("actor") or rebinding.group("description") or ""
        if _MARKET_PAYMENT_ACTOR_PATTERN.search(source) or _MARKET_SALES_SOURCE_PATTERN.search(
            source
        ):
            return True
        if any(term in reference for term in ("成交", "交易", "拍卖", "求购", "卖出")):
            return True
        if _has_independent_settlement_source(source):
            continue
    return False


def _is_direct_reality_settlement(unit: _EconomyUnit) -> bool:
    if not any(term in unit.text for term in _REAL_SETTLEMENT_TERMS):
        return False
    if not any(term in unit.text for term in _DIRECT_SETTLEMENT_TERMS):
        return False
    has_market_source = _has_asserted_term(
        unit.text, _MARKET_TRANSACTION_SOURCE_TERMS
    ) or _has_market_money_reference(unit.text)
    if not has_market_source and not _is_market_completion(unit):
        return False
    return _DIRECT_SETTLEMENT_DENIAL.search(unit.text) is None


def _has_exchange_between(
    units: tuple[_EconomyUnit, ...],
    market_index: int,
    settlement_index: int,
    market_position: int,
    reality_position: int,
) -> bool:
    official_exchange_seen = False
    for unit in units[market_index : settlement_index + 1]:
        bounded_text = unit.text
        if unit.start < market_position:
            bounded_text = bounded_text[market_position - unit.start + 1 :]
        if unit.start + len(unit.text) > reality_position:
            bounded_text = bounded_text[: max(0, reality_position - unit.start)]
        if "官方兑换" in bounded_text:
            official_exchange_seen = True
        if (
            official_exchange_seen
            and _COMPLETED_EXCHANGE_PATTERN.search(bounded_text)
            and _NEGATED_EXCHANGE_PATTERN.search(bounded_text) is None
        ):
            return True
    return False


def _has_direct_market_settlement(units: tuple[_EconomyUnit, ...]) -> bool:
    for index, market_unit in enumerate(units):
        if not _is_market_completion(market_unit):
            continue
        market_position = market_unit.start + min(
            market_unit.text.find(term)
            for term in _MARKET_SCENE_TERMS
            if term in market_unit.text
        )
        for settlement_index in range(index, len(units)):
            settlement_unit = units[settlement_index]
            paragraph_gap = settlement_unit.paragraph_index - market_unit.paragraph_index
            if paragraph_gap > 2:
                break
            if not _is_direct_reality_settlement(settlement_unit):
                continue
            reality_position = settlement_unit.start + min(
                settlement_unit.text.find(term)
                for term in _REAL_SETTLEMENT_TERMS
                if term in settlement_unit.text
            )
            if reality_position <= market_position:
                continue
            if _has_exchange_between(
                units,
                index,
                settlement_index,
                market_position,
                reality_position,
            ):
                continue
            return True
    return False


def _clean_item_name(value: str) -> str:
    item = value.strip(" ，。；：、【】")
    for prefix in ("已经识别的", "已识别的"):
        if item.startswith(prefix):
            item = item[len(prefix) :]
    for marker in ("面板写着", "面板显示", "系统显示", "写着", "显示", "标着", "旁边的", "旁边"):
        if marker in item:
            item = item.rsplit(marker, 1)[-1]
    for prefix in ("夜烬", "他", "她", "那件", "一件", "一个", "一颗", "一块"):
        if item.startswith(prefix) and item not in _ITEM_PRONOUNS:
            item = item[len(prefix) :]
    return item.strip(" ，。；：、【】")


def _item_mentions(units: tuple[_EconomyUnit, ...]) -> tuple[_ItemMention, ...]:
    mentions: list[_ItemMention] = []
    for unit_index, unit in enumerate(units):
        identified_matches = [
            *_NAME_PANEL_PATTERN.finditer(unit.text),
            *_ITEM_USE_PATTERN.finditer(unit.text),
            *_ITEM_IDENTIFIED_PATTERN.finditer(unit.text),
            *_INLINE_IDENTIFIED_ITEM_PATTERN.finditer(unit.text),
        ]
        for match in identified_matches:
            item = _clean_item_name(match.group("item"))
            if item and not item.endswith(("把", "将", "对")):
                mentions.append(_ItemMention(item, True, unit_index, unit.start + match.start()))
        if "裂纹狼心" in unit.text and any(term in unit.text for term in ("用途", "正式名称", "已识别")):
            mentions.append(
                _ItemMention("裂纹狼心", True, unit_index, unit.start + unit.text.find("裂纹狼心"))
            )
        for pattern in _ITEM_UNIDENTIFIED_PATTERNS:
            for match in pattern.finditer(unit.text):
                item = _clean_item_name(match.group("item"))
                if item:
                    mentions.append(_ItemMention(item, False, unit_index, unit.start + match.start()))
        for pattern in _CURRENT_ITEM_PATTERNS:
            for match in pattern.finditer(unit.text):
                item = _clean_item_name(match.group("item"))
                if item:
                    mentions.append(_ItemMention(item, None, unit_index, unit.start + match.start()))
    return tuple(sorted(mentions, key=lambda mention: mention.position))


def _appraisal_actions(units: tuple[_EconomyUnit, ...]) -> tuple[_AppraisalAction, ...]:
    actions: list[_AppraisalAction] = []
    for unit_index, unit in enumerate(units):
        explicit_positions: set[int] = set()
        for pattern in _APPRAISAL_ACTION_PATTERNS:
            for match in pattern.finditer(unit.text):
                if _LOCAL_ACTION_NEGATION.search(unit.text[: match.start()]):
                    continue
                item = _clean_item_name(match.group("item"))
                if item:
                    actions.append(_AppraisalAction(item, unit_index, unit.start + match.end()))
                    explicit_positions.update(
                        range(unit.start + match.start(), unit.start + match.end())
                    )
        for term in _APPRAISAL_ACTION_TERMS:
            start = 0
            while True:
                index = unit.text.find(term, start)
                if index < 0:
                    break
                position = unit.start + index
                if (
                    position not in explicit_positions
                    and _LOCAL_ACTION_NEGATION.search(unit.text[:index]) is None
                ):
                    actions.append(
                        _AppraisalAction(_IMPLICIT_ITEM_REFERENCE, unit_index, position)
                    )
                start = index + len(term)
    return tuple(sorted(actions, key=lambda action: action.position))


def _has_reappraised_identified_item(units: tuple[_EconomyUnit, ...]) -> bool:
    mentions = _item_mentions(units)
    for action in _appraisal_actions(units):
        nearby = [
            mention
            for mention in mentions
            if (
                mention.position < action.position
                and 0
                <= units[action.unit_index].paragraph_index
                - units[mention.unit_index].paragraph_index
                <= 2
            )
        ]
        if action.item in _ITEM_PRONOUNS or action.item == _IMPLICIT_ITEM_REFERENCE:
            if nearby and nearby[-1].identified:
                return True
            continue
        same_item = [mention for mention in nearby if mention.item == action.item]
        if same_item and same_item[-1].identified:
            return True
    return False


def _order_identity(text: str) -> tuple[str | None, str | None, bool]:
    label = None
    for kind, pattern in _ORDER_LABEL_PATTERNS:
        match = pattern.search(text)
        if match:
            label = f"{kind}:{match.group('label')}"
            break

    owner_match = _ORDER_PLAYER_OWNER_PATTERN.search(text)
    if owner_match is None:
        owner_match = _ORDER_NARRATED_OWNER_PATTERN.search(text)
    if owner_match is None:
        owner_match = _ORDER_POSSESSIVE_OWNER_PATTERN.search(text)
    if owner_match is None:
        owner_match = _ORDER_HOLDER_OWNER_PATTERN.search(text)
    if owner_match is None:
        owner_match = _ORDER_WAITING_OWNER_PATTERN.search(text)
    owner = owner_match.group("owner") if owner_match else None
    if owner in {"该", "这", "同一"}:
        owner = None
    return owner, label, _ORDER_REFERENCE_PATTERN.search(text) is not None


def _order_event_span(text: str, start: int, end: int) -> str:
    left = 0
    for match in _ORDER_CLAUSE_BREAK.finditer(text, 0, start):
        left = match.end()
    right_match = _ORDER_CLAUSE_BREAK.search(text, end)
    right = right_match.start() if right_match else len(text)
    return text[left:right].strip()


def _order_identity_at(text: str, start: int, end: int) -> tuple[str | None, str | None, bool]:
    return _order_identity(_order_event_span(text, start, end))


def _order_events_for_terms(
    units: tuple[_EconomyUnit, ...],
    terms: tuple[str, ...],
    *,
    require_order_context: bool = False,
) -> list[_OrderEvent]:
    events: list[_OrderEvent] = []
    for unit in units:
        for term in terms:
            start = 0
            while True:
                index = unit.text.find(term, start)
                if index < 0:
                    break
                span = _order_event_span(unit.text, index, index + len(term))
                owner, label, referential = _order_identity(span)
                if require_order_context and not any(
                    marker in span for marker in ("求购单", "订单", "单求购")
                ) and label is None:
                    start = index + len(term)
                    continue
                events.append(
                    _OrderEvent(
                        paragraph_index=unit.paragraph_index,
                        position=unit.start + index,
                        owner=owner,
                        label=label,
                        referential=referential,
                    )
                )
                start = index + len(term)
    return sorted(set(events), key=lambda event: event.position)


def _buyer_reconfirm_positions(units: tuple[_EconomyUnit, ...]) -> list[_OrderEvent]:
    events: list[_OrderEvent] = []
    for unit in units:
        for match in _BUYER_RECONFIRM_PATTERN.finditer(unit.text):
            prefix = unit.text[max(0, match.start() - 10) : match.start()]
            if any(marker in prefix for marker in _NEGATED_WAIT_MARKERS):
                continue
            owner, label, referential = _order_identity_at(
                unit.text, match.start(), match.end()
            )
            events.append(
                _OrderEvent(
                    paragraph_index=unit.paragraph_index,
                    position=unit.start + match.start(),
                    owner=owner,
                    label=label,
                    referential=referential,
                )
            )
    return events


def _funded_order_positions(units: tuple[_EconomyUnit, ...]) -> list[_OrderEvent]:
    positions: list[_OrderEvent] = []
    for unit_index, unit in enumerate(units):
        matches = [
            match
            for term in _FUNDED_ORDER_TERMS
            for match in re.finditer(re.escape(term), unit.text)
        ]
        matches.extend(_FUNDED_ORDER_PATTERN.finditer(unit.text))
        matches.extend(_FUNDED_MONEY_PATTERN.finditer(unit.text))
        for match in matches:
            span = _order_event_span(unit.text, match.start(), match.end())
            owner, label, referential = _order_identity(span)
            has_order_context = any(
                marker in span for marker in ("求购单", "订单", "单求购")
            ) or label is not None
            if not has_order_context:
                prior_span = unit.text[: match.start()].rstrip(" ，,、")
                prior_match = list(_ORDER_CLAUSE_BREAK.finditer(prior_span))
                if prior_match:
                    prior_span = prior_span[prior_match[-1].end() :].strip()
                if not prior_span and unit_index > 0:
                    prior_unit = units[unit_index - 1]
                    if unit.paragraph_index - prior_unit.paragraph_index <= 1:
                        prior_span = _order_event_span(
                            prior_unit.text, len(prior_unit.text), len(prior_unit.text)
                        )
                prior_owner, prior_label, _ = _order_identity(prior_span)
                prior_has_order = any(
                    marker in prior_span for marker in ("求购单", "订单", "单求购")
                ) or prior_label is not None
                if not prior_has_order:
                    continue
                owner, label, referential = prior_owner, prior_label, True
            positions.append(
                _OrderEvent(
                    paragraph_index=unit.paragraph_index,
                    position=unit.start + match.start(),
                    owner=owner,
                    label=label,
                    referential=referential,
                )
            )
    return sorted(set(positions), key=lambda event: event.position)


def _same_order(*events: _OrderEvent) -> bool:
    for field in ("owner", "label"):
        values = {getattr(event, field) for event in events if getattr(event, field) is not None}
        if len(values) > 1:
            return False
    return True


def _has_buyer_reconfirmation_after_funded_sale(units: tuple[_EconomyUnit, ...]) -> bool:
    funded_events = _funded_order_positions(units)
    completed_events = _order_events_for_terms(units, _COMPLETED_ORDER_TERMS)
    confirm_events = _buyer_reconfirm_positions(units)
    for funded in funded_events:
        for completed in completed_events:
            if (
                completed.position <= funded.position
                or completed.paragraph_index > funded.paragraph_index + 2
            ):
                continue
            for confirm in confirm_events:
                if (
                    confirm.position > completed.position
                    and confirm.paragraph_index <= funded.paragraph_index + 2
                    and _same_order(funded, completed, confirm)
                ):
                    return True
    return False


def detect_economy_boundary_violations(body: str) -> tuple[EconomyBoundaryViolation, ...]:
    """Find only explicit market, appraisal and exchange boundary violations."""

    units = _economy_units(body)
    violations: list[EconomyBoundaryViolation] = []
    if _has_direct_market_settlement(units):
        violations.append(
            EconomyBoundaryViolation(
                code="market_direct_reality_settlement",
                issue="交易行成交所得被直接写入现实账户，交易与现实兑换混成了一步。",
                revision="交易行只进游戏钱包；现实收益必须在离开交易行后走独立官方兑换。",
            )
        )
    if _has_reappraised_identified_item(units):
        violations.append(
            EconomyBoundaryViolation(
                code="identified_item_reappraised",
                issue="已显示正式名称、用途或已识别状态的物品又被送去鉴定或验货。",
                revision="已识别物不重复鉴定；只有明确标为未鉴定的物品才交给鉴定师。",
            )
        )
    if _has_buyer_reconfirmation_after_funded_sale(units):
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
