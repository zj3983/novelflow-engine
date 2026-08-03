import pytest

from packages.story_core.chapter_planning import build_outline_chapter_plan


def _scene_chain() -> list[dict[str, str]]:
    return [
        {
            "location": "灰狼坡外围",
            "pov": "夜烬",
            "goal": "找到空出的刷新点",
            "obstacle": "入口挤满等怪的玩家",
            "action": "夜烬沿侧坡绕到灌木后",
            "change": "他找到一只刚刷新的灰狼",
            "next": "先试着单独击杀",
        },
        {
            "location": "侧坡灌木带",
            "pov": "夜烬",
            "goal": "补齐任务材料",
            "obstacle": "灰狼连续贴近，法力下降",
            "action": "夜烬拉开距离连续清怪",
            "change": "毒腺数量达到提交要求",
            "next": "回村提交委托",
        },
        {
            "location": "灰烬村药剂铺",
            "pov": "夜烬",
            "goal": "提交清道夫委托",
            "obstacle": "柜台前排着交任务的玩家",
            "action": "夜烬排队交出毒腺",
            "change": "委托完成并取得经验",
            "next": "查看新出现的收购单",
        },
    ]


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
                    "scene_chain": _scene_chain(),
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
    assert plan["event_plan"]["scene_chain"] == _scene_chain()
    assert plan["memory_constraints"] == {}
    assert "chapter_summary" not in plan


def test_outline_does_not_copy_protagonist_intent_to_every_cast_member():
    context = {
        "project_snapshot": {
            "outline_context": {
                "chapter": {
                    "chapter_number": 1,
                    "title": "女儿回来了",
                    "goal": "周建平想弄清女儿为何突然回来。",
                    "action": "周建平试着问她近况。",
                    "turn": "周清妍误会父亲不肯帮忙，转身要走。",
                    "cast": ["周建平", "周清妍", "刘桂芬"],
                    "scene_chain": _scene_chain(),
                }
            }
        }
    }

    plan = build_outline_chapter_plan(context, 1)

    assert plan is not None
    assert plan["character_moves"] == [
        {
            "name": "周建平",
            "goal": "周建平想弄清女儿为何突然回来。",
            "emotion": "",
            "action": "周建平试着问她近况。",
            "priority": "primary",
        }
    ]


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


def test_outline_without_scene_chain_requires_director_model():
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


def test_outline_attribute_decision_is_handed_to_event_plan() -> None:
    context = {
        "project_snapshot": {
            "outline_context": {
                "chapter": {
                    "chapter_number": 2,
                    "goal": "升级",
                    "action": "击败灰狼",
                    "attribute_allocation_decision": {"mode": "allocate", "allocations": {"智力": 5}, "remaining": 0},
                    "scene_chain": _scene_chain(),
                }
            }
        }
    }

    plan = build_outline_chapter_plan(context, 2)

    assert plan["event_plan"]["attribute_allocation_decision"]["allocations"] == {"智力": 5}


def test_outline_structured_progression_is_handed_to_event_plan() -> None:
    progression = {"from": "Lv.1", "to": "Lv.2", "reason": "quest reward"}
    context = {
        "project_snapshot": {
            "outline_context": {
                "chapter": {
                    "chapter_number": 1,
                    "goal": "Complete the starter quest.",
                    "action": "Turn in the quest and level up.",
                    "level_target": "Lv.2",
                    "level_change": {"from": "Lv.1", "to": "Lv.2"},
                    "progression": progression,
                    "scene_chain": _scene_chain(),
                }
            }
        }
    }

    plan = build_outline_chapter_plan(context, 1)

    assert plan["event_plan"]["level_target"] == "Lv.2"
    assert plan["event_plan"]["level_change"] == {"from": "Lv.1", "to": "Lv.2"}
    assert plan["event_plan"]["progression"] == progression
    assert plan["event_plan"]["attribute_allocation_level_target"] == 2


@pytest.mark.parametrize(
    "progression_field",
    [
        {"level_change": {"from": "Lv.1", "to": "Lv.2"}},
        {"progression": {"previous_level": "Lv.1", "target_level": "Lv.2"}},
    ],
)
def test_outline_nested_progression_produces_level_target(progression_field: dict) -> None:
    chapter = {
        "chapter_number": 1,
        "goal": "Complete the starter quest.",
        "action": "Turn in the quest.",
        "scene_chain": _scene_chain(),
        **progression_field,
    }

    plan = build_outline_chapter_plan(
        {"project_snapshot": {"outline_context": {"chapter": chapter}}},
        1,
    )

    assert plan["event_plan"]["attribute_allocation_level_target"] == 2
