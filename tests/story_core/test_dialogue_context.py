from packages.story_core.dialogue_context import build_dialogue_context


def test_dialogue_context_builds_scene_contract_without_scripted_lines():
    context = build_dialogue_context(
        {
            "cards": [
                {
                    "identity": {"name": "林修"},
                    "relationship_context": [
                        {"target": "沈墨璃", "trust": 0.4, "tension": 0.7, "bond": "刚开始互相信任"}
                    ],
                },
                {"identity": {"name": "沈墨璃"}},
            ]
        },
        {
            "event_plan": {"chapter_satisfaction": {"emotion_target": "两人决定是否继续引出寒毒"}},
            "character_moves": {
                "林修": [{"goal": "劝沈墨璃停手", "emotion": "担心", "action": "按住她的手腕"}],
                "沈墨璃": [{"goal": "确认寒毒位置", "emotion": "着急", "action": "继续运转灵力"}],
            },
        },
    )

    assert context["conversation_reason"] == "两人决定是否继续引出寒毒"
    assert context["participants"] == [
        {"name": "林修", "want": "劝沈墨璃停手", "emotion": "担心"},
        {"name": "沈墨璃", "want": "确认寒毒位置", "emotion": "着急"},
    ]
    assert context["relationships"][0]["target"] == "沈墨璃"
    assert "不突然开玩笑" in context["tone_boundary"]
    assert context["expected_change"] == "两人决定是否继续引出寒毒"
    assert "speaker_intents" not in context
    assert "action" not in str(context["participants"])


def test_dialogue_context_reads_existing_unsaid_pressure_without_inventing_it():
    context = build_dialogue_context(
        {"cards": [{"identity": {"name": "林修"}}]},
        {
            "event_plan": {
                "chapter_satisfaction": {"emotion_target": "林修改变主意"},
                "unsaid_pressure": "林修没有说出寒毒已经碰到心脉",
            }
        },
    )

    assert context["unsaid_pressure"] == "林修没有说出寒毒已经碰到心脉"


def test_dialogue_context_drops_another_speakers_copied_intent():
    character_context = {
        "cards": [
            {"identity": {"name": "林修"}},
            {"identity": {"name": "小乐"}},
        ]
    }
    copied = {
        "goal": "林修要稳住残镜封锁",
        "emotion": "警惕",
        "action": "林修拆开阵心石，再让小乐辨认气息",
    }

    context = build_dialogue_context(
        character_context,
        {"character_moves": {"林修": [copied], "小乐": [copied]}},
    )

    assert [item["name"] for item in context["participants"]] == ["林修"]


def test_dialogue_context_has_no_genre_terms_or_dialogue_examples():
    context = build_dialogue_context({}, {})
    rendered = str(context)

    assert "面板" not in rendered
    assert "任务" not in rendered
    assert "法杖" not in rendered
    assert "先试" not in rendered
