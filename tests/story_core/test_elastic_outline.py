from __future__ import annotations

import pytest

from packages.story_core.elastic_outline import (
    outline_window_status,
    validate_outline_for_project,
)


def _outline(*, strategy: str = "observe", last_chapter: int = 30) -> dict:
    return {
        "overall": {
            "core_ending_chapter": 150,
            "extension_ceiling_chapter": 500,
            "current_strategy": strategy,
            "ending_contract": "两条线完整收束。",
        },
        "arcs": [
            {
                "id": "opening",
                "start_chapter": 1,
                "end_chapter": 30,
                "game_line_payoff": "完成阶段目标。",
                "reality_line_payoff": "解决现实压力。",
                "extension_gate": {
                    "continue_route": "进入主城。",
                    "close_route": "转入校验者结局。",
                },
            }
        ],
        "chapters": [
            {"chapter_number": number}
            for number in range(1, last_chapter + 1)
        ],
    }


def _volume_outline(
    start_chapter: int,
    end_chapter: int,
    *,
    detailed: range,
) -> dict:
    return {
        "overall": {
            "core_ending_chapter": end_chapter,
            "extension_ceiling_chapter": end_chapter,
        },
        "arcs": [
            {
                "id": "active-volume",
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
                "is_final_arc": True,
            }
        ],
        "chapters": [
            {"chapter_number": number}
            for number in detailed
        ],
    }


def test_missing_detail_targets_the_whole_active_volume() -> None:
    status = outline_window_status(
        _volume_outline(153, 212, detailed=range(153, 163)),
        current_chapter=152,
    )

    assert status["target_volume_id"] == "active-volume"
    assert status["target_volume_range"] == [153, 212]
    assert status["missing_chapter_numbers"] == list(range(163, 213))
    assert status["next_chapter_numbers"] == list(range(163, 213))
    assert status["detail_batches"][0] == list(range(163, 178))
    assert status["detail_batches"][1] == list(range(178, 193))
    assert status["detail_status"] == "partial"


def test_window_status_warns_with_three_or_fewer_planned_chapters() -> None:
    status = outline_window_status(_outline(last_chapter=20), current_chapter=17)
    assert status["last_planned_chapter"] == 20
    assert status["remaining_detailed_chapters"] == 3
    assert status["target_volume_range"] == [1, 30]
    assert status["target_last_chapter"] == 30
    assert status["needs_extension"] is True
    assert status["next_chapter_numbers"] == list(range(21, 31))


def test_partial_volume_requests_all_remaining_chapters() -> None:
    status = outline_window_status(_outline(last_chapter=20), current_chapter=10)
    assert status["remaining_detailed_chapters"] == 10
    assert status["needs_extension"] is True
    assert status["next_chapter_numbers"] == list(range(21, 31))


def test_volume_exposes_missing_numbers_without_warning_threshold() -> None:
    status = outline_window_status(_outline(last_chapter=18), current_chapter=10)
    assert status["remaining_detailed_chapters"] == 8
    assert status["needs_extension"] is True
    assert status["next_chapter_numbers"] == list(range(19, 31))


def test_window_exposes_missing_numbers_after_progress_reaches_threshold() -> None:
    status = outline_window_status(_outline(last_chapter=20), current_chapter=18)
    assert status["remaining_detailed_chapters"] == 2
    assert status["needs_extension"] is True
    assert status["next_chapter_numbers"] == list(range(21, 31))


def test_missing_volume_does_not_fabricate_window_to_extension_ceiling() -> None:
    status = outline_window_status(_outline(last_chapter=490), current_chapter=490)
    assert status["detail_status"] == "volume_missing"
    assert status["target_volume_range"] is None
    assert status["target_last_chapter"] == 490
    assert status["next_chapter_numbers"] == []


def test_window_at_ceiling_does_not_request_committed_chapters() -> None:
    status = outline_window_status(_outline(last_chapter=490), current_chapter=500)
    assert status["target_last_chapter"] == 500
    assert status["next_chapter_numbers"] == []


def test_volume_extension_includes_every_missing_detail_in_active_volume() -> None:
    status = outline_window_status(_outline(last_chapter=20), current_chapter=25)
    assert status["next_chapter_numbers"] == list(range(21, 31))


def test_sparse_window_requests_every_missing_chapter_in_target_window() -> None:
    outline = _outline(last_chapter=20)
    outline["chapters"].append({"chapter_number": 30})

    status = outline_window_status(outline, current_chapter=20)

    assert status["last_planned_chapter"] == 30
    assert status["remaining_detailed_chapters"] == 0
    assert status["target_last_chapter"] == 30
    assert status["needs_extension"] is True
    assert status["next_chapter_numbers"] == list(range(21, 30))


@pytest.mark.parametrize(
    "entrypoint", [outline_window_status, validate_outline_for_project]
)
@pytest.mark.parametrize("current_chapter", [True, "1", 1.0, -1])
def test_public_entrypoints_reject_invalid_current_chapter(
    entrypoint, current_chapter: object
) -> None:
    with pytest.raises(ValueError, match="^invalid_current_chapter$"):
        entrypoint(_outline(), current_chapter=current_chapter)


@pytest.mark.parametrize(
    "entrypoint", [outline_window_status, validate_outline_for_project]
)
def test_public_entrypoints_reject_current_chapter_beyond_ceiling(entrypoint) -> None:
    with pytest.raises(
        ValueError, match="^current_chapter_exceeds_extension_ceiling$"
    ):
        entrypoint(_outline(), current_chapter=501)


def test_core_ending_cannot_precede_committed_chapter() -> None:
    with pytest.raises(ValueError, match="core_ending_before_current_chapter"):
        validate_outline_for_project(
            {
                "overall": {
                    "core_ending_chapter": 20,
                    "extension_ceiling_chapter": 30,
                }
            },
            current_chapter=21,
        )


def test_close_strategy_requires_route_for_next_chapters_arc() -> None:
    outline = _outline(strategy="close", last_chapter=30)
    outline["overall"]["extension_ceiling_chapter"] = 150
    outline["arcs"].append(
        {
            "id": "city",
            "start_chapter": 31,
            "end_chapter": 60,
            "extension_gate": {"continue_route": "继续扩张。", "close_route": ""},
        }
    )

    with pytest.raises(ValueError, match="close_route_required_for_active_arc"):
        validate_outline_for_project(outline, current_chapter=30)
