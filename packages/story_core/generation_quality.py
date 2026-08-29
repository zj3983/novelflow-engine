from __future__ import annotations

from typing import Any

from packages.story_core.simplified_review import build_simplified_review


REGENERATION_CONTINUITY_QUALITY_ISSUES: tuple[str, ...] = (
    "body",
    "chapter_title",
    "cadence",
    "next_outline",
    "timeline",
    "chapter_summaries",
    "chapter_title_summary",
    "cadence_summary",
    "summary",
)
NON_BLOCKING_QUALITY_ISSUES = {"body_too_long"}


def blocking_quality_issues(quality_report: dict[str, Any]) -> list[str]:
    return [
        issue
        for raw_issue in (quality_report.get("issues") or [])
        if (issue := str(raw_issue).strip())
        and issue != "writing_review"
        and issue not in NON_BLOCKING_QUALITY_ISSUES
    ]


def is_regeneration_continuity_failure(
    quality_report: dict[str, Any],
    writing_review: dict[str, Any] | None,
) -> bool:
    del writing_review
    quality_issues = [
        str(item).strip()
        for item in (quality_report.get("issues") or [])
        if str(item).strip()
    ]
    if not quality_issues:
        return False
    return not any(
        issue not in REGENERATION_CONTINUITY_QUALITY_ISSUES
        for issue in quality_issues
    )


def regeneration_quality_blocking(
    quality_report: dict[str, Any],
    writing_review: dict[str, Any] | None,
) -> bool:
    if not writing_review:
        return True
    combined_report = {**quality_report, "writing_review": writing_review}
    simplified = build_simplified_review(combined_report)
    if simplified.get("has_hard_errors"):
        return True
    return bool(blocking_quality_issues(quality_report))


def promote_downstream_rewrite_status(quality_report: dict[str, Any]) -> None:
    writing_review = (
        quality_report.get("writing_review")
        if isinstance(quality_report.get("writing_review"), dict)
        else {}
    )
    required = bool(writing_review.get("downstream_rewrite_required"))
    quality_report["downstream_rewrite_required"] = required
    if required and writing_review.get("downstream_chapter_number"):
        quality_report["downstream_chapter_number"] = writing_review[
            "downstream_chapter_number"
        ]
    else:
        quality_report.pop("downstream_chapter_number", None)


def chapter_outline_title(
    outline_context: Any,
    chapter_number: int,
) -> str | None:
    if not isinstance(outline_context, dict):
        return None
    chapter = outline_context.get("chapter")
    if not isinstance(chapter, dict):
        return None
    try:
        planned_number = int(chapter.get("chapter_number") or 0)
    except (TypeError, ValueError):
        return None
    title = str(chapter.get("title") or "").strip()
    return title if planned_number == chapter_number and title else None
