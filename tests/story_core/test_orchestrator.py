from copy import deepcopy
import json
import subprocess

import pytest
from packages.story_core.generation_progress import generation_progress

from packages.story_core.models import CharacterState, StoryState
from packages.story_core.model_gateway import ModelResponse
from packages.story_core.genre_types.base import GenrePlugin
from packages.story_core import orchestrator as orchestrator_module
from packages.story_core.orchestrator import StoryOrchestrator

_REAL_CHAT = StoryOrchestrator._chat


def _outline_scene_chain(pov: str = "Lin") -> list[dict[str, str]]:
    return [
        {
            "location": "起始地点",
            "pov": pov,
            "goal": "确认眼前目标",
            "obstacle": "有人当场阻拦",
            "action": f"{pov}先查清阻拦的原因",
            "change": "他找到可以继续行动的入口",
            "next": "转去处理主要冲突",
        },
        {
            "location": "冲突现场",
            "pov": pov,
            "goal": "完成主要行动",
            "obstacle": "原来的办法行不通",
            "action": f"{pov}换了一种办法继续尝试",
            "change": "阻力被解决，但留下代价",
            "next": "去确认行动结果",
        },
        {
            "location": "结果发生处",
            "pov": pov,
            "goal": "拿到本章结果",
            "obstacle": "结果还差最后一步",
            "action": f"{pov}完成最后一步并检查结果",
            "change": "本章目标兑现，新的问题出现",
            "next": "按新线索继续行动",
        },
    ]


def _trope_plugin() -> GenrePlugin:
    return GenrePlugin(
        plugin_id="urban",
        name="urban",
        keywords=(),
        core_promises=(),
        ledger_fields=(),
        rulebook={},
        quality_checks=(),
        trope_templates=(
            {
                "id": "trial",
                "name": "Trial Stage",
                "trigger": "rain invitation",
                "beats": ["accept the rain duel"],
                "payoff": "win trust without revealing the hidden card",
                "avoid": ["do not switch tropes"],
            },
        ),
    )


def test_compact_world_context_keeps_all_scoped_modules_without_keyword_reselection():
    compacted = orchestrator_module._compact_world_context_for_prompt(
        {
            "premise": "神域资源会受限流转。",
            "world_rules": ["基础规则。"],
            "power_system": ["力量规则。"],
            "progression_rules": ["成长规则。"],
            "economy_rules": ["经济规则。"],
            "quest_rules": ["任务规则。"],
            "faction_rules": ["阵营规则。"],
            "panel_rules": ["面板规则。"],
            "reality_bridge_rules": ["现实规则。"],
            "locations": [
                {"name": "灰烬村", "description": "新手村"},
                {"title": "后坡", "description": "巡查区域"},
            ],
            "factions": [
                {"name": "灰烬村守卫队", "description": "守卫"},
                {"name": "白河商会", "description": "商会"},
            ],
        },
        "这段文本不包含任何模块关键词",
        max_rules=8,
    )

    assert compacted["rules"] == [
        "基础规则。",
        "力量规则。",
        "成长规则。",
        "经济规则。",
        "任务规则。",
        "阵营规则。",
        "面板规则。",
        "现实规则。",
    ]
    assert compacted["entities"] == [
        "灰烬村：新手村",
        "后坡：巡查区域",
        "灰烬村守卫队：守卫",
    ]
    assert len(compacted["rules"]) <= 8


def test_workflow_character_names_come_from_card_identities():
    payload = {
        "selection": "planned_characters",
        "requested_names": ["苏叶"],
        "cards": [
            {"identity": {"name": "苏叶", "role": "protagonist"}},
            {"identity": {"name": "顾明", "role": "supporting"}},
        ],
    }

    assert orchestrator_module._planning_character_names(payload) == ["苏叶", "顾明"]


def test_orchestrator_memory_normalization_receives_protagonist_real_and_game_aliases(monkeypatch):
    captured = {}

    def fake_normalize(
        payload,
        *,
        body,
        existing_character_names,
        evidence_character_names=None,
        character_aliases_by_name=None,
        protagonist_aliases=None,
    ):
        captured["existing_character_names"] = existing_character_names
        captured["evidence_character_names"] = evidence_character_names
        captured["character_aliases_by_name"] = character_aliases_by_name
        captured["protagonist_aliases"] = protagonist_aliases
        return {
            "summary": "记忆完成",
            "facts": [],
            "unresolved_threads": [],
            "next_focus": "",
            "chapter_title": "",
            "character_updates": [],
            "ledger_updates": {},
            "ledger_evidence": {},
            "rejected_updates": [],
        }

    orchestrator = StoryOrchestrator()
    monkeypatch.setattr(orchestrator, "_timed_chat", lambda *_args, **_kwargs: ("{}", ""))
    monkeypatch.setattr(orchestrator_module, "normalize_post_draft_memory", fake_normalize)
    story = StoryState(
        story_id="s-orchestrator-memory-aliases",
        outline="网游开局。",
        genre="game_webnovel",
        style="紧凑",
        characters=[
            CharacterState(name="苏叶", game_id="夜烬", role="protagonist"),
            CharacterState(name="林峰", game_id="青锋", role="supporting"),
        ],
    )

    memory, status = orchestrator._extract_final_body_memory(
        story,
        "青锋把五点加到智力上。",
        1,
    )

    assert status["status"] == "ok"
    assert memory["summary"] == "记忆完成"
    assert captured["protagonist_aliases"] == {"苏叶", "夜烬"}
    assert captured["existing_character_names"] == {"苏叶", "林峰"}
    assert captured["evidence_character_names"] == {"苏叶", "夜烬", "林峰", "青锋"}
    assert captured["character_aliases_by_name"] == {"苏叶": {"夜烬"}, "林峰": {"青锋"}}


def _attribute_rule() -> dict:
    return {
        "mode": "free",
        "points_per_level": 5,
        "starting_level": 1,
        "base_attributes": {"\u667a\u529b": 5, "\u529b\u91cf": 5},
        "allow_carry": True,
        "respec_rule": "one reset per week",
    }


def test_apply_ledger_updates_awards_and_allocates_level_up_points() -> None:
    story = StoryState(
        story_id="s-attribute-update",
        outline="web game opening",
        genre="web game",
        style="plain",
        characters=[CharacterState(name="Su Ye", role="protagonist")],
        progression_ledger={"protagonist": {"level": "Lv.1"}},
        world_context={"power_system_spec": {"attribute_allocation": _attribute_rule()}},
    )

    orchestrator_module._apply_ledger_updates(
        story,
        {
            "protagonist": {
                "level": "Lv.2",
                "attribute_allocation": {
                    "allocations": {"\u667a\u529b": 5},
                    "remaining": 0,
                    "reason": "mage route",
                },
            }
        },
        chapter_number=4,
    )

    protagonist = story.progression_ledger["protagonist"]
    assert protagonist["attributes"] == {"\u667a\u529b": 10, "\u529b\u91cf": 5}
    assert protagonist["unallocated_attribute_points"] == 0
    assert protagonist["attribute_point_awards"] == [{"level": 2, "points": 5, "chapter": 4}]
    assert protagonist["attribute_allocations"][0]["allocations"] == {"\u667a\u529b": 5}
    assert "attribute_allocation" not in protagonist


def test_apply_ledger_updates_leaves_projects_without_rules_unchanged() -> None:
    story = StoryState(
        story_id="s-no-attribute-rule",
        outline="web game opening",
        genre="web game",
        style="plain",
        progression_ledger={"protagonist": {"level": "Lv.1"}},
    )

    orchestrator_module._apply_ledger_updates(story, {"protagonist": {"level": "Lv.2"}}, chapter_number=4)

    protagonist = story.progression_ledger["protagonist"]
    assert not {"attributes", "unallocated_attribute_points", "attribute_point_awards", "attribute_allocations"} & set(protagonist)


def test_simulated_state_deltas_prefer_nested_level_updates_over_legacy_flat_levels() -> None:
    story = StoryState(
        story_id="s-flat-level-conflict",
        outline="web game opening",
        genre="web game",
        style="plain",
        characters=[CharacterState(name="Su Ye", role="protagonist")],
        progression_ledger={"level": "Lv.1", "protagonist": {"level": "Lv.1"}},
        world_context={"power_system_spec": {"attribute_allocation": _attribute_rule()}},
    )

    orchestrator_module.apply_simulated_state_deltas(
        story,
        world_events=[
            {
                "state_delta": {
                    "protagonist": {
                        "level": "Lv.2",
                        "attribute_allocation": {"allocations": {"\u667a\u529b": 5}, "remaining": 0},
                    }
                }
            }
        ],
        chapter_number=4,
    )

    character = story.characters[0]
    assert story.progression_ledger["protagonist"]["level"] == "Lv.2"
    assert "level" not in story.progression_ledger
    assert story.progression_ledger["protagonist"]["unallocated_attribute_points"] == 0
    assert character.game_panel.level == "Lv.2"
    assert character.game_panel.attributes == {"\u667a\u529b": 10, "\u529b\u91cf": 5}
    assert character.game_state["current"]["level"] == "Lv.2"
    assert character.game_state["current"]["attributes"] == {"\u667a\u529b": 10, "\u529b\u91cf": 5}


def test_simulated_state_deltas_still_migrate_a_legacy_flat_level() -> None:
    story = StoryState(
        story_id="s-flat-level-migration",
        outline="web game opening",
        genre="web game",
        style="plain",
        characters=[CharacterState(name="Su Ye", role="protagonist")],
        progression_ledger={"level": "Lv.1"},
    )

    orchestrator_module.apply_simulated_state_deltas(
        story,
        world_events=[{"state_delta": {"pressure": {"market_anomaly": 1}}}],
        chapter_number=4,
    )

    assert story.progression_ledger["protagonist"]["level"] == "Lv.1"
    assert story.characters[0].game_panel.level == "Lv.1"


def test_ledger_updates_fall_back_to_a_valid_flat_level_when_nested_level_is_damaged() -> None:
    story = StoryState(
        story_id="s-damaged-nested-level",
        outline="web game opening",
        genre="web game",
        style="plain",
        progression_ledger={"level": "Lv.900", "protagonist": {"level": "damaged"}},
        world_context={"power_system_spec": {"attribute_allocation": _attribute_rule()}},
    )

    orchestrator_module._apply_ledger_updates(story, {"protagonist": {"level": "Lv.901"}}, chapter_number=4)

    protagonist = story.progression_ledger["protagonist"]
    assert protagonist["unallocated_attribute_points"] == 5
    assert protagonist["attribute_point_awards"] == [{"level": 901, "points": 5, "chapter": 4}]


def test_ledger_updates_prefer_a_valid_nested_level_over_a_flat_level() -> None:
    story = StoryState(
        story_id="s-valid-nested-level",
        outline="web game opening",
        genre="web game",
        style="plain",
        progression_ledger={"level": "Lv.900", "protagonist": {"level": "Lv.800"}},
        world_context={"power_system_spec": {"attribute_allocation": _attribute_rule()}},
    )

    orchestrator_module._apply_ledger_updates(story, {"protagonist": {"level": "Lv.801"}}, chapter_number=4)

    protagonist = story.progression_ledger["protagonist"]
    assert protagonist["unallocated_attribute_points"] == 5
    assert protagonist["attribute_point_awards"] == [{"level": 801, "points": 5, "chapter": 4}]


def test_simulated_state_deltas_preserve_legacy_attribute_directives_without_a_rule() -> None:
    story = StoryState(
        story_id="s-no-rule-public-regression",
        outline="web game opening",
        genre="web game",
        style="plain",
        characters=[CharacterState(name="Su Ye", role="protagonist", game_state={"current": {"level": "Lv.1"}})],
        progression_ledger={"protagonist": {"level": "Lv.1"}, "economy": {}, "equipment": {}, "pressure": {}},
    )
    expected_ledger = {
        "protagonist": {
            "level": "Lv.1",
            "attribute_allocation": {"allocations": {"\u667a\u529b": 1}},
        },
        "economy": {},
        "equipment": {},
        "pressure": {},
    }

    orchestrator_module.apply_simulated_state_deltas(
        story,
        world_events=[{"state_delta": deepcopy(expected_ledger)}],
        chapter_number=4,
    )

    assert story.progression_ledger == expected_ledger
    assert "unallocated_attribute_points" not in story.characters[0].game_state["current"]
    assert "attribute_point_awards" not in story.characters[0].game_state["current"]
    assert "attribute_allocations" not in story.characters[0].game_state["current"]


def test_structured_attribute_rule_syncs_ledger_values_without_legacy_suye_fallback() -> None:
    story = StoryState(
        story_id="s-attribute-sync",
        outline="web game opening",
        genre="web game",
        style="plain",
        characters=[CharacterState(name="\u82cf\u53f6", role="\u4e3b\u89d2", game_id="Night")],
        progression_ledger={
            "protagonist": {
                "level": "Lv.2",
                "attributes": {"\u667a\u529b": 10, "\u529b\u91cf": 5},
                "unallocated_attribute_points": 2,
                "attribute_point_awards": [{"level": 2, "points": 5, "chapter": 4}],
                "attribute_allocations": [{"chapter": 4, "allocations": {"\u667a\u529b": 3}, "remaining": 2, "reason": "mage"}],
            }
        },
        world_context={"power_system_spec": {"attribute_allocation": _attribute_rule()}},
    )

    orchestrator_module._sync_character_game_panels(story, 4)

    character = story.characters[0]
    assert character.game_panel.attributes == {"\u667a\u529b": 10, "\u529b\u91cf": 5}
    assert character.game_panel.unallocated_attribute_points == 2
    assert character.game_panel.attribute_point_awards == [{"level": 2, "points": 5, "chapter": 4}]
    assert character.game_panel.attribute_allocations[0]["remaining"] == 2
    assert character.game_state["current"]["attributes"] == {"\u667a\u529b": 10, "\u529b\u91cf": 5}
    assert character.game_state["current"]["unallocated_attribute_points"] == 2


@pytest.mark.parametrize("failure_code", ["provider_unavailable", "request_timed_out"])
def test_chat_returns_error_tuple_when_cli_provider_fails(monkeypatch, failure_code):
    from packages.story_core.runtime_config import StageRuntimeSettings

    settings = StageRuntimeSettings(
        provider_id="codexcli",
        protocol="codex_cli",
        model="codex-model",
        codex_command="codex",
    )
    monkeypatch.setattr(orchestrator_module, "resolve_stage_runtime", lambda stage: settings)

    class FailingGateway:
        def complete_stage(self, stage, request):
            return ModelResponse.failure(request, failure_code)

    story = StoryState(
        story_id="s-chat-cli-failure",
        outline="A scribe tests failure handling.",
        genre="fantasy",
        style="noir",
    )
    text, error = _REAL_CHAT(
        StoryOrchestrator(model_gateway=FailingGateway()),
        story,
        "prompt",
        max_tokens=16,
        json_mode=False,
        stage="写作",
    )

    assert text == ""
    assert "model_request_failed" in error


def test_orchestrator_runs_all_phases_and_returns_bundle():
    story = StoryState(
        story_id="s-orc-001",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
            )
        ],
    )

    bundle = StoryOrchestrator().generate_next_chapter(story)

    assert bundle.chapter_number == 1
    assert bundle.body
    assert bundle.chapter_title
    assert bundle.next_outline
    assert "writing_review" in bundle.quality_report


def test_actionable_chapter_outline_skips_planner_model(monkeypatch):
    story = StoryState(
        story_id="s-outline-planning",
        outline="夜烬通过新手任务建立第一笔游戏收入。",
        outline_context={
            "chapter": {
                "chapter_number": 1,
                "title": "第一笔收入",
                "goal": "完成灰狼材料任务",
                "obstacle": "灰狼刷新点竞争激烈",
                "action": "夜烬换到侧坡收集材料",
                "turn": "任务材料比预想更快凑齐",
                "payoff": "提交任务并升到二级",
                "ending_hook": "交易行出现新的收购单",
                "cast": ["夜烬"],
                "scene_chain": _outline_scene_chain("夜烬"),
            }
        },
        genre="game fantasy",
        style="webnovel",
        characters=[CharacterState(name="夜烬", role="protagonist")],
    )
    orchestrator = StoryOrchestrator()
    calls: list[str] = []
    body = "夜烬沿着侧坡清理灰狼，凑齐材料后回村提交任务。" * 300

    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        orchestrator_module,
        "_review_chapter_body",
        lambda *_args, **_kwargs: {"pass": True, "issues": [], "revision_plan": []},
    )

    def fake_timed_chat(_story, _prompt, *, agent, **_kwargs):
        calls.append(agent)
        if agent == "planner":
            raise AssertionError("完整章节细纲不应调用规划模型")
        if agent == "writer":
            return body, ""
        if agent == "memory":
            return json.dumps(
                {
                    "summary": "夜烬完成材料任务并升到二级。",
                    "facts": [{"text": "夜烬升到二级", "evidence": "提交任务并升到二级"}],
                    "unresolved_threads": [],
                    "next_focus": "查看新的收购单",
                    "chapter_title": "第一笔收入",
                    "character_updates": [],
                    "ledger_updates": {},
                    "ledger_evidence": {},
                },
                ensure_ascii=False,
            ), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)

    bundle = orchestrator.generate_next_chapter(story)

    assert "planner" not in calls
    assert bundle.event_plan["chapter_title"] == "第一笔收入"
    assert bundle.event_plan["chapter_satisfaction"]["visible_payoff"] == "提交任务并升到二级"


def test_outline_level_up_without_attribute_decision_is_completed_before_writer(monkeypatch):
    story = StoryState(
        story_id="s-outline-attribute-gate",
        outline="Lin completes the starter quest.",
        outline_context={
            "chapter": {
                "chapter_number": 1,
                "title": "First Level",
                "goal": "Complete the starter quest.",
                "obstacle": "The gate is guarded.",
                "action": "Lin turns in the quest.",
                "turn": "The reward raises Lin's level.",
                "payoff": "Lin reaches Lv.2.",
                "ending_hook": "A new route opens.",
                "level_target": "Lv.2",
                "cast": ["Lin"],
            }
        },
        genre="fantasy",
        style="plain",
        characters=[CharacterState(name="Lin", role="protagonist")],
        progression_ledger={"protagonist": {"level": "Lv.1", "unallocated_attribute_points": 0}},
        world_context={
            "power_system_spec": {
                "attribute_allocation": {
                    "mode": "free",
                    "points_per_level": 5,
                    "starting_level": 1,
                    "base_attributes": {"Intelligence": 5, "Constitution": 5},
                    "allow_carry": True,
                    "respec_rule": "Respec in town.",
                }
            }
        },
    )
    revised_plan = {
        "character_moves": [{"name": "Lin", "action": "Allocate the level reward."}],
        "chapter_intent": {"chapter_title": "First Level"},
        "event_plan": {
            "ordered_actions": ["Lin allocates the level reward."],
            "attribute_allocation_level_target": 2,
            "attribute_allocation_decision": {
                "mode": "allocate",
                "allocations": {"Intelligence": 5},
                "remaining": 0,
            },
            "chapter_satisfaction": {
                "core_event": "Lin turns in the starter quest.",
                "obstacle": "The gate is guarded.",
                "visible_payoff": "Lin reaches Lv.2.",
                "cost": "The route is now known to rivals.",
                "state_change": "Lin allocates five attribute points.",
                "next_hook": "A new route opens.",
            },
            "chapter_end_hook": {"type": "reveal", "strength": "medium", "content": "A new route opens."},
            "scene_chain": _outline_scene_chain("Lin"),
        },
        "memory_constraints": {},
    }
    orchestrator = StoryOrchestrator()
    calls: list[str] = []

    def fake_timed_chat(_story, _prompt, *, agent, **_kwargs):
        calls.append(agent)
        if agent == "planner":
            return json.dumps(revised_plan), ""
        if agent == "writer":
            return "", "writer stopped after gate observation"
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)

    orchestrator.generate_next_chapter(story)

    assert calls[:2] == ["planner", "writer"]


def test_outline_level_up_with_valid_attribute_decision_reaches_writer_unchanged(monkeypatch):
    decision = {
        "mode": "allocate",
        "allocations": {"Intelligence": 5},
        "remaining": 0,
        "reason": "Strengthen the starter spell.",
    }
    story = StoryState(
        story_id="s-outline-valid-attribute-decision",
        outline="Lin completes the starter quest.",
        outline_context={
            "chapter": {
                "chapter_number": 1,
                "title": "First Level",
                "goal": "Complete the starter quest.",
                "action": "Lin turns in the quest.",
                "payoff": "Lin reaches Lv.2.",
                "ending_hook": "A new route opens.",
                "level_target": "Lv.2",
                "attribute_allocation_decision": decision,
                "cast": ["Lin"],
                "scene_chain": _outline_scene_chain("Lin"),
            }
        },
        genre="fantasy",
        style="plain",
        characters=[CharacterState(name="Lin", role="protagonist")],
        progression_ledger={"protagonist": {"level": "Lv.1", "unallocated_attribute_points": 0}},
        world_context={
            "power_system_spec": {
                "attribute_allocation": {
                    "mode": "free",
                    "points_per_level": 5,
                    "starting_level": 1,
                    "base_attributes": {"Intelligence": 5},
                    "allow_carry": True,
                    "respec_rule": "Respec in town.",
                }
            }
        },
    )
    orchestrator = StoryOrchestrator()
    calls: list[str] = []
    captured: dict = {}
    original_body_prompt = orchestrator._body_prompt

    def capture_body_prompt(story, chapter_number, plan):
        captured["decision"] = plan["event_plan"]["attribute_allocation_decision"]
        return original_body_prompt(story, chapter_number, plan)

    def fake_timed_chat(_story, prompt, *, agent, **_kwargs):
        calls.append(agent)
        if agent == "planner":
            raise AssertionError("a valid outline decision must not be regenerated")
        if agent == "writer":
            return "", "writer stopped after plan observation"
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_body_prompt", capture_body_prompt)
    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)

    orchestrator.generate_next_chapter(story)

    assert calls == ["writer"]
    assert captured["decision"] == decision


def test_writer_request_failure_is_preserved_in_failed_bundle(monkeypatch):
    story = StoryState(
        story_id="s-writer-request-failure",
        outline="夜烬完成灰狼材料任务。",
        outline_context={
            "chapter": {
                "chapter_number": 1,
                "title": "第一笔收入",
                "goal": "完成灰狼材料任务",
                "obstacle": "灰狼刷新点竞争激烈",
                "action": "夜烬换到侧坡收集材料",
                "turn": "材料比预想更快凑齐",
                "payoff": "提交任务并升到二级",
                "ending_hook": "交易行出现新的收购单",
                "cast": ["夜烬"],
                "scene_chain": _outline_scene_chain("夜烬"),
            }
        },
        genre="game fantasy",
        style="webnovel",
        characters=[CharacterState(name="夜烬", role="protagonist")],
    )
    orchestrator = StoryOrchestrator()
    writer_error = "整章写作 第1章 model_request_failed:codexcli_failed:command not found"

    def fake_timed_chat(_story, _prompt, *, agent, **_kwargs):
        if agent == "writer":
            return "", writer_error
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)

    bundle = orchestrator.generate_next_chapter(story)

    assert bundle.quality_report["failure_reason"] == writer_error
    assert writer_error in bundle.quality_report["issues"]


def test_generation_attaches_resolved_trope_contract_to_review_without_extra_provider_calls(monkeypatch):
    """The resolved trope_contract on the simulation_plan must flow
    through the canonical review service exactly once per chapter so
    soft reviewers can see it, and the bounded flow must not double-
    dispatch the writer for a passing body.
    """
    from packages.story_core.review.contracts import ReviewResult
    from packages.story_core.review.service import ReviewService

    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)
    # Force the canonical hard gate to pass so the short test body
    # does not trigger a model revision. The soft review path still
    # runs normally so we can verify the simulation_plan propagation.
    def _passing_hard(self, *, body, context):
        return ReviewResult.from_findings([])

    monkeypatch.setattr(ReviewService, "run_hard_gate", _passing_hard)
    monkeypatch.setattr(
        "packages.story_core.chapter_seed.select_genre_plugins",
        lambda *args, **kwargs: [_trope_plugin()],
    )
    body = "Lin accepts the rain duel, wins trust without revealing the hidden card, and keeps the larger arc open."
    memory = json.dumps(
        {
            "summary": "Lin accepts the duel.",
            "facts": [{"text": "Lin accepted the rain duel", "evidence": "accepts the rain duel"}],
            "unresolved_threads": [],
            "next_focus": "check who sent the invitation",
            "chapter_title": "Rain Duel",
            "character_updates": [],
            "ledger_updates": {},
            "ledger_evidence": {},
        },
        ensure_ascii=False,
    )
    seen_contracts: list[dict | None] = []
    # The plot_spine soft reviewer is the single source the bounded
    # service runs against the simulation_plan; capture it to confirm
    # the resolved trope_contract reaches the soft review path.
    def plot_spine_spy(_body, simulation_plan):
        seen_contracts.append(simulation_plan.get("trope_contract") if isinstance(simulation_plan, dict) else None)
        return {"pass": True, "issues": [], "revision_plan": []}

    monkeypatch.setattr(orchestrator_module, "review_plot_spine_completion", plot_spine_spy)

    def run_story(outline_context):
        story = StoryState(
            story_id=f"s-trope-review-{bool(outline_context)}",
            outline="urban story",
            genre="urban",
            genre_plugin_ids=["urban"],
            style="plain",
            outline_context=outline_context,
            characters=[CharacterState(name="Lin", role="protagonist")],
        )
        orchestrator = StoryOrchestrator()
        calls: list[str] = []

        def fake_timed_chat(_story, _prompt, *, agent, **_kwargs):
            calls.append(agent)
            if agent == "planner":
                raise AssertionError("complete outline_context should skip planner")
            if agent == "writer":
                return body, ""
            if agent == "memory":
                return memory, ""
            raise AssertionError(agent)

        monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
        return orchestrator.generate_next_chapter(story), calls

    valid_context = {
        "active_arc": {"trope_id": "trial"},
        "chapter": {
            "chapter_number": 1,
            "title": "Rain Duel",
            "goal": "answer the invitation",
            "obstacle": "public pressure",
            "action": "accept the rain duel",
            "turn": "wins trust without revealing the hidden card",
            "payoff": "wins trust",
            "ending_hook": "check who sent the invitation",
            "trope_beat": "accept the rain duel",
            "cast": ["Lin"],
            "scene_chain": _outline_scene_chain("Lin"),
        },
    }
    invalid_context = {
        "chapter": {
            "chapter_number": 1,
            "title": "Rain Duel",
            "goal": "answer the invitation",
            "obstacle": "public pressure",
            "action": "accept the rain duel",
            "turn": "wins trust without revealing the hidden card",
            "payoff": "wins trust",
            "ending_hook": "check who sent the invitation",
            "cast": ["Lin"],
            "scene_chain": _outline_scene_chain("Lin"),
        },
    }

    _, calls_with_contract = run_story(valid_context)
    _, calls_without_contract = run_story(invalid_context)

    # Bounded flow: a passing hard gate means the controller does not
    # double-dispatch the writer for a revision.
    assert calls_with_contract == calls_without_contract == ["writer"]
    # The valid context attaches the resolved trope_contract to the
    # simulation_plan that reaches the soft reviewers; the invalid
    # context never resolves one.
    assert seen_contracts[0] == {
        "template_id": "trial",
        "name": "Trial Stage",
        "trigger": "rain invitation",
        "current_beat": "accept the rain duel",
        "payoff": "win trust without revealing the hidden card",
        "avoid": ["do not switch tropes"],
    }
    assert seen_contracts[1] is None


def test_attach_trope_contract_to_simulation_plan_deepcopies_only_resolved_contract():
    contract = {
        "template_id": "trial",
        "current_beat": "accept the rain duel",
        "payoff": "win trust without revealing the hidden card",
        "avoid": ["do not switch tropes"],
    }
    seed = {
        "trope_contract": contract,
        "simulation_blueprint": {"trope_templates": [{"id": "trial"}]},
    }
    plan = {"review_focus": ["existing"]}

    attached = orchestrator_module._attach_trope_contract_to_simulation_plan(plan, seed)

    contract["avoid"].append("mutated")
    assert attached["trope_contract"]["avoid"] == ["do not switch tropes"]
    assert attached["review_focus"] == ["existing"]
    assert "trope_templates" not in attached
    assert "trope_candidates" not in attached


def test_trope_beat_miss_remains_advisory_without_full_chapter_revision(passing_review_service, monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)
    initial_body = "林站在屋檐下想了想明天的安排，最后没有回应邀请就离开了。"
    revised_body = "林在雨夜接下挑战，赢得信任且不暴露底牌。"
    revision_prompts: list[str] = []

    def review(_chapter, body, *_args, **_kwargs):
        if body == initial_body:
            return {
                "pass": False,
                "issues": ["套路节点未兑现：本章未写出当前节点「雨夜接下挑战」的正文动作或反馈。"],
                "revision_plan": ["按套路节点改：本章必须兑现「雨夜接下挑战」，并落到回报「赢得信任且不暴露底牌」。"],
                "plot_spine_review": {
                    "diagnostics": {
                        "trope_avoid": ["不要换套路", "不要提前解决整条主线"],
                    }
                },
            }
        return {"pass": True, "issues": [], "revision_plan": []}

    monkeypatch.setattr(orchestrator_module, "_review_chapter_body", review)
    story = StoryState(
        story_id="s-trope-revision-gate",
        outline="urban story",
        genre="urban",
        style="plain",
        outline_context={
            "chapter": {
                "chapter_number": 1,
                "title": "Rain Duel",
                "goal": "answer the invitation",
                "obstacle": "public pressure",
                "action": "accept the rain duel",
                "turn": "wins trust without revealing the hidden card",
                "payoff": "wins trust",
                "ending_hook": "check who sent the invitation",
                "cast": ["Lin"],
                "scene_chain": _outline_scene_chain("Lin"),
            }
        },
        characters=[CharacterState(name="Lin", role="protagonist")],
    )
    orchestrator = StoryOrchestrator()
    calls: list[str] = []
    memory = json.dumps(
        {
            "summary": "林接下挑战。",
            "facts": [{"text": "林雨夜接下挑战", "evidence": "雨夜接下挑战"}],
            "unresolved_threads": [],
            "next_focus": "追查邀请来源",
            "chapter_title": "雨夜挑战",
            "character_updates": [],
            "ledger_updates": {},
            "ledger_evidence": {},
        },
        ensure_ascii=False,
    )

    writer_calls = 0

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        nonlocal writer_calls
        calls.append(agent)
        if agent == "planner":
            raise AssertionError("complete outline_context should skip planner")
        if agent == "writer" and writer_calls == 0:
            writer_calls += 1
            return initial_body, ""
        if agent == "writer":
            writer_calls += 1
            revision_prompts.append(prompt)
            return revised_body, ""
        if agent == "memory":
            return memory, ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)

    bundle = orchestrator.generate_next_chapter(story)

    assert calls == ["writer"]
    assert bundle.body == initial_body
    assert revision_prompts == []


def test_incomplete_chapter_outline_uses_planner_model(monkeypatch):
    story = StoryState(
        story_id="s-model-planning-fallback",
        outline="主角继续推进任务。",
        outline_context={"chapter": {"chapter_number": 1, "goal": "继续升级"}},
        genre="fantasy",
        style="webnovel",
        characters=[CharacterState(name="林照", role="protagonist")],
    )
    orchestrator = StoryOrchestrator()
    planner_calls = 0
    original_timed_chat = orchestrator._timed_chat

    def count_planner(*args, **kwargs):
        nonlocal planner_calls
        if kwargs.get("agent") == "planner":
            planner_calls += 1
        return original_timed_chat(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "_timed_chat", count_planner)

    bundle = orchestrator.generate_next_chapter(story)

    assert bundle.body
    assert planner_calls == 1


def test_only_whole_chapter_pipeline_remains_in_production():
    orchestrator = StoryOrchestrator()
    story = StoryState(
        story_id="s-whole-chapter-only",
        outline="主角处理眼前冲突。",
        genre="都市",
        style="",
    )

    assert "分段" not in orchestrator._body_prompt(
        story,
        1,
        {"event_plan": {"chapter_title": "眼前冲突"}},
    )


def _post_draft_plan() -> dict:
    return {
        "character_moves": [
            {"name": "林照", "goal": "去东院", "emotion": "愤怒", "action": "搬炉", "priority": 1}
        ],
        "chapter_intent": {"chapter_title": "计划标题", "next_focus": "去东院"},
        "event_plan": {
            "turn": "计划把炉搬到东院",
            "next_focus": "去东院",
            "world_reactions": [],
            "chapter_satisfaction": {
                "core_event": "林照处理断香炉的去向",
                "obstacle": "周执事要求林照立刻作出决定",
                "visible_payoff": "林照确认断香炉仍有调查价值",
                "cost": "林照的行动引起周执事注意",
                "state_change": "断香炉从无人看管变为由林照负责",
                "next_hook": "账房要求林照次日回话",
            },
            "chapter_end_hook": {
                "type": "悬念钩",
                "strength": "medium",
                "content": "账房要求林照次日回话",
            },
        },
        "memory_constraints": {
            "ledger_updates": {"protagonist": {"location": "东院", "spirit_stones": 99}}
        },
        "chapter_summary": {
            "summary": "计划中的错误摘要",
            "facts": ["林照得到九十九枚灵石"],
            "unresolved_threads": ["东院的秘密"],
            "next_focus": "去东院",
            "chapter_title": "计划标题",
        },
    }


def _post_draft_memory_payload() -> dict:
    return {
        "summary": "林照把断香炉搬回偏殿，周执事让他明早去账房。",
        "facts": [{"text": "断香炉已搬回偏殿", "evidence": "把断香炉搬回偏殿"}],
        "unresolved_threads": [{"text": "账房为何找林照", "evidence": "明早去账房回话"}],
        "next_focus": "明早去账房",
        "chapter_title": "搬炉",
        "character_updates": [
            {"name": "林照", "goal": "明早去账房", "location": "偏殿", "evidence": "林照把断香炉搬回偏殿"}
        ],
        "ledger_updates": {"protagonist": {"location": "偏殿"}},
        "ledger_evidence": {"protagonist.location": "搬回偏殿"},
    }


def _disable_optional_writing_passes(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        orchestrator_module,
        "_review_chapter_body",
        lambda *_args, **_kwargs: {"pass": True, "issues": []},
    )


def _reviewable_body(text: str) -> str:
    compact_chars = max(1, len("".join(text.split())))
    return text * (4300 // compact_chars + 1)


@pytest.mark.parametrize(
    ("body_chars", "expected_ceiling", "expected_tokens"),
    [(3000, 4200, 4700), (5000, 5000, 5500), (6000, 5500, 6000)],
)
def test_revision_char_ceiling_tracks_original_without_exceeding_chapter_limits(
    body_chars, expected_ceiling, expected_tokens
):
    body = "字" * body_chars

    assert orchestrator_module._revision_char_ceiling(body) == expected_ceiling
    assert orchestrator_module._revision_max_tokens(body) == expected_tokens


def test_revision_prompt_requires_local_replacement_with_a_concrete_hard_ceiling():
    story = StoryState(
        story_id="s-revision-ceiling",
        outline="林照处理断香炉。",
        genre="xuanhuan",
        style="幽默",
        characters=[CharacterState(name="林照", role="主角")],
    )
    body = "林照把断香炉搬进偏殿。" * 400

    prompt = StoryOrchestrator()._render_revision_prompt(story, 1, body, _post_draft_plan(), {"issues": []})

    assert f"硬上限：{orchestrator_module._revision_char_ceiling(body)}字" in prompt
    assert "只能通过替换、合并、删除和必要的局部补写完成" in prompt
    assert "不要因为补问题而扩写整章" in prompt


def test_over_length_body_is_fixed_in_single_revise_without_compression_model_call(monkeypatch):
    """The plan forbids a second model body modification after the
    bounded controller. Over-length must be reported as a
    ``length.out_of_range`` blocking finding inside the same revise
    pass — no separate ``章节压缩`` writer call.

    This test runs the *real* ``ReviewService`` (no canned
    ``run_hard_gate`` override) and spies on the orchestrator's
    constructor kwargs. Two assertions make the wiring regression
    fail loud:

    1. ``hard_max_chars`` must equal ``CHAPTER_HARD_MAX_CHARS`` so
       ``_run_length_check`` is configured to surface
       ``length.out_of_range`` on over-length bodies.
    2. The bounded controller must drive the body back into the
       length window via a single ``审稿改稿`` call, never via a
       separate ``章节压缩`` writer call.

    A future refactor that drops ``hard_max_chars`` from the
    orchestrator's ``ReviewService`` constructor — or that
    re-introduces the compression model call — will fail one or
    both checks.
    """
    from packages.story_core.review.service import ReviewService

    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    # The bounded controller alone must drive the body back into
    # range. ``_should_compress_chapter`` is intentionally NOT
    # monkeypatched — the orchestrator no longer asks.
    over_length_body = "原" * 5800
    in_range_body = "正" * 4800

    captured_kwargs: dict = {}

    class _SpyReviewService(ReviewService):
        """Spy + length-only ``ReviewService``.

        Records the kwargs the orchestrator handed to the
        ``ReviewService`` constructor so the wire check below can
        assert ``hard_max_chars`` is set. Forwards only the length
        configuration (``hard_max_chars`` / ``min_chars`` /
        ``char_tolerance``) to the real ``ReviewService.__init__``,
        and forces every other reviewer callable to ``None`` so the
        synthetic test body (a single character repeated N times)
        cannot trigger arbitrary findings from the orchestrator's
        real continuity / fragments / consistency / critical /
        genre / soft reviewers. The bounded controller's behavior
        under test is the length-only path, and we want the test
        to be deterministic.
        """

        def __init__(self, **kwargs):
            captured_kwargs.clear()
            captured_kwargs.update(kwargs)
            super().__init__(
                hard_max_chars=int(kwargs.get("hard_max_chars") or 0),
                min_chars=int(kwargs.get("min_chars") or 0),
                char_tolerance=int(kwargs.get("char_tolerance") or 0),
                review_continuity=None,
                review_fragments=None,
                review_consistency=None,
                review_critical_rules=None,
                profile_for=None,
                review_style=None,
                review_prose_quality=None,
                review_adversarial_cuts=None,
                review_ai_flavor=None,
                review_reader_feel=None,
                review_cold_reader=None,
                review_plot_spine=None,
            )

    monkeypatch.setattr(orchestrator_module, "ReviewService", _SpyReviewService)

    # Pin the soft review to a clean pass so the synthetic test
    # body cannot trigger arbitrary prose / AI-flavor / cold-reader
    # findings. The hard gate still runs the real ``_run_length_check``
    # with the production ceiling — that is the path under test.
    from packages.story_core.review.contracts import ReviewResult

    def _passing_soft(self, *, body, context):
        return ReviewResult.from_findings([])

    monkeypatch.setattr(ReviewService, "run_soft_review", _passing_soft)

    story = StoryState(
        story_id="s-length-in-revise",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角", location="祖祠")],
    )
    orchestrator = StoryOrchestrator()
    agent_calls: list[str] = []

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        agent_calls.append((agent, stage))
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer" and stage.startswith("整章写作"):
            return over_length_body, ""
        if agent == "writer" and "审稿改稿" in stage:
            # The revise prompt must tell the writer to also
            # shorten the body. Verify the length instruction is
            # in the prompt so the LLM has what it needs.
            assert "length.out_of_range" in prompt or "硬上限" in prompt or "字数" in prompt
            return in_range_body, ""
        if agent == "memory":
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError((agent, stage))

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    # Wire check: the orchestrator must hand the production
    # hard ceiling to ``ReviewService`` so ``_run_length_check``
    # surfaces ``length.out_of_range`` on over-length bodies.
    assert captured_kwargs.get("hard_max_chars") == orchestrator_module.CHAPTER_HARD_MAX_CHARS, (
        "Orchestrator must wire hard_max_chars=CHAPTER_HARD_MAX_CHARS into "
        f"ReviewService for the length check to surface length.out_of_range. "
        f"Got: {captured_kwargs.get('hard_max_chars')!r}"
    )

    # The bounded controller's revise is the ONLY model body
    # modification — no separate compression writer call ever fires.
    writer_stages = [stage for agent, stage in agent_calls if agent == "writer"]
    assert not any(stage.startswith("章节压缩") for stage in writer_stages)
    assert sum(1 for stage in writer_stages if stage.startswith("整章写作")) == 1
    assert sum(1 for stage in writer_stages if "审稿改稿" in stage) == 1
    # The saved body is the revised one, already in the length
    # window.
    assert bundle.body == in_range_body
    assert orchestrator_module._chapter_char_count(bundle.body) <= orchestrator_module.MAX_CHAPTER_CHARS + orchestrator_module.CHAPTER_MAX_CHAR_TOLERANCE


@pytest.mark.parametrize("genre_plugin_ids", [["xuanhuan"], []])
def test_runtime_expansion_prompt_uses_non_game_scope_without_game_id(passing_review_service, monkeypatch, genre_plugin_ids):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        orchestrator_module,
        "_review_chapter_body",
        lambda *_args, **_kwargs: {"pass": True, "issues": [], "revision_plan": []},
    )
    initial_body = "林照登录游戏后看见背包掉落异常。" * 30
    expanded_body = _reviewable_body("林照守住断香炉，逼周执事先开口。")
    story = StoryState(
        story_id=f"s-expansion-non-game-{'explicit' if genre_plugin_ids else 'untyped'}",
        outline="主角登录游戏，查看掉落、背包和任务面板。",
        genre="",
        genre_plugin_ids=genre_plugin_ids,
        style="白描",
        current_chapter=1,
        characters=[CharacterState(name="林照", role="主角", location="祖祠")],
    )
    orchestrator = StoryOrchestrator()
    expansion_prompts = []

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer" and stage.startswith("整章写作"):
            return initial_body, ""
        if agent == "writer" and stage.startswith("章节扩写"):
            expansion_prompts.append(prompt)
            return expanded_body, ""
        if agent == "memory":
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError((agent, stage))

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)

    orchestrator.generate_next_chapter(story)

    assert len(expansion_prompts) == 1
    instructions = expansion_prompts[0].split("原正文：", 1)[0]
    assert "不得新增原文或章节计划之外的设定、能力、人物关系、事件结算。" in instructions
    assert all(term not in instructions for term in ("交易", "委托", "修理", "药水"))


def test_orchestrator_persists_only_memory_extracted_after_final_body(passing_review_service, monkeypatch):
    _disable_optional_writing_passes(monkeypatch)
    monkeypatch.setattr(
        orchestrator_module,
        "apply_simulated_state_deltas",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("simulated delta must not persist")),
    )
    story = StoryState(
        story_id="s-final-memory-order",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角", current_emotion="平静", location="祖祠")],
        progression_ledger={"protagonist": {"location": "祖祠"}},
    )
    final_body = _reviewable_body("林照把断香炉搬回偏殿。周执事让他明早去账房回话。")
    calls = []
    orchestrator = StoryOrchestrator()

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        calls.append((agent, stage, prompt))
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            return final_body, ""
        if agent == "memory":
            assert final_body in prompt
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    assert [item[0] for item in calls] == ["planner", "writer", "memory"]
    assert bundle.chapter_summary["facts"] == ["断香炉已搬回偏殿"]
    assert bundle.updated_story.progression_ledger["protagonist"]["location"] == "偏殿"
    assert "spirit_stones" not in bundle.updated_story.progression_ledger["protagonist"]
    assert bundle.updated_story.characters[0].location == "偏殿"
    assert bundle.updated_story.characters[0].current_emotion == "平静"
    assert bundle.chapter_summary["primary_conflict"] == {}
    assert bundle.chapter_summary["secondary_conflict"] == {}
    assert bundle.chapter_summary["event_beat"] == {}
    assert "计划中的错误摘要" not in bundle.updated_story.model_dump_json()
    assert "九十九枚灵石" not in bundle.updated_story.model_dump_json()
    assert bundle.simulation_plan["memory_sync"]["status"] == "ok"
    assert bundle.quality_report["memory_sync"]["status"] == "ok"


def test_orchestrator_retries_director_once_after_invalid_json(monkeypatch):
    _disable_optional_writing_passes(monkeypatch)
    story = StoryState(
        story_id="s-director-json-retry",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角", location="祖祠")],
    )
    orchestrator = StoryOrchestrator()
    planner_calls = 0

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        nonlocal planner_calls
        if agent == "planner":
            planner_calls += 1
            if planner_calls == 1:
                return "", "计划返回内容不是有效 JSON"
            assert "上一次返回不是有效 JSON" in prompt
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            return "林照把断香炉搬回偏殿。", ""
        if agent == "memory":
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)

    bundle = orchestrator.generate_next_chapter(story)

    assert planner_calls == 2
    assert bundle.body == "林照把断香炉搬回偏殿。"


def test_orchestrator_retries_writer_once_after_empty_body(passing_review_service, monkeypatch):
    _disable_optional_writing_passes(monkeypatch)
    story = StoryState(
        story_id="s-writer-empty-retry",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角", location="祖祠")],
    )
    orchestrator = StoryOrchestrator()
    writer_calls = 0

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        nonlocal writer_calls
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            writer_calls += 1
            if writer_calls == 1:
                return "", "正文返回为空"
            assert "上一次没有返回正文" in prompt
            return "林照把断香炉搬回偏殿。", ""
        if agent == "memory":
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)

    bundle = orchestrator.generate_next_chapter(story)

    assert writer_calls == 2
    assert bundle.body == "林照把断香炉搬回偏殿。"


def test_orchestrator_memory_failure_uses_body_fallback_without_planned_state(passing_review_service, monkeypatch):
    _disable_optional_writing_passes(monkeypatch)
    monkeypatch.setattr(orchestrator_module, "apply_simulated_state_deltas", lambda *_args, **_kwargs: None)
    story = StoryState(
        story_id="s-final-memory-fallback",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角", current_emotion="平静", location="祖祠")],
        progression_ledger={"protagonist": {"location": "祖祠"}},
    )
    final_body = _reviewable_body("林照把断香炉搬回偏殿。")
    orchestrator = StoryOrchestrator()

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            return final_body, ""
        if agent == "memory":
            return "", "memory unavailable"
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    assert bundle.simulation_plan["memory_sync"]["status"] == "fallback"
    assert bundle.updated_story.progression_ledger["protagonist"]["location"] == "祖祠"
    assert "spirit_stones" not in bundle.updated_story.progression_ledger["protagonist"]
    assert bundle.updated_story.characters[0].location == "祖祠"
    assert bundle.updated_story.characters[0].current_emotion == "平静"
    assert bundle.chapter_summary["summary"] in final_body
    assert bundle.chapter_summary["next_focus"] == ""
    assert bundle.chapter_summary["primary_conflict"] == {}
    assert bundle.chapter_summary["secondary_conflict"] == {}
    assert bundle.chapter_summary["event_beat"] == {}
    assert "计划中的错误摘要" not in bundle.updated_story.model_dump_json()


def test_grounded_memory_without_title_does_not_use_director_conflict_for_title(passing_review_service, monkeypatch):
    _disable_optional_writing_passes(monkeypatch)
    plan = _post_draft_plan()
    plan["character_moves"] = [
        {"name": "夜烬", "goal": "回村补给并购买药水", "emotion": "平静", "action": "回村", "priority": 1}
    ]
    plan["chapter_intent"]["chapter_title"] = "导演计划标题"
    plan["chapter_intent"]["next_focus"] = "回村补给并购买药水"
    plan["event_plan"]["next_focus"] = "回村补给并购买药水"
    body = _reviewable_body("夜烬打倒灰狼。")
    memory = {
        "summary": body,
        "facts": [{"text": "夜烬打倒灰狼", "evidence": "夜烬打倒灰狼"}],
        "unresolved_threads": [],
        "next_focus": "",
        "chapter_title": "",
        "character_updates": [],
        "ledger_updates": {},
        "ledger_evidence": {},
    }
    story = StoryState(
        story_id="s-title-from-body-only",
        outline="夜烬在新手村打灰狼。",
        genre="game_webnovel",
        style="白描",
        characters=[CharacterState(name="夜烬", role="主角")],
    )
    orchestrator = StoryOrchestrator()

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        if agent == "planner":
            return json.dumps(plan, ensure_ascii=False), ""
        if agent == "writer":
            return body, ""
        if agent == "memory":
            return json.dumps(memory, ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    assert bundle.quality_report["memory_sync"]["status"] == "ok"
    assert bundle.chapter_title != "导演计划标题"
    assert bundle.chapter_title != "回村补给"


def test_refresh_revised_bundle_reextracts_memory_from_revised_body(monkeypatch):
    _disable_optional_writing_passes(monkeypatch)
    base_story = StoryState(
        story_id="s-revised-memory",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角", current_emotion="平静", location="祖祠")],
        progression_ledger={"protagonist": {"location": "祖祠"}},
    )
    initial_body = "林照把断香炉搬回偏殿。周执事让他明早去账房回话。"
    orchestrator = StoryOrchestrator()

    def initial_chat(_story, prompt, *, agent, stage, **_kwargs):
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            return initial_body, ""
        if agent == "memory":
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", initial_chat)
    bundle = orchestrator.generate_next_chapter(base_story)
    bundle.body = "林照把断香炉搬到后院。"
    revised_memory = {
        "summary": "林照把断香炉搬到后院。",
        "facts": [{"text": "断香炉已搬到后院", "evidence": "把断香炉搬到后院"}],
        "unresolved_threads": [],
        "next_focus": "",
        "chapter_title": "后院",
        "character_updates": [
            {"name": "林照", "location": "后院", "evidence": "林照把断香炉搬到后院"}
        ],
        "ledger_updates": {"protagonist": {"location": "后院"}},
        "ledger_evidence": {"protagonist.location": "搬到后院"},
    }

    def revised_chat(_story, prompt, *, agent, stage, **_kwargs):
        assert agent == "memory"
        assert bundle.body in prompt
        return json.dumps(revised_memory, ensure_ascii=False), ""

    monkeypatch.setattr(orchestrator, "_timed_chat", revised_chat)
    refreshed = orchestrator.refresh_revised_bundle_metadata(base_story, bundle)

    assert refreshed.chapter_summary["summary"] == revised_memory["summary"]
    assert refreshed.chapter_summary["facts"] == ["断香炉已搬到后院"]
    assert refreshed.updated_story.characters[0].location == "后院"
    assert refreshed.updated_story.progression_ledger["protagonist"]["location"] == "后院"
    assert refreshed.simulation_plan["memory_sync"]["status"] == "ok"
    assert refreshed.quality_report["memory_sync"]["status"] == "ok"
    assert "偏殿" not in refreshed.chapter_summary["summary"]


@pytest.mark.real_review_gate
def test_memory_extraction_uses_selected_revision_body(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)
    initial_body = _reviewable_body("林照按计划把断香炉留在东院。")
    revised_body = _reviewable_body("林照把断香炉搬回偏殿。周执事让他明早去账房回话。")

    # The bounded review flow runs the canonical ReviewService. Make
    # the first call block (so the controller triggers a revision)
    # and the second call pass (so the candidate is accepted).
    from packages.story_core.review.contracts import ReviewFinding, ReviewResult
    from packages.story_core.review.service import ReviewService

    _hard_calls = {"count": 0}

    def _variable_hard(self, *, body, context):
        _hard_calls["count"] += 1
        if body == initial_body:
            return ReviewResult.from_findings(
                [
                    ReviewFinding(
                        code="continuity.conflict",
                        category="hard",
                        blocking=True,
                        message="连续性冲突：地点错误",
                        suggestion="按场景修正地点。",
                        source="continuity",
                    )
                ]
            )
        return ReviewResult.from_findings([])

    monkeypatch.setattr(ReviewService, "run_hard_gate", _variable_hard)
    monkeypatch.setattr(
        orchestrator_module,
        "choose_best_revision",
        lambda **kwargs: {
            "body": kwargs["candidate_body"],
            "quality": kwargs["candidate_quality"],
            "report": {"selected": "candidate"},
        },
    )
    story = StoryState(
        story_id="s-memory-after-revision",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角", location="祖祠")],
    )
    orchestrator = StoryOrchestrator()
    calls = []

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        calls.append((agent, stage))
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer" and "审稿改稿" not in stage:
            return initial_body, ""
        if agent == "writer":
            return revised_body, ""
        if agent == "memory":
            assert revised_body in prompt
            assert initial_body not in prompt
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    assert [item[0] for item in calls] == ["planner", "writer", "writer", "memory"]
    assert bundle.body == revised_body
    assert bundle.chapter_summary["facts"] == ["断香炉已搬回偏殿"]


def test_dialogue_advice_does_not_trigger_full_revision_but_updates_memory(passing_review_service, monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)
    initial_body = _reviewable_body("林照问：“账房？”周执事说：“明早。”")

    def review(_chapter, body, *_args, **_kwargs):
        return {"pass": False, "issues": ["对话不够自然，人物只说短句。"]}

    monkeypatch.setattr(orchestrator_module, "_review_chapter_body", review)
    story = StoryState(
        story_id="s-dialogue-revision",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角")],
    )
    orchestrator = StoryOrchestrator()
    calls = []

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        calls.append((agent, stage))
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            return initial_body, ""
        if agent == "memory":
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    assert [agent for agent, _stage in calls] == ["planner", "writer", "memory"]
    assert bundle.body == initial_body
    assert "revision_safety" not in bundle.quality_report
    assert bundle.quality_report["memory_sync"]["status"] != "skipped"
    assert bundle.updated_story.writing_lessons == []


def test_ordinary_prose_advice_does_not_trigger_revision_or_learning(passing_review_service, monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)
    body = _reviewable_body("林照把断香炉搬回偏殿。周执事让他明早去账房回话。")
    monkeypatch.setattr(
        orchestrator_module,
        "_review_chapter_body",
        lambda *_args, **_kwargs: {"pass": False, "issues": ["章末动作还可以更具体。"]},
    )
    story = StoryState(
        story_id="s-prose-advice",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角")],
    )
    orchestrator = StoryOrchestrator()
    calls = []

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        calls.append((agent, stage))
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            return body, ""
        if agent == "memory":
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    assert [agent for agent, _stage in calls] == ["planner", "writer", "memory"]
    assert "revision_safety" not in bundle.quality_report
    assert bundle.updated_story.writing_lessons == []


def test_unresolved_dialogue_advice_is_not_sent_to_full_revision(passing_review_service, monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)
    body = _reviewable_body("林照问：“账房？”周执事说：“明早。”")
    monkeypatch.setattr(
        orchestrator_module,
        "_review_chapter_body",
        lambda *_args, **_kwargs: {"pass": False, "issues": ["对话不够自然，人物只说短句。"]},
    )
    story = StoryState(
        story_id="s-unresolved-dialogue",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角")],
    )
    orchestrator = StoryOrchestrator()

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            return body, ""
        if agent == "memory":
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    assert bundle.body == body
    assert "revision_safety" not in bundle.quality_report
    assert "accepted_revision_actions" not in bundle.quality_report
    assert bundle.quality_report["memory_sync"]["status"] != "skipped"
    assert bundle.updated_story.writing_lessons == []


@pytest.mark.real_review_gate
def test_progress_artifacts_expose_rewrite_inputs_for_transparency(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)

    # The bounded flow runs the canonical ReviewService. Block on
    # the first body, pass on the revised, so the controller fires
    # the rewrite event the test asserts against.
    from packages.story_core.review.contracts import ReviewFinding, ReviewResult
    from packages.story_core.review.service import ReviewService

    def _variable_hard(self, *, body, context):
        if body == "first draft":
            return ReviewResult.from_findings(
                [
                    ReviewFinding(
                        code="continuity.conflict",
                        category="hard",
                        blocking=True,
                        message="连续性冲突：人物状态与上一章不一致。",
                        suggestion="把对话拆成两三句，让主角先停顿。",
                        source="continuity",
                    )
                ]
            )
        return ReviewResult.from_findings([])

    monkeypatch.setattr(ReviewService, "run_hard_gate", _variable_hard)
    story = StoryState(
        story_id="s-progress-rewrite-transparency",
        outline="夜烬在灰烬村第一次试炼失落与秩序。",
        genre="game fantasy",
        style="webnovel",
        characters=[CharacterState(name="夜烬", role="protagonist"), CharacterState(name="洛婶", role="npc")],
    )
    orchestrator = StoryOrchestrator()
    events: list[object] = []
    safety_results: list[dict] = []
    revision_max_tokens: list[int] = []
    real_choose_best_revision = orchestrator_module.choose_best_revision

    def capture_safety(**kwargs):
        result = real_choose_best_revision(**kwargs)
        safety_results.append({"inputs": kwargs, "result": result})
        return result

    monkeypatch.setattr(orchestrator_module, "choose_best_revision", capture_safety)

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        if agent == "planner":
            plan = {
                "character_moves": [{"name": "夜烬", "goal": "找到第一条可复盘支线", "emotion": "紧张", "action": "观察"}],
                "chapter_intent": {"chapter_title": "第一章 开局试验", "next_focus": "推进清道夫任务"},
                "event_plan": {
                    "chapter_title": "第一章 开局试验",
                    "next_focus": "推进清道夫任务",
                    "turn": "稳住局面",
                    "chapter_satisfaction": {
                        "core_event": "夜烬确认第一条支线线索",
                        "obstacle": "灰烬村线索混乱且时间有限",
                        "visible_payoff": "夜烬找到可复盘的任务入口",
                        "cost": "夜烬的试探引起旁人警觉",
                        "state_change": "清道夫任务从未知变为可以推进",
                        "next_hook": "洛婶透露下一条任务线索",
                    },
                    "chapter_end_hook": {
                        "type": "悬念钩",
                        "strength": "medium",
                        "content": "洛婶透露下一条任务线索",
                    },
                },
                "memory_constraints": {},
                "chapter_summary": {
                    "summary": "夜烬在灰烬村完成第一次试练。",
                    "facts": ["见习冒险者第一次见到掉落异常"],
                    "unresolved_threads": [],
                    "next_focus": "补足基础生计",
                    "chapter_title": "第一章 开局试验",
                },
            }
            return json.dumps(plan, ensure_ascii=False), ""
        if agent == "writer" and stage.startswith("整章写作"):
            return "first draft", ""
        if agent == "writer" and "审稿改稿" in stage:
            revision_max_tokens.append(int(_kwargs["max_tokens"]))
            return "revised draft", ""
        if agent == "memory":
            memory = {
                "summary": "夜烬稳住了第一轮输出。",
                "facts": [{"text": "完成第一轮试练", "evidence": "first draft"}],
                "unresolved_threads": [],
                "next_focus": "",
                "chapter_title": "第一章 开局试验",
                "character_updates": [{"name": "夜烬", "current_emotion": "警惕", "location": "灰烬村"}],
                "ledger_updates": {},
                "ledger_evidence": {},
            }
            return json.dumps(memory, ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    with generation_progress(events.append):
        orchestrator.generate_next_chapter(story)

    dict_steps = [entry for entry in events if isinstance(entry, dict)]
    rewrite_event = next(
        (entry for entry in dict_steps if str(entry.get("message", "")).startswith("审稿改稿中")),
        None,
    )
    assert rewrite_event is not None
    artifact = rewrite_event.get("artifact")
    assert isinstance(artifact, dict), artifact
    inputs = artifact.get("inputs", {})
    assert isinstance(inputs, dict)
    assert "character_cards" in inputs
    assert "outline" in inputs
    assert "writer_plan" in inputs
    assert "review_snapshot" in inputs
    assert isinstance(inputs.get("character_cards"), dict)
    assert inputs.get("outline")
    assert safety_results
    safety_inputs = safety_results[0]["inputs"]
    assert safety_inputs["original_quality"]["has_hard_errors"] is True
    assert safety_inputs["candidate_quality"]["has_hard_errors"] is False
    assert revision_max_tokens == [orchestrator_module._revision_max_tokens("first draft")]

    completion_event = next(
        entry for entry in dict_steps if entry.get("message") == "审稿改稿完成"
    )
    outputs = completion_event["artifact"]["outputs"]
    safety_report = safety_results[0]["result"]["report"]
    for key in (
        "reason",
        "original_score",
        "candidate_score",
        "original_issue_count",
        "candidate_issue_count",
        "original_chars",
        "candidate_chars",
    ):
        assert outputs[key] == safety_report[key]

    plan_event = next(
        (entry for entry in dict_steps if str(entry.get("message", "")).startswith("剧情计划生成中")),
        None,
    )
    assert plan_event is not None
    plan_artifact = plan_event.get("artifact")
    assert isinstance(plan_artifact, dict)
    plan_inputs = plan_artifact.get("inputs", {})
    assert "story_outline" in plan_inputs
    assert "character_cards" in plan_inputs
    assert "world_simulation" not in plan_artifact.get("used_modules", [])

    director_done = next(
        (entry for entry in dict_steps if entry.get("message") == "剧情计划生成完成"),
        None,
    )
    assert director_done is not None
    assert "world_simulation" not in director_done["artifact"].get("used_modules", [])
    assert not any(entry.get("stage") == "world_response" for entry in dict_steps)

    workflow_steps = {
        entry["artifact"]["workflow_step"]["id"]: entry
        for entry in dict_steps
        if isinstance(entry.get("artifact"), dict)
        and isinstance(entry["artifact"].get("workflow_step"), dict)
    }
    assert "load_writer_skills" not in workflow_steps
    assert not any(
        isinstance(entry.get("artifact"), dict)
        and entry["artifact"].get("key") == "writer_skill_context"
        for entry in dict_steps
    )
    assert [
        step_id
        for step_id in (
            "read_outline",
            "read_characters",
            "read_world_state",
            "director_plan",
            "prepare_writing_context",
            "write_body",
            "review_body",
            "write_memory",
        )
        if step_id not in workflow_steps
    ] == []
    assert workflow_steps["read_characters"]["artifact"]["workflow_step"]["reads"]
    assert workflow_steps["director_plan"]["artifact"]["outputs"]
    assert workflow_steps["prepare_writing_context"]["source"] == "context_builder"
    assert workflow_steps["write_body"]["artifact"]["outputs"]["body_chars"] > 0


def test_workflow_step_reports_explicit_reads_and_outputs():
    orchestrator = StoryOrchestrator()
    events: list[object] = []

    with generation_progress(events.append):
        orchestrator._emit_workflow_step(
            "read_outline",
            "读取大纲",
            status="done",
            source="context_loader",
            used_modules=["outline_agent"],
            reads=["总纲", "第2章细纲", "上一章结尾"],
            outputs={"chapter_goal": "推进灰狼坡任务"},
        )

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, dict)
    assert event["status"] == "done"
    assert event["stage"] == "read_outline"
    artifact = event["artifact"]
    assert artifact["workflow_step"] == {
        "id": "read_outline",
        "label": "读取大纲",
        "reads": ["总纲", "第2章细纲", "上一章结尾"],
        "pipeline_stage": "context",
    }
    assert artifact["used_modules"] == ["outline_agent"]
    assert artifact["outputs"] == {"chapter_goal": "推进灰狼坡任务"}


# The orchestrator no longer runs a separate compression model
# call after the bounded controller — the over-length
# ``length.out_of_range`` finding is handed to the same revise
# pass. The ``test_compression_re_evaluates_canonical_review_for_compressed_body``
# test that previously lived here is obsolete; the new contract
# is pinned by ``test_over_length_body_is_fixed_in_single_revise_without_compression_model_call``
# above.
