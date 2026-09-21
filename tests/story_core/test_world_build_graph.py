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
from packages.story_core.world_build.tasks import parse_task_payload
from packages.story_core.world_build.validators import make_world_validators
from packages.story_core.world_build.validators import power_final_owner_task
from packages.story_core.build_graph.contracts import BuildDiagnostic
from packages.story_core.power_system_spec import validate_power_system_spec


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


def _structured_payloads() -> dict[str, list[Any]]:
    sections = _power_sections()
    payloads: dict[str, list[Any]] = {key: [value] for key, value in sections.items()}
    payloads.update(_generic_payloads())
    return payloads


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
    assert any(item["code"] == "power.attributes.missing" for item in state["tasks"]["power_system_attributes"]["diagnostics"])


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
