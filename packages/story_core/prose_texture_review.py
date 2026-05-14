"""Unified prose texture review: combines quality scoring and adversarial cuts.

Finds sentences that read like rules, prompts, validator output, or AI-generated
fiction — and optionally provides conservative replacement suggestions.
"""

from __future__ import annotations

import re
from typing import Any


# --- Pattern definitions ---

EXPLANATORY_RULE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        r"放上去的[^。！？!?]{0,16}她看[；;，,][^。！？!?]{0,20}没放上去的[^。！？!?]{0,16}她不问",
        "这句在替规则说话，不是人物自然反应。",
        "删掉解释句，只保留NPC继续做手头工作的动作，让读者自己看懂边界。",
    ),
    (
        r"柜台很窄[^。！？!?]{0,24}规矩也很窄",
        "这是抽象总结，像作者在给规则下定义。",
        "改成柜台、账本、材料、NPC动作等可见细节。",
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
)

VALIDATOR_LANGUAGE_TERMS: tuple[str, ...] = (
    "信息边界",
    "NPC门槛",
    "规则未明",
    "材料暂不外露",
    "下一步目标",
    "场景卡",
    "质感审核",
    "硬规则",
)

VALIDATOR_TERMS_ADVERSARIAL = (
    "信息边界",
    "NPC门槛",
    "规则未明",
    "材料暂不外露",
    "爽点",
    "节奏",
    "读者期待",
)

AI_TEXTURE_TERMS: tuple[str, ...] = (
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
    "很清楚",
    "很直接",
    "数据异常",
    "异常标记",
    "异常掉落",
    "数据很干净",
    "风险也是",
    "不能全卖",
    "也不能不卖",
)

SLOGAN_LIKE_PATTERNS: tuple[str, ...] = (
    r"代价很小[，,]但代价存在",
    r"[^。！？!?]{1,12}是真的[，,][^。！？!?]{1,12}也是真的",
)


# --- Helpers ---

def _sentence_windows(body: str) -> list[str]:
    windows = re.split(r"(?<=[。！？!?])", body)
    return [window.strip() for window in windows if window.strip()]


def _find_term_quote(body: str, term: str) -> str:
    for sentence in _sentence_windows(body):
        if term in sentence:
            return sentence[:120]
    index = body.find(term)
    if index < 0:
        return term
    return body[max(0, index - 30) : index + len(term) + 50].strip()


def _dedupe_issues(issues: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for issue in issues:
        key = (issue.get("type", ""), issue.get("quote", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def _replacement_for_cut(quote: str, cut_type: str) -> str:
    if cut_type == "slogan_like_summary":
        if "代价" in quote:
            return "主角低头看了一眼状态条，少掉的那一截不多，却足够让他把手从下一次尝试前收回来。"
        if "热闹" in quote or "缺钱" in quote:
            return "村口的吆喝声一阵压过一阵，有人攥着空钱袋问价，也有人把刚剥下来的材料摊在掌心里等人开口。"
        return "他没有急着下结论，只把眼前能看见的变化一项项记下来。"
    if cut_type == "expository_rule_statement":
        if "只负责发委托" in quote:
            return "柜台旁的任务牌压着一角，药瓶、账本和收料的小木盘分成三处摆着，谁该走哪一步一眼就能看明白。"
        return "柜台后的人只扫了一眼台面，手里的笔没停，账本翻到委托那一页。"
    if cut_type == "validator_language":
        return "他把这句话压回心里，先看眼前的人怎么做。"
    return ""


# --- Main review ---

def review_prose_texture(body: str) -> dict[str, Any]:
    """Score reader-facing fiction texture and find sentences that need cutting.

    Combines the concerns of prose_quality_review and adversarial_cut_review
    into a single pass:
    - Finds explanatory/rule-like sentences
    - Detects validator and AI-trace terminology
    - Identifies slogan-like summaries
    - Optionally provides replacement suggestions
    """

    issues: list[dict[str, str]] = []
    scores = {
        "scene_naturalness": 8,
        "dialogue_texture": 8,
        "ai_trace": 8,
        "reader_pull": 8,
    }

    # Explanatory rule patterns
    for pattern, reason, suggestion in EXPLANATORY_RULE_PATTERNS:
        match = re.search(pattern, body)
        if match:
            issues.append({
                "type": "explanatory_rule_sentence",
                "quote": match.group(0),
                "reason": reason,
                "suggestion": suggestion,
            })
            scores["scene_naturalness"] = min(scores["scene_naturalness"], 6)

    # Expository rule patterns (adversarial cuts)
    for pattern, reason in EXPOSITORY_RULE_PATTERNS:
        for match in re.finditer(pattern, body):
            issues.append({
                "type": "expository_rule_statement",
                "quote": match.group(0),
                "reason": reason,
                "suggestion": "保留事实边界，但用NPC动作、柜台流程、任务牌或对话暗示。",
            })
            scores["scene_naturalness"] = min(scores["scene_naturalness"], 5)

    # Validator language
    all_validator_terms = set(VALIDATOR_LANGUAGE_TERMS) | set(VALIDATOR_TERMS_ADVERSARIAL)
    for term in sorted(all_validator_terms):
        if term in body:
            issues.append({
                "type": "validator_language",
                "quote": _find_term_quote(body, term),
                "reason": f"“{term}”是审核/规则层词，不像角色在世界里会自然想到的表达。",
                "suggestion": "改成角色动作、界面反馈、NPC台词或场景观察。",
            })
            scores["ai_trace"] = min(scores["ai_trace"], 6)

    # AI texture terms
    for term in AI_TEXTURE_TERMS:
        if term in body:
            issues.append({
                "type": "mechanical_explanation",
                "quote": _find_term_quote(body, term),
                "reason": f"“{term}”容易把叙事推向分析报告，而不是沉浸场景。",
                "suggestion": "用具体动作、犹豫、对话、价格变化或身体反应替代抽象判断。",
            })
            scores["ai_trace"] = min(scores["ai_trace"], 7)

    # Slogan-like patterns
    for pattern in SLOGAN_LIKE_PATTERNS:
        for match in re.finditer(pattern, body):
            issues.append({
                "type": "slogan_like_summary",
                "quote": match.group(0),
                "reason": "这类对称总结像作者金句，信息量少，容易显得刻意。",
                "suggestion": "改成可见动作、具体数字、环境反应或人物选择。",
            })
            scores["ai_trace"] = min(scores["ai_trace"], 6)

    issues = _dedupe_issues(issues)

    # Compute overall score
    penalty = sum(
        12 if issue["type"] in ("explanatory_rule_sentence", "expository_rule_statement") else 10
        for issue in issues
    )
    overall = max(0, min(100, 88 - penalty))
    if not body.strip():
        overall = 0
        scores = {key: 0 for key in scores}
        issues.append({
            "type": "empty_body",
            "quote": "",
            "reason": "正文为空。",
            "suggestion": "补写完整章节正文。",
        })

    if overall >= 90:
        level = "质感稳定，可直接继续"
    elif overall >= 80:
        level = "合格，仍可局部打磨"
    elif overall >= 70:
        level = "可读但需要润色"
    else:
        level = "需要改稿"

    strengths = []
    if not issues:
        strengths.append("没有发现明显解释腔、审核术语或规则替正文说话的问题。")
    if any(token in body for token in ("没追问", "继续给药瓶贴签", "没再多问")):
        strengths.append("NPC边界通过动作呈现，比直接解释规则更自然。")

    # Build adversarial cuts for replacement patches
    cuts: list[dict[str, str]] = []
    for issue in issues:
        if issue["type"] in ("slogan_like_summary", "expository_rule_statement", "validator_language"):
            quote = issue.get("quote", "").strip("。！？!? \n\t")
            if quote:
                replacement = _replacement_for_cut(quote, issue["type"])
                if replacement and replacement != quote:
                    cuts.append({
                        "quote": quote,
                        "type": issue["type"],
                        "severity": "high" if issue["type"] in ("expository_rule_statement", "validator_language") else "medium",
                        "reason": issue["reason"],
                        "suggestion": replacement,
                    })

    pressure = min(100, sum(22 if cut["severity"] == "high" else 20 for cut in cuts))

    return {
        "reviewer": "prose_texture/v1",
        "pass": overall >= 80 and not issues,
        "overall": overall,
        "level": level,
        "scores": scores,
        "issues": issues,
        "strengths": strengths,
        "cuts": cuts,
        "cut_pressure": pressure,
    }


# --- Backwards compatibility ---

# Re-export old names for code that imports them directly
review_prose_quality = review_prose_texture


def build_expression_patch_suggestions(review: dict[str, Any]) -> list[dict[str, str]]:
    """Build conservative patch suggestions from prose texture review output.

    Accepts either the unified prose_texture_review dict or the old
    adversarial_cut_review dict (with a "cuts" key).
    """
    # Support both unified format and old adversarial_cut format
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
        patches.append({
            "target_text": _with_sentence_punctuation(quote),
            "replacement_text": replacement,
        })
    return _dedupe_patches(patches)


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
