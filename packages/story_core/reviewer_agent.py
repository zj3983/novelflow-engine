from __future__ import annotations

from typing import Any

from packages.story_core.prose_rule_review import review_critical_prose_rules
from packages.story_core.progression_lead_review import review_progression_lead
from packages.story_core.web_game_review import review_web_game_chapter


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _collect_issues(*reports: dict[str, Any], limit: int = 16) -> list[str]:
    issues: list[str] = []
    for report in reports:
        for item in report.get("issues", []) or []:
            text = str(item.get("reason") if isinstance(item, dict) else item).strip()
            if text and text not in issues:
                issues.append(text)
            if len(issues) >= limit:
                return issues
        critical = report.get("hard_issues") if isinstance(report.get("hard_issues"), list) else []
        for item in critical:
            text = str(item).strip()
            if text and text not in issues:
                issues.append(text)
            if len(issues) >= limit:
                return issues
    return issues


def _collect_plan(*reports: dict[str, Any], limit: int = 12) -> list[str]:
    plan: list[str] = []
    for report in reports:
        for item in report.get("revision_plan", []) or []:
            text = str(item).strip()
            if text and text not in plan:
                plan.append(text)
            if len(plan) >= limit:
                return plan
    return plan


def review_reviewer_agent(
    *,
    chapter_number: int,
    body: str,
    event_plan: dict[str, Any] | None = None,
    world_facts: list[Any] | None = None,
    protagonist_names: list[str] | None = None,
    critical_review: dict[str, Any] | None = None,
    web_game_review: dict[str, Any] | None = None,
    progression_lead_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reviewer agent: hard continuity, rule, game-ledger, and progression checks."""

    event_plan = _as_dict(event_plan)
    critical = critical_review or review_critical_prose_rules(body, protagonist_names=protagonist_names or [])
    web_game = web_game_review or review_web_game_chapter(
        chapter_number=chapter_number,
        body=body,
        event_plan=event_plan,
        world_facts=world_facts or [],
    )
    progression = progression_lead_review or review_progression_lead(
        chapter_number=chapter_number,
        body=body,
        event_plan=event_plan,
        world_facts=world_facts or [],
    )
    issues = _collect_issues(critical, web_game, progression)
    revision_plan = _collect_plan(critical, web_game, progression)
    scores = {
        "critical": 8 if critical.get("pass", True) else 5,
        "web_game": 8 if web_game.get("pass", True) else 5,
        "progression": 8 if progression.get("pass", True) else 5,
    }
    passed = bool(critical.get("pass", True)) and bool(web_game.get("pass", True)) and bool(progression.get("pass", True)) and not issues
    return {
        "reviewer": "reviewer_agent/v1",
        "role": "审稿 Agent",
        "pass": passed,
        "verdict": "硬伤检查通过" if passed else "存在硬伤或连续性风险",
        "scores": scores,
        "issues": issues,
        "revision_plan": revision_plan,
        "critical_review": critical,
        "web_game_review": web_game,
        "progression_lead_review": progression,
    }
