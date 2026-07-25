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
    "交易行不能直接现实结算。",
)

_APPRAISAL_RULES: tuple[str, ...] = (
    "仅未鉴定物品可交给鉴定师。",
    "已识别物品不重复鉴定。",
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
_NUMBERED_CHAPTER = re.compile(r"第(?:[一二三四五六七八九十百千万零〇两\d]+|[Nn])章")


def market_rules() -> tuple[str, ...]:
    return _MARKET_RULES


def exchange_rules() -> tuple[str, ...]:
    return _EXCHANGE_RULES


def appraisal_rules() -> tuple[str, ...]:
    return _APPRAISAL_RULES


def _text_entries(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(text for item in value.values() for text in _text_entries(item))
    if isinstance(value, (list, tuple)):
        return tuple(text for item in value for text in _text_entries(item))
    return ()


def _has_ordered_new_contract(text: str) -> bool:
    scope_positions = tuple(
        match.start()
        for match in re.finditer(r"第一章|第1章|本章", text)
    )
    transaction_positions = tuple(
        match.start()
        for match in re.finditer(r"卖出裂纹狼心|交易成交", text)
    )
    exchange_position = text.find("官方兑换")
    urgency_position = text.find("现实急账")
    if not transaction_positions:
        return False
    transaction_position = min(transaction_positions)
    relevant_scopes = tuple(position for position in scope_positions if position < transaction_position)
    if not relevant_scopes or not (transaction_position < exchange_position < urgency_position):
        return False
    scope_position = max(relevant_scopes)
    return not any(
        scope_position < match.start() <= urgency_position
        for match in _NUMBERED_CHAPTER.finditer(text)
    )


def _has_non_first_numbered_chapter(text: str) -> bool:
    return any(
        match.group()[1:-1] not in ("一", "1")
        for match in _NUMBERED_CHAPTER.finditer(text)
    )


def _denies_current_economy(text: str) -> bool:
    return any(
        not match.group().endswith("担保交易")
        for match in _ECONOMY_DENIAL.finditer(text)
    )


def first_chapter_market_exchange_authorized(
    event_plan: dict[str, Any] | None = None,
    world_facts: list[str] | None = None,
) -> bool:
    entries = (
        *_text_entries(event_plan or {}),
        *(str(item) for item in (world_facts or [])),
    )
    for text in entries:
        if _has_non_first_numbered_chapter(text) or _denies_current_economy(text):
            continue
        if _has_ordered_new_contract(text):
            return True
        # Legacy project input only; new prompt rules must never emit these markers.
        if any(marker in text for marker in _LEGACY_OPENING_MARKERS):
            return True
    return False
