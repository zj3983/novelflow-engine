from __future__ import annotations

from typing import Any


HARD_TOKENS = (
    "body_too_short",
    "body_too_long",
    "正文为空",
    "字数不足",
    "字数超出",
    "题材污染",
    "设定冲突",
    "人物错位",
    "人物状态",
    "角色状态",
    "时间线",
    "数值冲突",
    "连续性冲突",
)

AI_FLAVOR_TOKENS = (
    "AI味",
    "模型腔",
    "报告腔",
    "套话",
    "公式句",
    "抽象总结",
    "重复句式",
    "段首",
)

NESTED_REVIEW_KEYS = (
    "reader_agent_review",
    "editor_agent_review",
    "reviewer_agent_review",
    "ai_flavor_review",
    "cold_reader_review",
)

INTERNAL_ISSUES = {"writing_review", "primary_conflict", "secondary_conflict", "event_beat"}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _issue_text(issue: Any) -> str:
    if isinstance(issue, str):
        return issue.strip()
    if isinstance(issue, dict):
        for key in ("reason", "message", "issue", "type"):
            text = str(issue.get(key) or "").strip()
            if text:
                return text
    return ""


def _collect_issues(report: dict[str, Any]) -> list[str]:
    sources: list[dict[str, Any]] = [report]
    writing = _as_dict(report.get("writing_review"))
    sources.append(writing)
    for key in NESTED_REVIEW_KEYS:
        sources.append(_as_dict(report.get(key)))
        sources.append(_as_dict(writing.get(key)))

    collected: list[str] = []
    for source in sources:
        for issue in source.get("issues") or []:
            text = _issue_text(issue)
            if text and text not in INTERNAL_ISSUES:
                collected.append(text)
    return collected


def _category(message: str) -> str:
    if any(token in message for token in HARD_TOKENS):
        return "hard"
    if any(token in message for token in AI_FLAVOR_TOKENS):
        return "ai_flavor"
    return "prose"


def _suggestion(category: str) -> str:
    if category == "hard":
        return "先修正设定、状态或篇幅问题，再继续生成后续章节。"
    if category == "ai_flavor":
        return "删除抽象判断和固定套话，改成角色动作、对白或现场结果。"
    return "只修改对应段落，保留已经成立的剧情和人物状态。"


def build_simplified_review(quality_report: Any, *, limit: int = 5) -> dict[str, Any]:
    report = _as_dict(quality_report)
    seen: set[str] = set()
    grouped: dict[str, list[dict[str, str]]] = {"hard": [], "prose": [], "ai_flavor": []}

    for message in _collect_issues(report):
        key = "".join(message.split()).rstrip("。；;！!")
        if not key or key in seen:
            continue
        seen.add(key)
        category = _category(message)
        grouped[category].append(
            {
                "category": category,
                "severity": "blocking" if category == "hard" else "advisory",
                "message": message,
                "suggestion": _suggestion(category),
            }
        )

    ordered = [*grouped["hard"], *grouped["prose"], *grouped["ai_flavor"]]
    selected = ordered[: max(1, limit)]
    has_hard_errors = bool(grouped["hard"])
    return {
        "schema_version": "simplified-review/v1",
        "pass": not has_hard_errors,
        "has_hard_errors": has_hard_errors,
        "summary": "存在必须修复的硬伤" if has_hard_errors else ("可以继续，建议局部修改" if ordered else "未发现需要处理的问题"),
        "categories": {
            "hard": {"label": "硬伤", "count": len(grouped["hard"])},
            "prose": {"label": "正文", "count": len(grouped["prose"])},
            "ai_flavor": {"label": "AI味", "count": len(grouped["ai_flavor"])},
        },
        "issues": selected,
        "total_issues": len(ordered),
    }
