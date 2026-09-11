from __future__ import annotations

from copy import deepcopy

import pytest

from packages.story_core.generation_consistency_gate import (
    GenerationConsistencyGate,
    evaluate_generation_consistency,
)
from packages.story_core.consistency_replanning import (
    ConsistencyReplanRequest,
    build_consistency_replan_request,
    run_consistency_replan,
)


def _story(*, acquired_chapter: int = 25) -> dict:
    return {
        "current_chapter": 40,
        "characters": [
            {
                "name": "林照",
                "role": "protagonist",
                "current_state": {"history": [{"chapter": 1, "current": {"location": "北岸"}}]},
            },
            {
                "name": "顾闻舟",
                "role": "supporting",
                "current_state": {"history": [{"chapter": 1, "current": {"location": "北岸"}}]},
            },
        ],
        "progression_ledger": {
                "protagonist": {"history": [{"chapter": acquired_chapter, "current": {"skills": ["FUTURE_SKILL_999"]}}]},
        },
        "knowledge_ledger": [
            {
                "fact_id": "future-secret",
                "fact": "FUTURE_SECRET_999",
                "learned_chapter": 40,
                "known_by": ["林照"],
            }
        ],
        "equipment_cards": [
            {
                "id": "future-equipment",
                "name": "FUTURE_EQUIPMENT_999",
                "history": [{"chapter": 1, "current_owner": "顾闻舟"}],
            }
        ],
        "relationship_graph": [],
    }


def _blocked_plan() -> dict:
    return {
        "chapter_number": 20,
        "chapter_intent": {"chapter_title": "旧案"},
        "character_moves": [
            {
                "name": "林照",
                "location": "北岸",
                "skills_used": ["FUTURE_SKILL_999"],
                "knowledge_fact_ids": ["future-secret"],
                "equipment_used": ["FUTURE_EQUIPMENT_999"],
            },
            {"name": "顾闻舟", "location": "北岸"},
        ],
    }


def _gate(plan: dict | None = None) -> GenerationConsistencyGate:
    return evaluate_generation_consistency(
        _story(), plan or _blocked_plan(), target_chapter=20
    )


def test_replan_request_contains_all_blocking_evidence_and_immutable_history_rule() -> None:
    request = build_consistency_replan_request(
        target_chapter=20,
        original_plan=_blocked_plan(),
        consistency_gate=_gate(),
        attempt_number=1,
    )

    assert isinstance(request, ConsistencyReplanRequest)
    assert request.historical_boundary == 19
    assert {item.code for item in request.blocking_findings} == {
        "SKILL_NOT_YET_ACQUIRED",
        "KNOWLEDGE_NOT_YET_LEARNED",
        "EQUIPMENT_NOT_OWNED",
    }
    prompt = request.director_guidance
    assert "不可变" in prompt
    assert "FUTURE_SKILL_999" in prompt
    assert "FUTURE_SECRET_999" in prompt
    assert "FUTURE_EQUIPMENT_999" in prompt
    assert "ledger" in prompt


def test_replan_rechecks_revised_plan_instead_of_trusting_director_status() -> None:
    original = _blocked_plan()
    director_claimed_clear_but_still_blocked = deepcopy(original)
    calls: list[ConsistencyReplanRequest] = []

    result = run_consistency_replan(
        source=_story(),
        target_chapter=20,
        original_plan=original,
        original_gate=_gate(original),
        plan_replanner=lambda request: calls.append(request)
        or director_claimed_clear_but_still_blocked,
    )

    assert result.status == "still_blocking"
    assert result.remaining_gate.status == "blocking"
    assert calls[0].attempt_number == 1


def test_clean_replan_preserves_source_and_returns_warning_status_without_second_attempt() -> None:
    source = _story()
    before = deepcopy(source)
    revised = {
        "chapter_number": 20,
        "character_moves": [
            {"name": "林照", "location": "不明地点"},
            {"name": "顾闻舟", "location": "北岸"},
        ],
    }
    result = run_consistency_replan(
        source=source,
        target_chapter=20,
        original_plan=_blocked_plan(),
        original_gate=_gate(),
        plan_replanner=lambda _request: revised,
    )

    assert result.status == "replanned_with_warnings"
    assert result.remaining_gate.status == "warnings"
    assert source == before
    assert result.attempt_number == 1


def test_replan_attempt_is_bounded() -> None:
    with pytest.raises(ValueError, match="replan_attempt_limit"):
        run_consistency_replan(
            source=_story(),
            target_chapter=20,
            original_plan=_blocked_plan(),
            original_gate=_gate(),
            plan_replanner=lambda _request: _blocked_plan(),
            attempt_number=2,
        )


def test_replan_rechecks_a_tampered_clear_gate_and_keeps_chapter_one_boundary() -> None:
    source = _story()
    original = _blocked_plan()
    tampered_gate = GenerationConsistencyGate(
        target_chapter=1,
        status="clear",
        warnings=[],
        checked_characters=[],
        checked_at_boundary=0,
    )
    calls: list[ConsistencyReplanRequest] = []

    result = run_consistency_replan(
        source=source,
        target_chapter=1,
        original_plan=original,
        original_gate=tampered_gate,
        plan_replanner=lambda request: calls.append(request) or {
            "chapter_number": 1,
            "character_moves": [{"name": "林照", "location": "北岸"}],
        },
    )

    assert calls[0].historical_boundary == 0
    assert {item.code for item in calls[0].blocking_findings} == {
        "SKILL_NOT_YET_ACQUIRED",
        "KNOWLEDGE_NOT_YET_LEARNED",
    }
    assert result.original_gate.status == "blocking"


def test_replan_uses_the_target_boundary_for_an_old_chapter_rewrite() -> None:
    source = _story(acquired_chapter=125)
    gate = evaluate_generation_consistency(source, _blocked_plan(), target_chapter=120)
    calls: list[ConsistencyReplanRequest] = []

    run_consistency_replan(
        source=source,
        target_chapter=120,
        original_plan=_blocked_plan(),
        original_gate=gate,
        plan_replanner=lambda request: calls.append(request) or {
            "chapter_number": 120,
            "character_moves": [{"name": "林照", "location": "北岸"}],
        },
    )

    assert calls[0].historical_boundary == 119
    skill_warning = next(
        item
        for item in calls[0].blocking_findings
        if item.code == "SKILL_NOT_YET_ACQUIRED"
    )
    assert skill_warning.observed == {"acquired_chapter": 125}


def test_one_replan_request_contains_blocking_findings_for_multiple_characters() -> None:
    source = _story()
    source["characters"].append(
        {
            "name": "顾闻舟",
            "role": "supporting",
            "current_state": {"history": [{"chapter": 1, "current": {"location": "北岸"}}]},
        }
    )
    source["progression_ledger"]["顾闻舟"] = {
        "history": [{"chapter": 30, "current": {"skills": ["FUTURE_SKILL_B"]}}]
    }
    original = _blocked_plan()
    original["character_moves"].append(
        {"name": "顾闻舟", "location": "北岸", "skills_used": ["FUTURE_SKILL_B"]}
    )
    gate = evaluate_generation_consistency(source, original, target_chapter=20)
    calls: list[ConsistencyReplanRequest] = []

    run_consistency_replan(
        source=source,
        target_chapter=20,
        original_plan=original,
        original_gate=gate,
        plan_replanner=lambda request: calls.append(request) or {
            "chapter_number": 20,
            "character_moves": [
                {"name": "林照", "location": "北岸"},
                {"name": "顾闻舟", "location": "北岸"},
            ],
        },
    )

    assert {item.character_name for item in calls[0].blocking_findings} == {
        "林照",
        "顾闻舟",
    }
    assert {item.character_name for item in calls[0].blocking_findings if item.code == "SKILL_NOT_YET_ACQUIRED"} == {
        "林照",
        "顾闻舟",
    }
