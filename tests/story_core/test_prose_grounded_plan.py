from packages.story_core.orchestrator import _prose_grounded_writing_plan


def test_writer_plan_hides_simulation_report_fields():
    plan = {
        "chapter_number": 2,
        "chapter_title": "第2章 清道夫委托",
        "event_plan": {
            "turn": "压力来自补给成本",
            "pivot": "这才合理",
            "collision": "世界反应升级",
            "stakes": "证据链逼近",
            "next_focus": "狼坡样本",
            "ordered_actions": [{"name": "夜烬", "action": "在柜台前数铜币"}],
            "world_reactions": ["木牌记录往下滚动两行"],
        },
        "conflict_summary": {"summary": "压力来自世界反应"},
        "simulation_plan": {
            "chapter_goal": "压力来自补给成本",
            "event_plan": {"stakes": "证据链逼近"},
            "required_beats": ["写出木杖耐久下降"],
            "forbidden_moves": ["不要写公会锁定坐标"],
        },
    }

    grounded = _prose_grounded_writing_plan(plan)
    text = str(grounded)

    assert "conflict_summary" not in grounded
    assert "turn" not in grounded["scene_flow"]
    assert "pivot" not in grounded["scene_flow"]
    assert "collision" not in grounded["scene_flow"]
    assert "stakes" not in grounded["scene_flow"]
    assert "pressure" not in grounded
    assert "event_plan" not in grounded
    assert "world_events" not in grounded
    assert "simulation_plan" not in grounded
    assert "压力来自补给成本" not in text
    assert "这才合理" not in text
    assert "证据链逼近" not in text
    assert "木牌记录往下滚动两行" in text
    assert "在柜台前数铜币" in text
