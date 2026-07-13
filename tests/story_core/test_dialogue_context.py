from packages.story_core.dialogue_context import build_dialogue_context


def test_dialogue_context_keeps_emotional_job_and_relationship_gate_separate():
    context = build_dialogue_context(
        {
            "cards": [
                {
                    "identity": {"name": "苏叶"},
                    "relationship_context": [{"target": "洛婶", "trust": 0.2, "tension": 0.4, "bond": "普通熟人"}],
                }
            ]
        },
        {"event_plan": {"chapter_satisfaction": {"emotion_target": "被对方说中后先压住火气"}}},
    )

    assert context["emotional_job"] == "被对方说中后先压住火气"
    assert context["relationships"][0]["target"] == "洛婶"
    assert "不突然开玩笑" in context["tone_gate"]
    assert "改变" in context["dialogue_test"]
