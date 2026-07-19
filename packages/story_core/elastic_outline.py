from __future__ import annotations

from typing import Any

from packages.story_core.project_outline import normalize_project_outline


DETAIL_WINDOW = 30
EXTENSION_WARNING = 10


def outline_window_status(
    outline: dict[str, Any], *, current_chapter: int
) -> dict[str, Any]:
    normalized = normalize_project_outline(outline)
    last_planned = max(
        [int(item["chapter_number"]) for item in normalized["chapters"]]
        or [current_chapter]
    )
    remaining = max(0, last_planned - current_chapter)
    target_last = min(
        current_chapter + DETAIL_WINDOW,
        normalized["overall"]["extension_ceiling_chapter"],
    )
    needs_extension = remaining <= EXTENSION_WARNING
    next_numbers = (
        list(range(last_planned + 1, target_last + 1))
        if needs_extension and last_planned < target_last
        else []
    )
    return {
        "last_planned_chapter": last_planned,
        "remaining_detailed_chapters": remaining,
        "target_last_chapter": target_last,
        "needs_extension": bool(next_numbers),
        "next_chapter_numbers": next_numbers,
    }


def validate_outline_for_project(
    outline: dict[str, Any], *, current_chapter: int
) -> dict[str, Any]:
    normalized = normalize_project_outline(outline)
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
