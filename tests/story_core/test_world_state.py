from packages.story_core.world_state import (
    append_continuity_facts,
    normalize_world_context,
    relevant_continuity_facts,
)


def test_normalize_world_context_separates_static_snapshot_and_facts() -> None:
    result = normalize_world_context(
        blueprint={
            "premise": "灵气依赖地脉。",
            "current_arc": "雪山神殿封锁。",
            "time_state": {"marker": "第三日清晨"},
            "continuity_state": {
                "running_facts": ["林修负伤。"],
                "chapter_facts": [
                    {"chapter_number": 147, "facts": ["林修负伤。", "神殿入口已经封死。"]}
                ],
            },
        },
        state={
            "world_facts": [
                "世界前提：灵气依赖地脉。",
                "第147章事实：林修负伤。",
                "第147章摘要：林修在雪山神殿与敌人周旋。",
            ]
        },
        current_focus="守住神殿入口。",
    )

    assert result.static_blueprint == {"premise": "灵气依赖地脉。"}
    assert result.world_snapshot == {
        "current_arc": "雪山神殿封锁。",
        "time_state": {"marker": "第三日清晨"},
        "current_focus": "守住神殿入口。",
    }
    assert result.continuity_facts == [
        {
            "text": "林修负伤。",
            "source_chapter": 147,
            "status": "active",
            "updated_chapter": 147,
        },
        {
            "text": "神殿入口已经封死。",
            "source_chapter": 147,
            "status": "active",
            "updated_chapter": 147,
        },
    ]


def test_continuity_facts_drop_legacy_continue_placeholders() -> None:
    result = normalize_world_context(
        blueprint={},
        state={
            "continuity_facts": [
                {"text": "continue", "source_chapter": 1},
                {"text": "陈默亲眼看到预言中的车祸发生。", "source_chapter": 1},
            ],
            "world_facts": ["第1章事实：continue", "第1章摘要：continue"],
        },
    )

    assert [item["text"] for item in result.continuity_facts] == [
        "陈默亲眼看到预言中的车祸发生。"
    ]


def test_normalize_world_context_keeps_unknown_short_fact_but_excludes_body_fragment() -> None:
    body_fragment = "林修抬头看见殿门上的旧纹亮起。" * 30
    result = normalize_world_context(
        blueprint={"world_rules": ["越境使用法术会反噬。"]},
        state={
            "world_facts": [
                "世界规则：越境使用法术会反噬。",
                "白塔只在月末开放。",
                body_fragment,
            ]
        },
    )

    assert [item["text"] for item in result.continuity_facts] == ["白塔只在月末开放。"]


def test_append_and_retrieve_continuity_facts_are_deduplicated_and_relevant() -> None:
    facts = append_continuity_facts(
        [
            {
                "text": "林修负伤。",
                "source_chapter": 146,
                "status": "active",
                "updated_chapter": 146,
            },
            {
                "text": "白塔只在月末开放。",
                "source_chapter": 20,
                "status": "active",
                "updated_chapter": 20,
            },
        ],
        chapter_number=147,
        facts=["林修负伤。", "神殿入口已经封死。"],
    )

    assert facts[0]["source_chapter"] == 146
    assert facts[0]["updated_chapter"] == 147
    assert [item["text"] for item in relevant_continuity_facts(facts, query_terms=["林修", "神殿"], limit=2)] == [
        "林修负伤。",
        "神殿入口已经封死。",
    ]
