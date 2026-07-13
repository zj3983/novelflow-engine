from __future__ import annotations

import re
from typing import Any


AGENT_REVIEW_KEYS = ("reader_agent_review", "editor_agent_review", "reviewer_agent_review")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any, limit: int = 140) -> str:
    if isinstance(value, dict):
        value = value.get("reason") or value.get("suggestion") or value.get("type") or ""
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _normalize_issue_text(text: str) -> str:
    text = re.sub(r"段首主语过度单调：[^。；，,]+×\d+", "段首主语过度单调", text)
    text = re.sub(r"短段比例\d+%", "短段比例过高", text)
    return text


def _lesson_from_review(agent_name: str, review: dict[str, Any]) -> str | None:
    if not review:
        return None
    issue = next((_text(item) for item in _as_list(review.get("issues")) if _text(item)), "")
    issue = _normalize_issue_text(issue)
    plan = next((_text(item) for item in _as_list(review.get("revision_plan")) if _text(item)), "")
    if not issue and not plan:
        return None
    role = str(review.get("role") or agent_name).replace("_agent_review", "")
    if issue and plan:
        return f"{role}经验：上次问题是「{issue}」；下次写前先做到：{plan}"
    if issue:
        return f"{role}经验：下次写前避免「{issue}」"
    return f"{role}经验：下次写前先做到：{plan}"


def lessons_from_quality_report(quality_report: dict[str, Any], *, max_lessons: int = 6) -> list[str]:
    """Keep only changes that an accepted revision proved useful."""
    quality = _as_dict(quality_report)
    revision_safety = _as_dict(quality.get("revision_safety"))
    if not revision_safety.get("accepted") or revision_safety.get("selected") != "candidate":
        return []

    lessons: list[str] = []
    for item in _as_list(quality.get("accepted_revision_actions")):
        text = _text(item)
        if text:
            lesson = f"已验证改法：{text}"
            if lesson not in lessons:
                lessons.append(lesson)
        if len(lessons) >= max_lessons:
            break
    return lessons


def merge_writing_lessons(existing: Any, additions: list[str], *, limit: int = 24) -> list[str]:
    merged: list[str] = []
    for item in _as_list(existing):
        text = _text(item, 240)
        if text and text not in merged:
            merged.append(text)
    for item in additions:
        text = _text(item, 240)
        if text and text not in merged:
            merged.append(text)
    return merged[-limit:]


def learning_snapshot(lessons: Any, *, max_items: int = 8) -> dict[str, Any]:
    items = [_text(item, 220) for item in _as_list(lessons) if _text(item, 220)]
    return {
        "schema_version": "writing-learning/v1",
        "lessons": items[-max_items:],
        "usage": "写前先读这些经验，优先避免重复失败项；不要把本字段原文写进正文。",
    }
