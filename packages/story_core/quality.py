from __future__ import annotations


def validate_bundle(bundle: dict) -> dict:
    issues: list[str] = []

    if not bundle.get("body"):
        issues.append("body")
    if not bundle.get("chapter_title"):
        issues.append("chapter_title")
    if not bundle.get("cadence"):
        issues.append("cadence")
    if not bundle.get("next_outline"):
        issues.append("next_outline")

    updated_story = bundle.get("updated_story") or {}
    if not updated_story.get("timeline"):
        issues.append("timeline")
    if not updated_story.get("chapter_summaries"):
        issues.append("chapter_summaries")

    chapter_summary = bundle.get("chapter_summary") or {}
    if not chapter_summary.get("chapter_title"):
        issues.append("chapter_title_summary")
    if not chapter_summary.get("cadence"):
        issues.append("cadence_summary")
    if not chapter_summary.get("facts"):
        issues.append("facts")
    if not chapter_summary.get("next_focus"):
        issues.append("next_focus")
    if not chapter_summary.get("primary_conflict"):
        issues.append("primary_conflict")
    if not chapter_summary.get("secondary_conflict"):
        issues.append("secondary_conflict")
    if not chapter_summary.get("event_beat"):
        issues.append("event_beat")

    return {"ok": not issues, "issues": issues}
