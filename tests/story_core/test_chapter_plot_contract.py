from packages.story_core.chapter_plot_contract import build_chapter_plot_contract


def test_plot_contract_collapses_plan_into_writer_facing_story_beats():
    contract = build_chapter_plot_contract(
        {
            "event_plan": {
                "chapter_satisfaction": {
                    "core_event": "拿到任务前置",
                    "emotion_target": "先压住兴奋",
                    "state_change": ["毒腺进度增加"],
                    "next_hook": "去后坡找更快的路线",
                },
                "ordered_actions": [
                    {"goal": "确认掉落", "action": "打两只灰狼", "obstacle": "法力不够", "choice": "停在坡口", "result": "看见额外材料"}
                ],
            },
            "simulation_plan": {"fact_locks": ["不能公开异常来源"]},
        }
    )

    assert contract["chapter_goal"] == "拿到任务前置"
    assert contract["emotional_goal"] == "先压住兴奋"
    assert contract["beats"][0]["obstacle"] == "法力不够"
    assert contract["fact_locks"] == ["不能公开异常来源"]
