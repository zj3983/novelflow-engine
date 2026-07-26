import json

from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import StoryOrchestrator, _director_plan_quality_issues, _normalize_intent


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
