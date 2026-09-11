from copy import deepcopy

import pytest

from packages.story_core.character_inspection import (
    CharacterTimelineEvent,
    check_character_consistency,
    get_character_timeline,
)


def _story() -> dict:
    return {
        "story_id": "character-inspection-test",
        "outline": "林照追查旧案。",
        "genre": "网游",
        "style": "克制",
        "current_chapter": 50,
        "characters": [
            {
                "name": "林照",
                "role": "protagonist",
                "current_state": {
                    "current": {
                        "location": "FUTURE_LOCATION_999",
                        "emotion": "FUTURE_EMOTION_999",
                    },
                    "history": [
                        {"chapter": 20, "current": {"location": "黑风城"}},
                        {"chapter": 10, "current": {"location": "青云城", "emotion": "平静"}},
                    ],
                },
            },
            {
                "name": "顾闻舟",
                "role": "supporting",
                "current_state": {
                    "current": {"location": "北岸"},
                    "history": [{"chapter": 10, "current": {"location": "北岸"}}],
                },
            },
        ],
        "progression_ledger": {
            "protagonist": {
                "level": "Lv.99",
                "skills": ["FUTURE_SKILL_999"],
                "history": [
                    {"chapter": 25, "current": {"level": "Lv.11", "skills": ["御剑术"]}},
                    {"chapter": 12, "current": {"level": "Lv.10"}},
                ],
            },
            "characters": {
                "顾闻舟": {
                    "history": [{"chapter": 12, "skill": "顾闻舟专属术"}],
                }
            },
        },
        "equipment_cards": [
            {
                "id": "black-sword",
                "name": "玄铁剑",
                "equipment_type": "weapon",
                "first_appearance_chapter": 10,
                "last_update_chapter": 20,
                "current_owner": "林照",
                "history": [
                    {"chapter": 20, "current_owner": "林照"},
                    {"chapter": 10, "current_owner": "顾闻舟"},
                ],
            },
            {
                "id": "future-relic",
                "name": "FUTURE_EQUIPMENT_999",
                "equipment_type": "accessory",
                "first_appearance_chapter": 40,
                "last_update_chapter": 40,
                "current_owner": "林照",
                "history": [{"chapter": 40, "current_owner": "林照"}],
            },
        ],
        "knowledge_ledger": [
            {
                "fact_id": "secret-owner",
                "fact": "黑戒指真正主人是苏玄",
                "learned_chapter": 30,
                "known_by": ["林照"],
                "visibility": "private",
            },
            {
                "fact_id": "wrong-route",
                "fact": "旧路线在第20章失效",
                "learned_chapter": 10,
                "invalidated_chapter": 20,
                "known_by": ["林照"],
                "visibility": "private",
            },
            {
                "fact_id": "gu-secret",
                "fact": "顾闻舟的私密线索",
                "learned_chapter": 12,
                "known_by": ["顾闻舟"],
                "visibility": "private",
            },
            {
                "fact_id": "future-secret",
                "fact": "FUTURE_KNOWLEDGE_999",
                "learned_chapter": 40,
                "known_by": ["林照"],
                "visibility": "private",
            },
        ],
        "relationship_graph": [
            {
                "id": "rel-lin-gu",
                "source": "林照",
                "target": "顾闻舟",
                "first_chapter": 10,
                "last_changed_chapter": 30,
                "trust": 90,
                "changes": [
                    {"chapter_number": 30, "trust": 80, "summary": "共同承担风险"},
                    {"chapter_number": 10, "trust": 20, "summary": "初次合作"},
                    {"chapter_number": 40, "current_state": "FUTURE_RELATION_999"},
                ],
            }
        ],
        "memory_index": [
            {"chapter_number": 10, "characters": ["林照"], "summary": "明确出场"},
            {"chapter_number": 11, "characters": ["顾闻舟"], "summary": "顾闻舟出场"},
            {"chapter_number": 12, "characters": ["陌生人"], "summary": "没有林照名字"},
        ],
    }


def _events(story: dict, character: str = "林照", **kwargs) -> list[CharacterTimelineEvent]:
    return get_character_timeline(story, character, **kwargs)


def test_timeline_replays_state_progression_equipment_knowledge_relationship_and_appearance() -> None:
    events = _events(_story())

    assert all(isinstance(item, CharacterTimelineEvent) for item in events)
    assert [item.chapter_number for item in events] == sorted(item.chapter_number for item in events)

    location = [item for item in events if item.category == "location"]
    assert [(item.chapter_number, item.before, item.after) for item in location] == [
        (10, None, "青云城"),
        (20, "青云城", "黑风城"),
    ]

    levels = [item for item in events if item.category == "progression"]
    assert any(item.chapter_number == 12 and item.after == "Lv.10" for item in levels)
    assert any(item.chapter_number == 25 and item.before == "Lv.10" and item.after == "Lv.11" for item in levels)

    skills = [item for item in events if item.category == "skill"]
    assert [(item.chapter_number, item.after) for item in skills] == [(25, "御剑术")]

    equipment = [item for item in events if item.category == "equipment"]
    assert any(item.chapter_number == 20 and item.title == "获得装备" and item.after == "玄铁剑" for item in equipment)

    knowledge = [item for item in events if item.category == "knowledge"]
    assert [(item.chapter_number, item.title, item.metadata["fact_id"]) for item in knowledge] == [
        (10, "得知信息", "wrong-route"),
        (20, "知识失效", "wrong-route"),
        (30, "得知信息", "secret-owner"),
        (40, "得知信息", "future-secret"),
    ]

    relationship = [item for item in events if item.category == "relationship" and item.metadata.get("field") == "trust"]
    assert [(item.chapter_number, item.before, item.after) for item in relationship] == [
        (10, None, 20),
        (30, 20, 80),
    ]

    appearance = [item for item in events if item.category == "appearance"]
    assert [(item.chapter_number, item.title) for item in appearance] == [(10, "首次出场")]


def test_timeline_end_range_excludes_future_and_does_not_use_latest_sentinels() -> None:
    events = _events(_story(), end_chapter=20)

    assert events
    assert max(item.chapter_number for item in events) <= 20
    serialized = str([item.model_dump(mode="json") for item in events])
    assert "FUTURE_LOCATION_999" not in serialized
    assert "FUTURE_SKILL_999" not in serialized
    assert "FUTURE_EQUIPMENT_999" not in serialized
    assert "FUTURE_KNOWLEDGE_999" not in serialized
    assert "FUTURE_EMOTION_999" not in serialized
    assert "FUTURE_RELATION_999" not in serialized


def test_timeline_equipment_loss_is_character_scoped_and_private_knowledge_isolated() -> None:
    story = _story()
    lin_events = _events(story, "林照")
    gu_events = _events(story, "顾闻舟")

    assert any(item.title == "失去装备" and item.before == "玄铁剑" for item in gu_events)
    assert any(item.after == "玄铁剑" and item.title == "获得装备" for item in gu_events)
    assert not any(item.metadata.get("fact_id") in {"secret-owner", "future-secret"} for item in gu_events)
    assert any(item.metadata.get("fact_id") == "gu-secret" for item in gu_events)
    assert not any(item.after == "顾闻舟专属术" for item in lin_events)


def test_timeline_is_deterministic_and_does_not_mutate_story_state() -> None:
    story = _story()
    before = deepcopy(story)

    first = [item.model_dump(mode="json") for item in _events(story)]
    second = [item.model_dump(mode="json") for item in _events(deepcopy(story))]

    assert first == second
    assert story == before


def test_timeline_uses_explicit_memory_character_names_only_for_appearance() -> None:
    story = _story()
    story["memory_index"] = [{"chapter_number": 8, "summary": "林照似乎更警惕"}]

    assert not any(item.category == "appearance" for item in _events(story))


def test_timeline_rejects_invalid_ranges_and_unknown_characters() -> None:
    with pytest.raises(ValueError, match="chapter"):
        _events(_story(), start_chapter=20, end_chapter=10)
    with pytest.raises(KeyError, match="character_not_found"):
        _events(_story(), "不存在")


def test_consistency_uses_start_of_target_chapter_boundary_and_structured_context_only() -> None:
    story = _story()
    context = {
        "character_name": "林照",
        "location": "黑风城",
        "skills_used": ["御剑术"],
        "equipment_used": ["玄铁剑"],
        "knowledge_fact_ids": ["secret-owner"],
        "relationship_expectations": [{"target": "顾闻舟", "trust_min": 70}],
    }

    warnings = check_character_consistency(
        story,
        "林照",
        target_chapter=20,
        planned_context=context,
    )
    assert {item.code for item in warnings} == {
        "LOCATION_MISMATCH",
        "SKILL_NOT_YET_ACQUIRED",
        "KNOWLEDGE_NOT_YET_LEARNED",
        "EQUIPMENT_NOT_OWNED",
        "RELATIONSHIP_STATE_MISMATCH",
    }
    assert all(item.target_chapter == 20 for item in warnings)
    assert all(item.evidence for item in warnings)
    assert any(item.code == "SKILL_NOT_YET_ACQUIRED" and item.observed == {"acquired_chapter": 25} for item in warnings)

    at_26 = check_character_consistency(
        story,
        "林照",
        target_chapter=26,
        planned_context={"skills_used": ["御剑术"]},
    )
    assert not any(item.code == "SKILL_NOT_YET_ACQUIRED" for item in at_26)


def test_consistency_detects_wrong_historical_equipment_owner_without_latest_leakage() -> None:
    warnings = check_character_consistency(
        _story(),
        "林照",
        target_chapter=15,
        planned_context={"equipment_used": ["玄铁剑"]},
    )

    equipment_warnings = [item for item in warnings if item.code == "EQUIPMENT_NOT_OWNED"]
    assert len(equipment_warnings) == 1
    assert equipment_warnings[0].observed == {"owner": "顾闻舟", "chapter": 10}


def test_consistency_does_not_warn_for_unknown_values_or_other_character_facts() -> None:
    story = _story()
    unknown = check_character_consistency(
        story,
        "林照",
        target_chapter=1,
        planned_context={
            "location": "FUTURE_LOCATION_999",
            "skills_used": ["FUTURE_SKILL_999", "顾闻舟专属术"],
            "equipment_used": ["FUTURE_EQUIPMENT_999"],
            "relationship_expectations": [{"target": "顾闻舟", "trust_min": 70}],
        },
    )

    assert unknown == []
    assert "FUTURE_LOCATION_999" not in str(unknown)
    assert "FUTURE_SKILL_999" not in str(unknown)
    assert "FUTURE_EQUIPMENT_999" not in str(unknown)
    assert "FUTURE_KNOWLEDGE_999" not in str(unknown)


def test_consistency_is_character_scoped_and_does_not_use_latest_relationship_score() -> None:
    story = _story()
    warnings = check_character_consistency(
        story,
        "林照",
        target_chapter=15,
        planned_context={"relationship_expectations": [{"target": "顾闻舟", "trust_min": 70}]},
    )

    assert [item.code for item in warnings] == ["RELATIONSHIP_STATE_MISMATCH"]
    assert warnings[0].observed == 20


def test_timeline_does_not_attribute_unscoped_global_progression_to_supporting_roles() -> None:
    story = _story()
    story["progression_ledger"]["events"] = [
        {"chapter": 6, "skills": ["FUTURE_GLOBAL_SKILL_999"]},
        {"chapter": 7, "character_name": "顾闻舟", "skill": "顾闻舟全局技能"},
    ]

    protagonist_events = _events(story, "林照")
    supporting_events = _events(story, "顾闻舟")

    assert any(item.after == "FUTURE_GLOBAL_SKILL_999" for item in protagonist_events)
    assert not any(item.after == "FUTURE_GLOBAL_SKILL_999" for item in supporting_events)
    assert any(item.after == "顾闻舟全局技能" for item in supporting_events)


def test_consistency_validates_target_and_plan_character() -> None:
    with pytest.raises(ValueError, match="target_chapter"):
        check_character_consistency(_story(), "林照", target_chapter=0, planned_context={})
    with pytest.raises(ValueError, match="character"):
        check_character_consistency(
            _story(),
            "林照",
            target_chapter=2,
            planned_context={"character_name": "顾闻舟"},
        )
