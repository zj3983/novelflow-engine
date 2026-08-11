from __future__ import annotations

import json
from copy import deepcopy
import inspect

import pytest

from packages.story_core.model_gateway import ModelResponse
from packages.story_core.outline_planning import (
    INITIAL_OUTLINE_CHAPTER_COUNT,
    validate_generated_continuation_plan,
    validate_generated_opening_plan,
    validate_generated_trope_selection,
)
from packages.story_core.outline_planning_generation import (
    LLMOutlinePlanningGenerator,
    OutlinePlanningBrief,
    PlanningCharacterSeed,
    _expand_character_seed,
)
from packages.story_core.runtime_config import StageRuntimeSettings


def test_generator_constructor_does_not_accept_legacy_strategy_resolver() -> None:
    assert "strategy_resolver" not in inspect.signature(LLMOutlinePlanningGenerator).parameters


def test_character_seed_keeps_personality_out_of_history_and_uses_complete_speech_guidance() -> None:
    card = _expand_character_seed(
        PlanningCharacterSeed(
            name="陈砚",
            role="早餐店临时店主",
            character_tier="protagonist",
            first_appearance=1,
            age=29,
            origin="在老街早餐店长大，成年后去外地做厨师。",
            current_identity="返乡接店的失业厨师",
            occupation="厨师",
            immediate_problem="早餐店欠着三个月房租。",
            immediate_goal="先核清欠租和店内账目。",
            failure_stakes="店铺被收回，父母留下的旧账也失去查证机会。",
            personality="嘴硬心软，不愿在人前示弱。",
            speech_style="话少，句子短，常用修鞋和过日子的比喻。",
            action_style="先核对账目，再决定是否让步。",
            decision_rule="先把事实弄清，再谈人情。",
            dialogue_examples=["合同呢？", "七天，可以。"],
        )
    )

    assert card.background_profile.formative_events == []
    assert card.story_drive.motivation != "嘴硬心软，不愿在人前示弱。"
    assert "句子短" not in card.performance_profile.speech_style
    assert "必要的对象、原因和决定" in card.performance_profile.speech_style
    assert all(len(example) >= 10 for example in card.dialogue_examples)


def _card(name: str, tier: str) -> dict:
    return {
        "name": name,
        "role": tier,
        "character_tier": tier,
        "first_appearance": 0 if tier == "long_term_antagonist" else 1,
        "identity_profile": {"origin": "青石镇", "current_identity": "宗门中人", "occupation": "处理宗门差事"},
        "background_profile": {},
        "current_life_profile": {},
        "story_drive": {"immediate_goal": "控制祖祠局面", "failure_stakes": "失去宗门位置"},
        "performance_profile": {},
        "dialogue_examples": ["这件事先说清楚。", "你把来龙去脉交代完整。"],
        "relationship_notes": [],
    }


def _valid_plan() -> dict:
    return {
        "outline": {
            "overall": {
                "story": "林照追查祖祠旧案。",
                "theme_statement": "守住事实，比赢下一次争斗更重要。",
                "foreground_story": "林照追查祖祠纵火案并争取查档资格。",
                "background_story": "宗门高层借旧案清洗异己并改写名册。",
                "book_objective": "林照公开旧案真相并取得宗门执法权。",
                "ending_image": "重开的祖祠前，林照把旧名册交还死者家属。",
                "protagonist_goal": "查清旧案。",
                "main_conflict": "有人销毁证据。",
                "growth_path": "从守祠杂役成长为能调用宗门规则的人。",
                "ending_direction": "旧案公开。",
                "primary_trope_id": "low_status_reversal",
            },
            "arcs": [{
                "id": "opening",
                "title": "祖祠旧案",
                "start_chapter": 1,
                "end_chapter": 10,
                "goal": "找到换名册的人",
                "obstacle": "赵衡控制清点权",
                "payoff": "取得查档资格",
                "emotional_curve": "先受压，再反查，卷尾公开拿出证据。",
                "key_results": ["取得查档资格", "找到旧名册", "确认高层参与改名"],
                "hook_plan": "旧名册缺页在第三阶段回收。",
                "irreversible_change": "林照公开挑战管事，无法再做旁观的杂役。",
                "trope_id": "low_status_reversal",
                "end_state": "祖祠不再由赵衡独占",
                "stage_antagonist": "赵衡",
                "long_term_antagonist_traces": ["旧名册被换过"],
            }],
            "chapters": [
                {
                    "chapter_number": number,
                    "title": f"祖祠第{number}步",
                    "goal": "查清异动",
                    "obstacle": "赵衡阻拦",
                    "action": "林照留下证据",
                    "turn": "发现一处矛盾",
                    "payoff": "得到可验证线索",
                    "ending_hook": "有人提前来过",
                    "trope_beat": "低位压力" if number == 1 else None,
                    "cast": ["林照", "赵衡"],
                }
                for number in range(1, INITIAL_OUTLINE_CHAPTER_COUNT + 1)
            ],
        },
        "characters": [
            _card("林照", "protagonist"),
            _card("赵衡", "stage_antagonist"),
            _card("周满", "supporting"),
            _card("顾长老", "long_term_antagonist"),
        ],
    }


def _detailed_chapter_template() -> dict:
    """Return the rolling-only fields a chapter window response
    must carry.

    The plan rule: ``GeneratedChapterWindow`` carries the
    rolling fields; the three-level outline schema does not.
    Tests that stub the model response use this template to
    avoid ``ProjectOutline`` rejecting the rolling fields when
    the chapter rows are later validated.
    """

    return {
        "core_conflict": "赵衡设置阻碍，林照被迫应对",
        "gain": "掌握一条可验证线索",
        "cost": "得罪赵衡，失去观察的余地",
        "foreshadowing": ["旧名册缺页"],
        "state_delta_summary": "林照公开立场，冲突进入下一阶段",
        "scene_chain": [
            {
                "location": "祖祠",
                "pov": "林照",
                "goal": "确认现场状况",
                "obstacle": "赵衡阻拦",
                "action": "林照留下证据",
                "change": "获得新线索",
                "next": "前往管事处对质",
                "state_delta": {"clue": 1},
            },
            {
                "location": "管事处",
                "pov": "林照",
                "goal": "对质",
                "obstacle": "赵衡回避",
                "action": "林照出示证据",
                "change": "赵衡被迫回应",
                "next": "为下一章埋伏笔",
                "state_delta": {"tension": 1},
            },
        ],
    }


def _brief() -> OutlinePlanningBrief:
    return OutlinePlanningBrief(
        novel_type_id="xuanhuan",
        title="我替宗门看守断香炉",
        overall_context={
            "story": "守祠杂役发现断香炉会指出宗门旧案，必须在证据被毁前查清真相，否则会被当成盗宝者处死。",
            "protagonist_goal": "查清旧案并保住性命。",
            "main_conflict": "执事要销毁证据并把罪名推给主角。",
            "growth_path": "从忍让求生变成敢于掌握证据和规则。",
            "ending_direction": "主角公开旧案并建立新的宗门查验规则。",
            "positioning": {
                "protagonist_profile": "谨慎的守祠杂役，习惯忍让。",
                "inciting_incident": "断香炉第一次指出被封住的旧案证物。",
                "failure_stakes": "主角会被处死，旧案也会永远被掩埋。",
                "excitement_point": "利用破损器物留下的痕迹翻查旧案。",
                "target_audience": "喜欢玄幻升级和查案推进的读者。",
                "reader_promise": "每个阶段查出一件旧物的真相，并获得可见成长。",
            },
            "core_advantage": {
                "name": "断香炉残痕",
                "type": "线索能力",
                "ability": "看见破损器物留下的一段因果痕迹。",
                "growth_rule": "每查清一件旧案，能看到的痕迹更完整。",
                "limits": "只能读取已经发生且留有实物痕迹的事件。",
                "early_payoff": "找到祖祠失火留下的第一处证据。",
            },
            "central_mystery": {
                "surface_anomaly": "断香炉会显示不属于当前年代的残痕。",
                "hidden_truth": "香炉保存着被宗门改写的历史。",
                "reality_impact": "每次恢复旧事都会改变当前宗门关系。",
                "reveal_path": ["验证火灾残痕", "找到被改写的名册", "公开宗门旧史"],
            },
            "protagonist_drive": {
                "immediate_need": "洗清盗宝嫌疑并保住性命。",
                "trigger": "断香炉指出被封住的旧案证物。",
                "short_term_goal": "在证据被毁前查清祖祠失火案。",
                "failure_stakes": "主角会被处死，旧案也会永远被掩埋。",
                "long_term_transition": "从自证清白转向恢复被改写的宗门历史。",
            },
        },
        opening_direction={
            "title": "断香炉",
            "hook": "祖祠断香炉提醒林照别让人挖第三块青砖。",
            "opening_promise": "每次解决具体问题都会换来一条可验证线索。",
            "primary_trope_id": "low_status_reversal",
        },
        author_constraints=["白描，对话完整自然。"],
    )


def _trope_templates() -> list[dict]:
    return [
        {"id": "trope-a", "name": "A", "beats": ["beat-a1", "beat-a2"]},
        {"id": "trope-b", "name": "B", "beats": ["beat-b1"]},
    ]


def _trope_plan() -> dict:
    plan = _valid_plan()
    plan["outline"]["overall"]["primary_trope_id"] = "trope-a"
    plan["outline"]["arcs"][0]["trope_id"] = "trope-a"
    plan["outline"]["chapters"][0]["trope_beat"] = "beat-a1"
    return plan


def _outline_power_spec() -> dict:
    return {
        "name": "神域职业体系",
        "origin": ["职业权能来自转职试炼"],
        "stages": [
            {"name": "见习者", "level": 1, "entry": "创建角色", "change": "获得通用能力", "failure": "重新建号"},
            {"name": "正式职业", "level": 10, "entry": "完成正式转职", "change": "获得职业资源", "failure": "任务冷却"},
            {"name": "专精", "level": 20, "entry": "完成专精试炼", "change": "强化方向", "failure": "材料损失"},
            {"name": "进阶职业", "level": 30, "entry": "完成分支任务", "change": "获得分支能力", "failure": "晋升延期"},
            {"name": "传承", "level": 60, "entry": "完成传承试炼", "change": "获得职业权柄", "failure": "传承反噬"},
        ],
        "paths": [{"name": "法师", "branches": ["元素法师", "秘术法师"], "advancement": ["元素核心试炼"], "role": "远程输出"}],
        "advancement": ["晋升必须满足条件并支付材料"],
        "costs": ["失败损失材料并进入冷却"],
        "counters": ["沉默克制施法"],
        "boundaries": ["不得无条件跨阶段"],
        "continuity_ledger": ["level", "class_path", "skills", "equipment", "resources", "conditions"],
        "skills": ["完整技能目录不应进入大纲"],
        "equipment": ["完整装备目录不应进入大纲"],
        "social_impact": ["不应进入大纲"],
        "visibility": ["不应进入大纲"],
    }


def test_outline_prompt_receives_compact_power_contract_and_explicit_game_milestones() -> None:
    captured: dict = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured["system"] = payload["messages"][0]["content"]
        captured["context"] = json.loads(payload["messages"][1]["content"])
        plan = _valid_plan()
        plan["outline"]["overall"]["primary_trope_id"] = "login_character_creation"
        plan["outline"]["arcs"][0]["trope_id"] = "login_character_creation"
        plan["outline"]["arcs"][0]["game_line_payoff"] = "完成新手区域的首个核心目标。"
        plan["outline"]["arcs"][0]["reality_line_payoff"] = "解决眼前的一项现实压力。"
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    payload = _brief().model_dump(mode="json")
    payload["novel_type_id"] = "game_webnovel"
    payload["opening_direction"]["primary_trope_id"] = "login_character_creation"
    payload["power_system_spec"] = _outline_power_spec()
    generator = LLMOutlinePlanningGenerator(post_json=fake_post, runtime_resolver=fixture.resolve)

    generator.generate(OutlinePlanningBrief.model_validate(payload), mode="initial")

    power = captured["context"]["power_system"]
    assert [stage["level"] for stage in power["stages"]] == [1, 10, 20, 30, 60]
    assert power["paths"] == [{"name": "法师", "branches": ["元素法师", "秘术法师"], "advancement": ["元素核心试炼"]}]
    assert "skills" not in power and "equipment" not in power
    contract = "\n".join([captured["system"], *captured["context"]["validation_rules"]])
    assert "Lv10" in contract and "正式转职" in contract
    assert "Lv20" in contract and "专精" in contract and "第二次转职" in contract
    assert "Lv30" in contract and "进阶分支" in contract
    assert "Lv60" in contract and "传承" in contract
    assert "不得虚构" in contract and "技能" in contract and "装备" in contract
    assert "先安排解锁" in contract and "账本" in contract
    assert "条件" in contract and "代价" in contract and "失败" in contract
    assert "pacing_stage_id" in contract
    assert "reference_range" in contract and "planned_length" in contract


def test_outline_prompt_fills_only_the_selected_genre_outline_template() -> None:
    captured: dict = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured["system"] = payload["messages"][0]["content"]
        captured["context"] = json.loads(payload["messages"][1]["content"])
        return {
            "choices": [
                {"message": {"content": json.dumps(_valid_plan(), ensure_ascii=False)}}
            ]
        }

    fixture = RecordingRuntime()
    LLMOutlinePlanningGenerator(
        post_json=fake_post, runtime_resolver=fixture.resolve
    ).generate(_brief(), mode="initial")

    template_text = json.dumps(
        captured["context"]["genre_outline_template"], ensure_ascii=False
    )


def _codex_phase_content(prompt: dict) -> dict:
    plan = _valid_plan()
    if prompt["generation_phase"] == "outline":
        plan["outline"]["chapters"] = []
        return {"outline": plan["outline"]}
    if prompt["generation_phase"] == "characters":
        return {
            "characters": [
                {
                    "name": card["name"],
                    "role": card["role"],
                    "character_tier": card["character_tier"],
                    "first_appearance": card["first_appearance"],
                    "age": card["identity_profile"].get("age"),
                    "origin": card["identity_profile"]["origin"],
                    "current_identity": card["identity_profile"]["current_identity"],
                    "occupation": card["identity_profile"]["occupation"],
                    "authority_scope": "只处理职责范围内的事",
                    "immediate_problem": "眼前的冲突正在逼近",
                    "immediate_goal": card["story_drive"]["immediate_goal"],
                    "long_term_goal": "完成自己的长期目标",
                    "failure_stakes": card["story_drive"]["failure_stakes"],
                    "personality": "做事有明确取舍",
                    "speech_style": "按关系和场合说完整的话",
                    "action_style": "先观察再行动",
                    "emotional_trigger": "利益受损",
                    "decision_rule": "先保住最重要的目标",
                    "hidden_matter": "",
                    "dialogue_examples": card["dialogue_examples"],
                }
                for card in plan["characters"]
            ]
        }
    template = plan["outline"]["chapters"][0]
    detailed = _detailed_chapter_template()
    return {
        "chapters": [
            {
                **template,
                **detailed,
                "chapter_number": number,
                "trope_beat": template["trope_beat"] if number == 1 else None,
            }
            for number in prompt["target_chapter_numbers"]
        ]
    }
    assert "力量成长线" in template_text
    assert "游戏成长线" not in template_text
    assert "genre_outline_template" in captured["system"]
    assert "逐项填写" in captured["system"]


def test_outline_prompt_does_not_fabricate_power_contract_for_legacy_brief() -> None:
    captured: dict = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured.update(json.loads(payload["messages"][1]["content"]))
        return {"choices": [{"message": {"content": json.dumps(_valid_plan(), ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    LLMOutlinePlanningGenerator(post_json=fake_post, runtime_resolver=fixture.resolve).generate(
        _brief(), mode="initial"
    )
    assert "power_system" not in captured


def test_non_game_outline_prompt_uses_general_long_form_fields_without_game_dual_lines() -> None:
    captured: dict = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured["system"] = payload["messages"][0]["content"]
        captured["context"] = json.loads(payload["messages"][1]["content"])
        plan = _valid_plan()
        plan["outline"]["arcs"][0]["game_line_payoff"] = "不该进入非网游大纲"
        plan["outline"]["arcs"][0]["reality_line_payoff"] = "不该进入非网游大纲"
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    generator = LLMOutlinePlanningGenerator(post_json=fake_post, runtime_resolver=fixture.resolve)

    result = generator.generate(_brief(), mode="initial")

    contract = "\n".join([captured["system"], *captured["context"]["validation_rules"]])
    assert "Every core arc must state a concrete game_line_payoff and reality_line_payoff" not in contract
    overall_fields = captured["context"]["output_schema"]["$defs"]["OverallOutline"]["properties"]
    arc_fields = captured["context"]["output_schema"]["$defs"]["ArcOutline"]["properties"]
    assert {"theme_statement", "foreground_story", "background_story", "book_objective", "ending_image"} <= set(overall_fields)
    assert {"emotional_curve", "key_results", "hook_plan", "irreversible_change"} <= set(arc_fields)
    assert result.outline.arcs[0].game_line_payoff == ""
    assert result.outline.arcs[0].reality_line_payoff == ""


def test_game_outline_generation_still_requires_game_and_reality_payoffs() -> None:
    def fake_post(base_url, path, payload, api_key, **kwargs):
        return {"choices": [{"message": {"content": json.dumps(_valid_plan(), ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    payload = _brief().model_dump(mode="json")
    payload["novel_type_id"] = "game_webnovel"
    generator = LLMOutlinePlanningGenerator(post_json=fake_post, runtime_resolver=fixture.resolve)

    with pytest.raises(ValueError, match="outline_planning_generation_failed") as exc_info:
        generator.generate(OutlinePlanningBrief.model_validate(payload), mode="initial")

    assert exc_info.value.__cause__ is not None
    assert "missing_game_dual_line_payoff:opening" in str(exc_info.value.__cause__)


def test_generated_opening_requires_complete_long_form_volume_fields() -> None:
    plan = _valid_plan()
    plan["outline"]["arcs"][0]["emotional_curve"] = ""

    with pytest.raises(ValueError, match="missing_arc_field:opening:emotional_curve"):
        validate_generated_opening_plan(
            plan,
            expected_chapter_numbers=list(range(1, INITIAL_OUTLINE_CHAPTER_COUNT + 1)),
        )

def test_xianxia_structured_power_prompt_omits_game_only_milestone_rules() -> None:
    captured: dict = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured["system"] = payload["messages"][0]["content"]
        captured["context"] = json.loads(payload["messages"][1]["content"])
        return {"choices": [{"message": {"content": json.dumps(_valid_plan(), ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    payload = _brief().model_dump(mode="json")
    payload["novel_type_id"] = "xianxia"
    payload["power_system_spec"] = _outline_power_spec()

    LLMOutlinePlanningGenerator(post_json=fake_post, runtime_resolver=fixture.resolve).generate(
        OutlinePlanningBrief.model_validate(payload), mode="initial"
    )

    contract = "\n".join([captured["system"], *captured["context"]["validation_rules"]])
    assert "power_system" in captured["context"]
    assert "不得虚构" in contract and "免费晋升" in contract
    assert "Lv10" not in contract
    assert "Lv20" not in contract
    assert "第二次转职" not in contract


def test_trope_validator_rejects_invalid_primary_arc_and_beat() -> None:
    plan = _trope_plan()
    plan["outline"]["overall"]["primary_trope_id"] = "missing"
    with pytest.raises(ValueError, match="^invalid_primary_trope_id$"):
        validate_generated_trope_selection(plan, _trope_templates())

    plan = _trope_plan()
    plan["outline"]["arcs"][0]["trope_id"] = "missing"
    with pytest.raises(ValueError, match="^invalid_arc_trope_id:opening$"):
        validate_generated_trope_selection(plan, _trope_templates())

    plan = _trope_plan()
    plan["outline"]["chapters"][0]["trope_beat"] = "wrong beat"
    with pytest.raises(ValueError, match="^invalid_chapter_trope_beat:1$"):
        validate_generated_trope_selection(plan, _trope_templates())


def test_trope_validator_rejects_empty_string_beat_when_candidates_exist() -> None:
    plan = _trope_plan()
    plan["outline"]["chapters"][0]["trope_beat"] = ""

    with pytest.raises(ValueError, match="^invalid_chapter_trope_beat:1$"):
        validate_generated_trope_selection(plan, _trope_templates())


def test_generator_drops_invalid_optional_trope_beat_before_strict_validation() -> None:
    def fake_post(base_url, path, payload, api_key, **kwargs):
        plan = _valid_plan()
        plan["outline"]["chapters"][0]["trope_beat"] = "模型改写的低位压力"
        return {
            "choices": [
                {"message": {"content": json.dumps(plan, ensure_ascii=False)}}
            ]
        }

    result = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=RecordingRuntime().resolve,
    ).generate(_brief(), mode="initial")

    assert result.outline.chapters[0].trope_beat is None


def test_trope_validator_uses_active_arc_precedence_for_overlapping_arcs() -> None:
    plan = _trope_plan()
    plan["outline"]["arcs"] = [
        {**plan["outline"]["arcs"][0], "id": "outer", "start_chapter": 1, "end_chapter": 10, "trope_id": "trope-a"},
        {**plan["outline"]["arcs"][0], "id": "inner", "start_chapter": 5, "end_chapter": 6, "trope_id": "trope-b"},
    ]
    plan["outline"]["chapters"][4]["trope_beat"] = "beat-b1"

    validate_generated_trope_selection(plan, _trope_templates())

    plan["outline"]["chapters"][4]["trope_beat"] = "beat-a1"
    with pytest.raises(ValueError, match="^invalid_chapter_trope_beat:5$"):
        validate_generated_trope_selection(plan, _trope_templates())


def test_trope_validator_allows_missing_chapter_beats() -> None:
    plan = _trope_plan()
    for chapter in plan["outline"]["chapters"]:
        chapter["trope_beat"] = None

    validate_generated_trope_selection(plan, _trope_templates())


def test_trope_validator_requires_primary_when_candidates_exist() -> None:
    plan = _trope_plan()
    plan["outline"]["overall"]["primary_trope_id"] = None

    with pytest.raises(ValueError, match="^invalid_primary_trope_id$"):
        validate_generated_trope_selection(plan, _trope_templates())


def test_trope_validator_does_not_grandfather_fallback_beats_by_default() -> None:
    plan = _trope_plan()
    fallback = deepcopy(plan["outline"])
    plan["outline"]["overall"]["primary_trope_id"] = "deleted-trope"
    plan["outline"]["arcs"][0]["trope_id"] = "deleted-trope"
    plan["outline"]["chapters"][0]["trope_beat"] = "deleted beat"
    fallback["overall"]["primary_trope_id"] = "deleted-trope"
    fallback["arcs"][0]["trope_id"] = "deleted-trope"
    fallback["chapters"][0]["trope_beat"] = "deleted beat"

    with pytest.raises(ValueError, match="^unexpected_chapter_trope_beat:1$"):
        validate_generated_trope_selection(
            plan,
            [],
            expected_primary_trope_id="deleted-trope",
            fallback_outline=fallback,
        )

    validate_generated_trope_selection(
        plan,
        [],
        expected_primary_trope_id="deleted-trope",
        fallback_outline=fallback,
        committed_through_chapter=1,
    )


def test_trope_validator_does_not_grandfather_changed_beat_for_current_template() -> None:
    plan = _trope_plan()
    fallback = deepcopy(plan["outline"])
    plan["outline"]["chapters"][0]["trope_beat"] = "removed beat"
    fallback["chapters"][0]["trope_beat"] = "removed beat"

    with pytest.raises(ValueError, match="^invalid_chapter_trope_beat:1$"):
        validate_generated_trope_selection(
            plan,
            _trope_templates(),
            fallback_outline=fallback,
            committed_through_chapter=1,
        )


def test_trope_validator_requires_all_nulls_when_no_candidates() -> None:
    plan = _trope_plan()
    plan["outline"]["overall"]["primary_trope_id"] = None
    plan["outline"]["arcs"][0]["trope_id"] = None
    for chapter in plan["outline"]["chapters"]:
        chapter["trope_beat"] = None

    validate_generated_trope_selection(plan, [])

    plan["outline"]["chapters"][0]["trope_beat"] = "beat-a1"
    with pytest.raises(ValueError, match="^unexpected_chapter_trope_beat:1$"):
        validate_generated_trope_selection(plan, [])

    plan = _trope_plan()
    plan["outline"]["arcs"][0]["trope_id"] = None
    for chapter in plan["outline"]["chapters"]:
        chapter["trope_beat"] = None
    with pytest.raises(ValueError, match="^unexpected_primary_trope_id$"):
        validate_generated_trope_selection(plan, [])

    plan = _trope_plan()
    plan["outline"]["overall"]["primary_trope_id"] = None
    for chapter in plan["outline"]["chapters"]:
        chapter["trope_beat"] = None
    with pytest.raises(ValueError, match="^unexpected_arc_trope_id:opening$"):
        validate_generated_trope_selection(plan, [])


def test_opening_and_continuation_validators_call_shared_trope_validator() -> None:
    plan = _trope_plan()
    plan["outline"]["overall"]["primary_trope_id"] = "trope-b"

    with pytest.raises(ValueError, match="^unexpected_primary_trope_id$"):
        validate_generated_opening_plan(
            plan,
            expected_chapter_numbers=list(range(1, INITIAL_OUTLINE_CHAPTER_COUNT + 1)),
            trope_templates=_trope_templates(),
            expected_primary_trope_id="trope-a",
        )

    continuation = _trope_plan()
    continuation["outline"]["chapters"] = [
        {**continuation["outline"]["chapters"][0], "chapter_number": 31, "cast": ["Existing", "New"]}
    ]
    continuation["characters"] = [_card("New", "supporting")]
    continuation["outline"]["arcs"][0]["trope_id"] = "trope-b"
    with pytest.raises(ValueError, match="^invalid_chapter_trope_beat:31$"):
        validate_generated_continuation_plan(
            continuation,
            expected_chapter_numbers=[31],
            existing_character_names={"Existing"},
            trope_templates=_trope_templates(),
            expected_primary_trope_id="trope-a",
        )


class RecordingRuntime:
    def __init__(self) -> None:
        self.calls = []
        self.runtime_calls = []
        self.prompt_context = {}

    def post(self, base_url, path, payload, api_key, **kwargs):
        self.calls.append({"base_url": base_url, "path": path, "payload": payload, "api_key": api_key, "kwargs": kwargs})
        self.prompt_context = json.loads(payload["messages"][1]["content"])
        plan = _valid_plan()
        targets = self.prompt_context.get(
            "target_chapter_numbers",
            list(range(1, INITIAL_OUTLINE_CHAPTER_COUNT + 1)),
        )
        template = plan["outline"]["chapters"][0]
        plan["outline"]["chapters"] = [
            {
                **template,
                "chapter_number": number,
                "trope_beat": template["trope_beat"] if number == 1 else None,
            }
            for number in targets
        ]
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    def resolve(self, stage):
        self.runtime_calls.append(stage)
        return StageRuntimeSettings(
            provider_id="openai",
            protocol="openai_compatible",
            model="planning-test-model",
            base_url="http://runtime.test",
            api_key="test-key",
            codex_command="codex-test",
            temperature=0.29,
        )

    def generator(self) -> LLMOutlinePlanningGenerator:
        return LLMOutlinePlanningGenerator(
            post_json=self.post,
            runtime_resolver=self.resolve,
        )

    def brief(self, *, current_chapter: int, existing_chapters: list[int]) -> OutlinePlanningBrief:
        payload = _brief().model_dump(mode="json")
        outline = _valid_plan()["outline"]
        template = outline["chapters"][0]
        outline["overall"].update(
            {
                "core_ending_chapter": 150,
                "extension_ceiling_chapter": 500,
                "current_strategy": "expand",
                "ending_contract": "Close both story lines.",
            }
        )
        outline["arcs"][0].update(
            {
                "end_chapter": 150,
                "game_line_payoff": "Win the active game arc.",
                "reality_line_payoff": "Resolve the active reality pressure.",
                "extension_gate": {
                    "continue_route": "Enter the next city.",
                    "close_route": "Close through the verifier ending.",
                },
            }
        )
        outline["chapters"] = [
            {**template, "chapter_number": number}
            for number in existing_chapters
        ]
        payload.update(
            existing_outline=outline,
            current_chapter=current_chapter,
        )
        return OutlinePlanningBrief.model_validate(payload)


@pytest.fixture
def generator_fixture() -> RecordingRuntime:
    return RecordingRuntime()


def test_outline_generation_routes_through_planner_gateway() -> None:
    calls = []

    class Gateway:
        def complete_stage(self, stage, request):
            calls.append((stage, request))
            return ModelResponse.success(
                request,
                text=json.dumps(_valid_plan(), ensure_ascii=False),
            )

    runtime_calls = []
    runtime = StageRuntimeSettings(
        provider_id="deepseek",
        protocol="openai_compatible",
        model="deepseek-chat",
        api_key="test-key",
        base_url="https://api.deepseek.test",
        temperature=0.31,
    )
    result = LLMOutlinePlanningGenerator(
        runtime_resolver=lambda stage: runtime_calls.append(stage) or runtime,
        model_gateway=Gateway(),
    ).generate(_brief(), mode="initial")

    assert result.outline.chapters
    assert runtime_calls == ["planner"]
    assert calls[0][0] == "planner"
    assert calls[0][1].operation == "outline_planning"
    assert calls[0][1].json_mode is True


def test_planning_brief_has_one_overall_source_instead_of_three_story_core_copies() -> None:
    payload = _brief().model_dump(mode="json")

    assert payload["overall_context"]["story"]
    assert "story_core" not in payload
    assert "character_story_core" not in payload
    assert "planning_story_core" not in payload


def test_generator_requests_one_compact_structured_plan() -> None:
    recording = RecordingRuntime()
    generator = recording.generator()

    result = generator.generate(_brief(), mode="initial", guidance="  反派要有现实利益  ")

    assert len(recording.calls) == 1
    assert recording.runtime_calls == ["planner"]
    assert result.outline.chapters[0].chapter_number == 1
    request = recording.calls[0]
    assert request["path"] == "/chat/completions"
    assert request["payload"]["model"] == "planning-test-model"
    assert request["payload"]["temperature"] == 0.29
    assert request["payload"]["response_format"] == {"type": "json_object"}
    prompt = json.loads(request["payload"]["messages"][1]["content"])
    assert set(prompt) == {
        "mode",
        "genre_label",
        "genre_description",
        "genre_core_promises",
        "genre_rulebook",
        "genre_quality_checks",
        "genre_trope_templates",
            "genre_power_system_template",
            "genre_outline_template",
        "title",
        "overall_context",
        "opening_direction",
        "author_constraints",
        "existing_outline",
        "existing_characters",
        "existing_character_names",
        "current_chapter",
        "recent_chapter_summaries",
        "continuation_start_chapter",
        "historical_chapter_summaries",
        "one_time_guidance",
        "output_schema",
        "validation_rules",
        "target_chapter_numbers",
        "current_strategy",
    }
    assert prompt["overall_context"]["positioning"]["failure_stakes"]
    assert "写长篇最怕" not in request["payload"]["messages"][1]["content"]
    assert prompt["one_time_guidance"] == "反派要有现实利益"
    assert prompt["opening_direction"]["primary_trope_id"] == "low_status_reversal"
    assert prompt["genre_trope_templates"]
    assert prompt["genre_power_system_template"]["system_form"]
    assert prompt["genre_power_system_template"]["required_sections"]
    assert prompt["genre_power_system_template"]["minimum_path_count"] >= 1
    assert "genre_trope_templates" in request["payload"]["messages"][1]["content"]
    schema_text = json.dumps(prompt["output_schema"], ensure_ascii=False)
    assert '"start_chapter"' in schema_text
    assert '"long_term_antagonist_traces"' in schema_text
    assert '"stage_antagonist"' in schema_text
    assert '"additionalProperties": false' in schema_text
    assert all(tier in schema_text for tier in (
        "protagonist",
        "stage_antagonist",
        "long_term_antagonist",
        "supporting",
    ))
    rules_text = "\n".join(prompt["validation_rules"])
    assert "stage_antagonist" in rules_text
    assert "exactly equal" in rules_text
    assert "target_chapter_numbers" in rules_text
    assert "cast" in rules_text
    assert "overall.primary_trope_id" in rules_text
    assert "arc.trope_id" in rules_text
    assert "trope_beat only on milestone chapters" in rules_text
    assert "must exactly equal a beat" in rules_text
    system_text = request["payload"]["messages"][0]["content"]
    assert "Choose one overall.primary_trope_id from prompt_context.genre_trope_templates" in system_text
    assert "Use null for overall.primary_trope_id, arc.trope_id, and chapter.trope_beat when prompt_context.genre_trope_templates is empty" in system_text
    assert "Do not assign trope_beat to every chapter" in system_text
    assert "Do not change trope_id inside an arc" in system_text
    assert "chapter body" not in json.dumps(prompt, ensure_ascii=False).lower()
    assert "五章" not in request["payload"]["messages"][0]["content"]


@pytest.mark.parametrize(
    "scenario",
    ["initial", "regenerate_continuation", "regenerate_unstarted"],
)
def test_codexcli_full_plan_is_generated_in_three_bounded_phases(scenario: str) -> None:
    calls: list[dict] = []
    systems: list[str] = []

    def fake_post(base_url, path, payload, api_key, **kwargs):
        prompt = json.loads(payload["messages"][1]["content"])
        calls.append(prompt)
        systems.append(payload["messages"][0]["content"])
        plan = _valid_plan()
        if prompt["generation_phase"] == "outline":
            plan["outline"]["chapters"] = []
            content = {"outline": plan["outline"]}
        elif prompt["generation_phase"] == "characters":
            content = {
                "characters": [
                    {
                        "name": card["name"],
                        "role": card["role"],
                        "character_tier": card["character_tier"],
                        "first_appearance": card["first_appearance"],
                        "age": card["identity_profile"].get("age"),
                        "origin": card["identity_profile"]["origin"],
                        "current_identity": card["identity_profile"]["current_identity"],
                        "occupation": card["identity_profile"]["occupation"],
                        "authority_scope": "只处理职责范围内的事",
                        "immediate_problem": "眼前的冲突正在逼近",
                        "immediate_goal": card["story_drive"]["immediate_goal"],
                        "long_term_goal": "完成自己的长期目标",
                        "failure_stakes": card["story_drive"]["failure_stakes"],
                        "personality": "做事有明确取舍",
                        "speech_style": "按关系和场合说完整的话",
                        "action_style": "先观察再行动",
                        "emotional_trigger": "利益受损",
                        "decision_rule": "先保住最重要的目标",
                        "hidden_matter": "",
                        "dialogue_examples": card["dialogue_examples"],
                    }
                    for card in plan["characters"]
                ]
            }
        else:
            template = plan["outline"]["chapters"][0]
            detailed = _detailed_chapter_template()
            content = {
                "chapters": [
                    {
                        **template,
                        **detailed,
                        "chapter_number": number,
                        "trope_beat": template["trope_beat"] if number == 1 else None,
                    }
                    for number in prompt["target_chapter_numbers"]
                ]
            }
        return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}

    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=lambda _stage: StageRuntimeSettings(
            provider_id="codexcli",
            protocol="codex_cli",
            model="planning-test-model",
            codex_command="codex-test",
        ),
    )

    brief = _brief()
    mode = "initial" if scenario == "initial" else "regenerate"
    if scenario == "regenerate_continuation":
        brief = brief.model_copy(
            update={
                "current_chapter": 145,
                "continuation_start_chapter": 141,
                "historical_chapter_summaries": [
                    {"chapter_number": 1, "title": "开端", "summary": "主角进入宗门。"},
                    {"chapter_number": 141, "title": "断点", "summary": "主角守住关键证据。"},
                ],
            }
        )

    plan = generator.generate(brief, mode=mode)

    assert [call["generation_phase"] for call in calls] == [
        "outline",
        "characters",
        "chapters",
    ]
    assert calls[0]["target_chapter_numbers"] == []
    assert "theme_statement" in systems[0]
    assert "core_ending_chapter" in systems[0]
    assert "extension_ceiling_chapter" in systems[0]
    assert "exactly three key_results" in systems[0]
    assert "concrete personal name" in systems[0]
    assert "character cards" not in systems[0].lower()
    assert any(
        "concrete personal name" in rule
        for rule in calls[1]["validation_rules"]
    )
    expected_numbers = (
        list(range(1, INITIAL_OUTLINE_CHAPTER_COUNT + 1))
        if scenario in {"initial", "regenerate_unstarted"}
        else list(range(146, 156))
    )
    assert calls[2]["target_chapter_numbers"] == expected_numbers
    assert len(plan.outline.chapters) == INITIAL_OUTLINE_CHAPTER_COUNT


def test_codexcli_retries_a_phase_after_schema_validation_failure() -> None:
    outline_attempts = 0
    retry_system_messages: list[str] = []

    def fake_post(base_url, path, payload, api_key, **kwargs):
        nonlocal outline_attempts
        prompt = json.loads(payload["messages"][1]["content"])
        phase = prompt["generation_phase"]
        plan = _valid_plan()
        if phase == "outline":
            outline_attempts += 1
            plan["outline"]["chapters"] = []
            plan["outline"]["overall"].update(
                {
                    "core_ending_chapter": 10,
                    "extension_ceiling_chapter": 20,
                    "expansion_route": "继续追查下一宗旧案",
                    "closing_route": "公开现有证据并收束旧案",
                }
            )
            if outline_attempts > 1:
                plan["outline"]["arcs"][0]["extension_gate"] = {
                    "continue_route": "进入内门追查下一宗旧案",
                    "close_route": "公开名册并完成当前旧案",
                }
            retry_system_messages.extend(
                message["content"]
                for message in payload["messages"][2:]
                if message.get("role") == "system"
            )
            content = {"outline": plan["outline"]}
        elif phase == "characters":
            content = _codex_phase_content(prompt)
        else:
            content = _codex_phase_content(prompt)
        return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}

    runtime = lambda _stage: StageRuntimeSettings(
        provider_id="codexcli",
        protocol="codex_cli",
        model="planning-test-model",
        codex_command="codex-test",
    )

    plan = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=runtime,
    ).generate(_brief(), mode="initial")

    assert outline_attempts == 2
    assert any("missing_arc_extension_route" in message for message in retry_system_messages)
    assert plan.outline.arcs[0].extension_gate.continue_route


def test_codexcli_foundation_only_stops_before_characters_and_chapters() -> None:
    calls: list[str] = []

    def fake_post(base_url, path, payload, api_key, **kwargs):
        prompt = json.loads(payload["messages"][1]["content"])
        calls.append(prompt["generation_phase"])
        plan = _valid_plan()
        plan["outline"]["chapters"] = []
        plan["outline"]["arcs"][0].update({
            "core_loop": "查证、受阻、换证据路径、公开一项结果",
            "escalations": ["取得查档资格", "找到被换过的名册"],
            "midpoint_turn": "林照发现失火和换名册是同一批人所为",
            "climax": "林照当众拿出无法销毁的证据",
            "active_long_term_lines": ["被改写的宗门旧史"],
        })
        return {
            "choices": [{
                "message": {
                    "content": json.dumps({"outline": plan["outline"]}, ensure_ascii=False)
                }
            }]
        }

    plan = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=lambda _stage: StageRuntimeSettings(
            provider_id="codexcli",
            protocol="codex_cli",
            model="planning-test-model",
            codex_command="codex-test",
        ),
    ).generate(_brief(), mode="initial", stop_after_phase="outline_foundation")

    assert calls == ["outline"]
    assert plan.characters == []
    assert plan.outline.chapters == []


def test_continuation_regenerate_does_not_prompt_with_future_placeholders() -> None:
    captured: dict = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured.update(json.loads(payload["messages"][1]["content"]))
        raise RuntimeError("stop_after_prompt_capture")

    brief = _brief().model_copy(
        update={
            "current_chapter": 147,
            "continuation_start_chapter": 147,
            "existing_outline": {
                "arcs": [
                    {"id": "history", "start_chapter": 1, "end_chapter": 147},
                    {"id": "future-shell", "start_chapter": 148, "end_chapter": 300},
                ],
                "chapters": [
                    {"chapter_number": 147, "title": "已发生"},
                    {"chapter_number": 148, "title": "未来占位"},
                ],
            },
        }
    )
    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=lambda _stage: StageRuntimeSettings(
            provider_id="codexcli",
            protocol="codex_cli",
            model="planning-test-model",
            codex_command="codex-test",
        ),
    )

    with pytest.raises(ValueError, match="outline_planning_generation_failed"):
        generator.generate(
            brief,
            mode="regenerate",
            stop_after_phase="outline_foundation",
        )

    assert [arc["id"] for arc in captured["existing_outline"]["arcs"]] == ["history"]
    assert [chapter["chapter_number"] for chapter in captured["existing_outline"]["chapters"]] == [147]


def test_codexcli_generation_callbacks_keep_completed_phases_after_later_failure() -> None:
    events: list[tuple[str, str, dict | None, str]] = []

    def fake_post(base_url, path, payload, api_key, **kwargs):
        prompt = json.loads(payload["messages"][1]["content"])
        if prompt["generation_phase"] == "chapters":
            raise TimeoutError("chapter timeout")
        content = _codex_phase_content(prompt)
        return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}

    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=lambda _stage: StageRuntimeSettings(
            provider_id="codexcli", protocol="codex_cli", model="planning-test-model", codex_command="codex-test"
        ),
    )

    with pytest.raises(ValueError, match="outline_planning_generation_failed"):
        generator.generate(
            _brief(),
            mode="initial",
            phase_callback=lambda phase, status, payload, error: events.append((phase, status, payload, error)),
        )

    completed = [phase for phase, status, _, _ in events if status == "completed"]
    assert completed == ["outline_foundation", "character_roster"]
    assert events[-1][0:2] == ("chapter_window", "failed")
    assert "chapter_window_generation_failed" in events[-1][3]


def test_codexcli_generation_reuses_validated_cached_phases() -> None:
    cached: dict[str, dict] = {}
    first_calls: list[str] = []

    def first_post(base_url, path, payload, api_key, **kwargs):
        prompt = json.loads(payload["messages"][1]["content"])
        first_calls.append(prompt["generation_phase"])
        if prompt["generation_phase"] == "chapters":
            raise TimeoutError("chapter timeout")
        content = _codex_phase_content(prompt)
        return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}

    runtime = lambda _stage: StageRuntimeSettings(
        provider_id="codexcli", protocol="codex_cli", model="planning-test-model", codex_command="codex-test"
    )
    with pytest.raises(ValueError):
        LLMOutlinePlanningGenerator(post_json=first_post, runtime_resolver=runtime).generate(
            _brief(),
            mode="initial",
            phase_callback=lambda phase, status, payload, _error: cached.update({phase: payload})
            if status == "completed" and payload
            else None,
        )

    resumed_calls: list[str] = []

    def resumed_post(base_url, path, payload, api_key, **kwargs):
        prompt = json.loads(payload["messages"][1]["content"])
        resumed_calls.append(prompt["generation_phase"])
        content = _codex_phase_content(prompt)
        return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}

    plan = LLMOutlinePlanningGenerator(post_json=resumed_post, runtime_resolver=runtime).generate(
        _brief(), mode="initial", phase_payloads=cached
    )

    assert first_calls == ["outline", "characters", "chapters"]
    assert resumed_calls == ["chapters"]
    assert len(plan.outline.chapters) == INITIAL_OUTLINE_CHAPTER_COUNT


def test_codexcli_retries_once_when_chapter_window_is_not_json() -> None:
    chapter_attempts = 0

    def fake_post(base_url, path, payload, api_key, **kwargs):
        nonlocal chapter_attempts
        prompt = json.loads(payload["messages"][1]["content"])
        if prompt["generation_phase"] == "chapters":
            chapter_attempts += 1
            if chapter_attempts == 1:
                return {"choices": [{"message": {"content": "not-json"}}]}
        content = _codex_phase_content(prompt)
        return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}

    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=lambda _stage: StageRuntimeSettings(
            provider_id="codexcli", protocol="codex_cli", model="planning-test-model", codex_command="codex-test"
        ),
    )

    plan = generator.generate(_brief(), mode="initial")

    assert chapter_attempts == 2
    assert len(plan.outline.chapters) == INITIAL_OUTLINE_CHAPTER_COUNT


def test_codexcli_marks_chapter_phase_failed_when_combined_plan_validation_fails() -> None:
    events: list[tuple[str, str, str]] = []

    def fake_post(base_url, path, payload, api_key, **kwargs):
        prompt = json.loads(payload["messages"][1]["content"])
        content = _codex_phase_content(prompt)
        if prompt["generation_phase"] == "chapters":
            content["chapters"][0]["cast"] = ["未登记角色"]
        return {"choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}]}

    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=lambda _stage: StageRuntimeSettings(
            provider_id="codexcli", protocol="codex_cli", model="planning-test-model", codex_command="codex-test"
        ),
    )

    with pytest.raises(ValueError, match="outline_planning_generation_failed"):
        generator.generate(
            _brief(),
            mode="initial",
            phase_callback=lambda phase, status, _payload, error: events.append((phase, status, error)),
        )

    assert events[-1][0:2] == ("chapter_window", "failed")
    assert events[-1][2].startswith("combined_outline_validation_failed:")


@pytest.mark.parametrize("mode", ["initial", "regenerate", "extend"])
def test_generator_forbids_exact_financial_hard_anchors_in_every_mode(
    mode: str,
) -> None:
    recording = RecordingRuntime()
    if mode == "initial":
        brief = _brief()
    else:
        existing_end = 10 if mode == "extend" else 20
        brief = recording.brief(
            current_chapter=10,
            existing_chapters=list(range(1, existing_end + 1)),
        )

    recording.generator().generate(brief, mode=mode)

    request = recording.calls[0]["payload"]
    rules_text = "\n".join(recording.prompt_context["validation_rules"])
    required_rule = (
        "All outline narrative text may describe financial outcomes but must not contain "
        "exact currency amounts, account balances, or fee percentages."
    )
    assert required_rule in rules_text
    assert required_rule in request["messages"][0]["content"]


def test_generator_sanitizes_financial_anchors_before_validation() -> None:
    def fake_post(base_url, path, payload, api_key, **kwargs):
        plan = _valid_plan()
        plan["outline"]["chapters"][0]["turn"] = (
            "平台扣除5%手续费后，到账1764.00元。"
        )
        return {
            "choices": [
                {"message": {"content": json.dumps(plan, ensure_ascii=False)}}
            ]
        }

    fixture = RecordingRuntime()
    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=fixture.resolve,
    )

    plan = generator.generate(_brief(), mode="initial")

    turn = plan.outline.chapters[0].turn
    assert "1764" not in turn
    assert "5%" not in turn
    assert "具体数额" in turn or "平台规则" in turn


def test_generator_rejects_selected_primary_trope_drift() -> None:
    def fake_post(base_url, path, payload, api_key, **kwargs):
        plan = _valid_plan()
        plan["outline"]["overall"]["primary_trope_id"] = "golden_finger_first_test"
        plan["outline"]["arcs"][0]["trope_id"] = "golden_finger_first_test"
        plan["outline"]["chapters"][0]["trope_beat"] = "异常出现"
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=fixture.resolve,
    )

    with pytest.raises(ValueError, match="^outline_planning_generation_failed$") as exc_info:
        generator.generate(_brief(), mode="initial")

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert str(exc_info.value.__cause__) == "unexpected_primary_trope_id"


def test_generator_allows_direct_initial_model_to_choose_primary_trope() -> None:
    recording = RecordingRuntime()
    payload = _brief().model_dump(mode="json")
    payload["opening_direction"]["primary_trope_id"] = None

    plan = recording.generator().generate(
        OutlinePlanningBrief.model_validate(payload),
        mode="initial",
    )

    assert plan.outline.overall.primary_trope_id == "low_status_reversal"
    assert recording.prompt_context["opening_direction"]["primary_trope_id"] is None


def test_extend_rejects_existing_primary_trope_drift() -> None:
    def fake_post(base_url, path, payload, api_key, **kwargs):
        prompt = json.loads(payload["messages"][1]["content"])
        plan = _valid_plan()
        template = plan["outline"]["chapters"][0]
        plan["outline"]["overall"]["primary_trope_id"] = "golden_finger_first_test"
        plan["outline"]["arcs"][0]["trope_id"] = "golden_finger_first_test"
        plan["outline"]["chapters"] = [
            {
                **template,
                "chapter_number": number,
                "trope_beat": "异常出现" if number == prompt["target_chapter_numbers"][0] else None,
                "cast": ["林照", "New"],
            }
            for number in prompt["target_chapter_numbers"]
        ]
        plan["characters"] = [_card("New", "supporting")]
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    brief = fixture.brief(current_chapter=10, existing_chapters=list(range(1, 11)))
    payload = brief.model_dump(mode="json")
    payload["existing_character_names"] = ["林照"]
    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=fixture.resolve,
    )

    with pytest.raises(ValueError, match="^outline_planning_generation_failed$") as exc_info:
        generator.generate(OutlinePlanningBrief.model_validate(payload), mode="extend")

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert str(exc_info.value.__cause__) == "unexpected_primary_trope_id"


def test_extend_preserves_null_tropes_for_legacy_project_without_lock() -> None:
    def fake_post(base_url, path, payload, api_key, **kwargs):
        prompt = json.loads(payload["messages"][1]["content"])
        plan = _valid_plan()
        template = plan["outline"]["chapters"][0]
        plan["outline"]["overall"]["primary_trope_id"] = "model-invented-trope"
        plan["outline"]["arcs"][0]["trope_id"] = "model-invented-trope"
        plan["outline"]["chapters"] = [
            {
                **template,
                "chapter_number": number,
                "trope_beat": "model invented beat",
                "cast": ["鏋楃収", "New"],
            }
            for number in prompt["target_chapter_numbers"]
        ]
        plan["characters"] = [_card("New", "supporting")]
        return {
            "choices": [
                {"message": {"content": json.dumps(plan, ensure_ascii=False)}}
            ]
        }

    fixture = RecordingRuntime()
    brief = fixture.brief(current_chapter=10, existing_chapters=list(range(1, 11)))
    payload = brief.model_dump(mode="json")
    payload["opening_direction"]["primary_trope_id"] = None
    payload["existing_outline"]["overall"]["primary_trope_id"] = None
    payload["existing_outline"]["arcs"][0]["trope_id"] = None
    payload["existing_character_names"] = ["鏋楃収"]
    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=fixture.resolve,
    )

    result = generator.generate(
        OutlinePlanningBrief.model_validate(payload),
        mode="extend",
    )

    assert result.outline.overall.primary_trope_id is None
    assert all(arc.trope_id is None for arc in result.outline.arcs)
    assert all(chapter.trope_beat is None for chapter in result.outline.chapters)


@pytest.mark.parametrize("mode", ["extend", "regenerate"])
def test_generator_uses_existing_locked_arc_context_for_omitted_arc_beats(mode: str) -> None:
    def fake_post(base_url, path, payload, api_key, **kwargs):
        prompt = json.loads(payload["messages"][1]["content"])
        plan = _valid_plan()
        template = plan["outline"]["chapters"][0]
        plan["outline"]["arcs"] = [
            arc
            for arc in prompt["existing_outline"]["arcs"]
            if arc["id"] != "locked-inner"
        ]
        plan["outline"]["chapters"] = [
            {
                **template,
                "chapter_number": number,
                "trope_beat": "异常出现" if number == 11 else None,
                "cast": ["林照", "New"] if mode == "extend" else template["cast"],
            }
            for number in prompt["target_chapter_numbers"]
        ]
        if mode == "extend":
            plan["characters"] = [_card("New", "supporting")]
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    existing_chapters = list(range(1, 11)) if mode == "extend" else list(range(1, 21))
    brief = fixture.brief(current_chapter=10, existing_chapters=existing_chapters)
    payload = brief.model_dump(mode="json")
    payload["existing_outline"]["arcs"].append(
        {
            **payload["existing_outline"]["arcs"][0],
            "id": "locked-inner",
            "start_chapter": 11,
            "end_chapter": 20,
            "trope_id": "golden_finger_first_test",
        }
    )
    payload["existing_character_names"] = ["林照"]
    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=fixture.resolve,
    )

    plan = generator.generate(OutlinePlanningBrief.model_validate(payload), mode=mode)

    assert any(chapter.trope_beat == "异常出现" for chapter in plan.outline.chapters)


def test_extend_prompt_requests_only_missing_window_chapters(generator_fixture) -> None:
    brief = generator_fixture.brief(
        current_chapter=10,
        existing_chapters=list(range(1, 11)),
    )

    generator_fixture.generator().generate(brief, mode="extend")

    assert generator_fixture.prompt_context["target_chapter_numbers"] == list(range(11, 21))
    assert generator_fixture.prompt_context["current_strategy"] == "expand"


def test_regenerate_requests_next_detail_window(generator_fixture) -> None:
    brief = generator_fixture.brief(
        current_chapter=10,
        existing_chapters=list(range(1, 21)),
    )

    generator_fixture.generator().generate(brief, mode="regenerate")

    assert generator_fixture.prompt_context["target_chapter_numbers"] == list(range(11, 21))


def test_continuation_regenerate_ignores_previous_batch_ceiling(generator_fixture) -> None:
    brief = generator_fixture.brief(
        current_chapter=145,
        existing_chapters=list(range(136, 154)),
    )
    payload = brief.model_dump(mode="json")
    payload["existing_outline"]["overall"].update(
        core_ending_chapter=153,
        extension_ceiling_chapter=153,
    )
    payload["continuation_start_chapter"] = 141
    payload["historical_chapter_summaries"] = [
        {"chapter_number": 1, "title": "维修铺", "summary": "林修从凡俗维修铺起步。"},
        {"chapter_number": 141, "title": "雪山神殿", "summary": "林修守住残镜并发现皇血牵引。"},
    ]

    generator_fixture.generator().generate(
        OutlinePlanningBrief.model_validate(payload),
        mode="regenerate",
    )

    prompt = generator_fixture.prompt_context
    assert prompt["target_chapter_numbers"] == list(range(146, 156))
    assert prompt["continuation_start_chapter"] == 141
    assert prompt["historical_chapter_summaries"] == [
        {
            "start_chapter": 1,
            "end_chapter": 141,
            "chapter_digest": [
                "第1章 维修铺：林修从凡俗维修铺起步。",
                "第141章 雪山神殿：林修守住残镜并发现皇血牵引。",
            ],
        }
    ]
    rules = "\n".join(prompt["validation_rules"])
    assert "whole book" in rules
    assert "historical arcs" in rules


def test_continuation_history_is_compacted_into_bounded_chapter_blocks(generator_fixture) -> None:
    brief = generator_fixture.brief(current_chapter=145, existing_chapters=list(range(136, 154)))
    payload = brief.model_dump(mode="json")
    payload["continuation_start_chapter"] = 141
    payload["historical_chapter_summaries"] = [
        {"chapter_number": number, "title": f"节点{number}", "summary": "剧情" * 160}
        for number in range(1, 22)
    ]

    generator_fixture.generator().generate(
        OutlinePlanningBrief.model_validate(payload),
        mode="regenerate",
    )

    blocks = generator_fixture.prompt_context["historical_chapter_summaries"]
    assert [(block["start_chapter"], block["end_chapter"]) for block in blocks] == [
        (1, 10),
        (11, 20),
        (21, 21),
    ]
    assert sum(len(block["chapter_digest"]) for block in blocks) == 21
    assert max(len(item) for block in blocks for item in block["chapter_digest"]) <= 100


def test_initial_requires_unstarted_project(generator_fixture) -> None:
    brief = generator_fixture.brief(current_chapter=1, existing_chapters=list(range(1, 11)))

    with pytest.raises(ValueError, match="^initial_outline_requires_unstarted_project$"):
        generator_fixture.generator().generate(brief, mode="initial")


def test_extend_rejects_full_window(generator_fixture) -> None:
    brief = generator_fixture.brief(current_chapter=10, existing_chapters=list(range(1, 21)))

    with pytest.raises(ValueError, match="^outline_window_already_full$"):
        generator_fixture.generator().generate(brief, mode="extend")


def test_extend_prompt_includes_sparse_window_holes(generator_fixture) -> None:
    brief = generator_fixture.brief(
        current_chapter=10,
        existing_chapters=[*range(1, 11), 15],
    )

    generator_fixture.generator().generate(brief, mode="extend")

    assert generator_fixture.prompt_context["target_chapter_numbers"] == [
        *range(11, 15),
        *range(16, 21),
    ]


def test_regenerate_stops_at_extension_ceiling(generator_fixture) -> None:
    brief = generator_fixture.brief(current_chapter=490, existing_chapters=list(range(1, 491)))
    payload = brief.model_dump(mode="json")
    payload["existing_outline"]["overall"]["extension_ceiling_chapter"] = 500
    brief = OutlinePlanningBrief.model_validate(payload)

    generator_fixture.generator().generate(brief, mode="regenerate")

    assert generator_fixture.prompt_context["target_chapter_numbers"] == list(range(491, 501))


def test_regenerate_at_extension_ceiling_rejects_before_model_call(generator_fixture) -> None:
    brief = generator_fixture.brief(
        current_chapter=500,
        existing_chapters=list(range(1, 501)),
    )

    with pytest.raises(ValueError, match="^outline_window_already_full$"):
        generator_fixture.generator().generate(brief, mode="regenerate")

    assert generator_fixture.calls == []
    assert generator_fixture.runtime_calls == []


def test_extend_accepts_only_new_character_cards_and_existing_cast() -> None:
    prompt_context = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        prompt_context.update(json.loads(payload["messages"][1]["content"]))
        plan = _valid_plan()
        template = plan["outline"]["chapters"][0]
        plan["outline"]["arcs"] = []
        plan["outline"]["chapters"] = [
            {
                **template,
                "chapter_number": number,
                "trope_beat": None,
                "cast": ["林照", "新角色"],
            }
            for number in prompt_context["target_chapter_numbers"]
        ]
        plan["characters"] = [_card("新角色", "supporting")]
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    brief = fixture.brief(current_chapter=10, existing_chapters=list(range(1, 11)))
    payload = brief.model_dump(mode="json")
    payload["existing_characters"] = [{"name": "林照"}]
    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=fixture.resolve,
    )

    plan = generator.generate(OutlinePlanningBrief.model_validate(payload), mode="extend")

    assert [card.name for card in plan.characters] == ["新角色"]
    rules = "\n".join(prompt_context["validation_rules"])
    assert "only newly introduced character cards" in rules
    assert "existing_character_names" in rules


def test_extend_accepts_seventh_existing_character_in_cast() -> None:
    prompt_context = {}
    detailed_names = [f"已有角色{number}" for number in range(1, 7)]
    all_names = [*detailed_names, "第七个已有角色"]

    def fake_post(base_url, path, payload, api_key, **kwargs):
        prompt_context.update(json.loads(payload["messages"][1]["content"]))
        plan = _valid_plan()
        template = plan["outline"]["chapters"][0]
        plan["outline"]["arcs"] = []
        plan["outline"]["chapters"] = [
            {
                **template,
                "chapter_number": number,
                "trope_beat": None,
                "cast": ["第七个已有角色", "新角色"],
            }
            for number in prompt_context["target_chapter_numbers"]
        ]
        plan["characters"] = [_card("新角色", "supporting")]
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    brief = fixture.brief(current_chapter=10, existing_chapters=list(range(1, 11)))
    payload = brief.model_dump(mode="json")
    payload["existing_characters"] = [{"name": name} for name in detailed_names]
    payload["existing_character_names"] = all_names
    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=fixture.resolve,
    )

    plan = generator.generate(OutlinePlanningBrief.model_validate(payload), mode="extend")

    assert [card.name for card in plan.characters] == ["新角色"]
    assert prompt_context["existing_character_names"] == all_names


@pytest.mark.parametrize(
    "returned_name,cast,error",
    [
        (
            "第七个已有角色",
            ["第七个已有角色"],
            "duplicate_existing_character_card:第七个已有角色",
        ),
        ("新角色", ["未知角色"], "missing_character_card:未知角色"),
    ],
)
def test_extend_wraps_model_contract_errors_uniformly(
    returned_name: str,
    cast: list[str],
    error: str,
) -> None:
    existing_name = "第七个已有角色"

    def fake_post(base_url, path, payload, api_key, **kwargs):
        prompt = json.loads(payload["messages"][1]["content"])
        plan = _valid_plan()
        template = plan["outline"]["chapters"][0]
        plan["outline"]["arcs"] = []
        plan["outline"]["chapters"] = [
            {
                **template,
                "chapter_number": number,
                "cast": cast,
            }
            for number in prompt["target_chapter_numbers"]
        ]
        plan["characters"] = [_card(returned_name, "supporting")]
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    brief = fixture.brief(current_chapter=10, existing_chapters=list(range(1, 11)))
    payload = brief.model_dump(mode="json")
    payload["existing_character_names"] = [existing_name]
    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=fixture.resolve,
    )

    with pytest.raises(ValueError, match="^outline_planning_generation_failed$") as exc_info:
        generator.generate(OutlinePlanningBrief.model_validate(payload), mode="extend")

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert str(exc_info.value.__cause__) == error


def test_generator_rejects_invalid_output_and_long_guidance() -> None:
    runtime_calls = []
    generator = LLMOutlinePlanningGenerator(
        post_json=lambda *args, **kwargs: {"choices": [{"message": {"content": "{}"}}]},
        runtime_resolver=lambda name: runtime_calls.append(name) or StageRuntimeSettings(
            provider_id="codexcli", protocol="codex_cli", model="planning-test-model"
        ),
    )

    with pytest.raises(ValueError, match="outline_planning_generation_failed"):
        generator.generate(_brief(), mode="initial")
    with pytest.raises(ValueError, match="regeneration_guidance_too_long"):
        generator.generate(_brief(), mode="initial", guidance="x" * 1001)

    assert runtime_calls == ["planner"]
