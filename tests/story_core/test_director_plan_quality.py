import json

from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import (
    StoryOrchestrator,
    _director_plan_quality_issues,
    _normalize_event_plan,
    _normalize_intent,
)


def _story() -> StoryState:
    return StoryState(
        story_id="director-gate",
        outline="夜烬在灰狼坡完成清道夫委托。",
        genre="网游",
        style="白描",
        author_constraints=["游戏内行动使用夜烬，材料是灰狼毒腺。"],
        world_facts=["灰狼掉落灰狼毒腺。"],
        progression_ledger={"economy": {"inventory": {"灰狼毒腺": 8, "粗糙狼皮": 7}}},
        characters=[
            CharacterState(name="苏叶", role="主角", game_id="夜烬"),
            CharacterState(name="白河仓库收购方", role="收购方NPC"),
        ],
        outline_context={"schema_version": "outline-context/v1"},
    )


def _complete_plan(ordered_actions: object) -> dict:
    return {
        "character_moves": {},
        "event_plan": {
            "ordered_actions": ordered_actions,
            "chapter_satisfaction": {
                "core_event": "林照拿到祖祠账册",
                "obstacle": "赵管事提前锁住侧门",
                "visible_payoff": "账册当场打开",
                "cost": "赵管事记住林照的查账意图",
                "state_change": "林照确认香灰被人调换",
                "next_hook": "账册里少了三个名字",
            },
            "chapter_end_hook": {"type": "悬念钩", "strength": "medium", "content": "缺失名单指向内院"},
        },
    }


def test_director_quality_gate_rejects_missing_contract_and_continuity_errors():
    plan = {
        "character_moves": [
            {"name": "苏叶", "action": "去灰狼坡刷灰鼠毒腺"},
            {"name": "白河仓库收购方", "action": "询问材料来源"},
        ],
        "event_plan": {
            "ordered_actions": [{"name": "苏叶", "action": "击杀灰鼠"}],
            "chapter_satisfaction": {},
            "chapter_end_hook": None,
        },
    }

    issues = _director_plan_quality_issues(_story(), plan)
    joined = "\n".join(issues)

    assert "chapter_satisfaction" in joined
    assert "chapter_end_hook" in joined
    assert "苏叶" in joined and "夜烬" in joined
    assert "灰鼠毒腺" in joined and "灰狼毒腺" in joined
    assert "白河仓库收购方" in joined


def test_normalize_intent_keeps_string_conflicts():
    intent = _normalize_intent(
        {
            "primary_conflict": "血量不足但还要补齐任务材料",
            "secondary_conflict": "柜台快关门",
        }
    )

    assert intent["primary_conflict"]["summary"] == "血量不足但还要补齐任务材料"
    assert intent["secondary_conflict"]["summary"] == "柜台快关门"


def test_director_quality_gate_accepts_complete_continuous_plan():
    plan = {
        "character_moves": [{"name": "夜烬", "action": "补齐灰狼毒腺后提交任务"}],
        "event_plan": {
            "ordered_actions": [{"name": "夜烬", "action": "击杀灰狼并提交灰狼毒腺"}],
            "chapter_satisfaction": {
                "core_event": "完成清道夫委托",
                "obstacle": "法力不足",
                "visible_payoff": "获得任务经验",
                "cost": "消耗药水和法杖耐久",
                "state_change": "任务变为已完成",
                "next_hook": "NPC给出下一环线索",
            },
            "chapter_end_hook": {"type": "渴望钩", "strength": "medium", "content": "下一环任务出现"},
        },
    }

    assert _director_plan_quality_issues(_story(), plan) == []


def test_director_quality_gate_rejects_plan_without_executable_actions():
    plan = {
        "character_moves": [],
        "event_plan": {
            "ordered_actions": [],
            "chapter_satisfaction": {
                "core_event": "完成清道夫委托",
                "obstacle": "法力不足",
                "visible_payoff": "获得任务经验",
                "cost": "消耗药水和法杖耐久",
                "state_change": "任务变为已完成",
                "next_hook": "NPC给出下一环线索",
            },
            "chapter_end_hook": {"type": "渴望钩", "strength": "medium", "content": "下一环任务出现"},
        },
    }

    issues = _director_plan_quality_issues(_story(), plan)

    assert any("可执行动作" in issue for issue in issues)


def test_director_quality_gate_rejects_missing_blank_and_null_actions():
    for incomplete_move in ({"name": "夜烬"}, {"name": "夜烬", "action": "   "}, {"name": "夜烬", "action": None}):
        plan = {
            "character_moves": [incomplete_move],
            "event_plan": {
                "ordered_actions": [],
                "chapter_satisfaction": {
                    "core_event": "完成清道夫委托",
                    "obstacle": "法力不足",
                    "visible_payoff": "获得任务经验",
                    "cost": "消耗药水和法杖耐久",
                    "state_change": "任务变为已完成",
                    "next_hook": "NPC给出下一环线索",
                },
                "chapter_end_hook": {"type": "渴望钩", "strength": "medium", "content": "下一环任务出现"},
            },
        }

        issues = _director_plan_quality_issues(_story(), plan)

        assert any("可执行动作" in issue for issue in issues), incomplete_move


def test_director_quality_gate_and_event_plan_normalization_accept_text_ordered_actions():
    plan = {
        "character_moves": {},
        "event_plan": {
            "ordered_actions": ["章首，林照核对祖祠账册", "林照带周满检查侧门香灰"],
            "chapter_satisfaction": {
                "core_event": "林照拿到祖祠账册",
                "obstacle": "赵管事提前锁住侧门",
                "visible_payoff": "账册当场打开",
                "cost": "赵管事记住林照的查账意图",
                "state_change": "林照确认香灰被人调换",
                "next_hook": "账册里少了三个名字",
            },
            "chapter_end_hook": {"type": "悬念钩", "strength": "medium", "content": "缺失名单指向内院"},
        },
    }

    issues = _director_plan_quality_issues(_story(), plan)
    event_plan = _normalize_event_plan(plan["event_plan"], chapter_number=2, story=_story())

    assert issues == []
    assert [(item["name"], item["action"]) for item in event_plan["ordered_actions"]] == [
        ("", "章首，林照核对祖祠账册"),
        ("", "林照带周满检查侧门香灰"),
    ]


def test_ordered_action_object_is_one_action_instead_of_grouped_mapping():
    event_plan = _normalize_event_plan(
        {"ordered_actions": {"name": "林照", "action": "查香灰"}},
        chapter_number=2,
        story=_story(),
    )

    assert [(item["name"], item["action"]) for item in event_plan["ordered_actions"]] == [
        ("林照", "查香灰")
    ]


def test_text_ordered_action_infers_known_real_name_and_triggers_game_id_guard():
    plan = {
        "character_moves": {},
        "event_plan": {
            "ordered_actions": ["苏叶击杀灰狼", "夜烬提交灰狼毒腺"],
            "chapter_satisfaction": {
                "core_event": "完成清道夫委托",
                "obstacle": "法力不足",
                "visible_payoff": "获得任务经验",
                "cost": "消耗药水和法杖耐久",
                "state_change": "任务变为已完成",
                "next_hook": "NPC给出下一环线索",
            },
            "chapter_end_hook": {"type": "渴望钩", "strength": "medium", "content": "下一环任务出现"},
        },
    }

    issues = _director_plan_quality_issues(_story(), plan)
    event_plan = _normalize_event_plan(plan["event_plan"], chapter_number=2, story=_story())

    assert any("苏叶" in issue and "夜烬" in issue for issue in issues)
    assert [item["name"] for item in event_plan["ordered_actions"]] == ["苏叶", "夜烬"]


def test_text_ordered_actions_only_infer_known_actor_at_sentence_start():
    story = StoryState(
        story_id="ordered-name-inference",
        outline="林照与周满查祖祠。",
        genre="悬疑",
        style="白描",
        characters=[
            CharacterState(name="周满", role="配角"),
            CharacterState(name="林照", role="主角"),
        ],
    )

    event_plan = _normalize_event_plan(
        {
            "ordered_actions": [
                "章首从青烟写起",
                "林照询问周满",
                "路人拦住林照",
                "章首从青烟写起，林照推开侧门",
            ]
        },
        chapter_number=2,
        story=story,
    )

    assert [(item["name"], item["action"]) for item in event_plan["ordered_actions"]] == [
        ("", "章首从青烟写起"),
        ("林照", "林照询问周满"),
        ("", "路人拦住林照"),
        ("", "章首从青烟写起，林照推开侧门"),
    ]


def test_game_quality_gate_scans_reality_name_without_treating_target_as_actor():
    plan = _complete_plan(["灰狼扑向苏叶"])

    issues = _director_plan_quality_issues(_story(), plan)
    event_plan = _normalize_event_plan(plan["event_plan"], chapter_number=2, story=_story())

    assert event_plan["ordered_actions"][0]["name"] == ""
    assert any("苏叶" in issue and "夜烬" in issue for issue in issues)


def test_quality_gate_allows_placeholder_terms_in_unstructured_text_actions():
    story = StoryState(
        story_id="placeholder-text-terms",
        outline="林照查祖祠。",
        genre="玄幻",
        style="白描",
        characters=[CharacterState(name="林照", role="主角")],
    )

    for action in ("询问收购方价格", "向陌生路人问路", "请店员拿出账册"):
        issues = _director_plan_quality_issues(story, _complete_plan([action]))

        assert issues == [], action


def test_quality_gate_rejects_structured_placeholder_actor_names():
    story = StoryState(
        story_id="structured-placeholder-actors",
        outline="林照向收购方询价。",
        genre="玄幻",
        style="白描",
        characters=[CharacterState(name="林照", role="主角")],
    )
    ordered_plan = _complete_plan([{"name": "白河仓库收购方", "action": "上门压价"}])
    grouped_character_plan = _complete_plan(["林照核对账册"])
    grouped_character_plan["character_moves"] = {"白河仓库收购方": "上门压价"}
    grouped_ordered_plan = _complete_plan({"白河仓库收购方": "上门压价"})
    grouped_ordered_list_plan = _complete_plan({"白河仓库收购方": ["上门压价"]})

    for plan in (ordered_plan, grouped_character_plan, grouped_ordered_plan, grouped_ordered_list_plan):
        issues = _director_plan_quality_issues(story, plan)

        assert any("白河仓库收购方" in issue and "占位" in issue for issue in issues)


def test_quality_gate_keeps_concrete_xuanhuan_text_actions_valid():
    story = StoryState(
        story_id="xuanhuan-text-actions",
        outline="林照与周满查祖祠。",
        genre="玄幻",
        style="白描",
        characters=[CharacterState(name="林照", role="主角"), CharacterState(name="周满", role="配角")],
    )

    issues = _director_plan_quality_issues(story, _complete_plan(["林照询问周满", "周满检查香灰"]))

    assert issues == []


def test_writer_event_plan_drops_missing_null_and_blank_actions_from_mixed_input():
    event_plan = _normalize_event_plan(
        {
            "ordered_actions": [
                {"name": "林照", "action": "查香灰"},
                {},
                {"name": "赵管事", "action": None},
                {"name": "周满", "action": "   "},
                None,
                "林照询问周满",
            ]
        },
        chapter_number=2,
        story=StoryState(
            story_id="ordered-action-filter",
            outline="林照与周满查祖祠。",
            genre="悬疑",
            style="白描",
            characters=[CharacterState(name="林照", role="主角"), CharacterState(name="周满", role="配角")],
        ),
    )

    assert [(item["name"], item["action"]) for item in event_plan["ordered_actions"]] == [
        ("林照", "查香灰"),
        ("林照", "林照询问周满"),
    ]


def test_director_quality_gate_rejects_blank_text_only_ordered_actions():
    plan = {
        "character_moves": {},
        "event_plan": {
            "ordered_actions": ["", "   "],
            "chapter_satisfaction": {
                "core_event": "林照拿到祖祠账册",
                "obstacle": "赵管事提前锁住侧门",
                "visible_payoff": "账册当场打开",
                "cost": "赵管事记住林照的查账意图",
                "state_change": "林照确认香灰被人调换",
                "next_hook": "账册里少了三个名字",
            },
            "chapter_end_hook": {"type": "悬念钩", "strength": "medium", "content": "缺失名单指向内院"},
        },
    }

    issues = _director_plan_quality_issues(_story(), plan)

    assert any("可执行动作" in issue for issue in issues)


def test_director_quality_gate_checks_materials_outside_moves():
    plan = {
        "character_moves": [{"name": "夜烬", "action": "提交灰狼毒腺"}],
        "chapter_intent": {"next_focus": "向洛婶确认后续委托"},
        "event_plan": {
            "ordered_actions": [],
            "chapter_satisfaction": {
                "core_event": "完成清道夫委托",
                "obstacle": "法力不足",
                "visible_payoff": "交出灰鼠毒腺并获得任务经验",
                "cost": "消耗药水和法杖耐久",
                "state_change": "任务变为已完成",
                "next_hook": "NPC给出下一环线索",
            },
            "chapter_end_hook": {"type": "渴望钩", "strength": "medium", "content": "下一环任务出现"},
        },
    }

    issues = _director_plan_quality_issues(_story(), plan)

    assert any("灰鼠毒腺" in issue and "灰狼毒腺" in issue for issue in issues)


def test_director_quality_gate_rejects_generic_placeholder_plan():
    plan = {
        "character_moves": [{"name": "夜烬", "action": "完成本章推进"}],
        "event_plan": {
            "ordered_actions": [{"name": "夜烬", "action": "推进当前目标"}],
            "chapter_satisfaction": {
                "core_event": "完成本章推进",
                "obstacle": "出现可见阻力",
                "visible_payoff": "获得阶段收益",
                "cost": "付出可见代价",
                "state_change": "状态发生变化",
                "next_hook": "形成下一场压力",
            },
            "chapter_end_hook": {"type": "悬念钩", "strength": "medium", "content": "留下下一步"},
        },
    }

    issues = _director_plan_quality_issues(_story(), plan)

    assert any("空泛占位" in issue for issue in issues)


def test_director_quality_gate_rejects_collecting_material_already_sufficient_for_known_task():
    story = _story()
    story.progression_ledger["economy"] = {"inventory": {"灰狼毒腺": 16}}
    story.world_facts.append("清道夫委托需要灰狼毒腺×10。")
    plan = {
        "character_moves": [
            {"name": "夜烬", "goal": "补足毒腺后完成清道夫委托", "action": "继续去灰狼坡收集灰狼毒腺"}
        ],
        "event_plan": {
            "ordered_actions": [{"name": "夜烬", "action": "继续收集灰狼毒腺"}],
            "chapter_satisfaction": {
                "core_event": "完成清道夫委托",
                "obstacle": "法力不足",
                "visible_payoff": "获得任务经验",
                "cost": "消耗法杖耐久",
                "state_change": "任务完成",
                "next_hook": "出现下一环任务",
            },
            "chapter_end_hook": {"type": "渴望钩", "strength": "medium", "content": "下一环任务出现"},
        },
    }

    issues = _director_plan_quality_issues(story, plan)

    assert any("已有16份" in issue and "不应重复收集" in issue for issue in issues)


def test_model_fallback_without_outline_context_retries_bad_plan_then_stops_before_writer(monkeypatch):
    orchestrator = StoryOrchestrator()
    calls: list[str] = []
    story = _story()
    story.outline_context = {}
    bad_plan = {
        "character_moves": [{"name": "苏叶", "action": "刷灰鼠毒腺"}],
        "chapter_intent": {"chapter_title": "错误计划"},
        "event_plan": {"ordered_actions": [], "chapter_satisfaction": {}, "chapter_end_hook": None},
        "memory_constraints": {},
        "chapter_summary": {},
    }

    def fake_chat(_story, _prompt, *, agent, stage, **_kwargs):
        calls.append(f"{agent}:{stage}")
        assert agent == "planner"
        return json.dumps(bad_plan, ensure_ascii=False), ""

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_chat)

    bundle = orchestrator.generate_next_chapter(story)

    assert calls == ["planner:剧情计划生成", "planner:剧情计划重做"]
    assert bundle.body.startswith("生成失败：director_plan_quality_failed")
    assert "director_plan_quality_failed" in bundle.quality_report["failure_reason"]
