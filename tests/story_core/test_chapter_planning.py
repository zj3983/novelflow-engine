from packages.story_core.chapter_planning import build_outline_chapter_plan


def test_actionable_outline_builds_chapter_contract():
    context = {
        "project_snapshot": {
            "outline_context": {
                "chapter": {
                    "chapter_number": 2,
                    "title": "补齐委托",
                    "goal": "补齐清道夫委托所需材料",
                    "obstacle": "刷新点竞争激烈",
                    "action": "夜烬换到侧坡连续清怪",
                    "turn": "匿名寄售价格开始下滑",
                    "payoff": "交付任务并升级",
                    "ending_hook": "交易行出现新的收购单",
                    "cast": ["夜烬"],
                }
            }
        }
    }

    plan = build_outline_chapter_plan(context, 2)

    assert plan is not None
    assert plan["planning_source"] == "outline"
    assert plan["character_moves"] == [
        {
            "name": "夜烬",
            "goal": "补齐清道夫委托所需材料",
            "emotion": "",
            "action": "夜烬换到侧坡连续清怪",
            "priority": "primary",
        }
    ]
    assert plan["event_plan"]["ordered_actions"] == [
        "补齐清道夫委托所需材料",
        "刷新点竞争激烈",
        "夜烬换到侧坡连续清怪",
        "匿名寄售价格开始下滑",
        "交付任务并升级",
        "交易行出现新的收购单",
    ]
    satisfaction = plan["event_plan"]["chapter_satisfaction"]
    assert satisfaction["obstacle"] == "刷新点竞争激烈"
    assert satisfaction["visible_payoff"] == "交付任务并升级"
    assert satisfaction["state_change"] == "匿名寄售价格开始下滑"
    assert plan["event_plan"]["chapter_end_hook"]["content"] == "交易行出现新的收购单"
    assert plan["memory_constraints"] == {}
    assert "chapter_summary" not in plan


def test_incomplete_outline_requires_model_fallback():
    context = {
        "project_snapshot": {
            "outline_context": {
                "chapter": {
                    "chapter_number": 2,
                    "goal": "继续升级",
                }
            }
        }
    }

    assert build_outline_chapter_plan(context, 2) is None


def test_outline_for_another_chapter_is_not_used():
    context = {
        "project_snapshot": {
            "outline_context": {
                "chapter": {
                    "chapter_number": 3,
                    "goal": "进入矿洞",
                    "payoff": "找到矿洞入口",
                }
            }
        }
    }

    assert build_outline_chapter_plan(context, 2) is None
