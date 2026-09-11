from __future__ import annotations

import pytest

from packages.story_core.knowledge_ledger import (
    apply_knowledge_updates,
    get_character_knowledge,
)
from packages.story_core.memory import apply_post_chapter_updates
from packages.story_core.models import StoryState


def _story() -> dict:
    return {
        "story_id": "knowledge-test",
        "outline": "",
        "genre": "",
        "style": "",
        "characters": [
            {"name": "林照", "role": "protagonist"},
            {"name": "顾闻舟", "role": "supporting"},
        ],
        "knowledge_ledger": [
            {
                "fact_id": "secret-owner",
                "fact": "黑戒指真正主人是苏玄",
                "learned_chapter": 30,
                "known_by": ["林照"],
                "source": "chapter:30",
                "certainty": "certain",
                "visibility": "private",
            },
            {
                "fact_id": "public-gate",
                "fact": "北门在夜间关闭",
                "learned_chapter": 10,
                "known_by": ["*"],
                "source": "chapter:10",
                "certainty": "certain",
                "visibility": "public",
            },
            {
                "fact_id": "wrong-belief",
                "fact": "旧钥匙能打开北门",
                "learned_chapter": 10,
                "known_by": ["林照"],
                "source": "chapter:10",
                "certainty": "certain",
                "visibility": "private",
                "invalidated_chapter": 20,
            },
            {
                "fact_id": "gu-private",
                "fact": "顾闻舟私下保存了一封信",
                "learned_chapter": 12,
                "known_by": ["顾闻舟"],
                "source": "chapter:12",
                "certainty": "certain",
                "visibility": "private",
            },
        ],
    }


def test_knowledge_is_character_scoped_and_chapter_bounded() -> None:
    before_reveal = get_character_knowledge(_story(), "林照", as_of_chapter=15)
    at_reveal = get_character_knowledge(_story(), "林照", as_of_chapter=30)
    other_character = get_character_knowledge(_story(), "顾闻舟", as_of_chapter=30)

    assert {item["fact_id"] for item in before_reveal} == {"public-gate", "wrong-belief"}
    assert {item["fact_id"] for item in at_reveal} == {"public-gate", "secret-owner"}
    assert {item["fact_id"] for item in other_character} == {"public-gate", "gu-private"}


def test_public_knowledge_still_obeys_its_explicit_chapter_boundary() -> None:
    assert get_character_knowledge(_story(), "林照", as_of_chapter=9) == []
    assert [item["fact_id"] for item in get_character_knowledge(_story(), "林照", as_of_chapter=10)] == [
        "public-gate",
        "wrong-belief",
    ]


def test_relationship_endpoint_knowledge_is_character_scoped_and_hides_private_notes() -> None:
    story = _story()
    story["relationship_graph"] = [
        {
            "id": "rel-lin-gu",
            "source": "林照",
            "target": "顾闻舟",
            "first_chapter": 10,
            "source_knowledge": ["顾闻舟曾经改过一份名册"],
            "target_knowledge": ["林照正在查旧案"],
            "private_notes": ["顾闻舟受人指使"],
        }
    ]

    assert not get_character_knowledge(story, "林照", 9)
    lin_facts = get_character_knowledge(story, "林照", 10)
    gu_facts = get_character_knowledge(story, "顾闻舟", 10)
    assert any(item["fact"] == "顾闻舟曾经改过一份名册" for item in lin_facts)
    assert not any(item["fact"] == "林照正在查旧案" for item in lin_facts)
    assert any(item["fact"] == "林照正在查旧案" for item in gu_facts)
    assert all("顾闻舟受人指使" not in str(item) for item in [*lin_facts, *gu_facts])


def test_invalidated_knowledge_is_not_returned_after_invalidation() -> None:
    assert "wrong-belief" in {
        item["fact_id"]
        for item in get_character_knowledge(_story(), "林照", as_of_chapter=15)
    }
    assert "wrong-belief" not in {
        item["fact_id"]
        for item in get_character_knowledge(_story(), "林照", as_of_chapter=20)
    }


def test_structured_knowledge_updates_persist_without_llm_extraction() -> None:
    state = StoryState.model_validate(_story())

    apply_knowledge_updates(
        state,
        [
            {
                "fact_id": "new-clue",
                "fact": "井底藏着一枚铜印",
                "known_by": ["林照"],
                "source": "chapter:7",
                "visibility": "private",
            }
        ],
        chapter_number=7,
    )

    assert [item["fact_id"] for item in get_character_knowledge(state, "林照", 7)] == [
        "new-clue"
    ]
    assert get_character_knowledge(state, "顾闻舟", 7) == []


def test_knowledge_query_rejects_negative_boundary() -> None:
    with pytest.raises(ValueError, match="as_of_chapter"):
        get_character_knowledge(_story(), "林照", as_of_chapter=-1)


def test_chapter_commit_accepts_explicit_knowledge_updates() -> None:
    state = StoryState.model_validate(_story())

    apply_post_chapter_updates(
        state,
        "林照从旧信中确认井底藏着铜印。",
        7,
        post_draft_memory={
            "summary": "林照确认井底藏着铜印。",
            "knowledge_updates": [
                {
                    "fact_id": "well-seal",
                    "fact": "井底藏着一枚铜印",
                    "known_by": ["林照"],
                    "source": "chapter:7",
                    "visibility": "private",
                }
            ],
        },
    )

    assert [item["fact_id"] for item in get_character_knowledge(state, "林照", 7)] == [
        "well-seal"
    ]


def test_chapter_commit_rejects_future_learned_chapter() -> None:
    state = StoryState.model_validate(_story())

    committed = apply_knowledge_updates(
        state,
        [
            {
                "fact_id": "future-clue",
                "fact": "尚未发生的线索",
                "known_by": ["林照"],
                "learned_chapter": 8,
            }
        ],
        chapter_number=7,
    )

    assert committed == []
    assert not any(item.get("fact_id") == "future-clue" for item in state.knowledge_ledger)
