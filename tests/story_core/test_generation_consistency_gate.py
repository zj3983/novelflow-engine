from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

import packages.story_core.agents.pipeline as pipeline_module
from packages.story_core.agents.contracts import DirectorArtifact, EntityRequirement
from packages.story_core.continuity.delta import ContinuityDelta
from packages.story_core.generation_consistency_gate import (
    ConsistencyGateRequired,
    GenerationConsistencyGate,
    evaluate_generation_consistency,
    map_plan_to_character_contexts,
    require_generation_consistency,
)


def _story() -> dict:
    return {
        "story_id": "generation-gate-test",
        "outline": "林照追查旧案。",
        "genre": "网游",
        "style": "克制",
        "current_chapter": 300,
        "characters": [
            {
                "name": "林照",
                "role": "protagonist",
                "current_state": {
                    "current": {"location": "FUTURE_LOCATION_999"},
                    "history": [{"chapter": 10, "current": {"location": "秘境二层"}}],
                },
            },
            {
                "name": "顾闻舟",
                "role": "supporting",
                "current_state": {
                    "history": [{"chapter": 10, "current": {"location": "北岸"}}],
                },
            },
        ],
        "progression_ledger": {
            "protagonist": {
                "history": [
                    {"chapter": 25, "current": {"skills": ["FUTURE_SKILL_999"]}},
                ],
            },
        },
        "equipment_cards": [
            {
                "id": "future-equipment",
                "name": "FUTURE_EQUIPMENT_999",
                "first_appearance_chapter": 10,
                "history": [
                    {"chapter": 10, "current_owner": "顾闻舟"},
                ],
            },
        ],
        "knowledge_ledger": [
            {
                "fact_id": "future-secret",
                "fact": "FUTURE_SECRET_999",
                "learned_chapter": 40,
                "known_by": ["林照"],
                "visibility": "private",
            },
        ],
        "relationship_graph": [
            {
                "id": "lin-gu",
                "source": "林照",
                "target": "顾闻舟",
                "first_chapter": 10,
                "last_changed_chapter": 10,
                "trust": 20,
                "changes": [{"chapter": 10, "trust": 20}],
            },
        ],
    }


def _plan() -> dict:
    return {
        "character_moves": [
            {
                "name": "林照",
                "location": "FUTURE_LOCATION_999",
                "skills_used": ["FUTURE_SKILL_999"],
                "equipment_used": ["FUTURE_EQUIPMENT_999"],
                "knowledge_fact_ids": ["future-secret"],
                "relationship_expectations": [
                    {"target": "顾闻舟", "trust_min": 70},
                ],
            },
            {"name": "顾闻舟", "location": "北岸"},
        ],
    }


def test_mapper_uses_only_explicit_structured_actor_fields() -> None:
    contexts = map_plan_to_character_contexts(
        {
            "scene_cards": [
                {
                    "title": "FUTURE_LOCATION_999 is only a title",
                    "location": "黑风城",
                    "cast": [{"name": "林照", "skills_used": ["FUTURE_SKILL_999"]}],
                }
            ],
            "character_moves": [
                {"name": "林照", "equipment_used": ["FUTURE_EQUIPMENT_999"]}
            ],
        }
    )
    assert [item.character_name for item in contexts] == ["林照"]
    assert contexts[0].location == "黑风城"
    assert contexts[0].skills_used == ["FUTURE_SKILL_999"]
    assert contexts[0].equipment_used == ["FUTURE_EQUIPMENT_999"]


def test_legacy_move_normalizer_keeps_structured_gate_fields() -> None:
    from packages.story_core.orchestrator import _normalize_moves

    moves = _normalize_moves(
        [
            {
                "name": "林照",
                "action": "执行计划",
                "location": "FUTURE_LOCATION_999",
                "skills_used": ["FUTURE_SKILL_999"],
                "equipment_used": ["FUTURE_EQUIPMENT_999"],
                "knowledge_fact_ids": ["future-secret"],
                "relationship_expectations": [
                    {"target": "顾闻舟", "trust_min": 70}
                ],
            }
        ],
        require_action=True,
    )

    gate = evaluate_generation_consistency(
        _story(), {"character_moves": moves}, target_chapter=20
    )

    assert {item.code for item in gate.warnings} == {
        "LOCATION_MISMATCH",
        "SKILL_NOT_YET_ACQUIRED",
        "KNOWLEDGE_NOT_YET_LEARNED",
        "EQUIPMENT_NOT_OWNED",
        "RELATIONSHIP_STATE_MISMATCH",
    }


def test_gate_aggregates_multi_character_findings_and_policy() -> None:
    gate = evaluate_generation_consistency(_story(), _plan(), target_chapter=20)

    assert isinstance(gate, GenerationConsistencyGate)
    assert gate.status == "blocking"
    assert gate.checked_at_boundary == 19
    assert gate.checked_characters == ["林照", "顾闻舟"]
    assert {item.code for item in gate.warnings} == {
        "LOCATION_MISMATCH",
        "SKILL_NOT_YET_ACQUIRED",
        "KNOWLEDGE_NOT_YET_LEARNED",
        "EQUIPMENT_NOT_OWNED",
        "RELATIONSHIP_STATE_MISMATCH",
    }
    assert all(
        item.severity == ("error" if item.code in {
            "SKILL_NOT_YET_ACQUIRED",
            "KNOWLEDGE_NOT_YET_LEARNED",
            "EQUIPMENT_NOT_OWNED",
        } else "warning")
        for item in gate.warnings
    )
    assert all(item.character_name == "林照" for item in gate.warnings)


def test_require_gate_stops_before_writer_and_override_preserves_findings() -> None:
    with pytest.raises(ConsistencyGateRequired) as captured:
        require_generation_consistency(_story(), _plan(), target_chapter=20)

    gate = captured.value.gate
    assert gate.status == "blocking"
    overridden = require_generation_consistency(
        _story(), _plan(), target_chapter=20, override=True
    )
    assert overridden.status == "blocking"
    assert overridden.override_applied is True
    assert overridden.warnings == gate.warnings


def test_clean_plan_and_unknown_history_are_not_blocking() -> None:
    clean = evaluate_generation_consistency(
        _story(),
        {"character_moves": [{"name": "林照"}]},
        target_chapter=20,
    )
    assert clean.status == "clear"
    assert clean.warnings == []

    unknown = evaluate_generation_consistency(
        _story(),
        {"character_moves": [{"name": "新角色", "skills_used": ["FUTURE_SKILL_999"]}]},
        target_chapter=20,
    )
    assert unknown.status == "clear"
    assert unknown.checked_characters == []


def test_rewrite_boundary_and_chapter_one_do_not_leak_latest_mirrors() -> None:
    story = _story()
    before = deepcopy(story)
    rewrite = evaluate_generation_consistency(
        story,
        {"character_moves": [{"name": "林照", "location": "秘境二层"}]},
        target_chapter=120,
    )
    assert rewrite.status == "clear"
    assert rewrite.checked_at_boundary == 119
    assert all("FUTURE_" not in str(item.observed) for item in rewrite.warnings)

    first = evaluate_generation_consistency(
        story,
        {"character_moves": [{"name": "林照", "location": "FUTURE_LOCATION_999"}]},
        target_chapter=1,
    )
    assert first.status == "clear"
    assert first.checked_at_boundary == 0
    assert story == before


def test_modular_blocking_gate_is_a_writer_call_sentinel(monkeypatch) -> None:
    artifact = DirectorArtifact(
        chapter_number=20,
        chapter_goal="追查旧案",
        opening_state="夜色",
        scene_beats=[],
        ending_state="留下线索",
        entity_requirements=[
            EntityRequirement(kind="character", name="林照"),
            EntityRequirement(kind="technique", name="FUTURE_SKILL_999")
        ],
    )
    source = _story()
    before = deepcopy(source)
    writer_calls: list[object] = []

    monkeypatch.setattr(
        pipeline_module,
        "plan_director_artifact",
        lambda **_kwargs: SimpleNamespace(artifact=artifact, trace_id="director-test"),
    )

    def writer_sentinel(**_kwargs):
        writer_calls.append(_kwargs)
        raise AssertionError("Writer must not run before a blocking gate is overridden")

    monkeypatch.setattr(pipeline_module, "run_writer", writer_sentinel)

    with pytest.raises(ConsistencyGateRequired) as captured:
        pipeline_module.run_modular_pipeline(
            project_root=source,
            chapter_number=20,
            consistency_source=source,
        )

    assert captured.value.gate.status == "blocking"
    assert any(item.code == "SKILL_NOT_YET_ACQUIRED" for item in captured.value.gate.warnings)
    assert writer_calls == []
    assert source == before


def test_modular_gate_override_reaches_writer_and_keeps_gate_result(monkeypatch) -> None:
    artifact = DirectorArtifact(
        chapter_number=20,
        chapter_goal="追查旧案",
        opening_state="夜色",
        scene_beats=[],
        ending_state="留下线索",
        entity_requirements=[
            EntityRequirement(kind="character", name="林照"),
            EntityRequirement(kind="technique", name="FUTURE_SKILL_999")
        ],
    )
    writer_calls: list[object] = []

    monkeypatch.setattr(
        pipeline_module,
        "plan_director_artifact",
        lambda **_kwargs: SimpleNamespace(artifact=artifact, trace_id="director-test"),
    )

    def writer_stub(**kwargs):
        writer_calls.append(kwargs)
        return SimpleNamespace(
            body="林照在夜色中停下脚步。",
            context=SimpleNamespace(
                continuity_facts=[],
                character_cards=[],
                entity_cards=[],
            ),
            director_artifact=artifact,
            canon_preflight={},
            consistency_findings=[],
            trace_id="writer-test",
        )

    monkeypatch.setattr(pipeline_module, "run_writer", writer_stub)

    result = pipeline_module.run_modular_pipeline(
        project_root=_story(),
        chapter_number=20,
        consistency_source=_story(),
        consistency_override=True,
        fact_extractor=SimpleNamespace(
            extract=lambda _context: ContinuityDelta(chapter_number=20)
        ),
    )

    assert len(writer_calls) == 1
    assert result.consistency_gate is not None
    assert result.consistency_gate.status == "blocking"
    assert result.consistency_gate.override_applied is True
