from __future__ import annotations


def validate_bundle(bundle: dict) -> dict:
    issues: list[str] = []
    body = str(bundle.get("body") or "")
    compact_body = "".join(body.split())
    target_min_chars = 3800
    target_max_chars = 5500
    hard_max_chars = target_max_chars + 200
    enforce_min_chars = bool(
        bundle.get("enforce_target_chars")
        or bundle.get("manual_instructions")
        or isinstance(bundle.get("target_chars"), dict)
    )

    if not bundle.get("body"):
        issues.append("body")
    elif enforce_min_chars and len(compact_body) < target_min_chars:
        issues.append("body_too_short")
    elif len(compact_body) > hard_max_chars:
        issues.append("body_too_long")
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
    if not chapter_summary.get("summary"):
        issues.append("summary")

    return {
        "ok": not issues,
        "issues": issues,
        "metrics": {
            "body_chars": len(compact_body),
            "target_min_chars": target_min_chars,
            "target_max_chars": target_max_chars,
            "target_range": "4200到5500字",
        },
    }
