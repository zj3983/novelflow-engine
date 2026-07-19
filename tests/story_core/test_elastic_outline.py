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


def test_window_status_warns_with_ten_or_fewer_planned_chapters() -> None:
    status = outline_window_status(_outline(last_chapter=30), current_chapter=20)
    assert status == {
        "last_planned_chapter": 30,
        "remaining_detailed_chapters": 10,
        "target_last_chapter": 50,
        "needs_extension": True,
        "next_chapter_numbers": list(range(31, 51)),
    }


def test_full_window_does_not_request_more_chapters() -> None:
    status = outline_window_status(_outline(last_chapter=40), current_chapter=10)
    assert status["remaining_detailed_chapters"] == 30
    assert status["needs_extension"] is False
    assert status["next_chapter_numbers"] == []


def test_window_target_stops_at_extension_ceiling() -> None:
    status = outline_window_status(_outline(last_chapter=490), current_chapter=490)
    assert status["target_last_chapter"] == 500
    assert status["next_chapter_numbers"] == list(range(491, 501))


def test_window_at_ceiling_does_not_request_committed_chapters() -> None:
    status = outline_window_status(_outline(last_chapter=490), current_chapter=500)
    assert status["target_last_chapter"] == 500
    assert status["next_chapter_numbers"] == []


def test_window_extension_starts_after_current_when_outline_is_behind() -> None:
    status = outline_window_status(_outline(last_chapter=20), current_chapter=25)
    assert status["next_chapter_numbers"] == list(range(26, 56))
    assert all(number > 25 for number in status["next_chapter_numbers"])


def test_core_ending_cannot_precede_committed_chapter() -> None:
    with pytest.raises(ValueError, match="core_ending_before_current_chapter"):
        validate_outline_for_project(
            {
                "overall": {
                    "core_ending_chapter": 20,
                    "extension_ceiling_chapter": 20,
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
