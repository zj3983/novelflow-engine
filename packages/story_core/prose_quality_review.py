from __future__ import annotations

import re
from typing import Any


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

AI_TEXTURE_TERMS: tuple[str, ...] = (
    "意味着",
    "很清楚",
    "很直接",
    "异常",
    "数据很干净",
    "风险也是",
    "不能全卖",
    "也不能不卖",
)

SLOGAN_LIKE_PATTERNS: tuple[str, ...] = (
    r"代价很小[，,]但代价存在",
    r"[^。！？!?]{1,12}是真的[，,][^。！？!?]{1,12}也是真的",
)


def _sentence_windows(body: str) -> list[str]:
    windows = re.split(r"(?<=[。！？!?])", body)
    return [window.strip() for window in windows if window.strip()]


def _find_pattern_issue(body: str, pattern: str, reason: str, suggestion: str) -> dict[str, str] | None:
    match = re.search(pattern, body)
    if not match:
        return None
    return {
        "type": "explanatory_rule_sentence",
        "quote": match.group(0),
        "reason": reason,
        "suggestion": suggestion,
    }


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


def review_prose_quality(body: str) -> dict[str, Any]:
    """Score reader-facing fiction texture separately from hard-rule review.

    This reviewer intentionally prefers sentence-level diagnostics over broad
    pass/fail labels so it can catch prose that is technically valid but reads
    like rules, prompts, or validator output.
    """

    issues: list[dict[str, str]] = []
    scores = {
        "scene_naturalness": 8,
        "dialogue_texture": 8,
        "ai_trace": 8,
        "reader_pull": 8,
    }

    for pattern, reason, suggestion in EXPLANATORY_RULE_PATTERNS:
        issue = _find_pattern_issue(body, pattern, reason, suggestion)
        if issue:
            issues.append(issue)
            scores["scene_naturalness"] = min(scores["scene_naturalness"], 6)

    for term in VALIDATOR_LANGUAGE_TERMS:
        if term in body:
            issues.append(
                {
                    "type": "validator_language",
                    "quote": _find_term_quote(body, term),
                    "reason": f"“{term}”是审核/规则层词，不像角色在世界里会自然想到的表达。",
                    "suggestion": "改成角色动作、界面反馈、NPC台词或场景观察，不要把审核术语写进正文。",
                }
            )
            scores["ai_trace"] = min(scores["ai_trace"], 6)

    for term in AI_TEXTURE_TERMS:
        if term in body:
            issues.append(
                {
                    "type": "mechanical_explanation",
                    "quote": _find_term_quote(body, term),
                    "reason": f"“{term}”容易把叙事推向分析报告，而不是沉浸场景。",
                    "suggestion": "用具体动作、犹豫、对话、价格变化或身体反应替代抽象判断。",
                }
            )
            scores["ai_trace"] = min(scores["ai_trace"], 7)

    for pattern in SLOGAN_LIKE_PATTERNS:
        for match in re.finditer(pattern, body):
            issues.append(
                {
                    "type": "slogan_like_summary",
                    "quote": match.group(0),
                    "reason": "这类对称总结像作者金句，信息量少，容易显得空和刻意。",
                    "suggestion": "改成可见动作、具体数字、环境反应或人物选择，让判断藏在场景里。",
                }
            )
            scores["ai_trace"] = min(scores["ai_trace"], 6)

    issues = _dedupe_issues(issues)
    penalty = sum(12 if issue["type"] == "explanatory_rule_sentence" else 10 for issue in issues)
    overall = max(0, min(100, 88 - penalty))
    if not body.strip():
        overall = 0
        scores = {key: 0 for key in scores}
        issues.append(
            {
                "type": "empty_body",
                "quote": "",
                "reason": "正文为空。",
                "suggestion": "补写完整章节正文。",
            }
        )

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

    return {
        "reviewer": "prose_quality/v1",
        "pass": overall >= 80 and not issues,
        "overall": overall,
        "level": level,
        "scores": scores,
        "issues": issues,
        "strengths": strengths,
    }
