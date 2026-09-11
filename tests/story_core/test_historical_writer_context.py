from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from packages.story_core.agents.contracts import DirectorArtifact
from packages.story_core.agents.pipeline import _build_writer_request
from packages.story_core.context.writer_context import build_writer_context
from packages.story_core.agents.writer.prompt import build_writer_prompt
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator
from packages.story_core.writer_character_context import historical_writer_character_cards


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _artifact(chapter_number: int) -> DirectorArtifact:
    return DirectorArtifact(
        chapter_number=chapter_number,
        chapter_title=f"第{chapter_number}章",
        chapter_goal="沿着线索继续查证",
        opening_state="夜色",
        scene_beats=[],
        ending_state="线索暂时收束",
        entity_requirements=[],
    )


def _state() -> dict:
    return {
        "story_id": "writer-history-test",
        "outline": "",
        "genre": "网游",
        "style": "克制",
        "characters": [
            {
                "name": "林照",
                "role": "protagonist",
                "character_tier": "protagonist",
                "core_motivation": "查清旧案",
                "story_drive": {
                    "motivation": "查清旧案",
                    "long_term_goal": "找到真相",
                    "immediate_goal": "FUTURE_GOAL_999",
                },
                "current_life_profile": {
                    "immediate_problem": "FUTURE_PROBLEM_999",
                },
                "current_state": {
                    "current": {"location": "FUTURE_LOCATION_999"},
                    "recent_changes": [
                        {"chapter": 30, "current": {"location": "FUTURE_LOCATION_999"}},
                        {"chapter": 10, "current": {"location": "PAST_LOCATION_010"}},
                    ],
                },
                "real_state": {
                    "current": {"location": "FUTURE_REALITY_999"},
                    "recent_changes": [
                        {"chapter": 10, "current": {"location": "PAST_REALITY_010"}},
                    ],
                },
                "game_state": {
                    "current": {"level": 99, "skills": ["FUTURE_SKILL_999"]},
                    "recent_changes": [
                        {"chapter": 25, "current": {"level": 25, "skills": ["FUTURE_SKILL_999"]}},
                        {"chapter": 10, "current": {"level": 10, "skills": ["旧技能"]}},
                    ],
                },
            }
        ],
        "relationship_graph": [
            {
                "id": "rel-future",
                "source": "林照",
                "target": "顾闻舟",
                "first_chapter": 10,
                "source_knowledge": ["FUTURE_RELATION_KNOWLEDGE_080"],
                "current_state": "FUTURE_RELATION_999",
                "trust": 99,
                "tension": 1,
                "changes": [
                    {"chapter_number": 30, "trust": 99, "tension": 1},
                    {"chapter_number": 10, "trust": 20, "tension": 70},
                ],
            }
        ],
        "progression_ledger": {
            "protagonist": {
                "level": 99,
                "skills": ["FUTURE_SKILL_999"],
                "history": [
                    {"chapter": 25, "current": {"level": 25, "skills": ["FUTURE_SKILL_999"]}},
                    {"chapter": 10, "current": {"level": 10, "skills": ["旧技能"]}},
                ],
            }
        },
        "equipment_cards": [
            {
                "id": "historical-equipment",
                "name": "HISTORICAL_EQUIPMENT_010",
                "equipment_type": "weapon",
                "first_appearance_chapter": 10,
                "last_update_chapter": 30,
                "current_owner": "顾闻舟",
                "history": [
                    {"chapter": 30, "current_owner": "顾闻舟"},
                    {"chapter": 10, "current_owner": "林照"},
                ],
            },
            {
                "id": "future-equipment",
                "name": "FUTURE_EQUIPMENT_999",
                "equipment_type": "weapon",
                "first_appearance_chapter": 25,
                "last_update_chapter": 30,
                "current_owner": "林照",
                "history": [{"chapter": 25, "current_owner": "林照"}],
            },
        ],
        "knowledge_ledger": [
            {
                "fact_id": "future-secret",
                "fact": "FUTURE_SECRET_999",
                "learned_chapter": 40,
                "known_by": ["林照"],
                "source": "chapter:40",
                "visibility": "private",
            }
        ],
    }


def test_canonical_writer_context_uses_target_minus_one_and_scrubs_future_sentinels(
    tmp_path: Path,
) -> None:
    system_root = tmp_path / ".story-system"
    state = _state()
    _write_json(system_root / "state.json", state)
    _write_json(system_root / "project.json", {"title": "历史边界测试", "genre": "网游"})
    _write_json(system_root / "characters" / "lin.json", state["characters"][0])

    context = build_writer_context(
        project=tmp_path,
        chapter_number=20,
        director_artifact=_artifact(20),
    )
    request = _build_writer_request(context=context, director_artifact=_artifact(20))
    serialized = json.dumps(request.model_dump(mode="json"), ensure_ascii=False)
    prompt = build_writer_prompt(request)

    card = context.character_cards[0]
    assert card["historical_state"]["as_of_chapter"] == 19
    assert card["historical_state"]["current_state"] == {"location": "PAST_LOCATION_010"}
    assert card["historical_state"]["game_state"] == {"level": 10, "skills": ["旧技能"]}
    assert card["relationships"][0]["trust"] == 20
    assert card["knowledge"] == []
    assert card["equipment"] == [
        {
            "id": "historical-equipment",
            "name": "HISTORICAL_EQUIPMENT_010",
            "equipment_type": "weapon",
            "first_appearance_chapter": 10,
            "current_owner": "林照",
        }
    ]
    assert "PAST_LOCATION_010" in prompt
    assert "HISTORICAL_EQUIPMENT_010" in prompt
    assert '"trust":20' in prompt
    for sentinel in (
        "FUTURE_LOCATION_999",
        "FUTURE_REALITY_999",
        "FUTURE_GOAL_999",
        "FUTURE_PROBLEM_999",
        "FUTURE_SECRET_999",
        "FUTURE_SKILL_999",
        "FUTURE_EQUIPMENT_999",
        "FUTURE_RELATION_999",
        "FUTURE_RELATION_KNOWLEDGE_080",
    ):
        assert sentinel not in serialized
        assert sentinel not in prompt


def test_chapter_one_writer_context_does_not_read_chapter_one_end_state(tmp_path: Path) -> None:
    system_root = tmp_path / ".story-system"
    state = _state()
    _write_json(system_root / "state.json", state)
    _write_json(system_root / "project.json", {"title": "第一章边界", "genre": "网游"})
    _write_json(system_root / "characters" / "lin.json", state["characters"][0])
    _write_json(system_root / "chapters" / "0001.json", {"tail": "FUTURE_CHAPTER_ONE_END_999"})

    context = build_writer_context(
        project=tmp_path,
        chapter_number=1,
        director_artifact=_artifact(1),
    )

    assert context.previous_tail == ""
    assert context.character_cards[0]["historical_state"]["as_of_chapter"] == 0
    assert "FUTURE_LOCATION_999" not in json.dumps(context.model_dump(mode="json"), ensure_ascii=False)


def test_chapter_one_writer_context_ignores_undated_latest_state_mirrors(
    tmp_path: Path,
) -> None:
    system_root = tmp_path / ".story-system"
    state = _state()
    character = state["characters"][0]
    character["current_state"] = {
        "current": {"location": "FUTURE_LOCATION_300"},
        "recent_changes": [],
    }
    character["real_state"] = {
        "current": {"location": "FUTURE_REALITY_300"},
        "recent_changes": [],
    }
    character["game_state"] = {
        "current": {"level": 99},
        "recent_changes": [],
    }
    _write_json(system_root / "state.json", state)
    _write_json(system_root / "project.json", {"title": "无日期镜像", "genre": "网游"})
    _write_json(system_root / "characters" / "lin.json", character)

    context = build_writer_context(
        project=tmp_path,
        chapter_number=1,
        director_artifact=_artifact(1),
    )
    request = _build_writer_request(context=context, director_artifact=_artifact(1))
    serialized = json.dumps(request.model_dump(mode="json"), ensure_ascii=False)
    prompt = build_writer_prompt(request)

    card = context.character_cards[0]
    assert card["historical_state"]["current_state"] == {}
    assert card["historical_state"]["real_state"] == {}
    assert card["historical_state"]["game_state"] == {}
    for sentinel in (
        "FUTURE_LOCATION_300",
        "FUTURE_REALITY_300",
        '"level":99',
    ):
        assert sentinel not in serialized
        assert sentinel not in prompt


def test_chapter_one_writer_context_accepts_explicit_chapter_zero_baseline() -> None:
    state = _state()
    character = state["characters"][0]
    character["current_state"] = {
        "baseline": {"location": "INITIAL_VILLAGE"},
        "current": {"location": "FUTURE_LOCATION_300"},
        "recent_changes": [],
    }

    card = historical_writer_character_cards(
        state,
        as_of_chapter=0,
        is_game_story=True,
    )[0]

    assert card["historical_state"]["current_state"] == {
        "location": "INITIAL_VILLAGE"
    }
    assert "FUTURE_LOCATION_300" not in json.dumps(card, ensure_ascii=False)


def test_writer_context_omits_undated_relationship_knowledge_at_chapter_21(
    tmp_path: Path,
) -> None:
    system_root = tmp_path / ".story-system"
    state = _state()
    _write_json(system_root / "state.json", state)
    _write_json(system_root / "project.json", {"title": "关系知识边界", "genre": "网游"})
    _write_json(system_root / "characters" / "lin.json", state["characters"][0])

    context = build_writer_context(
        project=tmp_path,
        chapter_number=21,
        director_artifact=_artifact(21),
    )
    request = _build_writer_request(context=context, director_artifact=_artifact(21))
    serialized = json.dumps(request.model_dump(mode="json"), ensure_ascii=False)
    prompt = build_writer_prompt(request)

    assert "FUTURE_RELATION_KNOWLEDGE_080" not in serialized
    assert "FUTURE_RELATION_KNOWLEDGE_080" not in prompt


def test_legacy_orchestrator_writer_context_is_historical_for_rewrites() -> None:
    story = StoryState.model_validate(_state())
    plan = {
        "character_moves": [{"name": "林照", "action": "继续查证"}],
        "scene_cards": [{"line": "game", "location": "副本入口", "purpose": "查证"}],
    }

    context = StoryOrchestrator()._build_writer_context(story, 20, plan)
    serialized_context = json.dumps(context.character_context, ensure_ascii=False)
    prompt = StoryOrchestrator()._body_prompt(story, 20, plan)

    assert context.character_context["cards"][0]["historical_state"]["as_of_chapter"] == 19
    assert "PAST_LOCATION_010" in serialized_context
    for sentinel in (
        "FUTURE_LOCATION_999",
        "FUTURE_REALITY_999",
        "FUTURE_GOAL_999",
        "FUTURE_PROBLEM_999",
        "FUTURE_SECRET_999",
        "FUTURE_SKILL_999",
        "FUTURE_RELATION_999",
    ):
        assert sentinel not in serialized_context
        assert sentinel not in prompt


def test_historical_writer_cards_do_not_mutate_latest_state() -> None:
    state = _state()
    before = deepcopy(state)

    historical_writer_character_cards(state, as_of_chapter=19, is_game_story=True)

    assert state == before


def test_writer_boundary_excludes_same_chapter_skill_and_secret() -> None:
    before_skill = historical_writer_character_cards(
        _state(), as_of_chapter=24, is_game_story=True
    )[0]
    at_skill = historical_writer_character_cards(
        _state(), as_of_chapter=25, is_game_story=True
    )[0]

    assert "FUTURE_SKILL_999" not in json.dumps(before_skill, ensure_ascii=False)
    assert "FUTURE_EQUIPMENT_999" not in json.dumps(before_skill, ensure_ascii=False)
    assert "FUTURE_SKILL_999" in json.dumps(at_skill, ensure_ascii=False)
    assert "FUTURE_EQUIPMENT_999" in json.dumps(at_skill, ensure_ascii=False)

    before_secret = historical_writer_character_cards(_state(), as_of_chapter=39)[0]
    at_secret = historical_writer_character_cards(_state(), as_of_chapter=40)[0]
    assert before_secret["knowledge"] == []
    assert [item["fact_id"] for item in at_secret["knowledge"]] == ["future-secret"]
