from __future__ import annotations

from typing import Any

from packages.story_core.project_outline import normalize_project_outline


DETAIL_WINDOW = 30
EXTENSION_WARNING = 10


def _normalize_for_current_chapter(
    outline: dict[str, Any], *, current_chapter: int
) -> dict[str, Any]:
    if (
        isinstance(current_chapter, bool)
        or not isinstance(current_chapter, int)
        or current_chapter < 0
    ):
        raise ValueError("invalid_current_chapter")
    normalized = normalize_project_outline(outline)
    if current_chapter > normalized["overall"]["extension_ceiling_chapter"]:
        raise ValueError("current_chapter_exceeds_extension_ceiling")
    return normalized


def outline_window_status(
    outline: dict[str, Any], *, current_chapter: int
) -> dict[str, Any]:
    normalized = _normalize_for_current_chapter(
        outline, current_chapter=current_chapter
    )
    planned_numbers = {
        int(item["chapter_number"]) for item in normalized["chapters"]
    }
    last_planned = max(planned_numbers or {current_chapter})
    target_last = min(
        current_chapter + DETAIL_WINDOW,
        normalized["overall"]["extension_ceiling_chapter"],
    )
    target_numbers = range(current_chapter + 1, target_last + 1)
    remaining = 0
    for chapter_number in target_numbers:
        if chapter_number not in planned_numbers:
            break
        remaining += 1
    missing_candidates = [
        chapter_number
        for chapter_number in target_numbers
        if chapter_number not in planned_numbers
    ]
    needs_extension = (
        bool(missing_candidates) and remaining <= EXTENSION_WARNING
    )
    return {
        "last_planned_chapter": last_planned,
        "remaining_detailed_chapters": remaining,
        "target_last_chapter": target_last,
        "needs_extension": needs_extension,
        "next_chapter_numbers": missing_candidates if needs_extension else [],
    }


def validate_outline_for_project(
    outline: dict[str, Any], *, current_chapter: int
) -> dict[str, Any]:
    normalized = _normalize_for_current_chapter(
        outline, current_chapter=current_chapter
    )
    if normalized["overall"]["core_ending_chapter"] < current_chapter:
        raise ValueError("core_ending_before_current_chapter")
    if normalized["overall"]["current_strategy"] == "close":
        target = current_chapter + 1
        active = next(
            (
                arc
                for arc in normalized["arcs"]
                if arc["start_chapter"] <= target <= arc["end_chapter"]
            ),
            None,
        )
        if active is None or not active["extension_gate"]["close_route"].strip():
            raise ValueError("close_route_required_for_active_arc")
    return normalized
