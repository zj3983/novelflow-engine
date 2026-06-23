from __future__ import annotations

from typing import Any

from packages.story_core.cold_reader_review import review_cold_reader_experience


def _issue_reason(issue: Any) -> str:
    if isinstance(issue, dict):
        return str(issue.get("reason") or issue.get("suggestion") or issue.get("type") or "").strip()
    return str(issue or "").strip()


def review_reader_agent(
    body: str,
    *,
    previous_summary: str = "",
    cold_reader_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reader-facing agent: would a cold reader keep reading?"""

    cold = cold_reader_review or review_cold_reader_experience(body, previous_summary=previous_summary)
    issues = [_issue_reason(issue) for issue in cold.get("issues", [])]
    issues = [issue for issue in issues if issue]
    scores = cold.get("scores", {}) if isinstance(cold.get("scores"), dict) else {}
    passed = bool(cold.get("pass", True)) and not issues
    verdict = "有追读基础" if passed else "读者拉力不足"
    return {
        "reviewer": "reader_agent/v1",
        "role": "读者 Agent",
        "pass": passed,
        "verdict": verdict,
        "scores": scores,
        "issues": issues,
        "revision_plan": list(cold.get("revision_plan") or []),
        "cold_reader_review": cold,
    }
