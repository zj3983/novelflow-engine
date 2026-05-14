from __future__ import annotations

import re
from typing import Any


SLOGAN_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        r"代价很小[，,]但代价存在",
        "slogan_like_summary",
        "这句像作者在替场景下结论，读者看不到具体代价。",
    ),
    (
        r"[^。！？!?]{1,12}是真的[，,][^。！？!?]{1,12}也是真的",
        "slogan_like_summary",
        "这类对称句像金句总结，信息量低，容易显得刻意。",
    ),
)

EXPOSITORY_RULE_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"[^。！？!?]{0,20}看不见他(?:的)?背包[^。！？!?]{0,40}",
        "这句在解释系统权限，不像自然叙事。",
    ),
    (
        r"[^。！？!?]{0,16}只负责发委托[、,，]收材料[、,，]给药[^。！？!?]{0,20}",
        "这句把NPC服务规则直接念出来了。",
    ),
    (
        r"放上去的[^。！？!?]{0,16}她看[；;，,][^。！？!?]{0,20}没放上去的[^。！？!?]{0,16}她不问",
        "这句替规则说话，应该改成动作和柜台反馈。",
    ),
)

VALIDATOR_TERMS = (
    "信息边界",
    "NPC门槛",
    "规则未明",
    "材料暂不外露",
    "爽点",
    "节奏",
    "意味着",
    "阈值",
    "现金流",
    "可量化",
    "可计算",
    "容错率",
    "底层交互逻辑",
    "数学模型",
    "数据模型",
    "数据建模",
    "模型跑不动",
    "后台数据异常",
    "概率",
    "止损线",
    "资金链",
    "变量",
    "算法",
    "常规掉落池",
    "规则被硬生生撬开",
    "系统把溢出部分",
    "读者期待",
)


def _sentence_windows(body: str) -> list[str]:
    windows = re.split(r"(?<=[。！？!?])", body)
    return [window.strip() for window in windows if window.strip()]


def _term_sentence(body: str, term: str) -> str:
    for sentence in _sentence_windows(body):
        if term in sentence:
            return sentence[:140]
    index = body.find(term)
    if index < 0:
        return term
    return body[max(0, index - 40) : index + len(term) + 60].strip()


def _make_cut(
    *,
    quote: str,
    cut_type: str,
    severity: str,
    reason: str,
    action: str = "replace_with_scene_detail",
    suggestion: str,
) -> dict[str, str]:
    return {
        "quote": quote.strip("。！？!? \n\t"),
        "type": cut_type,
        "severity": severity,
        "reason": reason,
        "action": action,
        "suggestion": suggestion,
    }


def _dedupe(cuts: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for cut in cuts:
        key = (cut.get("type", ""), cut.get("quote", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(cut)
    return result


def review_adversarial_cuts(body: str) -> dict[str, Any]:
    """Find sentences that should be cut or replaced before polishing.

    This reviewer is deliberately expression-only. It does not infer or mutate
    world facts; it points to prose that should be converted into visible
    action, dialogue, UI feedback, or scene detail.
    """

    cuts: list[dict[str, str]] = []

    for pattern, cut_type, reason in SLOGAN_PATTERNS:
        for match in re.finditer(pattern, body):
            cuts.append(
                _make_cut(
                    quote=match.group(0),
                    cut_type=cut_type,
                    severity="medium",
                    reason=reason,
                    suggestion="换成具体场景：界面数值、人物动作、柜台反应、玩家喊价或身体代价，不要用总结句。",
                )
            )

    for pattern, reason in EXPOSITORY_RULE_PATTERNS:
        for match in re.finditer(pattern, body):
            cuts.append(
                _make_cut(
                    quote=match.group(0),
                    cut_type="expository_rule_statement",
                    severity="high",
                    reason=reason,
                    suggestion="保留事实边界，但用NPC动作、柜台流程、任务牌或对话暗示，不要直接解释系统规则。",
                )
            )

    for term in VALIDATOR_TERMS:
        if term in body:
            cuts.append(
                _make_cut(
                    quote=_term_sentence(body, term),
                    cut_type="validator_language",
                    severity="high",
                    reason=f"“{term}”属于规划/审稿层术语，不能出现在读者正文里。",
                    suggestion="把后台术语翻译成角色能看见、听见、做出的事。",
                )
            )

    cuts = _dedupe(cuts)
    pressure = min(100, sum(22 if cut["severity"] == "high" else 20 for cut in cuts))

    return {
        "reviewer": "adversarial_cut/v1",
        "pass": len(cuts) == 0,
        "cut_pressure": pressure,
        "cuts": cuts,
    }


def build_expression_patch_suggestions(review: dict[str, Any]) -> list[dict[str, str]]:
    """Build conservative patch suggestions from cut-review output.

    The replacements are intentionally generic scene beats. They avoid adding
    new world facts such as new monsters, currency amounts, hidden powers, or
    NPC omniscience. A future LLM patcher can replace this, but the contract
    should stay patch-only.
    """

    raw_cuts = review.get("cuts", []) if isinstance(review, dict) else []
    if not isinstance(raw_cuts, list):
        return []

    patches: list[dict[str, str]] = []
    for cut in raw_cuts:
        if not isinstance(cut, dict):
            continue
        quote = str(cut.get("quote") or "").strip()
        cut_type = str(cut.get("type") or "")
        if not quote:
            continue
        replacement = _replacement_for_cut(quote, cut_type)
        if not replacement or replacement == quote:
            continue
        patches.append({"target_text": _with_sentence_punctuation(quote), "replacement_text": replacement})
    return _dedupe_patches(patches)


def _replacement_for_cut(quote: str, cut_type: str) -> str:
    if cut_type == "slogan_like_summary":
        if "代价" in quote:
            return "夜烬低头看了一眼法力条，少掉的那一截不多，却足够让他把手从下一次尝试前收回来。"
        if "热闹" in quote or "缺钱" in quote:
            return "村口的吆喝声一阵压过一阵，有人攥着空钱袋问价，也有人把刚剥下来的材料摊在掌心里等人开口。"
        return "他没有急着下结论，只把眼前能看见的变化一项项记下来。"
    if cut_type == "expository_rule_statement":
        if "只负责发委托" in quote:
            return "柜台旁的任务牌压着一角，药瓶、账本和收料的小木盘分成三处摆着，谁该走哪一步一眼就能看明白。"
        return "洛婶只扫了一眼柜台上的东西，手里的笔没停，账本翻到委托那一页。"
    if cut_type == "validator_language":
        return "他把这句话压回心里，先看眼前的人怎么做。"
    return ""


def _with_sentence_punctuation(quote: str) -> str:
    if quote.endswith(("。", "！", "？", "!", "?")):
        return quote
    return f"{quote}。"


def _dedupe_patches(patches: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for patch in patches:
        target = patch["target_text"]
        if target in seen:
            continue
        seen.add(target)
        result.append(patch)
    return result
