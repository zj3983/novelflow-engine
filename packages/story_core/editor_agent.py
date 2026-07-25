from __future__ import annotations

from typing import Any

from packages.story_core.ai_flavor_review import review_ai_flavor
from packages.story_core.prose_quality_review import review_prose_quality
from packages.story_core.prose_style_review import review_prose_style


def _issue_text(issue: Any) -> str:
    if isinstance(issue, dict):
        quote = str(issue.get("quote") or "").strip()
        reason = str(issue.get("reason") or issue.get("type") or "").strip()
        if quote and reason:
            return f"{reason}：{quote}"
        return reason or quote
    return str(issue or "").strip()


def _merge_unique(items: list[str], additions: list[Any], *, limit: int = 12) -> list[str]:
    for item in additions:
        text = _issue_text(item)
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    return items


def review_editor_agent(
    body: str,
    *,
    genre_context: Any = None,
    prose_quality_review: dict[str, Any] | None = None,
    prose_style_review: dict[str, Any] | None = None,
    ai_flavor_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Editor agent: structure, rhythm, dialogue, and prose texture."""

    quality = prose_quality_review or review_prose_quality(body)
    style = prose_style_review or review_prose_style(body, genre_context=genre_context)
    ai = ai_flavor_review or review_ai_flavor(body)
    issues: list[str] = []
    _merge_unique(issues, quality.get("issues", []))
    _merge_unique(issues, style.get("issues", []))
    _merge_unique(issues, ai.get("issues", []))
    revision_plan: list[str] = []
    _merge_unique(revision_plan, quality.get("revision_plan", []), limit=10)
    _merge_unique(revision_plan, style.get("revision_plan", []), limit=10)
    _merge_unique(revision_plan, ai.get("revision_plan", []), limit=10)

    scores: dict[str, Any] = {
        "prose_quality": int(quality.get("overall", 0) or 0),
        "style_pass": 8 if style.get("pass", True) else 5,
        "ai_flavor": (ai.get("scores") or {}).get("ai_flavor", 0),
    }
    passed = bool(quality.get("pass", True)) and bool(style.get("pass", True)) and bool(ai.get("pass", True)) and not issues
    return {
        "reviewer": "editor_agent/v1",
        "role": "编辑 Agent",
        "pass": passed,
        "verdict": "结构和文风可继续" if passed else "需要编辑层修改",
        "scores": scores,
        "issues": issues,
        "revision_plan": revision_plan,
        "prose_quality_review": quality,
        "prose_style_review": style,
        "ai_flavor_review": ai,
    }
