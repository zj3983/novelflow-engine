from __future__ import annotations

from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from packages.story_core.project_outline import (
    ArcOutline,
    ChapterPlan,
    OverallOutline,
    ProjectOutline,
    normalize_project_outline,
    normalize_outline_for_story_type,
    outline_from_legacy_project,
    select_outline_context,
)


def test_non_game_outline_discards_game_only_arc_payoffs() -> None:
    payload = {
        "overall": {"story": "修理师追查仙器失控。"},
        "arcs": [
            {
                "id": "opening",
                "start_chapter": 1,
                "end_chapter": 10,
                "game_line_payoff": "错误混入的游戏线",
                "reality_line_payoff": "错误混入的现实线",
            }
        ],
    }

    generic = normalize_outline_for_story_type(payload, is_game_story=False)
    game = normalize_outline_for_story_type(payload, is_game_story=True)

    assert generic["arcs"][0]["game_line_payoff"] == ""
    assert generic["arcs"][0]["reality_line_payoff"] == ""
    assert game["arcs"][0]["game_line_payoff"] == "错误混入的游戏线"


def test_outline_arc_preserves_optional_game_pacing_stage_id() -> None:
    normalized = normalize_project_outline(
        {
            "arcs": [
                {
                    "id": "opening",
                    "start_chapter": 1,
                    "end_chapter": 50,
                    "pacing_stage_id": "newcomer_rise",
                }
            ]
        }
    )

    assert normalized["arcs"][0]["pacing_stage_id"] == "newcomer_rise"


def test_chapter_numeric_plan_round_trips_as_structured_outline_data() -> None:
    numeric_plan = {
        "experience": {"start": 0, "threshold": 100, "kills": [12] * 7 + [16]},
        "combat": {"fireball_damage": 32, "wolf_hp": 80},
        "official_exchange": {"gross_yuan": 1500.0, "fee_yuan": 7.5, "net_yuan": 1492.5},
    }

    normalized = normalize_project_outline(
        {"chapters": [{"chapter_number": 1, "numeric_plan": numeric_plan}]}
    )

    assert normalized["chapters"][0]["numeric_plan"] == numeric_plan


def test_overall_story_core_groups_round_trip_without_a_second_document() -> None:
    normalized = normalize_project_outline(
        {
            "overall": {
                "story": "苏叶进入神域，必须靠游戏收益解决现实急账。",
                "positioning": {
                    "protagonist_profile": "现实拮据但熟悉程序规则的青年。",
                    "inciting_incident": "外包中断，急账当天到期。",
                    "failure_stakes": "失去住处并留下逾期记录。",
                    "excitement_point": "把异常掉落藏在正常游戏流程里滚成优势。",
                    "target_audience": "喜欢网游升级和幕后领先的读者。",
                    "reader_promise": "每个阶段都有明确升级、收益或权限兑现。",
                },
                "protagonist_drive": {
                    "immediate_need": "解决现实急账。",
                    "trigger": "外包尾款无法及时到账。",
                    "short_term_goal": "卖出第一件异常掉落。",
                    "failure_stakes": "现实账单逾期。",
                    "long_term_transition": "从临时救急转向掌握游戏与现实边界。",
                },
                "core_advantage": {
                    "name": "混沌之种",
                    "type": "概率异常",
                    "ability": "合规掉落判定提高。",
                    "growth_rule": "随解析进度开放新的规则层。",
                    "limits": "不能跳过击杀、任务和交易流程。",
                    "early_payoff": "第一章卖出裂纹狼心。",
                },
                "central_mystery": {
                    "surface_anomaly": "掉落判定乘一千。",
                    "hidden_truth": "游戏与现实共享底层规则。",
                    "reality_impact": "游戏能力会逐步进入现实。",
                    "reveal_path": ["验证掉落", "发现地图响应", "进入中央封锁区"],
                },
            }
        }
    )

    assert normalized["overall"]["positioning"]["reader_promise"].startswith("每个阶段")
    assert normalized["overall"]["protagonist_drive"]["short_term_goal"] == "卖出第一件异常掉落。"
    assert normalized["overall"]["core_advantage"]["name"] == "混沌之种"
    assert normalized["overall"]["central_mystery"]["reveal_path"][-1] == "进入中央封锁区"
    context = select_outline_context(normalized, 1)
    assert context["overall"]["central_mystery"]["surface_anomaly"] == "掉落判定乘一千。"


def test_models_expose_the_canonical_outline_fields() -> None:
    outline = ProjectOutline(
        overall=OverallOutline(
            story="林照追查宗门旧案。",
            protagonist_goal="查清师父失踪真相",
            main_conflict="宗门长老封锁旧案",
            growth_path="从守祠弟子成长为执法堂首席",
            ending_direction="公开真相并重建宗门规则",
        ),
        arcs=[
            ArcOutline(
                id="opening",
                title="祖祠失火",
                start_chapter=1,
                end_chapter=8,
                goal="找到纵火者",
                obstacle="证据被毁",
                payoff="锁定内门嫌疑人",
                end_state="林照取得进入内门的资格",
            )
        ],
        chapters=[
            ChapterPlan(
                chapter_number=2,
                title="夜查祖祠",
                goal="寻找残留证据",
                obstacle="巡夜弟子提前换岗",
                action="潜入封锁区",
                turn="灰烬下发现第二组脚印",
                payoff="找到灰烬脚印",
                ending_hook="脚印通向内门",
            )
        ],
    )

    payload = outline.model_dump()

    assert payload["schema_version"] == "project-outline/v1"
    assert set(payload["overall"]) == {
        "story",
        "theme_statement",
        "foreground_story",
        "background_story",
        "book_objective",
        "ending_image",
        "protagonist_goal",
        "main_conflict",
        "growth_path",
        "ending_direction",
        "primary_trope_id",
        "core_ending_chapter",
        "extension_ceiling_chapter",
        "current_strategy",
        "ending_contract",
        "core_selling_point",
        "long_term_lines",
        "planned_arc_count",
        "planned_length",
        "expansion_route",
        "closing_route",
        "positioning",
        "protagonist_drive",
        "core_advantage",
        "central_mystery",
    }
    assert set(payload["arcs"][0]) == {
        "id",
        "title",
        "start_chapter",
        "end_chapter",
        "pacing_stage_id",
        "goal",
        "obstacle",
        "payoff",
        "trope_id",
        "end_state",
        "stage_antagonist",
        "long_term_antagonist_traces",
        "game_line_payoff",
        "reality_line_payoff",
        "emotional_curve",
        "key_results",
        "hook_plan",
        "irreversible_change",
        "extension_gate",
        "active_long_term_lines",
        "core_loop",
        "escalations",
        "midpoint_turn",
        "climax",
        "relationship_changes",
        "foreshadowing_in",
        "foreshadowing_out",
        "next_arc_entry",
    }
    assert payload["arcs"][0]["id"]
    assert set(payload["chapters"][0]) == {
        "chapter_number",
        "title",
        "goal",
        "obstacle",
        "action",
        "turn",
        "payoff",
        "ending_hook",
        "trope_beat",
        "cast",
            "level_target",
            "attribute_allocation_decision",
            "numeric_plan",
            "opponent_response",
            "emotional_change",
            "gain_or_loss",
            "must_include",
            "must_not_write",
            "scene_chain",
        }


def test_filled_long_form_outline_template_fields_round_trip() -> None:
    normalized = normalize_project_outline(
        {
            "overall": {
                "core_selling_point": "维修能力从家电一路作用到天地规则。",
                "long_term_lines": [
                    {
                        "name": "维修成长线",
                        "purpose": "推动能力与职业变化",
                        "start_state": "只能修普通家电",
                        "progression_steps": ["修法器", "修灵脉", "修世界规则"],
                        "final_payoff": "阻止万界崩坏",
                    }
                ],
                "planned_arc_count": 8,
                "planned_length": 320,
                "expansion_route": "进入更多世界处理不同层级的故障。",
                "closing_route": "回收天地故障源头并完成主角选择。",
            },
            "arcs": [
                {
                    "id": "opening",
                    "start_chapter": 1,
                    "end_chapter": 40,
                    "active_long_term_lines": ["维修成长线"],
                    "core_loop": "接单、诊断、维修、获得更高权限。",
                    "escalations": ["修家电", "修法器", "修护宗阵"],
                    "midpoint_turn": "故障并非自然形成。",
                    "climax": "公开修复护宗阵。",
                    "relationship_changes": ["宗门从轻视转为争取"],
                    "foreshadowing_in": ["异常裂纹"],
                    "foreshadowing_out": ["天机阁标记"],
                    "next_arc_entry": "天机阁派人上门。",
                }
            ],
            "chapters": [
                {
                    "chapter_number": 1,
                    "opponent_response": "掌柜拒绝让他碰坏掉的法器。",
                    "emotional_change": "从忍耐转为决定当场证明。",
                    "gain_or_loss": "获得第一次公开维修机会。",
                }
            ],
        }
    )

    assert normalized["overall"]["long_term_lines"][0]["progression_steps"][-1] == "修世界规则"
    assert normalized["arcs"][0]["escalations"] == ["修家电", "修法器", "修护宗阵"]
    assert normalized["chapters"][0]["opponent_response"].startswith("掌柜")


def test_elastic_outline_fields_round_trip() -> None:
    normalized = normalize_project_outline(
        {
            "overall": {
                "story": "夜烬从新手村走向主城。",
                "core_ending_chapter": 150,
                "extension_ceiling_chapter": 500,
                "current_strategy": "observe",
                "ending_contract": "现实线和游戏线都完成核心结局。",
            },
            "arcs": [
                {
                    "id": "opening",
                    "start_chapter": 1,
                    "end_chapter": 30,
                    "game_line_payoff": "进入主城并建立稳定材料渠道。",
                    "reality_line_payoff": "到账足够支付眼前急账的收入。",
                    "extension_gate": {
                        "continue_route": "进入主城并开放公会竞争。",
                        "close_route": "回收新手村线索并转入校验者结局。",
                    },
                }
            ],
        }
    )

    assert normalized["overall"]["core_ending_chapter"] == 150
    assert normalized["overall"]["extension_ceiling_chapter"] == 500
    assert normalized["overall"]["current_strategy"] == "observe"
    assert normalized["arcs"][0]["extension_gate"]["continue_route"]


@pytest.mark.parametrize(
    "decision",
    [
        {"mode": "carry", "allocations": {"智力": 5}, "remaining": 5},
        {"mode": "allocate", "allocations": {}, "remaining": 5},
        {"mode": "allocate", "allocations": {"智力": -1}, "remaining": 6},
        {"mode": "allocate", "allocations": {"": 5}, "remaining": 0},
        {"mode": "allocate", "allocations": {"智力、精神": 5}, "remaining": 0},
        {"mode": "allocate", "allocations": {"智力+精神": 5}, "remaining": 0},
        {
            "mode": "carry",
            "allocations": {},
            "remaining": 5,
            "reason": "等转职\n再分配",
        },
    ],
)
def test_attribute_allocation_decision_rejects_non_round_trip_shapes(
    decision: dict,
) -> None:
    with pytest.raises(ValidationError, match="invalid_attribute_allocation_decision"):
        normalize_project_outline(
            {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "attribute_allocation_decision": decision,
                    }
                ]
            }
        )


def test_old_outline_defaults_to_non_expanding_observe_mode() -> None:
    normalized = normalize_project_outline(
        {
            "arcs": [
                {"id": "opening", "start_chapter": 1, "end_chapter": 30}
            ],
            "chapters": [{"chapter_number": 1}],
        }
    )

    assert normalized["overall"]["core_ending_chapter"] == 30
    assert normalized["overall"]["extension_ceiling_chapter"] == 30
    assert normalized["overall"]["current_strategy"] == "observe"
    assert normalized["arcs"][0]["extension_gate"] == {
        "continue_route": "",
        "close_route": "",
    }


def test_legacy_outlines_normalize_missing_trope_fields_to_none() -> None:
    normalized = normalize_project_outline(
        {
            "overall": {"story": "旧版总纲"},
            "arcs": [{"id": "opening", "start_chapter": 1, "end_chapter": 3}],
            "chapters": [{"chapter_number": 1, "title": "第一章"}],
        }
    )

    assert normalized["overall"]["primary_trope_id"] is None
    assert normalized["arcs"][0]["trope_id"] is None
    assert normalized["chapters"][0]["trope_beat"] is None


def test_extension_ceiling_cannot_precede_core_ending() -> None:
    with pytest.raises(ValueError, match="extension_ceiling_before_core_ending"):
        normalize_project_outline(
            {
                "overall": {
                    "core_ending_chapter": 150,
                    "extension_ceiling_chapter": 120,
                }
            }
        )


def test_general_outline_keeps_long_form_story_and_volume_fields() -> None:
    normalized = normalize_project_outline(
        {
            "overall": {
                "story": "林修以维修之道追查天地崩坏。",
                "theme_statement": "修复世界之前，先决定什么值得保留。",
                "foreground_story": "林修修复法宝、阵法和灵脉，逐步建立自己的势力。",
                "background_story": "天机阁利用天地故障熔炼万界。",
                "book_objective": "林修建立万修宗，并阻止天机阁熔炼灵气界。",
                "ending_image": "恢复流动的灵气穿过各州，林修收起最后一件修复工具。",
            },
            "arcs": [
                {
                    "id": "opening",
                    "title": "青云宗立足",
                    "start_chapter": 1,
                    "end_chapter": 30,
                    "emotional_curve": "先受压，再以连续修复建立信任，卷尾首次公开反击。",
                    "key_results": ["取得正式弟子身份", "修复宗门灵气井", "拿到天机阁的第一条线索"],
                    "hook_plan": "灵气井中的旧刻痕在第三卷回收。",
                    "irreversible_change": "林修公开维修之道，无法再退回普通杂役身份。",
                }
            ],
        }
    )

    assert normalized["overall"]["foreground_story"].startswith("林修修复")
    assert normalized["overall"]["background_story"].startswith("天机阁")
    assert normalized["overall"]["book_objective"].endswith("灵气界。")
    assert normalized["arcs"][0]["key_results"] == [
        "取得正式弟子身份",
        "修复宗门灵气井",
        "拿到天机阁的第一条线索",
    ]
    assert normalized["arcs"][0]["irreversible_change"].startswith("林修公开")


def test_legacy_outline_derives_safe_long_form_defaults_without_overwriting_content() -> None:
    normalized = normalize_project_outline(
        {
            "overall": {
                "story": "林修从青云宗杂役起步，追查天地故障。",
                "ending_direction": "林修修复天道并建立万修宗。",
            },
            "arcs": [
                {
                    "id": "opening",
                    "goal": "取得正式弟子身份",
                    "payoff": "修复宗门灵气井",
                    "end_state": "林修获得独立修复法宝的资格",
                    "long_term_antagonist_traces": ["井底留有天机阁旧印"],
                }
            ],
        }
    )

    assert normalized["overall"]["foreground_story"] == normalized["overall"]["story"]
    assert normalized["overall"]["book_objective"] == normalized["overall"]["ending_direction"]
    assert normalized["overall"]["ending_image"] == normalized["overall"]["ending_direction"]
    assert normalized["arcs"][0]["key_results"] == [
        "取得正式弟子身份",
        "修复宗门灵气井",
        "林修获得独立修复法宝的资格",
    ]
    assert normalized["arcs"][0]["hook_plan"] == "井底留有天机阁旧印"
    assert normalized["arcs"][0]["irreversible_change"] == "林修获得独立修复法宝的资格"


def test_expandable_outline_requires_both_routes_for_core_arcs() -> None:
    with pytest.raises(ValueError, match="missing_arc_extension_route:opening"):
        normalize_project_outline(
            {
                "overall": {
                    "core_ending_chapter": 150,
                    "extension_ceiling_chapter": 500,
                },
                "arcs": [
                    {
                        "id": "opening",
                        "start_chapter": 1,
                        "end_chapter": 30,
                        "game_line_payoff": "进入主城。",
                        "reality_line_payoff": "解决急账。",
                        "extension_gate": {"continue_route": "继续", "close_route": ""},
                    }
                ],
            }
        )


def test_general_expandable_outline_does_not_require_game_dual_lines() -> None:
    normalized = normalize_project_outline(
        {
            "overall": {
                "core_ending_chapter": 150,
                "extension_ceiling_chapter": 500,
            },
            "arcs": [
                {
                    "id": "opening",
                    "start_chapter": 1,
                    "end_chapter": 30,
                    "extension_gate": {
                        "continue_route": "进入下一阶段。",
                        "close_route": "进入结局。",
                    },
                }
            ],
        }
    )

    assert normalized["arcs"][0]["game_line_payoff"] == ""
    assert normalized["arcs"][0]["reality_line_payoff"] == ""


def test_normalize_is_deterministic_non_mutating_json_serializable_and_sorted() -> None:
    payload = {
        "arcs": [
            {"id": "later", "title": "后段", "start_chapter": 11, "end_chapter": 20},
            {"id": "opening", "title": "开篇", "start_chapter": 1, "end_chapter": 10},
            {"id": "short", "title": "短阶段", "start_chapter": 1, "end_chapter": 3},
        ],
        "chapters": [
            {"chapter_number": 12, "goal": "通过内门考核"},
            {"chapter_number": 2, "goal": "查祖祠"},
        ],
    }
    original = deepcopy(payload)

    normalized = normalize_project_outline(payload)

    assert [arc["id"] for arc in normalized["arcs"]] == ["short", "opening", "later"]
    assert [chapter["chapter_number"] for chapter in normalized["chapters"]] == [2, 12]
    assert normalize_project_outline(payload) == normalized
    assert payload == original
    assert json.loads(json.dumps(normalized, ensure_ascii=False)) == normalized


def test_inverted_arc_range_reports_explicit_error() -> None:
    with pytest.raises(ValueError, match="invalid_arc_chapter_range"):
        normalize_project_outline(
            {
                "arcs": [
                    {
                        "id": "inverted",
                        "start_chapter": 3,
                        "end_chapter": 2,
                    }
                ]
            }
        )


@pytest.mark.parametrize("chapter_number", [0, True, 1.0, 1.5])
def test_chapter_number_requires_a_strict_positive_integer(chapter_number: object) -> None:
    with pytest.raises(ValueError):
        normalize_project_outline({"chapters": [{"chapter_number": chapter_number}]})


@pytest.mark.parametrize(
    "start_chapter,end_chapter",
    [(0, 1), (1, 0), (True, 2), (1, False), (1.0, 2), (1, 2.0), (1.5, 2)],
)
def test_arc_boundaries_require_strict_positive_integers(
    start_chapter: object,
    end_chapter: object,
) -> None:
    with pytest.raises(ValueError):
        normalize_project_outline(
            {
                "arcs": [
                    {
                        "id": "strict-range",
                        "start_chapter": start_chapter,
                        "end_chapter": end_chapter,
                    }
                ]
            }
        )


@pytest.mark.parametrize("payload", [[], "", 0, False])
def test_normalize_rejects_invalid_root_types(payload: object) -> None:
    with pytest.raises(ValueError):
        normalize_project_outline(payload)


def test_normalize_treats_only_none_as_an_empty_outline() -> None:
    assert normalize_project_outline(None) == normalize_project_outline({})


@pytest.mark.parametrize("invalid_overall", [None, [], False])
def test_malformed_overall_reports_validation_error(invalid_overall: object) -> None:
    with pytest.raises(ValidationError):
        normalize_project_outline({"overall": invalid_overall})


def test_arc_id_is_required() -> None:
    with pytest.raises(ValueError, match="Field required"):
        normalize_project_outline(
            {"arcs": [{"start_chapter": 1, "end_chapter": 2}]}
        )


@pytest.mark.parametrize("arc_id", ["", " ", "\t\n"])
def test_arc_id_must_not_be_blank(arc_id: str) -> None:
    with pytest.raises(ValueError, match="invalid_arc_id"):
        normalize_project_outline(
            {
                "arcs": [
                    {"id": arc_id, "start_chapter": 1, "end_chapter": 2}
                ]
            }
        )


def test_arc_ids_must_be_unique() -> None:
    with pytest.raises(ValueError, match="duplicate_arc_id"):
        normalize_project_outline(
            {
                "arcs": [
                    {"id": "same", "start_chapter": 1, "end_chapter": 2},
                    {"id": "same", "start_chapter": 3, "end_chapter": 4},
                ]
            }
        )


def test_schema_version_rejects_future_versions() -> None:
    with pytest.raises(ValueError, match="project-outline/v1"):
        normalize_project_outline({"schema_version": "project-outline/v2"})


@pytest.mark.parametrize(
    "payload",
    [
        {"unknown": "project"},
        {"overall": {"unknown": "overall"}},
        {"arcs": [{"id": "arc", "unknown": "arc"}]},
        {"chapters": [{"chapter_number": 1, "unknown": "chapter"}]},
    ],
)
def test_all_canonical_models_reject_unknown_fields(payload: dict) -> None:
    with pytest.raises(ValueError, match="extra_forbidden"):
        normalize_project_outline(payload)


def test_duplicate_chapter_outlines_report_explicit_error() -> None:
    with pytest.raises(ValueError, match="duplicate_chapter_outline"):
        normalize_project_outline(
            {
                "chapters": [
                    {"chapter_number": 3, "title": "初稿"},
                    {"chapter_number": 3, "title": "重复稿"},
                ]
            }
        )


def test_legacy_project_projects_into_three_levels_without_mutation() -> None:
    project = {
        "seed_outline": "林照靠断香炉追查宗门旧案。",
        "world_blueprint": {
            "current_arc": "先查清祖祠失火原因。",
            "opening_arc": {
                "chapter_beats": [
                    {
                        "chapter": 4,
                        "title": "追入内门",
                        "payoff": "确认接头人",
                        "hook": "接头人佩戴长老令牌",
                    },
                    {
                        "chapter": 2,
                        "title": "夜查祖祠",
                        "required_payoff": "找到灰烬脚印",
                        "ending_hook": "脚印通向内门",
                    },
                ]
            },
        },
    }
    original = deepcopy(project)

    outline = outline_from_legacy_project(project)

    assert outline["overall"]["story"] == "林照靠断香炉追查宗门旧案。"
    assert outline["arcs"] == [
        {
            "id": "legacy-opening",
            "title": "当前阶段",
            "start_chapter": 1,
            "end_chapter": 4,
            "goal": "先查清祖祠失火原因。",
            "obstacle": "",
            "payoff": "",
            "emotional_curve": "",
            "key_results": ["先查清祖祠失火原因。"],
            "hook_plan": "",
            "irreversible_change": "",
            "trope_id": None,
            "end_state": "",
            "stage_antagonist": "",
            "long_term_antagonist_traces": [],
            "game_line_payoff": "",
            "reality_line_payoff": "",
                "extension_gate": {"continue_route": "", "close_route": ""},
                "active_long_term_lines": [],
                "core_loop": "",
                "escalations": [],
                "midpoint_turn": "",
                "climax": "",
                "relationship_changes": [],
                "foreshadowing_in": [],
                "foreshadowing_out": [],
                "next_arc_entry": "",
        }
    ]
    assert [chapter["chapter_number"] for chapter in outline["chapters"]] == [2, 4]
    assert outline["chapters"][0]["title"] == "夜查祖祠"
    assert outline["chapters"][0]["payoff"] == "找到灰烬脚印"
    assert outline["chapters"][0]["ending_hook"] == "脚印通向内门"
    assert outline["chapters"][0]["cast"] == []
    assert outline["chapters"][1]["payoff"] == "确认接头人"
    assert outline["chapters"][1]["ending_hook"] == "接头人佩戴长老令牌"
    assert project == original
    assert "outline" not in project


def test_legacy_projection_tolerates_missing_or_malformed_optional_sections() -> None:
    assert outline_from_legacy_project({"seed_outline": "只有总纲"}) == {
        "schema_version": "project-outline/v1",
        "overall": {
            "story": "只有总纲",
            "theme_statement": "",
            "foreground_story": "只有总纲",
            "background_story": "",
            "book_objective": "",
            "ending_image": "",
            "protagonist_goal": "",
            "main_conflict": "",
            "growth_path": "",
            "ending_direction": "",
            "primary_trope_id": None,
            "core_ending_chapter": 1,
            "extension_ceiling_chapter": 1,
            "current_strategy": "observe",
                "ending_contract": "",
                "core_selling_point": "",
                "long_term_lines": [],
                "planned_arc_count": 0,
                "planned_length": 1,
                "expansion_route": "",
                "closing_route": "",
                "positioning": {
                    "protagonist_profile": "",
                    "inciting_incident": "",
                    "failure_stakes": "",
                    "excitement_point": "",
                    "target_audience": "",
                    "reader_promise": "",
                },
                "protagonist_drive": {
                    "immediate_need": "",
                    "trigger": "",
                    "short_term_goal": "",
                    "failure_stakes": "",
                    "long_term_transition": "",
                },
                "core_advantage": {
                    "name": "",
                    "type": "",
                    "ability": "",
                    "growth_rule": "",
                    "limits": "",
                    "early_payoff": "",
                },
                "central_mystery": {
                    "surface_anomaly": "",
                    "hidden_truth": "",
                    "reality_impact": "",
                    "reveal_path": [],
                },
        },
        "arcs": [],
        "chapters": [],
    }
    assert outline_from_legacy_project(
        {"world_blueprint": {"opening_arc": {"chapter_beats": [None, {"chapter": 0}]}}}
    )["chapters"] == []


def test_selection_returns_only_active_arc_and_target_chapter() -> None:
    outline = normalize_project_outline(
        {
            "overall": {"story": "总纲"},
            "arcs": [
                {"id": "broad", "title": "大阶段", "start_chapter": 1, "end_chapter": 30},
                {"id": "opening", "title": "开篇", "start_chapter": 1, "end_chapter": 10},
                {"id": "inner", "title": "内门", "start_chapter": 11, "end_chapter": 20},
            ],
            "chapters": [
                {"chapter_number": 2, "goal": "查祖祠"},
                {"chapter_number": 12, "goal": "过内门考核"},
            ],
        }
    )

    context = select_outline_context(outline, 12)

    assert set(context) == {"schema_version", "overall", "active_arc", "chapter"}
    assert context["schema_version"] == "outline-context/v1"
    assert context["overall"]["story"] == "总纲"
    assert context["active_arc"]["id"] == "inner"
    assert context["chapter"]["chapter_number"] == 12
    assert "arcs" not in context
    assert "chapters" not in context


def test_writing_context_omits_future_routes_and_outline_bulk() -> None:
    outline = normalize_project_outline(
        {
            "overall": {
                "story": "核心故事",
                "core_ending_chapter": 150,
                "extension_ceiling_chapter": 500,
                "current_strategy": "observe",
                "ending_contract": "两条线完整收束。",
            },
            "arcs": [
                {
                    "id": "opening",
                    "start_chapter": 1,
                    "end_chapter": 30,
                    "game_line_payoff": "游戏线阶段收束",
                    "reality_line_payoff": "现实线阶段收束",
                    "extension_gate": {
                        "continue_route": "跨服战争",
                        "close_route": "进入最终冲突",
                    },
                }
            ],
            "chapters": [{"chapter_number": 2, "goal": "完成前置任务"}],
        }
    )

    context = select_outline_context(outline, 2)

    assert context["overall"]["ending_contract"] == "两条线完整收束。"
    assert context["overall"]["current_strategy"] == "observe"
    assert "core_ending_chapter" not in context["overall"]
    assert "extension_gate" not in context["active_arc"]
    assert "arcs" not in context
    assert "chapters" not in context


def test_selection_overlap_tiebreakers_do_not_depend_on_input_order() -> None:
    arcs = [
        {"id": "broad", "start_chapter": 1, "end_chapter": 20},
        {"id": "wider-late", "start_chapter": 5, "end_chapter": 10},
        {"id": "beta", "start_chapter": 5, "end_chapter": 8},
        {"id": "alpha", "start_chapter": 5, "end_chapter": 8},
    ]

    selected_ids = [
        select_outline_context({"arcs": ordered_arcs}, 6)["active_arc"]["id"]
        for ordered_arcs in (arcs, list(reversed(arcs)))
    ]

    assert selected_ids == ["alpha", "alpha"]


def test_selection_context_preserves_trope_fields() -> None:
    outline = normalize_project_outline(
        {
            "overall": {
                "story": "总纲",
                "primary_trope_id": "golden_finger_first_test",
            },
            "arcs": [
                {
                    "id": "opening",
                    "start_chapter": 1,
                    "end_chapter": 5,
                    "trope_id": "resource_gate",
                }
            ],
            "chapters": [
                {
                    "chapter_number": 3,
                    "title": "试探",
                    "trope_beat": "付出代价拿到部分资源",
                }
            ],
        }
    )

    context = select_outline_context(outline, 3)

    assert context["overall"]["primary_trope_id"] == "golden_finger_first_test"
    assert context["active_arc"]["trope_id"] == "resource_gate"
    assert context["chapter"]["trope_beat"] == "付出代价拿到部分资源"


def test_selection_returns_none_when_chapter_has_no_matching_details() -> None:
    context = select_outline_context({"overall": {"story": "总纲"}}, 99)

    assert context["active_arc"] is None
    assert context["chapter"] is None


def test_outline_supports_opposition_and_chapter_cast() -> None:
    outline = normalize_project_outline(
        {
            "arcs": [
                {
                    "id": "opening",
                    "start_chapter": 1,
                    "end_chapter": 10,
                    "stage_antagonist": "赵衡",
                    "long_term_antagonist_traces": ["旧名册有一页被换过"],
                }
            ],
            "chapters": [
                {
                    "chapter_number": 1,
                    "cast": ["林照", "赵衡"],
                }
            ],
        }
    )

    context = select_outline_context(outline, 1)

    assert context["active_arc"]["stage_antagonist"] == "赵衡"
    assert context["active_arc"]["long_term_antagonist_traces"] == ["旧名册有一页被换过"]
    assert context["chapter"]["cast"] == ["林照", "赵衡"]


def test_outline_preserves_chapter_hard_constraints_and_scene_chain() -> None:
    scene = {
        "location": "药剂铺",
        "pov": "夜烬",
        "goal": "接取普通任务",
        "obstacle": "柜台前有人排队",
        "action": "夜烬等候后接下清道夫委托",
        "change": "任务进度从0/16开始",
        "next": "前往灰狼坡",
        "state_delta": {"quests": {"清道夫委托": "进行中"}},
    }
    outline = normalize_project_outline(
        {
            "chapters": [
                {
                    "chapter_number": 1,
                    "goal": "完成第一次异常验证",
                    "must_include": ["灰狼毒腺进度为8/16"],
                    "must_not_write": ["不要提交清道夫委托"],
                    "scene_chain": [scene, scene, scene],
                }
            ]
        }
    )

    context = select_outline_context(outline, 1)

    assert context["chapter"]["must_include"] == ["灰狼毒腺进度为8/16"]
    assert context["chapter"]["must_not_write"] == ["不要提交清道夫委托"]
    assert context["chapter"]["scene_chain"][0] == scene
