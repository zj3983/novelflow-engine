from __future__ import annotations


def validate_bundle(bundle: dict) -> dict:
    issues: list[str] = []

    if not bundle.get("body"):
        issues.append("body")
    if not bundle.get("next_outline"):
        issues.append("next_outline")

    updated_story = bundle.get("updated_story") or {}
    if not updated_story.get("timeline"):
        issues.append("timeline")
    if not updated_story.get("chapter_summaries"):
        issues.append("chapter_summaries")

    chapter_summary = bundle.get("chapter_summary") or {}
    if not chapter_summary.get("facts"):
        issues.append("facts")

    return {"ok": not issues, "issues": issues}
