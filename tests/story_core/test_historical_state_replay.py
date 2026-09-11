from __future__ import annotations

from copy import deepcopy

import pytest

from packages.story_core.historical_state_replay import (
    HistoricalCharacterState,
    get_character_state,
)
from packages.story_core.models import StoryState


def _story() -> dict:
    return {
        "story_id": "replay-test",
        "characters": [
            {
                "name": "林照",
                "role": "protagonist",
                "character_tier": "core",
                "story_function": "揭开黑戒指真相",
                "current_emotion": "未来情绪",
                "location": "未来地点",
                "goals": ["未来目标"],
                "current_state": {
                    "current": {
                        "location": "未来地点",
                        "emotion": "未来情绪",
                    },
                    "recent_changes": [
                        {
                            "chapter": 30,
                            "current": {"location": "终局城"},
                            "fact": "未来位置",
                        },
                        {
                            "chapter": 20,
                            "current": {"location": "乙地"},
                            "fact": "位置移动",
                        },
                        {
                            "chapter": 10,
                            "current": {"location": "甲地", "emotion": "警惕"},
                            "fact": "抵达甲地",
                        },
                    ],
                },
                "real_state": {
                    "current": {"location": "未来现实地点", "emotion": "未来现实情绪"},
                    "recent_changes": [
                        {"chapter": 20, "current": {"location": "公司"}},
                        {"chapter": 10, "current": {"location": "家中", "emotion": "疲惫"}},
                        {"chapter": 30, "current": {"location": "医院"}},
                    ],
                },
                "game_state": {
                    "current": {"location": "未来副本", "level": 99},
                    "recent_changes": [
                        {"chapter": 30, "current": {"location": "终焉副本", "level": 99}},
                        {"chapter": 20, "current": {"location": "黑石城", "level": 31}},
                        {"chapter": 10, "current": {"location": "新手村", "level": 12}},
                    ],
                },
                "game_panel": {"level": 99, "updated_chapter": 30},
            }
        ],
        "relationship_graph": [
            {
                "id": "rel-lin-mo",
                "source": "林照",
                "target": "墨离",
                "first_chapter": 10,
                "last_changed_chapter": 30,
                "current_state": "未来关系",
                "trust": 99,
                "tension": 88,
                "changes": [
                    {"chapter_number": 30, "trust": 99, "tension": 88, "summary": "未来关系"},
                    {"chapter_number": 25, "trust": 50, "tension": 20, "summary": "暂时合作"},
                    {"chapter_number": 10, "trust": 20, "tension": 70, "summary": "初次相遇"},
                ],
            }
        ],
        "progression_ledger": {
            "protagonist": {
                "level": 99,
                "skills": ["终焉技"],
                "history": [
                    {"chapter": 30, "current": {"level": 99, "skills": ["终焉技"]}},
                    {"chapter": 20, "current": {"level": 31, "skills": ["破阵术"]}},
                    {"chapter": 10, "current": {"level": 12, "skills": ["火球术"]}},
                ],
            }
        },
        "equipment_cards": [
            {
                "id": "black-ring",
                "name": "黑戒指",
                "equipment_type": "accessory",
                "first_appearance_chapter": 10,
                "last_update_chapter": 30,
                "current_owner": "未来持有者",
                "current_location": "终焉副本",
                "status": "已觉醒",
                "history": [
                    {
                        "chapter": 30,
                        "current": {
                            "current_owner": "未来持有者",
                            "current_location": "终焉副本",
                            "status": "已觉醒",
                        },
                    },
                    {
                        "chapter": 10,
                        "current": {
                            "current_owner": "林照",
                            "current_location": "甲地",
                            "status": "沉寂",
                        },
                    },
                ],
            }
        ],
    }


def test_replays_each_state_namespace_by_chapter_without_future_leakage() -> None:
    result = get_character_state(_story(), "林照", as_of_chapter=15)

    assert isinstance(result, HistoricalCharacterState)
    assert result.as_of_chapter == 15
    assert result.current_state == {"location": "甲地", "emotion": "警惕"}
    assert result.real_state == {"location": "家中", "emotion": "疲惫"}
    assert result.game_state == {"location": "新手村", "level": 12}
    assert result.current_emotion == "警惕"
    assert result.location == "甲地"
    assert result.relationships[0]["trust"] == 20
    assert result.relationships[0]["tension"] == 70
    assert result.progression == {"level": 12, "skills": ["火球术"]}
    assert result.evidence["current_state.location"] == {
        "value": "甲地",
        "chapter": 10,
        "source": "character.current_state.recent_changes",
    }
    assert "终局城" not in result.to_dict().__str__()


def test_replays_unsorted_events_and_uses_latest_event_per_field() -> None:
    result = get_character_state(_story(), "林照", as_of_chapter=25)

    assert result.current_state == {"location": "乙地", "emotion": "警惕"}
    assert result.real_state == {"location": "公司", "emotion": "疲惫"}
    assert result.game_state == {"location": "黑石城", "level": 31}
    assert result.current_state["location"] == "乙地"


def test_relationship_progression_and_equipment_are_historical() -> None:
    result = get_character_state(_story(), "林照", as_of_chapter=20)

    assert result.relationships == [
        {
            "id": "rel-lin-mo",
            "source": "林照",
            "target": "墨离",
            "trust": 20,
            "tension": 70,
            "evidence": {
                "trust": {"value": 20, "chapter": 10, "source": "relationship_graph.changes"},
                "tension": {"value": 70, "chapter": 10, "source": "relationship_graph.changes"},
            },
        }
    ]
    assert result.progression == {"level": 31, "skills": ["破阵术"]}
    assert result.equipment == [
        {
            "id": "black-ring",
            "name": "黑戒指",
            "equipment_type": "accessory",
            "first_appearance_chapter": 10,
            "current_owner": "林照",
            "current_location": "甲地",
            "status": "沉寂",
        }
    ]


def test_latest_only_values_stay_unknown_when_no_historical_event_exists() -> None:
    story = _story()
    character = story["characters"][0]
    character["current_state"] = {"current": {"location": "未来地点"}, "recent_changes": []}
    character["real_state"] = {"current": {"location": "未来现实地点"}, "recent_changes": []}
    character["game_state"] = {"current": {"level": 99}, "recent_changes": []}
    story["progression_ledger"]["protagonist"] = {"level": 99}
    story["equipment_cards"][0].pop("history")

    result = get_character_state(story, "林照", as_of_chapter=15)

    assert result.current_state == {}
    assert result.real_state == {}
    assert result.game_state == {}
    assert result.progression == {}
    assert result.equipment == [
        {
            "id": "black-ring",
            "name": "黑戒指",
            "equipment_type": "accessory",
            "first_appearance_chapter": 10,
        }
    ]
    assert "current_state.location" in result.unknown_fields
    assert "real_state.location" in result.unknown_fields
    assert "game_state.level" in result.unknown_fields


def test_stable_profile_is_current_and_not_rolled_back() -> None:
    result = get_character_state(_story(), "林照", as_of_chapter=10)

    assert result.profile["role"] == "protagonist"
    assert result.profile["importance"] == "core"
    assert result.profile["narrative_function"] == "揭开黑戒指真相"


def test_accepts_story_state_model_and_does_not_mutate_it() -> None:
    raw = _story()
    raw.update({"outline": "", "genre": "网游", "style": "克制"})
    state = StoryState.model_validate(raw)
    before = state.model_dump(mode="python")

    result = get_character_state(state, "林照", as_of_chapter=15)

    assert result.game_state["level"] == 12
    assert state.model_dump(mode="python") == before


def test_same_chapter_order_is_deterministic_and_validation_is_explicit() -> None:
    story = _story()
    story["characters"][0]["current_state"]["recent_changes"] = [
        {"chapter": 10, "current": {"location": "先写入"}},
        {"chapter": 10, "current": {"location": "后写入"}},
    ]

    first = get_character_state(story, "林照", as_of_chapter=10)
    second = get_character_state(deepcopy(story), "林照", as_of_chapter=10)

    assert first.to_dict() == second.to_dict()
    assert first.current_state["location"] == "后写入"
    with pytest.raises(ValueError, match="as_of_chapter"):
        get_character_state(story, "林照", as_of_chapter=0)
    with pytest.raises(KeyError, match="character_not_found"):
        get_character_state(story, "不存在", as_of_chapter=10)
