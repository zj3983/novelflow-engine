"""Deterministic checks for explicit project fact locks.

This module does not judge prose quality.  It only checks facts that the
project has deliberately kept fixed or unspecified, so a model cannot turn
an absent detail into new canon by writing it confidently in the draft.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


_VR_FORBIDDEN_INTERACTION = re.compile(r"鼠标|光标|点击|点选|双击|拖拽")
_EXACT_MONEY = re.compile(
    r"(?:余额|账户|银行卡|卡里|微信|支付宝)[^。！？\n]{0,12}"
    r"(?:\d+(?:\.\d+)?|[零〇一二两三四五六七八九十百千万]+)\s*元"
)
_REALITY_DEADLINE = re.compile(
    r"(?:房租|话费|手机|水费|电费|欠款|账单)[^。！？\n]{0,16}"
    r"(?:今天|明天|后天|\d+\s*[天日小时]|"
    r"[一二两三四五六七八九十百]+\s*[天日小时])"
    r"(?:后|内|前|到期|停机|截止)?"
)


def _rule_texts(rules: Iterable[Any]) -> list[str]:
    return [str(rule).strip() for rule in rules if str(rule).strip()]


def _mentions_unspecified(rule: str, subjects: tuple[str, ...]) -> bool:
    if not any(subject in rule for subject in subjects):
        return False
    return any(
        marker in rule
        for marker in ("未确定", "未明确", "没有确定", "尚未确定", "不得补写", "不能补写", "不得编造")
    )


def review_fact_locks(body: str, *, world_rules: Iterable[Any] = ()) -> dict[str, Any]:
    """Return blocking findings for violations of explicit world rules."""

    text = str(body or "")
    rules = _rule_texts(world_rules)
    issues: list[str] = []

    has_vr_interaction_rule = any(
        "虚拟现实" in rule
        and "交互" in rule
        and any(channel in rule for channel in ("视线", "语音", "动作", "手势"))
        for rule in rules
    )
    if has_vr_interaction_rule:
        terms = list(dict.fromkeys(_VR_FORBIDDEN_INTERACTION.findall(text)))
        if terms:
            issues.append(
                "虚拟现实交互违反项目规则：正文出现"
                + "、".join(terms[:4])
                + "，应改为视线、语音、手势或实际动作。"
            )

    money_unspecified = any(
        _mentions_unspecified(rule, ("余额", "账户", "银行卡", "现实金额"))
        for rule in rules
    )
    if money_unspecified and _EXACT_MONEY.search(text):
        issues.append("现实数值尚未确定，正文却补写了具体账户余额或金额。")

    deadline_unspecified = any(
        _mentions_unspecified(rule, ("期限", "日期", "房租", "手机状态", "停机"))
        for rule in rules
    )
    if deadline_unspecified and _REALITY_DEADLINE.search(text):
        issues.append("现实期限尚未确定，正文却补写了具体到期、停机或截止时间。")

    return {
        "pass": not issues,
        "issues": issues,
        "source": "deterministic_fact_locks",
    }


__all__ = ["review_fact_locks"]
