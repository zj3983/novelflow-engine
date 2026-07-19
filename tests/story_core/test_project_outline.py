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
    outline_from_legacy_project,
    select_outline_context,
)


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
        "protagonist_goal",
        "main_conflict",
        "growth_path",
        "ending_direction",
        "core_ending_chapter",
        "extension_ceiling_chapter",
        "current_strategy",
        "ending_contract",
    }
    assert set(payload["arcs"][0]) == {
        "id",
        "title",
        "start_chapter",
        "end_chapter",
        "goal",
        "obstacle",
        "payoff",
        "end_state",
        "stage_antagonist",
        "long_term_antagonist_traces",
        "game_line_payoff",
        "reality_line_payoff",
        "extension_gate",
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
        "cast",
    }


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


def test_expandable_outline_requires_dual_line_payoffs_for_core_arcs() -> None:
    with pytest.raises(ValueError, match="missing_arc_dual_line_payoff:opening"):
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
                        "extension_gate": {
                            "continue_route": "进入下一阶段。",
                            "close_route": "进入结局。",
                        },
                    }
                ],
            }
        )


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
            "end_state": "",
            "stage_antagonist": "",
            "long_term_antagonist_traces": [],
            "game_line_payoff": "",
            "reality_line_payoff": "",
            "extension_gate": {"continue_route": "", "close_route": ""},
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
            "protagonist_goal": "",
            "main_conflict": "",
            "growth_path": "",
            "ending_direction": "",
            "core_ending_chapter": 1,
            "extension_ceiling_chapter": 1,
            "current_strategy": "observe",
            "ending_contract": "",
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
