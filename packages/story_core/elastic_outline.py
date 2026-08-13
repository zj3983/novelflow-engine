from __future__ import annotations

from typing import Any

from packages.story_core.project_outline import normalize_project_outline
from packages.story_core.volume_outline import (
    find_volume_for_chapter,
    volume_detail_batches_for_missing,
)


DETAIL_WINDOW = 10
EXTENSION_WARNING = 3


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
    target_chapter = current_chapter + 1
    target_volume = find_volume_for_chapter(
        normalized["arcs"],
        target_chapter,
    )
    if target_volume is None:
        return {
            "target_volume_id": None,
            "target_volume_range": None,
            "missing_chapter_numbers": [],
            "detail_batches": [],
            "detail_status": "volume_missing",
            "last_planned_chapter": last_planned,
            "remaining_detailed_chapters": 0,
            "target_last_chapter": current_chapter,
            "needs_extension": False,
            "next_chapter_numbers": [],
        }

    target_start = int(target_volume["start_chapter"])
    target_last = int(target_volume["end_chapter"])
    target_numbers = range(target_start, target_last + 1)
    remaining = 0
    for chapter_number in range(current_chapter + 1, target_last + 1):
        if chapter_number not in planned_numbers:
            break
        remaining += 1
    missing_candidates = [
        chapter_number
        for chapter_number in target_numbers
        if chapter_number not in planned_numbers
    ]
    planned_in_volume = {
        chapter_number
        for chapter_number in planned_numbers
        if target_start <= chapter_number <= target_last
    }
    detail_batches = volume_detail_batches_for_missing(
        target_start,
        target_last,
        existing=planned_in_volume,
    )
    detail_status = (
        "complete"
        if not missing_candidates
        else "partial"
        if planned_in_volume
        else "missing"
    )
    return {
        "target_volume_id": str(target_volume["id"]),
        "target_volume_range": [target_start, target_last],
        "missing_chapter_numbers": missing_candidates,
        "detail_batches": detail_batches,
        "detail_status": detail_status,
        "last_planned_chapter": last_planned,
        "remaining_detailed_chapters": remaining,
        "target_last_chapter": target_last,
        "needs_extension": bool(missing_candidates),
        "next_chapter_numbers": missing_candidates,
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
