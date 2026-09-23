from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from packages.story_core.build_graph.contracts import BuildRunConflict
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.model_gateway import ModelRequest, ModelResponse
from packages.story_core.models import NovelProject
from packages.story_core.world_build.definition import build_world_build_graph
from packages.story_core.world_enrichment import _power_spec_for_genre
from packages.story_core.world_build.runner import (
    WorldBuildGraphFailure,
    WorldBuildGraphRunner,
)
from packages.story_core.world_build import runner as world_build_runner
from packages.story_core.world_build.tasks import (
    build_task_prompt,
    canonical_world_input,
    parse_task_payload,
    repair_fields_for_diagnostics,
)
from packages.story_core.world_build.validators import make_world_validators
from packages.story_core.world_build.validators import power_final_owner_task
from packages.story_core.world_build.power_repairs import (
    PowerPathRepairScope,
    merge_power_path_repair,
    power_path_repair_scope,
    raw_power_spec_from_artifacts,
)
from packages.story_core.build_graph.contracts import BuildDiagnostic
from packages.story_core.power_system_spec import PATH_FIELDS, PowerSystemValidationError, validate_power_system_spec


def _store(tmp_path: Path, *, plugin_id: str) -> FileProjectStore:
    root = tmp_path / f"project-{plugin_id}"
    root.mkdir()
    project = NovelProject(
        project_id=f"file:{plugin_id}",
        title="合成世界",
        seed_outline="一个作者明确的起点。",
        world_blueprint={"genre_plugin_ids": [plugin_id]},
    )
    store = FileProjectStore(root)
    store.snapshot_store.replace_json_transaction(
        {
            store.webnovel_dir / "project.json": project.model_dump(mode="json"),
            store.webnovel_dir / "state.json": {"genre_plugin_ids": [plugin_id]},
        }
    )
    return store


class ScriptedGateway:
    def __init__(self, payloads: dict[str, list[Any]]) -> None:
        self.payloads = {key: list(value) for key, value in payloads.items()}
        self.calls: list[ModelRequest] = []

    def complete_stage(self, _stage: str, request: ModelRequest) -> ModelResponse:
        self.calls.append(request)
        task_id = request.operation.removeprefix("world_build_")
        values = self.payloads.setdefault(task_id, [])
        value = values.pop(0) if values else {"_missing": True}
        if isinstance(value, Exception):
            return ModelResponse.failure(request, str(value))
        return ModelResponse.success(
            request,
            text=json.dumps(value, ensure_ascii=False),
            raw={"model": "synthetic-world-model"},
        )


def _generic_payloads() -> dict[str, list[Any]]:
    return {
        "world_core_rules": [
            {
                "premise": "承诺留下公开记录。",
                "world_rules": ["记录可以被查询，但不能被删除。"],
                "constraints": ["每次查询都会留下新的可追踪痕迹。"],
            }
        ],
        "world_economy": [{"economy_rules": ["信息以时间和信誉交换。"]}],
        "world_locations": [{"locations": [{"name": "旧档案馆", "description": "保存城市旧记录。"}]}],
        "world_factions": [{"factions": [{"name": "记录署", "description": "维护公开记录。"}]}],
        "world_society": [
            {
                "world_systems": {"conflict_engines": ["记录公开与隐私之间的冲突。"]},
                "living_world": {"reaction_rules": ["公开记录变化会引发组织反应。"]},
                "faction_rules": ["组织按权限共享信息。"],
            }
        ],
        "story_engine_compat": [
            {
                "current_arc": "主角收到一条迟到的回复。",
                "progression_rules": ["行动结果必须改变下一步条件。"],
                "chapter_formula": ["入口、行动、结果、选择。"],
                "forbidden_breaks": ["不得绕过已建立的记录规则。"],
                "opening_arc": {"goal": "查明回复来源。"},
                "volume_plan": {"volume_title": "第一卷", "target_chapters": 50},
                "longform_framework": {"series_premise": "记录会反过来塑造城市。"},
                "progression_ledger": {"open_threads": ["回复来源"]},
            }
        ],
    }


def _power_sections() -> dict[str, dict[str, Any]]:
    paths = [
        {
            "name": "血脉路线",
            "role": "直接强化身体与感知。",
            "core_resource": "血脉余量",
            "core_attributes": ["体魄"],
            "strengths": ["近身稳定"],
            "weaknesses": ["资源恢复慢"],
            "skill_categories": ["体术"],
            "branches": ["强化", "变异"],
            "advancement": ["完成血脉试炼"],
        },
        {
            "name": "法则路线",
            "role": "通过理解规则改变行动边界。",
            "core_resource": "法则线索",
            "core_attributes": ["洞察"],
            "strengths": ["远程控制"],
            "weaknesses": ["准备时间长"],
            "skill_categories": ["术式"],
            "branches": ["观测", "重写"],
            "advancement": ["完成法则验证"],
        },
    ]
    return {
        "power_system_foundation": {"name": "潮汐灵契", "origin": ["海潮留下的古老契约"]},
        "power_system_attributes": {"attributes": [{"name": "共鸣", "effect": "决定能否稳定使用契约。"}]},
        "power_system_paths": {"paths": paths},
        "power_system_stages": {
            "stages": [
                {"name": "听潮", "level": None, "entry": "找到第一处潮痕。", "change": "能够听见契约回声。", "failure": "暂时失去感知。"},
                {"name": "引潮", "level": None, "entry": "完成一次稳定共鸣。", "change": "能够引导局部潮汐。", "failure": "契约反噬。"},
                {"name": "定界", "level": None, "entry": "理解一条边界规则。", "change": "能够限定力量范围。", "failure": "边界失控。"},
            ]
        },
        "power_system_resources": {
            "skills": ["潮痕感知"],
            "equipment": ["潮汐刻盘"],
            "resources": ["潮汐余量"],
            "advancement": ["通过连续验证推进阶段。"],
        },
        "power_system_constraints": {
            "costs": ["每次越界都会消耗共鸣稳定度。"],
            "counters": ["干扰会切断未经验证的共鸣。"],
            "boundaries": ["不能凭空创造没有来源的事实。"],
            "social_impact": ["掌握潮痕的人会被组织争夺。"],
            "visibility": ["只有接触潮痕的人能确认使用痕迹。"],
            "continuity_ledger": ["阶段", "余量", "反噬", "边界"],
        },
    }


def _traditional_path_payload(name: str, *, weapons: bool = True) -> dict[str, Any]:
    payload = {
        "name": name,
        "role": "承担一类职业职责。",
        "core_resource": "职业资源",
        "core_attributes": ["体魄"],
        "armor": ["轻甲"],
        "combat_loop": "观察、选择、执行、复盘。",
        "strengths": ["稳定"],
        "weaknesses": ["准备成本高"],
        "skill_categories": ["基础技艺"],
        "branches": ["强化", "变异"],
        "transfer_task": "完成转职任务。",
        "advancement": ["完成一次阶段验证。"],
        "advancement_tree": [
            {
                "level": level,
                "tier_name": f"阶段{level}",
                "options": [
                    {
                        "name": f"选项{level}",
                        "transfer_task": f"完成{level}级任务",
                        "ability_changes": [f"获得{level}级能力"],
                    }
                ],
            }
            for level in (10, 30, 60)
        ],
    }
    if weapons:
        payload["weapons"] = ["专属武器"]
    return payload


def _traditional_game_power_sections() -> dict[str, dict[str, Any]]:
    sections = deepcopy(_power_sections())
    sections["power_system_paths"] = {
        "paths": [
            _traditional_path_payload(name)
            for name in ("战士", "法师", "游侠", "盗贼", "牧师", "召唤师")
        ]
    }
    sections["power_system_stages"] = {
        "stages": [
            {
                "name": name,
                "level": level,
                "entry": entry,
                "change": change,
                "failure": failure,
            }
            for name, level, entry, change, failure in (
                ("见习者", 1, "创建角色。", "获得通用技能。", "角色重建。"),
                ("正式职业", 10, "完成Lv.10转职任务。", "获得职业资源。", "任务冷却。"),
                ("专精", 20, "完成Lv.20专精试炼。", "强化战斗方向。", "材料损失。"),
                ("进阶职业", 30, "完成Lv.30分支任务。", "获得分支技能。", "晋升延期。"),
                ("传承", 60, "完成Lv.60传承试炼。", "获得职业权柄。", "传承反噬。"),
            )
        ]
    }
    constraints = deepcopy(sections["power_system_constraints"])
    constraints["continuity_ledger"] = [
        "level",
        "skills",
        "equipment",
        "resources",
        "conditions",
    ]
    constraints["class_advancement_tiers"] = [
        {
            "level": level,
            "name": f"Lv.{level}晋升",
            "purpose": f"定义{level}级职业里程碑。",
            "common_requirements": [f"达到{level}级并完成公共试炼。"],
            "failure_rule": "冷却后可以重新挑战。",
        }
        for level in (10, 30, 60)
    ]
    sections["power_system_constraints"] = constraints
    return sections


def _structured_payloads() -> dict[str, list[Any]]:
    sections = _power_sections()
    payloads: dict[str, list[Any]] = {key: [value] for key, value in sections.items()}
    payloads.update(_generic_payloads())
    return payloads


def _game_ecology_payload(*, include_missing_fields: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "npc_system": {"roles": ["公告板管理员"]},
        "quest_network": {"edges": ["维修单→灯标"]},
        "server_runtime": {"heartbeat": "按停电周期刷新"},
        "map_ecology": {"zones": ["新手村", "雾区"]},
    }
    if include_missing_fields:
        payload.update(
            {
                "quest_rules": ["维修单完成后才开放下一条灯标"],
                "panel_rules": ["公告板按登记顺序显示任务"],
            }
        )
    return payload


def test_world_graph_order_and_non_power_graph_excludes_power_tasks(tmp_path: Path) -> None:
    structured = build_world_build_graph(
        NovelProject(
            project_id="file:x",
            title="玄幻",
            world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
        )
    )
    assert structured.definition.ordered_task_ids == (
        "world_input",
        "world_core_rules",
        "power_system_foundation",
        "power_system_attributes",
        "power_system_paths",
        "power_system_stages",
        "power_system_resources",
        "power_system_constraints",
        "power_system_final",
        "world_economy",
        "world_locations",
        "world_factions",
        "world_society",
        "story_engine_compat",
    )
    game = build_world_build_graph(
        NovelProject(
            project_id="file:x",
            title="游戏",
            world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
        )
    )
    assert "game_ecology" in game.definition.ordered_task_ids
    assert game.definition.ordered_task_ids[-1] == "story_engine_compat"
    for plugin_id in ("generic_webnovel", "urban", "suspense"):
        graph = build_world_build_graph(
            NovelProject(
                project_id="file:x",
                title="非力量体系",
                world_blueprint={"genre_plugin_ids": [plugin_id]},
            )
        )
        assert not any(task.startswith("power_system_") for task in graph.definition.ordered_task_ids)


def test_game_ecology_initial_prompt_declares_every_output_field() -> None:
    graph = build_world_build_graph(
        NovelProject(
            project_id="file:x",
            title="游戏契约",
            world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
        )
    )

    prompt = build_task_prompt(graph, "game_ecology", {})
    contract_line = next(line for line in prompt.splitlines() if line.startswith("输出契约："))
    contract = json.loads(contract_line.removeprefix("输出契约："))

    assert set(contract) == set(graph.spec("game_ecology").output_fields)
    assert contract == {
        "map_ecology": "object",
        "npc_system": "object",
        "panel_rules": "string[]",
        "quest_network": "object",
        "quest_rules": "string[]",
        "server_runtime": "object",
    }


def test_story_engine_compat_initial_prompt_declares_every_output_field() -> None:
    graph = build_world_build_graph(
        NovelProject(
            project_id="file:x",
            title="长篇契约",
            world_blueprint={"genre_plugin_ids": ["urban"]},
        )
    )

    prompt = build_task_prompt(graph, "story_engine_compat", {})
    contract_line = next(line for line in prompt.splitlines() if line.startswith("输出契约："))
    contract = json.loads(contract_line.removeprefix("输出契约："))

    assert set(contract) == set(graph.spec("story_engine_compat").output_fields)
    assert contract == {
        "chapter_formula": "string[]",
        "current_arc": "string",
        "forbidden_breaks": "string[]",
        "longform_framework": "object",
        "opening_arc": "object",
        "progression_ledger": "object",
        "progression_rules": "string[]",
        "volume_plan": "object",
    }


@pytest.mark.parametrize("plugin_id", ["xuanhuan", "game_webnovel", "urban"])
def test_model_world_tasks_have_complete_output_contract(plugin_id: str) -> None:
    graph = build_world_build_graph(
        NovelProject(
            project_id="file:x",
            title="输出合同完整性",
            world_blueprint={"genre_plugin_ids": [plugin_id]},
        )
    )

    for spec in graph.specs.values():
        if spec.kind != "model":
            continue
        assert set(spec.output_fields) == set((spec.output_schema or {}).keys()), spec.task_id


def test_traditional_game_path_contract_declares_structured_path_fields() -> None:
    graph = build_world_build_graph(
        NovelProject(
            project_id="file:x",
            title="传统职业",
            world_blueprint={
                "genre_plugin_ids": ["game_webnovel"],
                "power_progression_mode": "traditional_class",
            },
        )
    )
    schema = graph.spec("power_system_paths").output_schema or {}
    assert "advancement_tree" in str(schema["paths"])
    assert "weapons" in str(schema["paths"])
    assert "combat_loop" in str(schema["paths"])


def test_nontraditional_game_path_contract_does_not_force_class_fields() -> None:
    graph = build_world_build_graph(
        NovelProject(
            project_id="file:x",
            title="自定义玩法",
            world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
        )
    )
    assert graph.spec("power_system_paths").output_schema == {"paths": "object[]"}
    assert "class_advancement_tiers" not in (graph.spec("power_system_constraints").output_schema or {})


def test_world_input_locks_power_progression_mode_before_power_tasks() -> None:
    game = NovelProject(
        project_id="file:x",
        title="自定义成长",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )
    assert canonical_world_input(game)["power_progression_mode"] == "custom"
    assert canonical_world_input(
        game,
        previous={"power_progression_mode": "custom"},
    )["power_progression_mode"] == "custom"
    game.world_blueprint["power_system_spec"] = {
        "class_advancement_tiers": [{"level": 10}],
    }
    assert canonical_world_input(
        game,
        previous={"novel_type_id": "game_webnovel", "power_progression_mode": "custom"},
    )["power_progression_mode"] == "custom"

    sections = _traditional_game_power_sections()
    valid_spec: dict[str, Any] = {}
    for section in sections.values():
        valid_spec.update(deepcopy(section))
    imported = game.model_copy(deep=True)
    imported.world_blueprint["power_system_spec"] = valid_spec
    assert canonical_world_input(imported)["power_progression_mode"] == "traditional_class"
    assert canonical_world_input(
        imported,
        previous={"novel_type_id": "urban", "power_progression_mode": "custom"},
    )["power_progression_mode"] == "traditional_class"


def test_explicit_power_progression_mode_controls_first_power_contracts() -> None:
    project = NovelProject(
        project_id="file:x",
        title="传统职业合同",
        world_blueprint={
            "genre_plugin_ids": ["game_webnovel"],
            "power_progression_mode": "traditional_class",
        },
    )
    graph = build_world_build_graph(project)
    assert canonical_world_input(project)["power_progression_mode"] == "traditional_class"
    schema = graph.spec("power_system_paths").output_schema or {}
    for field in PATH_FIELDS:
        assert field in str(schema["paths"])
    assert "class_advancement_tiers" in graph.spec("power_system_constraints").output_fields
    assert "class_advancement_tiers" in (graph.spec("power_system_constraints").output_schema or {})
    prompt = build_task_prompt(graph, "power_system_paths", {})
    assert all(field in prompt for field in PATH_FIELDS)
    constraints_prompt = build_task_prompt(graph, "power_system_constraints", {})
    assert "class_advancement_tiers" in constraints_prompt


def test_custom_game_section_validators_reject_late_mode_upgrade() -> None:
    project = NovelProject(
        project_id="file:x",
        title="自定义游戏",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )
    validators = make_world_validators(project, progression_mode="custom")
    path_result = validators["power.paths"](
        {
            "paths": [
                {"name": "路线一", "branches": ["甲", "乙"], "transfer_task": "转职"},
                {"name": "路线二", "branches": ["丙", "丁"], "advancement_tree": [{"level": 10}]},
            ]
        }
    )
    assert [(item.code, item.path) for item in path_result if item.code == "power.paths.mode_switch_field"] == [
        ("power.paths.mode_switch_field", "paths[0]"),
        ("power.paths.mode_switch_field", "paths[1]"),
    ]
    constraint_result = validators["power.constraints"](
        {
            **_power_sections()["power_system_constraints"],
            "class_advancement_tiers": [{"level": 10}],
        }
    )
    assert "power.constraints.mode_switch_field" in {item.code for item in constraint_result}

    custom_spec: dict[str, Any] = {}
    for section in _power_sections().values():
        custom_spec.update(deepcopy(section))
    custom_spec["paths"][0]["transfer_task"] = "模型擅自增加的转职任务。"
    custom_spec["class_advancement_tiers"] = [{"level": 10}]
    assert validate_power_system_spec(
        custom_spec,
        novel_type_id="game_webnovel",
        progression_mode="custom",
    )["paths"][0]["transfer_task"] == "模型擅自增加的转职任务。"
    with pytest.raises(PowerSystemValidationError):
        validate_power_system_spec(
            custom_spec,
            novel_type_id="game_webnovel",
            progression_mode="traditional_class",
        )


def test_late_constraints_mode_switch_is_repaired_without_upgrading_contract(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="game_webnovel")
    payloads = _structured_payloads()
    payloads["game_ecology"] = [_game_ecology_payload()]
    payloads["power_system_constraints"] = [
        {
            **_power_sections()["power_system_constraints"],
            "class_advancement_tiers": [
                {"level": level, "name": f"Lv.{level}", "purpose": "里程碑", "common_requirements": ["完成验证"], "failure_rule": "等待后重试。"}
                for level in (10, 30, 60)
            ],
        },
        deepcopy(_power_sections()["power_system_constraints"]),
    ]
    gateway = ScriptedGateway(payloads)
    project = NovelProject.model_validate(store.project())
    result = WorldBuildGraphRunner(project, store=store, model_gateway=gateway).run()

    assert store.build_artifact("world_input")["payload"]["power_progression_mode"] == "custom"
    assert store.build_artifact("power_system_paths") is not None
    assert store.build_artifact("power_system_constraints")["source"] == "ai_repair"
    assert "class_advancement_tiers" not in store.build_artifact("power_system_constraints")["payload"]
    assert store.build_artifact("power_system_final")["source"] == "deterministic"
    assert result.world_blueprint["power_system_spec"].get("class_advancement_tiers", []) == []
    assert len([call for call in gateway.calls if call.operation == "world_build_power_system_paths"]) == 1
    assert len([call for call in gateway.calls if call.operation == "world_build_power_system_constraints"]) == 2


@pytest.mark.parametrize(
    ("mode", "sections"),
    [
        ("custom", _power_sections),
        ("traditional_class", _traditional_game_power_sections),
    ],
)
def test_valid_imported_game_spec_locks_mode_and_skips_power_calls(
    tmp_path: Path,
    mode: str,
    sections: Any,
) -> None:
    store = _store(tmp_path, plugin_id="game_webnovel")
    raw_spec: dict[str, Any] = {}
    for section in sections().values():
        raw_spec.update(deepcopy(section))
    valid_spec = validate_power_system_spec(raw_spec, novel_type_id="game_webnovel")
    project = NovelProject.model_validate(store.project())
    project.world_blueprint["power_system_spec"] = valid_spec
    project.world_blueprint["power_system"] = ["作者原有摘要"]
    store.update_project({"world_blueprint": project.world_blueprint}, replace_world_blueprint=True)
    gateway = ScriptedGateway({**_structured_payloads(), **_generic_payloads(), "game_ecology": [_game_ecology_payload()]})

    result = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=gateway,
    ).run()

    assert store.build_artifact("world_input")["payload"]["power_progression_mode"] == mode
    assert not any(call.operation.startswith("world_build_power_system_") for call in gateway.calls), [call.operation for call in gateway.calls]
    assert store.build_artifact("power_system_paths")["source"] == "imported"
    assert store.build_artifact("power_system_constraints")["source"] == "imported"
    assert store.build_artifact("power_system_final")["source"] == "deterministic"
    assert result.world_blueprint["power_system"] == ["作者原有摘要"]
    assert result.world_blueprint["power_progression_mode"] == mode


@pytest.mark.parametrize(
    ("mode", "traditional"),
    [("custom", False), ("traditional_class", True)],
)
def test_legacy_completed_graph_mode_upgrade_is_metadata_only_and_zero_call(
    tmp_path: Path,
    mode: str,
    traditional: bool,
) -> None:
    store = _store(tmp_path, plugin_id="game_webnovel")
    project = NovelProject.model_validate(store.project())
    if traditional:
        project.world_blueprint["power_progression_mode"] = "traditional_class"
        raw_spec: dict[str, Any] = {}
        for section in _traditional_game_power_sections().values():
            raw_spec.update(deepcopy(section))
        project.world_blueprint["power_system_spec"] = validate_power_system_spec(
            raw_spec,
            novel_type_id="game_webnovel",
            progression_mode="traditional_class",
        )
        project.world_blueprint["power_system"] = ["作者原有摘要"]
        store.update_project({"world_blueprint": project.world_blueprint}, replace_world_blueprint=True)

    initial_gateway = ScriptedGateway(
        {
            **_structured_payloads(),
            **_generic_payloads(),
            "game_ecology": [_game_ecology_payload()],
        }
    )
    initial_runner = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=initial_gateway,
    )
    materialized = initial_runner.run()
    store.commit_build_graph_materialization(
        materialized,
        initial_runner.graph,
        initial_runner.service,
    )

    # Recreate the pre-mode-contract state without changing graph revisions.
    project_data = store.project()
    project_data["world_blueprint"].pop("power_progression_mode", None)
    store.update_project({"world_blueprint": project_data["world_blueprint"]}, replace_world_blueprint=True)
    artifact = store.build_artifact("world_input")
    assert artifact is not None
    artifact["payload"].pop("power_progression_mode", None)
    artifact_path = store.build_graph_store().artifact_path("world_input", artifact["revision"])
    store.snapshot_store.replace_json_transaction({artifact_path: artifact})

    revisions_before = {
        task_id: state["current_artifact_revision"]
        for task_id, state in store.build_graph_state()["tasks"].items()
    }
    empty_gateway = ScriptedGateway({})
    resumed_runner = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=empty_gateway,
    )
    resumed = resumed_runner.run()

    assert resumed.world_blueprint["power_progression_mode"] == mode
    assert empty_gateway.calls == []
    assert store.build_artifact("world_input")["revision"] == artifact["revision"]
    assert {
        task_id: state["current_artifact_revision"]
        for task_id, state in store.build_graph_state()["tasks"].items()
    } == revisions_before

    store.commit_build_graph_materialization(
        resumed,
        resumed_runner.graph,
        resumed_runner.service,
    )
    assert store.project()["world_blueprint"]["power_progression_mode"] == mode
    final_revisions = {
        task_id: state["current_artifact_revision"]
        for task_id, state in store.build_graph_state()["tasks"].items()
    }
    final_gateway = ScriptedGateway({})
    final_runner = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=final_gateway,
    )
    final_result = final_runner.run()
    assert final_result.world_blueprint["power_progression_mode"] == mode
    assert final_gateway.calls == []
    assert {
        task_id: state["current_artifact_revision"]
        for task_id, state in store.build_graph_state()["tasks"].items()
    } == final_revisions


def test_non_game_contract_stays_custom_even_with_class_like_existing_data() -> None:
    project = NovelProject(
        project_id="file:x",
        title="玄幻项目",
        world_blueprint={
            "genre_plugin_ids": ["xuanhuan"],
            "power_system_spec": {"class_advancement_tiers": [{"level": 10}]},
        },
    )
    assert canonical_world_input(project)["power_progression_mode"] == "custom"


def test_traditional_path_shape_is_rejected_at_section_boundary() -> None:
    project = NovelProject(
        project_id="file:x",
        title="传统路径边界",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )
    result = make_world_validators(project, progression_mode="traditional_class")["power.paths"](
        {
            "paths": [
                {
                    "name": "职业一",
                    "branches": ["a", "b"],
                    "transfer_task": "完成转职",
                    "advancement_tree": [{"level": 10}],
                }
            ]
        }
    )
    codes = {item.code for item in result}
    assert "power.paths.missing_weapons" in codes
    assert "power.paths.missing_combat_loop" in codes
    assert "power.paths.missing_advancement" in codes


def test_non_game_transfer_task_does_not_enable_traditional_game_contract() -> None:
    project = NovelProject(
        project_id="file:x",
        title="玄幻路线",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    paths = [
        {"name": "剑修", "branches": ["御剑", "剑阵"], "transfer_task": "完成剑心试炼。"},
        {"name": "符修", "branches": ["阵符", "战符"]},
    ]

    assert make_world_validators(project)["power.paths"]({"paths": paths}) is True

    sections = _power_sections()
    spec: dict[str, Any] = {}
    for payload in sections.values():
        spec.update(deepcopy(payload))
    spec["paths"] = paths
    validated = validate_power_system_spec(spec, novel_type_id="xuanhuan")
    assert validated["paths"][0]["transfer_task"] == "完成剑心试炼。"

    scope = power_path_repair_scope(
        {"paths": paths[:1]},
        (BuildDiagnostic("power.final.paths.minimum_count", "paths", "count"),),
        project,
        raw_spec={"paths": paths[:1], "class_advancement_tiers": [{"level": 10}]},
    )
    assert scope.append_count == 1
    assert scope.append_required_fields == ("name", "branches")


def test_wrapped_model_payload_keeps_unowned_fields_for_hard_rejection() -> None:
    payload, diagnostics = parse_task_payload(
        json.dumps(
            {
                "world_blueprint": {
                    "locations": [{"name": "旧档案馆", "description": "保存记录。"}],
                    "factions": [{"name": "越权势力", "description": "不属于地点任务。"}],
                }
            },
            ensure_ascii=False,
        ),
        ("locations",),
    )
    assert not diagnostics
    assert payload is not None and "factions" in payload
    validator = make_world_validators(
        NovelProject(
            project_id="file:x",
            title="ownership",
            world_blueprint={"genre_plugin_ids": ["urban"]},
        )
    )["world.locations"]
    result = validator(payload)
    assert any(item.code == "world.locations.unowned_field" for item in result)


def test_power_attributes_and_stages_have_one_focused_repair_and_final_passes(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    payloads = _structured_payloads()
    payloads["power_system_attributes"] = [{}, _power_sections()["power_system_attributes"]]
    payloads["power_system_stages"] = [
        {"stages": [{"entry": "找到潮痕。", "failure": "失去感知。"}]},
        _power_sections()["power_system_stages"],
    ]
    gateway = ScriptedGateway(payloads)
    project = NovelProject.model_validate(store.project())

    result = WorldBuildGraphRunner(project, store=store, model_gateway=gateway).run()

    state = store.build_graph_state()
    assert state is not None
    assert state["tasks"]["power_system_attributes"]["status"] == "completed"
    assert state["tasks"]["power_system_stages"]["status"] == "completed"
    assert store.build_artifact("power_system_attributes")["source"] == "ai_repair"
    assert store.build_artifact("power_system_stages")["source"] == "ai_repair"
    assert store.build_artifact("power_system_final")["source"] == "deterministic"
    assert result.world_blueprint["power_system_spec"]["name"] == "潮汐灵契"
    assert len([call for call in gateway.calls if call.operation == "world_build_power_system_attributes"]) == 2
    assert len([call for call in gateway.calls if call.operation == "world_build_power_system_stages"]) == 2
    attribute_spec = next(call for call in gateway.calls if call.operation == "world_build_power_system_attributes")
    stages_spec = next(call for call in gateway.calls if call.operation == "world_build_power_system_stages")
    assert '"attributes"' in attribute_spec.prompt
    assert '"stages"' in stages_spec.prompt
    attribute_repairs = [call for call in gateway.calls if call.operation == "world_build_power_system_attributes"]
    stage_repairs = [call for call in gateway.calls if call.operation == "world_build_power_system_stages"]
    assert "power.attributes.missing" in attribute_repairs[1].prompt
    assert "stages.missing_name" in stage_repairs[1].prompt
    assert "stages.missing_change" in stage_repairs[1].prompt


def test_repair_fields_map_nested_diagnostics_to_owned_top_level_fields() -> None:
    graph = build_world_build_graph(
        NovelProject(
            project_id="file:x",
            title="字段映射",
            world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
        )
    )

    fields = repair_fields_for_diagnostics(
        graph.spec("power_system_stages"),
        (BuildDiagnostic("stages.invalid_level", "stages[0].level", "level is invalid"),),
    )

    assert fields == ("stages",)


def test_repair_fields_fall_back_for_unscoped_diagnostics() -> None:
    graph = build_world_build_graph(
        NovelProject(
            project_id="file:x",
            title="无法定位",
            world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
        )
    )

    fields = repair_fields_for_diagnostics(
        graph.spec("game_ecology"),
        (BuildDiagnostic("task.invalid_json", "payload", "response is not an object"),),
    )

    assert fields is None


def test_game_ecology_repair_is_field_scoped_and_merges_full_candidate(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="game_webnovel")
    payloads = _structured_payloads()
    payloads["game_ecology"] = [
        _game_ecology_payload(include_missing_fields=False),
        {"quest_rules": ["维修单完成后才开放下一条灯标"], "panel_rules": ["公告板按登记顺序显示任务"]},
    ]
    gateway = ScriptedGateway(payloads)
    project = NovelProject.model_validate(store.project())

    result = WorldBuildGraphRunner(project, store=store, model_gateway=gateway).run()

    ecology_calls = [call for call in gateway.calls if call.operation == "world_build_game_ecology"]
    assert len(ecology_calls) == 2
    repair_prompt = ecology_calls[1].prompt
    assert "REPAIR FIELDS: quest_rules, panel_rules" in repair_prompt
    assert '输出契约：{"panel_rules":"string[]","quest_rules":"string[]"}' in repair_prompt
    assert "不要返回 npc_system" in repair_prompt

    artifact = store.build_artifact("game_ecology")
    assert artifact is not None
    assert artifact["source"] == "ai_repair"
    assert set(artifact["payload"]) == {
        "quest_rules",
        "panel_rules",
        "npc_system",
        "quest_network",
        "server_runtime",
        "map_ecology",
    }
    assert len(store.build_artifact_history("game_ecology")) == 1
    assert result.world_blueprint["quest_rules"]


def test_out_of_scope_field_in_repair_is_rejected_without_artifact(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="game_webnovel")
    payloads = _structured_payloads()
    payloads["game_ecology"] = [
        _game_ecology_payload(include_missing_fields=False),
        {
            "quest_rules": ["维修单完成后才开放下一条灯标"],
            "npc_system": {"roles": ["越界修改"]},
        },
    ]
    gateway = ScriptedGateway(payloads)
    project = NovelProject.model_validate(store.project())

    with pytest.raises(WorldBuildGraphFailure) as caught:
        WorldBuildGraphRunner(project, store=store, model_gateway=gateway).run()

    assert caught.value.task_id == "game_ecology"
    assert len([call for call in gateway.calls if call.operation == "world_build_game_ecology"]) == 2
    assert store.build_artifact("game_ecology") is None
    state = store.build_graph_state()
    assert state is not None
    diagnostics = state["tasks"]["game_ecology"]["diagnostics"]
    assert diagnostics[0]["code"] == "task.repair_out_of_scope"


def test_field_scoped_repair_still_allows_exactly_one_attempt(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="game_webnovel")
    payloads = _structured_payloads()
    payloads["game_ecology"] = [
        _game_ecology_payload(include_missing_fields=False),
        {"quest_rules": ["维修单完成后才开放下一条灯标"]},
    ]
    gateway = ScriptedGateway(payloads)
    project = NovelProject.model_validate(store.project())

    with pytest.raises(WorldBuildGraphFailure):
        WorldBuildGraphRunner(project, store=store, model_gateway=gateway).run()

    assert len([call for call in gateway.calls if call.operation == "world_build_game_ecology"]) == 2
    assert store.build_artifact("game_ecology") is None
    state = store.build_graph_state()
    assert state is not None
    assert state["tasks"]["game_ecology"]["status"] == "validation_failed"


def test_failed_focused_repair_keeps_task_failed_without_official_artifact(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    payloads = _structured_payloads()
    payloads["power_system_attributes"] = [{}, {}]
    gateway = ScriptedGateway(payloads)
    project = NovelProject.model_validate(store.project())

    with pytest.raises(WorldBuildGraphFailure) as caught:
        WorldBuildGraphRunner(project, store=store, model_gateway=gateway).run()

    assert caught.value.task_id == "power_system_attributes"
    state = store.build_graph_state()
    assert state is not None
    assert state["tasks"]["power_system_attributes"]["status"] == "validation_failed"
    assert store.build_artifact("power_system_attributes") is None
    assert store.build_artifact("power_system_foundation") is not None
    assert store.build_graph_service  # service surface remains available for retry
    assert store.build_graph_materialization() is None
    assert any(item["code"] == "task.repair_incomplete" for item in state["tasks"]["power_system_attributes"]["diagnostics"])


def test_resume_reuses_completed_artifacts_after_model_failure(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="urban")
    payloads = _generic_payloads()
    payloads["world_locations"] = [RuntimeError("timeout")]
    gateway = ScriptedGateway(payloads)
    project = NovelProject.model_validate(store.project())

    with pytest.raises(WorldBuildGraphFailure):
        WorldBuildGraphRunner(project, store=store, model_gateway=gateway).run()
    completed_before = {
        task_id: store.build_artifact(task_id)["revision"]
        for task_id in ("world_core_rules", "world_economy")
    }
    first_call_count = len(gateway.calls)
    gateway.payloads["world_locations"] = [_generic_payloads()["world_locations"][0]]
    result = WorldBuildGraphRunner(project, store=store, model_gateway=gateway).run()

    assert result.world_blueprint["locations"]
    assert len(gateway.calls) == first_call_count + 4  # locations, factions, society, compat
    assert gateway.calls[first_call_count].operation == "world_build_world_locations"
    assert store.build_artifact("world_core_rules")["revision"] == completed_before["world_core_rules"]
    assert store.build_artifact("world_economy")["revision"] == completed_before["world_economy"]


def test_author_premise_edit_advances_world_input_revision(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="urban")
    first_gateway = ScriptedGateway(_generic_payloads())
    first = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=first_gateway,
    ).run()
    store.update_project(
        {
            "world_blueprint": first.world_blueprint,
            "world_summary": first.world_summary,
            "current_focus": first.current_focus,
            "pipeline_stage": "environment_ready",
        },
        replace_world_blueprint=True,
    )
    graph = build_world_build_graph(NovelProject.model_validate(store.project()))
    service = store.build_graph_service(graph.definition)
    store.record_build_graph_materialization(graph, service, NovelProject.model_validate(store.project()))
    root_before = store.build_artifact("world_input")["revision"]

    edited_blueprint = dict(store.project()["world_blueprint"])
    edited_blueprint["premise"] = "作者刚刚修改的根设定。"
    store.update_project({"world_blueprint": edited_blueprint}, replace_world_blueprint=True)

    second_gateway = ScriptedGateway(_generic_payloads())
    WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=second_gateway,
    ).run()

    root_after = store.build_artifact("world_input")
    assert root_after["revision"] == root_before + 1
    assert root_after["payload"]["source_premise"] == "作者刚刚修改的根设定。"
    assert any(call.operation == "world_build_world_core_rules" for call in second_gateway.calls)


def test_completed_graph_can_materialize_after_previous_materialization_crash(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="urban")
    gateway = ScriptedGateway(_generic_payloads())
    project = NovelProject.model_validate(store.project())
    first = WorldBuildGraphRunner(project, store=store, model_gateway=gateway).run()
    first_call_count = len(gateway.calls)

    # Simulate a process crash after graph commits but before project.json and
    # the materialization marker are written.
    second = WorldBuildGraphRunner(
        project,
        store=store,
        model_gateway=ScriptedGateway({}),
    ).run()

    assert second.world_blueprint["locations"] == first.world_blueprint["locations"]
    assert len(gateway.calls) == first_call_count


def test_author_edit_cancels_active_model_run_and_preserves_edit(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="urban")
    payloads = _generic_payloads()
    gateway = ScriptedGateway(payloads)
    project = NovelProject.model_validate(store.project())
    edited = False

    def cancel_after_response() -> bool:
        nonlocal edited
        state = store.build_graph_state() or {}
        active = state.get("tasks", {})
        if edited or not any(item.get("active_run_id") for item in active.values() if isinstance(item, dict)):
            return False
        edited = True
        store.update_project(
            {"world_blueprint": {"genre_plugin_ids": ["urban"], "author_note": "作者刚刚编辑"}},
            replace_world_blueprint=True,
        )
        return True

    with pytest.raises(Exception) as caught:
        WorldBuildGraphRunner(
            project,
            store=store,
            model_gateway=gateway,
            cancel_check=cancel_after_response,
        ).run()

    assert caught.value.__class__.__name__ == "WorldBuildGraphCancelled"
    state = store.build_graph_state()
    assert state is not None
    runs = state["runs"]
    assert any(run["status"] == "conflict" for run in runs.values())
    assert store.project()["world_blueprint"]["author_note"] == "作者刚刚编辑"
    assert store.project().get("pipeline_stage", "imported") != "environment_ready"


def test_file_project_world_job_uses_persistent_graph_and_materializes_legacy_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.routes import file_projects

    store = _store(tmp_path, plugin_id="urban")
    gateway = ScriptedGateway(_generic_payloads())
    real_enrich = file_projects.enrich_project_world
    observed: dict[str, Any] = {}

    def graph_enrich(project: NovelProject, **kwargs: Any) -> NovelProject:
        observed["store"] = kwargs.get("store")
        return real_enrich(project, model_gateway=gateway, **kwargs)

    job_id = "wbg-graph-production"
    job = {
        "schema_version": "world-build-job/v1",
        "job_id": job_id,
        "project_id": "file:urban",
        "status": "queued",
        "progress": "等待构建核心规则",
        "active_module_id": "core_rules",
        "active_module_title": "核心规则",
        "active_module_status": "queued",
        "error": "",
        "created_at": "",
        "updated_at": "",
        "project_revision": file_projects._project_world_revision(store),
        "_project_root": str(store.root),
    }
    monkeypatch.setattr(file_projects, "_store_for", lambda _project_id: store)
    monkeypatch.setattr(file_projects, "enrich_project_world", graph_enrich)
    monkeypatch.setattr(file_projects, "_persist_world_build_job", lambda _job: None)
    with file_projects._world_build_jobs_lock:
        file_projects._world_build_jobs[job_id] = job
    try:
        file_projects._run_world_build_job(job_id, "file:urban")
        assert job["status"] == "completed"
    finally:
        with file_projects._world_build_jobs_lock:
            file_projects._world_build_jobs.pop(job_id, None)
            file_projects._active_world_build_jobs.pop("urban", None)

    assert observed["store"] is store
    assert store.build_artifact("world_core_rules") is not None
    marker = store.build_graph_materialization()
    assert marker is not None
    assert marker["schema_version"] == "build-graph-materialization/v1"
    saved = store.project()
    assert saved["pipeline_stage"] == "environment_ready"
    legacy = saved["world_blueprint"]["world_build_artifacts"]
    assert any(item["module_id"] == "world_core_rules" for item in legacy)


def test_existing_valid_power_spec_is_decomposed_without_power_model_calls(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    raw_spec: dict[str, Any] = {}
    for section in _power_sections().values():
        raw_spec.update(deepcopy(section))
    valid_spec = validate_power_system_spec(raw_spec, novel_type_id="xuanhuan")
    existing_project = NovelProject.model_validate(store.project()).model_copy(
        update={
            "world_blueprint": {
                "genre_plugin_ids": ["xuanhuan"],
                "premise": "作者已经写好的世界入口。",
                "power_system_spec": valid_spec,
                "power_system": ["作者保留的旧摘要"],
            }
        }
    )
    store.update_project(
        {"world_blueprint": existing_project.world_blueprint},
        replace_world_blueprint=True,
    )
    gateway = ScriptedGateway(_structured_payloads())

    result = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=gateway,
    ).run()

    assert not any(call.operation.startswith("world_build_power_system_") for call in gateway.calls)
    assert store.build_artifact("power_system_foundation")["source"] == "imported"
    assert store.build_artifact("power_system_attributes")["source"] == "imported"
    assert store.build_artifact("power_system_final")["source"] == "deterministic"
    assert result.world_blueprint["power_system_spec"] == _power_spec_for_genre(valid_spec, "xuanhuan")
    assert result.world_blueprint["power_system"] == ["作者保留的旧摘要"]
    assert result.world_blueprint["premise"] == "作者已经写好的世界入口。"


def test_materialization_marker_reconciles_author_edit_into_human_revision(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="urban")
    first_gateway = ScriptedGateway(_generic_payloads())
    first_project = NovelProject.model_validate(store.project())
    first = WorldBuildGraphRunner(
        first_project,
        store=store,
        model_gateway=first_gateway,
    ).run()
    store.update_project(
        {
            "world_summary": first.world_summary,
            "current_focus": first.current_focus,
            "world_blueprint": first.world_blueprint,
            "pipeline_stage": "environment_ready",
        },
        replace_world_blueprint=True,
    )
    graph = build_world_build_graph(NovelProject.model_validate(store.project()))
    service = store.build_graph_service(graph.definition)
    store.record_build_graph_materialization(graph, service, NovelProject.model_validate(store.project()))

    edited_blueprint = dict(store.project()["world_blueprint"])
    edited_blueprint["locations"] = [{"name": "作者新地点", "description": "作者手写的位置。"}]
    store.update_project({"world_blueprint": edited_blueprint}, replace_world_blueprint=True)
    second_gateway = ScriptedGateway(_generic_payloads())
    second = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=second_gateway,
    ).run()

    assert second.world_blueprint["locations"] == edited_blueprint["locations"]
    assert store.build_artifact("world_locations")["source"] == "human"
    assert [call.operation for call in second_gateway.calls] == [
        "world_build_world_factions",
        "world_build_world_society",
        "world_build_story_engine_compat",
    ]


def _commit_materialized_project(store: FileProjectStore, project: NovelProject) -> None:
    graph = build_world_build_graph(project)
    service = store.build_graph_service(
        graph.definition,
        validators=make_world_validators(project),
    )
    store.commit_build_graph_materialization(project, graph, service)


@pytest.mark.parametrize(
    ("old_plugin", "new_plugin", "old_payloads"),
    (
        ("urban", "xuanhuan", _generic_payloads()),
        ("xuanhuan", "urban", _structured_payloads()),
        ("game_webnovel", "urban", {**_structured_payloads(), "game_ecology": [{
            "quest_rules": ["任务由已确认的社会规则触发。"],
            "panel_rules": ["面板只显示作者明确要求的状态。"],
            "npc_system": {"roles": ["引导者"]},
            "quest_network": {"nodes": ["起点"]},
            "server_runtime": {"availability": "稳定"},
            "map_ecology": {"regions": ["旧城"]},
        }]}),
    ),
)
def test_world_genre_shape_migration_archives_old_graph_before_reset(
    tmp_path: Path,
    old_plugin: str,
    new_plugin: str,
    old_payloads: dict[str, list[Any]],
) -> None:
    store = _store(tmp_path, plugin_id=old_plugin)
    old_project = NovelProject.model_validate(store.project())
    WorldBuildGraphRunner(
        old_project,
        store=store,
        model_gateway=ScriptedGateway(old_payloads),
    ).run()
    old_tasks = set((store.build_graph_state() or {}).get("tasks", {}))
    assert old_tasks

    blueprint = dict(store.project().get("world_blueprint") or {})
    blueprint["genre_plugin_ids"] = [new_plugin]
    store.update_project({"world_blueprint": blueprint}, replace_world_blueprint=True)
    new_project = NovelProject.model_validate(store.project())
    WorldBuildGraphRunner(
        new_project,
        store=store,
        model_gateway=ScriptedGateway(_structured_payloads() if new_plugin == "xuanhuan" else _generic_payloads()),
    ).run()

    new_tasks = set((store.build_graph_state() or {}).get("tasks", {}))
    assert new_tasks != old_tasks
    if new_plugin != "xuanhuan":
        assert store.build_artifact("power_system_final") is None
    if new_plugin != "game_webnovel":
        assert store.build_artifact("game_ecology") is None
    archives = list((store.webnovel_dir / "build_graph_archives").glob("*/build_graph.json"))
    assert archives, "genre shape migration must preserve the old manifest"
    assert any(
        path.parent.joinpath("build_artifacts").exists()
        or path.parent.joinpath("build_runs").exists()
        for path in archives
    )


def test_canonical_valid_nontraditional_path_is_imported_without_power_calls(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    raw_spec: dict[str, Any] = {}
    for section in _power_sections().values():
        raw_spec.update(deepcopy(section))
    raw_spec["paths"] = [
        {"name": "观测路线", "branches": ["静观", "校验"]},
        {"name": "改写路线", "branches": ["拆解", "重组"]},
    ]
    valid_spec = validate_power_system_spec(raw_spec, novel_type_id="xuanhuan")
    project = NovelProject.model_validate(store.project()).model_copy(
        update={
            "world_blueprint": {
                "genre_plugin_ids": ["xuanhuan"],
                "power_system_spec": valid_spec,
            }
        }
    )
    store.update_project({"world_blueprint": project.world_blueprint}, replace_world_blueprint=True)
    gateway = ScriptedGateway(_structured_payloads())

    WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=gateway,
    ).run()

    assert not any(call.operation.startswith("world_build_power_system_") for call in gateway.calls)
    assert store.build_artifact("power_system_paths")["source"] == "imported"


def test_full_power_spec_edit_decomposes_to_human_sections_and_deterministic_final(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    first_gateway = ScriptedGateway(_structured_payloads())
    first = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=first_gateway,
    ).run()
    _commit_materialized_project(store, first)

    edited_blueprint = deepcopy(store.project()["world_blueprint"])
    edited_spec = deepcopy(edited_blueprint["power_system_spec"])
    edited_spec["attributes"][0]["effect"] = "作者确认共鸣会留下可追踪的回声。"
    edited_spec["stages"][0]["change"] = "作者确认第一阶段只能读取一条契约回声。"
    edited_blueprint["power_system_spec"] = edited_spec
    store.update_project({"world_blueprint": edited_blueprint}, replace_world_blueprint=True)

    second_gateway = ScriptedGateway(_structured_payloads())
    result = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=second_gateway,
    ).run()

    assert not any(call.operation.startswith("world_build_power_system_") for call in second_gateway.calls)
    assert store.build_artifact("power_system_attributes")["source"] == "human"
    assert store.build_artifact("power_system_stages")["source"] == "human"
    assert store.build_artifact("power_system_final")["source"] == "deterministic"
    assert result.world_blueprint["power_system_spec"]["attributes"][0]["effect"].startswith("作者确认")


def test_invalid_full_power_spec_edit_blocks_environment_without_ai_rewrite(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    first = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=ScriptedGateway(_structured_payloads()),
    ).run()
    _commit_materialized_project(store, first)
    edited_blueprint = deepcopy(store.project()["world_blueprint"])
    edited_blueprint["power_system_spec"]["attributes"] = []
    store.update_project({"world_blueprint": edited_blueprint}, replace_world_blueprint=True)

    gateway = ScriptedGateway({})
    with pytest.raises(WorldBuildGraphFailure) as caught:
        WorldBuildGraphRunner(
            NovelProject.model_validate(store.project()),
            store=store,
            model_gateway=gateway,
        ).run()

    assert caught.value.task_id == "project_reconciliation"
    assert not gateway.calls
    assert store.project()["pipeline_stage"] == "imported"
    assert store.build_artifact("power_system_attributes")["source"] != "human"


def test_model_input_contract_uses_declared_reads_not_all_ancestors(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    project = NovelProject.model_validate(store.project())
    WorldBuildGraphRunner(
        project,
        store=store,
        model_gateway=ScriptedGateway(_structured_payloads()),
    ).run()
    graph = build_world_build_graph(project)
    service = store.build_graph_service(graph.definition, validators=make_world_validators(project))
    from packages.story_core.world_build.tasks import build_input_contract

    locations = build_input_contract(project, graph, service, "world_locations")
    location_paths = {item["path"] for item in locations["reads"]}
    assert location_paths == {"build.world_input", "world_blueprint.economy_rules"}
    assert not any(task_id in str(locations["reads"]) for task_id in ("world_core_rules", "power_system", "world_factions"))

    stages = build_input_contract(project, graph, service, "power_system_stages")
    stage_paths = {item["path"] for item in stages["reads"]}
    assert stage_paths == {"build.world_input", "build.power_system.attributes", "build.power_system.paths"}
    assert not any(
        item["task_id"] in {"power_system_resources", "power_system_constraints", "world_core_rules"}
        for item in stages["reads"]
    )


def test_power_final_residual_routes_to_owner_once_and_persists_cap(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    project = NovelProject.model_validate(store.project())
    WorldBuildGraphRunner(
        project,
        store=store,
        model_gateway=ScriptedGateway(_structured_payloads()),
    ).run()
    runner = WorldBuildGraphRunner(project, store=store, model_gateway=ScriptedGateway({}))
    diagnostic = BuildDiagnostic(
        "power.final.paths.duplicate_names",
        "paths",
        "path names must be distinct",
    )
    assert power_final_owner_task(diagnostic) == "power_system_paths"
    assert runner._route_power_final_diagnostics((diagnostic,))
    assert runner.service.inspect_task("power_system_paths").status == "validation_failed"
    assert not runner._route_power_final_diagnostics((diagnostic,))
    budget = store.snapshot_store.read_json(store.webnovel_dir / "world_build_power_final_repair.json", {})
    assert budget["attempted_owners"] == ["power_system_paths"]


def test_materialization_project_and_marker_share_atomic_transaction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path, plugin_id="urban")
    project = NovelProject.model_validate(store.project())
    result = WorldBuildGraphRunner(
        project,
        store=store,
        model_gateway=ScriptedGateway(_generic_payloads()),
    ).run()
    graph = build_world_build_graph(result)
    service = store.build_graph_service(graph.definition, validators=make_world_validators(result))
    old_project = deepcopy(store.project())
    real_transaction = store.snapshot_store.replace_json_transaction

    def fail_if_marker(payloads: dict[Path, Any]) -> None:
        if any(path.name == "build_graph_materialization.json" for path in payloads):
            raise RuntimeError("simulated materialization crash")
        real_transaction(payloads)

    monkeypatch.setattr(store.snapshot_store, "replace_json_transaction", fail_if_marker)
    with pytest.raises(RuntimeError, match="simulated materialization crash"):
        store.commit_build_graph_materialization(result, graph, service)
    assert store.project() == old_project
    assert store.build_graph_materialization() is None

    monkeypatch.setattr(store.snapshot_store, "replace_json_transaction", real_transaction)
    store.commit_build_graph_materialization(result, graph, service)
    assert store.project()["pipeline_stage"] == "environment_ready"
    assert store.build_graph_materialization() is not None


def _prepare_power_final_residual(
    tmp_path: Path,
) -> tuple[FileProjectStore, dict[str, Any], dict[str, Any]]:
    store = _store(tmp_path, plugin_id="xuanhuan")
    WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=ScriptedGateway(_structured_payloads()),
    ).run()
    graph = build_world_build_graph(NovelProject.model_validate(store.project()))
    service = store.build_graph_service(graph.definition, validators=make_world_validators(NovelProject.model_validate(store.project())))
    current = store.build_artifact("power_system_constraints")
    assert current is not None
    residual = deepcopy(current["payload"])
    residual["continuity_ledger"] = ["阶段"]
    result = service.edit_artifact(
        "power_system_constraints",
        residual,
        expected_revision=current["revision"],
        requested_writes=graph.spec("power_system_constraints").task.owns,
    )
    assert result.artifact is not None
    return store, residual, deepcopy(_power_sections()["power_system_constraints"])


def test_power_final_residual_diagnostic_is_a_focused_repair_end_to_end(tmp_path: Path) -> None:
    store, _invalid_constraints, valid_constraints = _prepare_power_final_residual(tmp_path)
    payloads = _generic_payloads()
    payloads["power_system_constraints"] = [
        {"continuity_ledger": valid_constraints["continuity_ledger"]}
    ]
    gateway = ScriptedGateway(payloads)

    WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=gateway,
    ).run()

    calls = [call for call in gateway.calls if call.operation == "world_build_power_system_constraints"]
    assert len(calls) == 1
    assert "power.final.continuity_ledger.minimum_count" in calls[0].prompt
    assert "当前候选" in calls[0].prompt
    assert '输出契约：{"continuity_ledger":"string[]"}' in calls[0].prompt
    assert store.build_artifact("power_system_constraints")["source"] == "ai_repair"
    assert store.build_artifact("power_system_final")["source"] == "deterministic"


def test_power_final_constraint_repair_preserves_unaffected_fields(tmp_path: Path) -> None:
    store, invalid_constraints, valid_constraints = _prepare_power_final_residual(tmp_path)
    payloads = _generic_payloads()
    payloads["power_system_constraints"] = [
        {"continuity_ledger": valid_constraints["continuity_ledger"]}
    ]
    gateway = ScriptedGateway(payloads)

    WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=gateway,
    ).run()

    repaired = store.build_artifact("power_system_constraints")
    assert repaired is not None
    assert repaired["payload"]["continuity_ledger"] == valid_constraints["continuity_ledger"]
    assert repaired["payload"]["costs"] == invalid_constraints["costs"]
    assert repaired["payload"]["boundaries"] == invalid_constraints["boundaries"]


def test_power_path_repair_scope_targets_only_diagnostic_items_and_fields() -> None:
    project = NovelProject(
        project_id="file:path-repair",
        title="路径修复",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    payload = {
        "paths": [
            {"name": "同名", "branches": ["单分支"], "role": "保留"},
            {"name": "同名", "branches": ["观测", "重写"], "role": "不应变化"},
        ]
    }
    scope = power_path_repair_scope(
        payload,
        (
            BuildDiagnostic("power.final.paths.duplicate_names", "paths", "duplicate"),
            BuildDiagnostic("power.final.paths.distinct_branches", "paths", "branches"),
        ),
        project,
    )

    assert scope.update_fields == {0: ("branches",), 1: ("name",)}
    merged, diagnostics = merge_power_path_repair(
        payload,
        {
            "updates": [
                {"index": 0, "fields": {"branches": ["强化", "变异"]}},
                {"index": 1, "fields": {"name": "新名"}},
            ],
            "append": [],
        },
        scope,
    )

    assert not diagnostics
    assert merged is not None
    assert merged["paths"][0]["role"] == "保留"
    assert merged["paths"][1]["role"] == "不应变化"
    assert merged["paths"][0]["branches"] == ["强化", "变异"]
    assert merged["paths"][1]["name"] == "新名"


def test_path_section_validator_and_repair_scope_share_canonical_text_semantics() -> None:
    project = NovelProject(
        project_id="file:canonical-path-semantics",
        title="路径规范化",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    paths = [
        {"name": "路线\t甲\n", "branches": [" 生存\t路线\n", "生存 路线"]},
        {"name": " 路线\t甲 ", "branches": ["观测", "重写"]},
    ]

    section_result = make_world_validators(project)["power.paths"]({"paths": paths})
    section_codes = set() if section_result is True else {item.code for item in section_result}
    assert "paths.distinct_branches" in section_codes
    assert "paths.duplicate_names" in section_codes

    scope = power_path_repair_scope(
        {"paths": paths},
        (
            BuildDiagnostic("power.final.paths.distinct_branches", "paths", "branches"),
            BuildDiagnostic("power.final.paths.duplicate_names", "paths", "duplicate"),
        ),
        project,
    )
    assert scope.update_fields == {0: ("branches",), 1: ("name",)}

    spec: dict[str, Any] = {}
    for payload in _power_sections().values():
        spec.update(deepcopy(payload))
    spec["paths"] = paths
    with pytest.raises(PowerSystemValidationError) as caught:
        validate_power_system_spec(spec, novel_type_id="xuanhuan")
    assert {"paths.distinct_branches", "paths.duplicate_names"}.issubset(caught.value.violations)


def test_path_repair_scope_preserves_raw_indices_when_normalization_drops_items() -> None:
    project = NovelProject(
        project_id="file:canonical-path-indices",
        title="原始路径索引",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    paths = [
        {"name": "有效路线", "branches": ["观测", "重写"]},
        "invalid item",
        {"name": "待修路线", "branches": ["生存\t路线", "生存 路线"]},
    ]

    scope = power_path_repair_scope(
        {"paths": paths},
        (BuildDiagnostic("power.final.paths.distinct_branches", "paths", "branches"),),
        project,
    )

    assert scope.update_fields == {2: ("branches",)}


def test_ordinary_path_repair_uses_canonical_branch_diagnostic_and_exact_scope(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    payloads = _structured_payloads()
    first_candidate = deepcopy(_power_sections()["power_system_paths"])
    first_candidate["paths"][0]["branches"] = [" 生存\t路线\n", "生存 路线"]
    payloads["power_system_paths"] = [
        first_candidate,
        {
            "updates": [
                {"index": 0, "fields": {"branches": ["生存支线", "维修支线"]}}
            ],
            "append": [],
        },
    ]
    gateway = ScriptedGateway(payloads)

    WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=gateway,
    ).run()

    calls = [call for call in gateway.calls if call.operation == "world_build_power_system_paths"]
    assert len(calls) == 2
    assert "paths.distinct_branches" in calls[1].prompt
    assert '"index":0' in calls[1].prompt
    assert '"fields":["branches"]' in calls[1].prompt
    artifact = store.build_artifact("power_system_paths")
    assert artifact is not None and artifact["source"] == "ai_repair"
    assert artifact["payload"]["paths"][0]["branches"] == ["生存支线", "维修支线"]
    assert store.build_artifact("power_system_final") is not None


def test_empty_final_path_repair_scope_fails_without_model_call_and_consumes_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=ScriptedGateway(_structured_payloads()),
    ).run()
    before = store.build_artifact("power_system_paths")
    assert before is not None

    gateway = ScriptedGateway({})
    runner = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=gateway,
    )
    assert runner._route_power_final_diagnostics(
        (BuildDiagnostic("power.final.paths.distinct_branches", "paths", "branches"),)
    )
    empty_scope = PowerPathRepairScope({}, 0, tuple(PATH_FIELDS))
    monkeypatch.setattr(world_build_runner, "power_path_repair_scope", lambda *args, **kwargs: empty_scope)

    with pytest.raises(WorldBuildGraphFailure) as caught:
        runner.run()

    assert caught.value.task_id == "power_system_paths"
    assert [item.code for item in caught.value.diagnostics] == ["task.repair_scope_unresolved"]
    assert gateway.calls == []
    assert store.build_artifact("power_system_paths")["revision"] == before["revision"]
    state = store.build_graph_state()
    assert state["tasks"]["power_system_paths"]["status"] == "validation_failed"
    budget = json.loads((store.webnovel_dir / "world_build_power_final_repair.json").read_text(encoding="utf-8"))
    assert budget["failed_owners"] == ["power_system_paths"]


def test_empty_ordinary_path_repair_scope_fails_without_second_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    payloads = _structured_payloads()
    payloads["power_system_paths"] = [
        {"paths": [{"name": "", "branches": ["单分支"]}, {"name": "路线二", "branches": ["观测", "重写"]}]},
        {"updates": [{"index": 0, "fields": {"name": "修复路线", "branches": ["甲", "乙"]}}], "append": []},
    ]
    gateway = ScriptedGateway(payloads)
    empty_scope = PowerPathRepairScope({}, 0, tuple(PATH_FIELDS))
    monkeypatch.setattr(world_build_runner, "power_path_repair_scope", lambda *args, **kwargs: empty_scope)

    with pytest.raises(WorldBuildGraphFailure) as caught:
        WorldBuildGraphRunner(
            NovelProject.model_validate(store.project()),
            store=store,
            model_gateway=gateway,
        ).run()

    path_calls = [call for call in gateway.calls if call.operation == "world_build_power_system_paths"]
    assert len(path_calls) == 1
    assert caught.value.task_id == "power_system_paths"
    assert [item.code for item in caught.value.diagnostics] == ["task.repair_scope_unresolved"]
    assert store.build_artifact("power_system_paths") is None


def test_power_path_repair_scope_supports_advancement_tree_and_exact_append() -> None:
    project = NovelProject(
        project_id="file:path-repair",
        title="路径树",
        world_blueprint={
            "genre_plugin_ids": ["game_webnovel"],
            "power_progression_mode": "traditional_class",
        },
    )
    payload = {"paths": [{"name": "职业一", "branches": ["a", "b"], "advancement_tree": []}]}
    tree_scope = power_path_repair_scope(
        payload,
        (BuildDiagnostic("power.final.game.path_invalid_advancement_tree", "paths", "tree"),),
        project,
    )
    assert tree_scope.update_fields == {0: ("advancement_tree",)}

    append_scope = power_path_repair_scope(
        payload,
        (BuildDiagnostic("power.final.paths.minimum_count", "paths", "count"),),
        project,
    )
    assert append_scope.append_count == 5
    assert append_scope.append_required_fields == tuple(PATH_FIELDS)
    merged, diagnostics = merge_power_path_repair(
        payload,
        {"updates": [], "append": [_traditional_path_payload(f"职业{i}") for i in range(5)]},
        append_scope,
    )
    assert not diagnostics
    assert merged is not None and len(merged["paths"]) == 6


def _valid_advancement_tree() -> list[dict[str, Any]]:
    return [
        {
            "level": level,
            "tier_name": f"阶段{level}",
            "options": [
                {
                    "name": f"选项{level}",
                    "transfer_task": f"完成{level}级任务",
                    "ability_changes": [f"获得{level}级能力"],
                }
            ],
        }
        for level in (10, 30, 60)
    ]


@pytest.mark.parametrize(
    "diagnostic_code",
    (
        "power.final.game.path_invalid_advancement_tree",
        "power.final.game.path_incomplete_advancement_node",
        "power.final.game.path_incomplete_advancement_option",
    ),
)
def test_power_path_repair_scope_targets_only_invalid_advancement_tree_index(
    diagnostic_code: str,
) -> None:
    valid_tree = _valid_advancement_tree()
    invalid_tree = deepcopy(valid_tree)
    if diagnostic_code.endswith("invalid_advancement_tree"):
        invalid_tree.pop()
    elif diagnostic_code.endswith("incomplete_advancement_node"):
        invalid_tree[0]["tier_name"] = ""
    else:
        invalid_tree[0]["options"][0]["name"] = ""
    paths = [
        {"name": "职业一", "branches": ["a", "b"], "advancement_tree": valid_tree},
        {"name": "职业二", "branches": ["a", "b"], "advancement_tree": invalid_tree},
        {"name": "职业三", "branches": ["a", "b"], "advancement_tree": valid_tree},
    ]
    project = NovelProject(
        project_id="file:path-tree",
        title="精确树索引",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )
    scope = power_path_repair_scope(
        {"paths": paths},
        (BuildDiagnostic(diagnostic_code, "paths", "tree diagnostic"),),
        project,
        raw_spec={"paths": paths, "class_advancement_tiers": [{"level": 10}]},
    )

    assert scope.update_fields == {1: ("advancement_tree",)}
    out_of_scope, diagnostics = merge_power_path_repair(
        {"paths": paths},
        {"updates": [{"index": 0, "fields": {"advancement_tree": []}}], "append": []},
        scope,
    )
    assert out_of_scope is None
    assert [item.code for item in diagnostics] == ["task.repair_out_of_scope"]


def test_power_path_repair_uses_raw_committed_sections_for_traditional_mode() -> None:
    paths = [{"name": "自定义路线", "branches": ["a", "b"]}]
    project = NovelProject(
        project_id="file:path-raw-spec",
        title="未物化传统模式",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"], "power_progression_mode": "traditional_class"},
    )

    class FakeService:
        def inspect_artifact(self, task_id: str) -> Any:
            payloads = {
                "power_system_foundation": {"name": "体系", "origin": ["来源"]},
                "power_system_attributes": {"attributes": [{"name": "属性", "effect": "效果"}]},
                "power_system_paths": {"paths": paths},
                "power_system_stages": {"stages": []},
                "power_system_resources": {"skills": [], "equipment": [], "resources": [], "advancement": []},
                "power_system_constraints": {"class_advancement_tiers": [{"level": 10}]},
            }
            value = payloads.get(task_id)
            return type("Artifact", (), {"payload": value})() if value is not None else None

    raw_spec = raw_power_spec_from_artifacts(FakeService())
    scope = power_path_repair_scope(
        {"paths": paths},
        (BuildDiagnostic("power.final.paths.minimum_count", "paths", "count"),),
        project,
        raw_spec=raw_spec,
        progression_mode="traditional_class",
    )

    assert scope.append_count == 5
    assert scope.append_fields == tuple(PATH_FIELDS)


def test_power_path_repair_requires_every_update_target_and_field() -> None:
    scope = PowerPathRepairScope(
        update_fields={0: ("branches",), 2: ("name", "role")},
        append_count=1,
        append_fields=tuple(PATH_FIELDS),
    )
    base = {"paths": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}
    cases = (
        {"updates": [{"index": 0, "fields": {"branches": ["a", "b"]}}], "append": [{"name": "d"}]},
        {"updates": [{"index": 0, "fields": {"branches": ["a", "b"]}}, {"index": 2, "fields": {"name": "c"}}], "append": [{"name": "d"}]},
        {"updates": [], "append": [{"name": "d"}]},
    )
    for patch in cases:
        merged, diagnostics = merge_power_path_repair(base, patch, scope)
        assert merged is None
        assert [item.code for item in diagnostics] == ["task.repair_incomplete"]


def test_power_path_repair_rejects_out_of_scope_updates() -> None:
    project = NovelProject(
        project_id="file:path-repair",
        title="越界修复",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    payload = {"paths": [{"name": "路线", "branches": ["a"]}]}
    scope = power_path_repair_scope(
        payload,
        (BuildDiagnostic("power.final.paths.distinct_branches", "paths", "branches"),),
        project,
    )
    merged, diagnostics = merge_power_path_repair(
        payload,
        {"updates": [{"index": 0, "fields": {"name": "越界"}}], "append": []},
        scope,
    )
    assert merged is None
    assert [item.code for item in diagnostics] == ["task.repair_out_of_scope"]


def test_power_final_path_residual_uses_structured_patch_and_reruns_final(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    first_runner = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=ScriptedGateway(_structured_payloads()),
    )
    first_runner.run()

    current = store.build_artifact("power_system_paths")
    assert current is not None
    paths = current["payload"]["paths"]
    patch = {
        "updates": [
            {"index": index, "fields": {"weapons": [f"路线{index}媒介"]}}
            for index in range(len(paths))
        ],
        "append": [],
    }
    resumed_payloads = _structured_payloads()
    resumed_payloads["power_system_paths"] = [patch]
    second_gateway = ScriptedGateway(resumed_payloads)
    second_runner = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=second_gateway,
    )
    second_runner.service.invalidate_task(
        "power_system_paths",
        (
            BuildDiagnostic(
                "power.final.game.path_missing_weapon_affinity",
                "game.path_missing_weapon_affinity",
                "path weapons are required",
            ),
        ),
    )

    second_runner.run()

    calls = [call for call in second_gateway.calls if call.operation == "world_build_power_system_paths"]
    assert len(calls) == 1
    assert "power-path-repair/v1" in calls[0].prompt
    assert '输出契约：{"append":"object[]","updates":"{index:int,fields:object}[]"}' in calls[0].prompt
    repaired = store.build_artifact("power_system_paths")
    assert repaired is not None
    assert repaired["source"] == "ai_repair"
    assert all(path["weapons"] for path in repaired["payload"]["paths"])
    assert store.build_artifact("power_system_final")["source"] == "deterministic"


def test_power_final_path_repair_out_of_scope_stops_without_third_call(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=ScriptedGateway(_structured_payloads()),
    ).run()
    before = store.build_artifact("power_system_paths")
    assert before is not None
    gateway = ScriptedGateway(
        {
            "power_system_paths": [
                {"updates": [{"index": 0, "fields": {"name": "越界"}}], "append": []}
            ]
        }
    )
    runner = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=gateway,
    )
    runner.service.invalidate_task(
        "power_system_paths",
        (
            BuildDiagnostic(
                "power.final.game.path_missing_weapon_affinity",
                "game.path_missing_weapon_affinity",
                "path weapons are required",
            ),
        ),
    )

    with pytest.raises(WorldBuildGraphFailure) as caught:
        runner.run()

    assert caught.value.task_id == "power_system_paths"
    assert len([call for call in gateway.calls if call.operation == "world_build_power_system_paths"]) == 1
    after = store.build_artifact("power_system_paths")
    assert after is not None
    assert after["revision"] == before["revision"]
    state = store.build_graph_state()
    assert state is not None
    assert state["tasks"]["power_system_paths"]["status"] == "validation_failed"


def test_ordinary_traditional_path_repair_uses_structured_scoped_patch(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="game_webnovel")
    game_project = NovelProject.model_validate(store.project())
    game_project.world_blueprint["power_progression_mode"] = "traditional_class"
    game_sections = _traditional_game_power_sections()
    payloads = {task_id: [payload] for task_id, payload in game_sections.items()}
    payloads.update(_generic_payloads())
    payloads["game_ecology"] = [_game_ecology_payload()]
    first_paths = {
        "paths": [
            _traditional_path_payload("战士"),
            _traditional_path_payload("法师", weapons=False),
        ]
    }
    repair_patch = {
        "updates": [{"index": 1, "fields": {"weapons": ["专属武器"]}}],
        "append": [
            _traditional_path_payload(name)
            for name in ("游侠", "盗贼", "牧师", "召唤师")
        ],
    }
    payloads["power_system_paths"] = [first_paths, repair_patch]
    gateway = ScriptedGateway(payloads)

    result = WorldBuildGraphRunner(
        game_project,
        store=store,
        model_gateway=gateway,
    ).run()

    calls = [call for call in gateway.calls if call.operation == "world_build_power_system_paths"]
    assert len(calls) == 2
    assert "power-path-repair/v1" in calls[1].prompt
    assert '"updates":"{index:int,fields:object}[]"' in calls[1].prompt
    assert '"index":1' in calls[1].prompt
    assert '"fields":["weapons"]' in calls[1].prompt
    assert '"append_count":4' in calls[1].prompt
    assert "输出契约：{\"paths\":\"object[]\"}" not in calls[1].prompt
    artifact = store.build_artifact("power_system_paths")
    assert artifact is not None and artifact["source"] == "ai_repair"
    assert artifact["payload"]["paths"][0] == first_paths["paths"][0]
    assert artifact["payload"]["paths"][1]["weapons"] == ["专属武器"]
    assert len(artifact["payload"]["paths"]) == 6
    assert result.world_blueprint["power_system_spec"]["paths"][0]["name"] == "战士"


def test_power_path_repair_requires_traditional_append_fields_but_not_nontraditional_extras() -> None:
    traditional_scope = PowerPathRepairScope(
        update_fields={},
        append_count=2,
        append_fields=tuple(PATH_FIELDS),
        append_required_fields=tuple(PATH_FIELDS),
    )
    merged, diagnostics = merge_power_path_repair(
        {"paths": []},
        {"updates": [], "append": [{"name": "职业一", "branches": ["a", "b"]}] * 2},
        traditional_scope,
    )
    assert merged is None
    assert [item.code for item in diagnostics] == ["task.repair_incomplete"]

    project = NovelProject(
        project_id="file:nontraditional-append",
        title="自定义路线",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    scope = power_path_repair_scope(
        {"paths": [{"name": "已有", "branches": ["a", "b"]}]},
        (BuildDiagnostic("power.final.paths.minimum_count", "paths", "count"),),
        project,
    )
    merged, diagnostics = merge_power_path_repair(
        {"paths": [{"name": "已有", "branches": ["a", "b"]}]},
        {"updates": [], "append": [{"name": "新增", "branches": ["a", "b"]}]},
        scope,
    )
    assert not diagnostics
    assert merged is not None and merged["paths"][-1]["name"] == "新增"


def test_ordinary_path_repair_replaces_only_invalid_non_object_item(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    payloads = _structured_payloads()
    retained = deepcopy(_power_sections()["power_system_paths"]["paths"][0])
    payloads["power_system_paths"] = [
        {"paths": [retained, "bad"]},
        {
            "updates": [
                {
                    "index": 1,
                    "fields": {"name": "法则路线", "branches": ["观测", "重写"]},
                }
            ],
            "append": [],
        },
    ]
    gateway = ScriptedGateway(payloads)

    WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=gateway,
    ).run()

    calls = [call for call in gateway.calls if call.operation == "world_build_power_system_paths"]
    assert len(calls) == 2
    assert "power-path-repair/v1" in calls[1].prompt
    assert '"replace_indices":[1]' in calls[1].prompt
    artifact = store.build_artifact("power_system_paths")
    assert artifact is not None and artifact["source"] == "ai_repair"
    assert artifact["payload"]["paths"][0] == retained
    assert artifact["payload"]["paths"][1] == {
        "name": "法则路线",
        "branches": ["观测", "重写"],
    }


def test_invalid_path_item_replacement_is_limited_to_exact_diagnostic_index() -> None:
    project = NovelProject(
        project_id="file:path-replacement",
        title="路径替换边界",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    payload = {"paths": [{"name": "保留", "branches": ["甲", "乙"]}, "bad"]}
    scope = power_path_repair_scope(
        payload,
        (BuildDiagnostic("power.paths.invalid_item", "paths[1]", "invalid"),),
        project,
    )

    assert scope.replace_indices == (1,)
    assert scope.update_fields == {1: ("branches", "name")}
    merged, diagnostics = merge_power_path_repair(
        payload,
        {
            "updates": [
                {"index": 0, "fields": {"name": "越界", "branches": ["丙", "丁"]}}
            ],
            "append": [],
        },
        scope,
    )
    assert merged is None
    assert [item.code for item in diagnostics] == ["task.repair_out_of_scope"]


def test_power_final_residual_repair_failure_is_capped_end_to_end(tmp_path: Path) -> None:
    store, _invalid_constraints, _valid_constraints = _prepare_power_final_residual(tmp_path)
    payloads = _generic_payloads()
    payloads["power_system_constraints"] = [{}]
    gateway = ScriptedGateway(payloads)

    with pytest.raises(WorldBuildGraphFailure) as caught:
        WorldBuildGraphRunner(
            NovelProject.model_validate(store.project()),
            store=store,
            model_gateway=gateway,
        ).run()

    assert caught.value.task_id == "power_system_constraints"
    calls = [call for call in gateway.calls if call.operation == "world_build_power_system_constraints"]
    assert len(calls) == 1
    state = store.build_graph_state()
    assert state is not None
    assert state["tasks"]["power_system_constraints"]["status"] == "validation_failed"
    assert state["tasks"]["power_system_final"]["status"] == "stale"
    assert any(
        item["code"] == "task.repair_incomplete"
        for item in state["tasks"]["power_system_constraints"]["diagnostics"]
    )


def test_failed_power_final_repair_budget_blocks_same_generation_next_job(tmp_path: Path) -> None:
    store, _invalid_constraints, _valid_constraints = _prepare_power_final_residual(tmp_path)
    first_gateway = ScriptedGateway({**_generic_payloads(), "power_system_constraints": [{}]})

    with pytest.raises(WorldBuildGraphFailure):
        WorldBuildGraphRunner(
            NovelProject.model_validate(store.project()),
            store=store,
            model_gateway=first_gateway,
        ).run()

    first_calls = [
        call for call in first_gateway.calls if call.operation == "world_build_power_system_constraints"
    ]
    assert len(first_calls) == 1
    budget = store.snapshot_store.read_json(
        store.webnovel_dir / "world_build_power_final_repair.json",
        {},
    )
    assert budget["failed_owners"] == ["power_system_constraints"]

    second_gateway = ScriptedGateway(_generic_payloads())
    with pytest.raises(WorldBuildGraphFailure) as caught:
        WorldBuildGraphRunner(
            NovelProject.model_validate(store.project()),
            store=store,
            model_gateway=second_gateway,
        ).run()

    assert caught.value.task_id == "power_system_constraints"
    assert [item.code for item in caught.value.diagnostics] == [
        "power.final_repair_budget_exhausted"
    ]
    assert not second_gateway.calls
    state = store.build_graph_state()
    assert state is not None
    assert state["tasks"]["power_system_constraints"]["status"] == "validation_failed"


def test_power_placeholder_is_rejected_at_section_boundary_without_official_invalid_artifact(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    payloads = _structured_payloads()
    invalid = deepcopy(_power_sections()["power_system_constraints"])
    invalid["costs"] = ["TBD"]
    payloads["power_system_constraints"] = [
        invalid,
        {"costs": _power_sections()["power_system_constraints"]["costs"]},
    ]
    gateway = ScriptedGateway(payloads)

    WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=gateway,
    ).run()

    calls = [call for call in gateway.calls if call.operation == "world_build_power_system_constraints"]
    assert len(calls) == 2
    assert "power.constraints.costs.missing" in calls[1].prompt
    history = store.build_artifact_history("power_system_constraints")
    assert len(history) == 1
    assert history[0]["source"] == "ai_repair"


def test_power_final_diagnostic_routing_covers_section_or_explicit_global_boundary() -> None:
    routed = {
        "missing_name": "power_system_foundation",
        "missing_attributes": "power_system_attributes",
        "missing_equipment": "power_system_resources",
        "missing_costs": "power_system_constraints",
        "stages.missing_change": "power_system_stages",
        "paths.duplicate_names": "power_system_paths",
        "continuity_ledger.minimum_count": "power_system_constraints",
        "game.path_missing_weapon_affinity": "power_system_paths",
    }
    for code, task_id in routed.items():
        assert power_final_owner_task(BuildDiagnostic(f"power.final.{code}", code, code)) == task_id

    # Placeholder content is intentionally boundary-owned by section
    # validators because the canonical final validator cannot infer which
    # section supplied a nested placeholder.
    assert power_final_owner_task(
        BuildDiagnostic(
            "power.final.content.placeholder_or_low_information",
            "power_system_spec",
            "placeholder",
        )
    ) is None


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("author_constraints", ["新的作者约束"]),
        ("seed_outline", "新的种子大纲"),
    ),
)
def test_world_revision_includes_authoritative_root_inputs(
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    store = _store(tmp_path, plugin_id="urban")
    before = store.world_revision()
    store.update_project({field: value})
    assert store.world_revision() != before


def test_world_revision_includes_story_core_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path, plugin_id="urban")
    before = store.world_revision()
    monkeypatch.setattr(
        store,
        "story_core_context",
        lambda _stage: {"title": "story-core-v2", "world": "新的核心设定"},
    )
    assert store.world_revision() != before


def test_world_revision_is_stable_when_graph_internal_state_migrates(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="urban")
    first = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=ScriptedGateway(_generic_payloads()),
    ).run()
    _commit_materialized_project(store, first)

    blueprint = dict(store.project().get("world_blueprint") or {})
    blueprint["genre_plugin_ids"] = ["xuanhuan"]
    store.update_project({"world_blueprint": blueprint}, replace_world_blueprint=True)
    before = store.world_revision()

    WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=ScriptedGateway(_structured_payloads()),
    ).run()

    assert store.world_revision() == before


def test_materialization_rejects_root_input_edit_after_graph_run(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="urban")
    project = NovelProject.model_validate(store.project())
    result = WorldBuildGraphRunner(
        project,
        store=store,
        model_gateway=ScriptedGateway(_generic_payloads()),
    ).run()
    graph = build_world_build_graph(project)
    service = store.build_graph_service(graph.definition, validators=make_world_validators(project))
    expected = store.world_revision()
    store.update_project({"author_constraints": ["作者在运行中修改"]})

    with pytest.raises(ValueError, match="world_build_conflict"):
        store.commit_build_graph_materialization(
            result,
            graph,
            service,
            expected_project_revision=expected,
        )
    assert store.project()["author_constraints"] == ["作者在运行中修改"]
    assert store.project().get("pipeline_stage", "imported") != "environment_ready"


def test_genre_migration_resets_power_repair_budget_identity(tmp_path: Path) -> None:
    store = _store(tmp_path, plugin_id="xuanhuan")
    old_project = NovelProject.model_validate(store.project())
    old_runner = WorldBuildGraphRunner(
        old_project,
        store=store,
        model_gateway=ScriptedGateway(_structured_payloads()),
    )
    old_runner.run()
    budget_path = store.webnovel_dir / "world_build_power_final_repair.json"
    store.snapshot_store.replace_json_transaction(
        {
            budget_path: {
                "schema_version": "world-build-power-repair/v1",
                "definition_fingerprint": old_runner.graph.definition.definition_fingerprint,
                "world_input_revision": 1,
                "attempted_owners": ["power_system_paths"],
            }
        }
    )

    blueprint = dict(store.project().get("world_blueprint") or {})
    blueprint["genre_plugin_ids"] = ["urban"]
    store.update_project({"world_blueprint": blueprint}, replace_world_blueprint=True)
    WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=ScriptedGateway(_generic_payloads()),
    ).run()

    blueprint = dict(store.project().get("world_blueprint") or {})
    blueprint["genre_plugin_ids"] = ["xuanhuan"]
    store.update_project({"world_blueprint": blueprint}, replace_world_blueprint=True)
    new_runner = WorldBuildGraphRunner(
        NovelProject.model_validate(store.project()),
        store=store,
        model_gateway=ScriptedGateway({}),
    )
    budget = store.snapshot_store.read_json(budget_path, {})
    assert budget["definition_fingerprint"] == new_runner.graph.definition.definition_fingerprint
    assert budget["attempted_owners"] == []
    assert new_runner._route_power_final_diagnostics(
        (BuildDiagnostic("power.final.paths.duplicate_names", "paths", "duplicate"),)
    )
