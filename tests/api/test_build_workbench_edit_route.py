from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from threading import Event

import pytest

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects
from packages.story_core.build_graph.contracts import BuildDiagnostic
from packages.story_core.build_graph.definition import BuildGraphDefinition, BuildTaskDefinition
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.world_build.definition import WorldBuildTaskSpec
from packages.story_core.world_build import definition as world_definition
from packages.story_core.world_build import validators as world_validators


def _synthetic_graph():
    specs = (
        WorldBuildTaskSpec(
            BuildTaskDefinition(task_id="world_model", title="世界规则", owns=("world.rules",), validator_id="valid_label"),
            "model", ("label",),
        ),
        WorldBuildTaskSpec(
            BuildTaskDefinition(task_id="downstream_model", title="下游设定", dependencies=("world_model",), owns=("world.detail",)),
            "model", ("world_detail",),
        ),
        WorldBuildTaskSpec(
            BuildTaskDefinition(task_id="transitive_model", title="传递下游", dependencies=("downstream_model",), owns=("world.transitive",)),
            "model", ("world_transitive",),
        ),
        WorldBuildTaskSpec(
            BuildTaskDefinition(task_id="world_input", title="导入输入", owns=("world.input",)),
            "imported", ("world_input",),
        ),
        WorldBuildTaskSpec(
            BuildTaskDefinition(task_id="power_system_final", title="最终力量体系", owns=("world.power",)),
            "deterministic", ("power_system_final",),
        ),
    )
    definition = BuildGraphDefinition(graph_id="novelflow-project-build", tasks=tuple(spec.task for spec in specs))
    return SimpleNamespace(
        definition=definition,
        specs={spec.task.task_id: spec for spec in specs},
        spec=lambda task_id: {spec.task.task_id: spec for spec in specs}[task_id],
        structured_power=False,
        plugin_id=None,
        power_progression_mode=None,
    )


def _setup_project(tmp_path: Path, monkeypatch, *, stage="environment_ready"):
    root = tmp_path / "synthetic-project"
    (root / ".story-system").mkdir(parents=True)
    (root / ".webnovel").mkdir()
    (root / "chapters").mkdir()
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps({"schema_version": "story-system-master-setting/v1", "project": {
            "project_id": "p-synthetic-build-edit", "title": "Synthetic", "pipeline_stage": stage,
        }}), encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(json.dumps({
        "project_id": "p-synthetic-build-edit", "title": "Synthetic", "pipeline_stage": stage,
    }), encoding="utf-8")
    (root / ".webnovel" / "state.json").write_text(json.dumps({"story_id": "s-synthetic", "current_chapter": 0}), encoding="utf-8")
    store = FileProjectStore(root)
    graph = _synthetic_graph()
    validators = {
        "valid_label": lambda payload: () if isinstance(payload.get("label"), str) and payload["label"].strip()
        else BuildDiagnostic("missing_label", "world.rules.label", "label is required"),
    }
    service = store.build_graph_service(graph.definition, validators=validators)
    service.commit_candidate("world_model", {"label": "Initial"}, requested_writes=("world.rules",))
    service.commit_candidate("downstream_model", {"detail": "Initial"}, requested_writes=("world.detail",))
    service.commit_candidate("transitive_model", {"detail": "Initial"}, requested_writes=("world.transitive",))
    service.commit_candidate("world_input", {"input": "Imported"}, source="imported", requested_writes=("world.input",))
    service.commit_candidate("power_system_final", {"power": "Final"}, source="deterministic", requested_writes=("world.power",))
    marker = {
        "schema_version": "build-graph-materialization/v1",
        "graph_id": graph.definition.graph_id,
        "artifact_revisions": {task_id: 1 for task_id in graph.definition.tasks_by_id},
    }
    marker_path = root / ".webnovel" / "build_graph_materialization.json"
    marker_bytes = json.dumps(marker, ensure_ascii=False, indent=2).encode("utf-8")
    marker_path.write_bytes(marker_bytes)
    monkeypatch.setattr(file_projects, "_store_for", lambda _project_id: store)
    monkeypatch.setattr(world_definition, "build_world_build_graph", lambda _project: graph)
    monkeypatch.setattr(world_validators, "make_world_validators", lambda _project: validators)
    return store, graph, service, marker_path, marker_bytes


def _setup_power_paths_project(tmp_path: Path, monkeypatch):
    root = tmp_path / "synthetic-power-project"
    (root / ".story-system").mkdir(parents=True)
    (root / ".webnovel").mkdir()
    (root / "chapters").mkdir()
    project = {
        "project_id": "p-synthetic-power-repair",
        "title": "Synthetic Power",
        "pipeline_stage": "environment_ready",
        "world_blueprint": {},
    }
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps({"schema_version": "story-system-master-setting/v1", "project": project}), encoding="utf-8"
    )
    (root / ".webnovel" / "project.json").write_text(json.dumps(project), encoding="utf-8")
    (root / ".webnovel" / "state.json").write_text(json.dumps({"story_id": "s-synthetic-power", "current_chapter": 0}), encoding="utf-8")
    store = FileProjectStore(root)
    spec = WorldBuildTaskSpec(
        BuildTaskDefinition(
            task_id="power_system_paths",
            title="力量路线",
            owns=("power_system_spec.paths",),
            validator_id="valid_paths",
        ),
        "model",
        ("paths",),
    )
    definition = BuildGraphDefinition(graph_id="novelflow-project-build", tasks=(spec.task,))
    graph = SimpleNamespace(
        definition=definition,
        spec=lambda _task_id: spec,
        structured_power=True,
        plugin_id="fantasy",
        power_progression_mode=None,
    )
    service = store.build_graph_service(definition, validators={"valid_paths": lambda _payload: ()})
    service.commit_candidate(
        "power_system_paths",
        {"paths": [{"name": "", "branches": ["dawn", "dusk"]}]},
        requested_writes=spec.task.owns,
    )
    service.invalidate_task(
        "power_system_paths",
        (BuildDiagnostic("power.final.paths.missing_name", "paths[0].name", "route name is required"),),
    )
    monkeypatch.setattr(file_projects, "_store_for", lambda _project_id: store)
    monkeypatch.setattr(world_definition, "build_world_build_graph", lambda _project: graph)
    monkeypatch.setattr(world_validators, "make_world_validators", lambda _project: {})
    return store, service


def test_build_workbench_task_detail_and_validation_are_read_only(tmp_path, monkeypatch):
    store, graph, service, _marker_path, _marker_bytes = _setup_project(tmp_path, monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)
    before = service.inspect_graph().to_dict()
    before_artifact = store.build_artifact("world_model", 1)

    detail = client.get("/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model")
    listing = client.get("/file-projects/p-synthetic-build-edit/build-graph")
    passed = client.post("/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/validate", json={"payload": {"label": "Edited"}})
    failed = client.post("/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/validate", json={"payload": {"label": " "}})

    assert detail.status_code == 200
    assert detail.json()["editable"] is True
    assert detail.json()["artifact"]["payload"] == {"label": "Initial"}
    assert "payload" not in listing.json()["tasks"][0]
    assert passed.json()["passed"] is True
    assert failed.json()["passed"] is False
    assert failed.json()["diagnostics"][0]["path"] == "world.rules.label"
    assert service.inspect_graph().to_dict() == before
    assert store.build_artifact("world_model", 1) == before_artifact


def test_human_commit_advances_revision_stales_descendants_and_demotes_readiness(tmp_path, monkeypatch):
    store, _graph, service, marker_path, marker_bytes = _setup_project(tmp_path, monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.patch(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/artifact",
        json={"expected_revision": 1, "payload": {"label": "Edited"}},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["artifact"]["revision"] == 2
    assert body["artifact"]["source"] == "human"
    assert body["pipeline_stage"] == "world_ready"
    assert body["materialization_status"] == "outdated"
    current = service.inspect_graph()
    assert current.tasks["world_model"].current_artifact_revision == 2
    assert current.tasks["downstream_model"].status == "stale"
    assert current.tasks["transitive_model"].status == "stale"
    assert store.build_artifact("world_model", 2)["payload"] == {"label": "Edited"}
    assert marker_path.read_bytes() == marker_bytes


def test_invalid_conflict_and_noneditable_commits_do_not_mutate(tmp_path, monkeypatch):
    store, _graph, service, _marker_path, marker_bytes = _setup_project(tmp_path, monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)
    before_state = service.inspect_graph().to_dict()
    before_project = store.project()

    spoofed_source = client.patch(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/artifact",
        json={"expected_revision": 1, "payload": {"label": "Edited"}, "source": "llm"},
    )

    invalid = client.patch(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/artifact",
        json={"expected_revision": 1, "payload": {"label": ""}},
    )
    imported = client.patch(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_input/artifact",
        json={"expected_revision": 1, "payload": {"input": "New"}},
    )
    deterministic = client.patch(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/power_system_final/artifact",
        json={"expected_revision": 1, "payload": {"power": "New"}},
    )

    assert invalid.status_code == 422
    assert spoofed_source.status_code == 422
    assert invalid.json()["detail"]["diagnostics"][0]["code"] == "missing_label"
    assert imported.status_code == 403
    assert deterministic.status_code == 403
    assert service.inspect_graph().to_dict() == before_state
    assert store.project()["pipeline_stage"] == before_project["pipeline_stage"] == "environment_ready"
    assert store.build_graph_materialization() is not None

    committed = client.patch(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/artifact",
        json={"expected_revision": 1, "payload": {"label": "Edited"}},
    )
    assert committed.status_code == 200
    after_commit = service.inspect_graph().to_dict()
    conflict = client.patch(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/artifact",
        json={"expected_revision": 1, "payload": {"label": "Stale edit"}},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "build_revision_conflict"
    assert service.inspect_graph().to_dict() == after_commit
    assert store.build_artifact("world_model", 2)["payload"] == {"label": "Edited"}
    assert marker_bytes != b""


def test_workbench_ai_repair_commits_one_revision_and_stales_graph(tmp_path, monkeypatch):
    store, _graph, service, marker_path, marker_bytes = _setup_project(tmp_path, monkeypatch)
    calls = []

    class Gateway:
        def complete_stage(self, _stage, request):
            calls.append(request)
            return SimpleNamespace(
                ok=True,
                text='{"label":"Repaired"}',
                provider="test-provider",
                model="test-model",
                resolved_model="test-model-resolved",
            )

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", Gateway())
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/repair",
        json={"expected_revision": 1},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(calls) == 1
    assert body["artifact"]["revision"] == 2
    assert body["artifact"]["source"] == "ai_repair"
    assert body["artifact"]["parent_revision"] == 1
    assert body["artifact"]["provider"] == "test-provider"
    assert body["artifact"]["model"] == "test-model-resolved"
    assert body["artifact"]["prompt_call_id"]
    assert "Initial" in calls[0].prompt
    assert "Initial transitive" not in calls[0].prompt
    assert "downstream_model" not in calls[0].prompt
    assert body["pipeline_stage"] == "world_ready"
    assert body["materialization_status"] == "outdated"
    current = service.inspect_graph()
    assert current.tasks["downstream_model"].status == "stale"
    assert current.tasks["transitive_model"].status == "stale"
    assert store.build_artifact("world_model", 1)["payload"] == {"label": "Initial"}
    assert marker_path.read_bytes() == marker_bytes


def test_workbench_ai_repair_revision_conflict_has_zero_model_calls(tmp_path, monkeypatch):
    _store, _graph, service, _marker_path, _marker_bytes = _setup_project(tmp_path, monkeypatch)
    service.edit_artifact("world_model", {"label": "Human"}, expected_revision=1, requested_writes=("world.rules",))
    calls = []

    class Gateway:
        def complete_stage(self, *_args):
            calls.append(1)
            raise AssertionError("provider must not be called on revision conflict")

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", Gateway())
    response = TestClient(app, raise_server_exceptions=False).post(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/repair",
        json={"expected_revision": 1},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "build_revision_conflict"
    assert calls == []
    assert service.inspect_graph().tasks["world_model"].current_artifact_revision == 2


def test_workbench_rerun_regenerates_full_task_and_commits_through_build_graph(tmp_path, monkeypatch):
    store, _graph, service, marker_path, marker_bytes = _setup_project(tmp_path, monkeypatch)
    calls = []

    class Gateway:
        def complete_stage(self, _stage, request):
            calls.append(request)
            return SimpleNamespace(
                ok=True,
                text='{"label":"Regenerated"}',
                provider="test-provider",
                model="test-model",
                resolved_model="test-model-resolved",
            )

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", Gateway())
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/rerun",
        json={"expected_revision": 1},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(calls) == 1
    assert "完整任务重跑" in calls[0].prompt
    assert "REPAIR FIELDS" not in calls[0].prompt
    assert "这是唯一一次 focused repair" not in calls[0].prompt
    assert "当前候选" not in calls[0].prompt
    assert body["artifact"]["revision"] == 2
    assert body["artifact"]["source"] == "llm"
    assert body["artifact"]["parent_revision"] == 1
    assert body["artifact"]["provider"] == "test-provider"
    assert body["artifact"]["model"] == "test-model-resolved"
    assert body["artifact"]["prompt_call_id"]
    assert body["pipeline_stage"] == "world_ready"
    assert body["materialization_status"] == "outdated"
    current = service.inspect_graph()
    assert current.tasks["world_model"].current_artifact_revision == 2
    assert current.tasks["downstream_model"].status == "stale"
    assert current.tasks["transitive_model"].status == "stale"
    assert store.build_artifact("world_model", 1)["payload"] == {"label": "Initial"}
    assert store.build_artifact("world_model", 2)["payload"] == {"label": "Regenerated"}
    assert marker_path.read_bytes() == marker_bytes


def test_workbench_rerun_conflict_and_failure_do_not_mutate_official_state(tmp_path, monkeypatch):
    store, _graph, service, marker_path, marker_bytes = _setup_project(tmp_path, monkeypatch)
    calls = []

    class Gateway:
        def complete_stage(self, *_args):
            calls.append(1)
            return SimpleNamespace(ok=False, error="private detail", text="", provider="", model="", resolved_model="")

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", Gateway())
    client = TestClient(app, raise_server_exceptions=False)
    conflict = client.post(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/rerun",
        json={"expected_revision": 2},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "build_revision_conflict"
    assert calls == []

    failed = client.post(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/rerun",
        json={"expected_revision": 1},
    )
    assert failed.status_code == 422
    assert len(calls) == 1
    assert failed.json()["detail"]["diagnostics"][0]["code"] == "model.rerun_request_failed"
    current = service.inspect_graph()
    assert current.tasks["world_model"].status == "completed"
    assert current.tasks["world_model"].current_artifact_revision == 1
    assert current.tasks["downstream_model"].status == "completed"
    assert current.tasks["transitive_model"].status == "completed"
    assert store.project()["pipeline_stage"] == "environment_ready"
    assert client.get("/file-projects/p-synthetic-build-edit/build-graph").json()["materialization_status"] == "current"
    assert store.build_artifact("world_model", 2) is None
    assert marker_path.read_bytes() == marker_bytes


@pytest.mark.parametrize(
    ("response_text", "diagnostic_code"),
    [("not-json", "task.invalid_json"), ('{"label":""}', "missing_label")],
)
def test_workbench_rerun_invalid_output_preserves_readiness_and_downstream(
    tmp_path, monkeypatch, response_text, diagnostic_code
):
    store, _graph, service, marker_path, marker_bytes = _setup_project(tmp_path, monkeypatch)

    class Gateway:
        def complete_stage(self, *_args):
            return SimpleNamespace(
                ok=True,
                text=response_text,
                provider="test-provider",
                model="test-model",
                resolved_model="test-model",
            )

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", Gateway())
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/rerun",
        json={"expected_revision": 1},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["diagnostics"][0]["code"] == diagnostic_code
    current = service.inspect_graph()
    assert current.tasks["world_model"].status == "completed"
    assert current.tasks["world_model"].current_artifact_revision == 1
    assert current.tasks["downstream_model"].status == "completed"
    assert current.tasks["transitive_model"].status == "completed"
    assert store.project()["pipeline_stage"] == "environment_ready"
    assert client.get("/file-projects/p-synthetic-build-edit/build-graph").json()["materialization_status"] == "current"
    assert store.build_artifact("world_model", 2) is None
    assert marker_path.read_bytes() == marker_bytes


def test_human_edit_can_supersede_blocked_rerun_without_global_lock(tmp_path, monkeypatch):
    store, _graph, service, _marker_path, _marker_bytes = _setup_project(tmp_path, monkeypatch)
    entered = Event()
    release = Event()

    class BlockingGateway:
        def complete_stage(self, _stage, _request):
            entered.set()
            assert release.wait(10), "test did not release blocked model call"
            return SimpleNamespace(
                ok=True,
                text='{"label":"Rerun loses"}',
                provider="test-provider",
                model="test-model",
                resolved_model="test-model",
            )

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", BlockingGateway())
    client = TestClient(app, raise_server_exceptions=False)
    with ThreadPoolExecutor(max_workers=1) as executor:
        rerun_future = executor.submit(
            client.post,
            "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/rerun",
            json={"expected_revision": 1},
        )
        assert entered.wait(5), "task rerun did not reach provider call"
        running_graph = client.get("/file-projects/p-synthetic-build-edit/build-graph").json()
        assert running_graph["pipeline_stage"] == "environment_ready"
        assert running_graph["materialization_status"] == "current"
        assert running_graph["tasks"][0]["status"] == "running"
        assert file_projects._world_build_jobs_lock.acquire(timeout=1)
        file_projects._world_build_jobs_lock.release()

        human = client.patch(
            "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/artifact",
            json={"expected_revision": 1, "payload": {"label": "Human wins"}},
        )
        assert human.status_code == 200, human.text
        assert human.json()["artifact"]["revision"] == 2
        assert human.json()["artifact"]["source"] == "human"
        release.set()
        rerun = rerun_future.result(timeout=10)

    assert rerun.status_code == 409
    assert rerun.json()["detail"]["code"] == "build_run_conflict"
    current = service.inspect_graph()
    assert current.tasks["world_model"].current_artifact_revision == 2
    assert store.build_artifact("world_model", 2)["payload"] == {"label": "Human wins"}
    assert store.build_artifact("world_model", 3) is None


def test_rerun_rejects_active_world_build_and_build_graph_run_before_provider(tmp_path, monkeypatch):
    _store, _graph, service, _marker_path, _marker_bytes = _setup_project(tmp_path, monkeypatch)
    calls = []

    class Gateway:
        def complete_stage(self, *_args):
            calls.append(1)
            raise AssertionError("provider must not be called for a conflicting run")

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", Gateway())
    client = TestClient(app, raise_server_exceptions=False)
    monkeypatch.setattr(file_projects, "_has_active_world_build_job", lambda _project_id: True)
    world_build = client.post(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/rerun",
        json={"expected_revision": 1},
    )
    assert world_build.status_code == 409
    assert world_build.json()["detail"] == "world_build_in_progress"

    monkeypatch.setattr(file_projects, "_has_active_world_build_job", lambda _project_id: False)
    service.start_run("world_model", allow_completed_with_artifact=True)
    active_run = client.post(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/rerun",
        json={"expected_revision": 1},
    )
    assert active_run.status_code == 409
    assert active_run.json()["detail"]["code"] == "build_run_conflict"
    assert calls == []


@pytest.mark.parametrize("task_id", ["world_input", "power_system_final"])
def test_rerun_rejects_imported_and_deterministic_tasks(tmp_path, monkeypatch, task_id):
    _store, _graph, _service, _marker_path, _marker_bytes = _setup_project(tmp_path, monkeypatch)
    calls = []

    class Gateway:
        def complete_stage(self, *_args):
            calls.append(1)
            raise AssertionError("provider must not be called for a non-model task")

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", Gateway())
    response = TestClient(app, raise_server_exceptions=False).post(
        f"/file-projects/p-synthetic-build-edit/build-graph/tasks/{task_id}/rerun",
        json={"expected_revision": 1},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "build_task_not_rerunnable"
    assert calls == []


def test_workbench_ai_repair_failure_keeps_current_artifact_and_is_structured(tmp_path, monkeypatch):
    store, _graph, service, _marker_path, _marker_bytes = _setup_project(tmp_path, monkeypatch, stage="world_ready")
    calls = []

    class Gateway:
        def complete_stage(self, *_args):
            calls.append(1)
            return SimpleNamespace(ok=False, error="secret provider detail", text="", provider="", model="", resolved_model="")

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", Gateway())
    before_stage = store.project()["pipeline_stage"]
    response = TestClient(app, raise_server_exceptions=False).post(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/repair",
        json={"expected_revision": 1},
    )
    assert response.status_code == 422
    assert len(calls) == 1
    diagnostic = response.json()["detail"]["diagnostics"][0]
    assert diagnostic["code"] == "model.repair_request_failed"
    assert "secret" not in response.text
    state = service.inspect_graph()
    assert state.tasks["world_model"].current_artifact_revision == 1
    assert state.tasks["world_model"].status == "completed"
    assert store.project()["pipeline_stage"] == before_stage


@pytest.mark.parametrize(
    ("response_text", "response_ok", "diagnostic_code"),
    [
        ("", False, "model.repair_request_failed"),
        ("not-json", True, "task.invalid_json"),
        ('{"label":""}', True, "missing_label"),
    ],
)
def test_failed_repair_preserves_completed_task_readiness_and_marker(
    tmp_path, monkeypatch, response_text, response_ok, diagnostic_code
):
    store, _graph, service, marker_path, marker_bytes = _setup_project(tmp_path, monkeypatch)
    before = service.inspect_graph()
    before_task = before.tasks["world_model"]
    before_descendants = {
        task_id: before.tasks[task_id].status
        for task_id in ("downstream_model", "transitive_model")
    }
    calls = []

    class Gateway:
        def complete_stage(self, _stage, _request):
            calls.append(1)
            return SimpleNamespace(
                ok=response_ok,
                text=response_text,
                provider="p" if response_ok else "",
                model="m" if response_ok else "",
                resolved_model="m" if response_ok else "",
            )

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", Gateway())
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/repair",
        json={"expected_revision": 1},
    )

    assert response.status_code == 422
    assert len(calls) == 1
    assert response.json()["detail"]["diagnostics"][0]["code"] == diagnostic_code
    after = service.inspect_graph()
    task = after.tasks["world_model"]
    assert task.current_artifact_revision == before_task.current_artifact_revision == 1
    assert task.status == before_task.status == "completed"
    assert task.validation_status == before_task.validation_status == "passed"
    assert task.diagnostics == before_task.diagnostics
    assert task.active_run_id is None
    assert {task_id: after.tasks[task_id].status for task_id in before_descendants} == before_descendants
    assert store.build_artifact("world_model", 2) is None
    failed_runs = [run for run in after.runs.values() if run.task_id == "world_model" and run.status == "failed"]
    assert len(failed_runs) == 1
    assert failed_runs[0].diagnostics[0].code == diagnostic_code
    assert store.project()["pipeline_stage"] == "environment_ready"
    assert client.get("/file-projects/p-synthetic-build-edit/build-graph").json()["materialization_status"] == "current"
    assert marker_path.read_bytes() == marker_bytes


def test_human_edit_can_supersede_in_flight_ai_repair_without_global_lock(tmp_path, monkeypatch):
    store, _graph, service, marker_path, marker_bytes = _setup_project(tmp_path, monkeypatch)
    entered = Event()
    release = Event()
    calls = []

    class BlockingGateway:
        def complete_stage(self, _stage, _request):
            calls.append(1)
            entered.set()
            assert release.wait(10), "test did not release blocked model call"
            return SimpleNamespace(
                ok=True,
                text='{"label":"AI candidate"}',
                provider="test-provider",
                model="test-model",
                resolved_model="test-model",
            )

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", BlockingGateway())
    client = TestClient(app, raise_server_exceptions=False)
    with ThreadPoolExecutor(max_workers=1) as executor:
        repair_future = executor.submit(
            client.post,
            "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/repair",
            json={"expected_revision": 1},
        )
        assert entered.wait(5), "AI repair did not reach provider call"
        running_graph = client.get("/file-projects/p-synthetic-build-edit/build-graph").json()
        assert running_graph["pipeline_stage"] == "environment_ready"
        assert running_graph["materialization_status"] == "current"
        assert running_graph["tasks"][0]["status"] == "running"
        assert file_projects._world_build_jobs_lock.acquire(timeout=1)
        file_projects._world_build_jobs_lock.release()

        human = client.patch(
            "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/artifact",
            json={"expected_revision": 1, "payload": {"label": "Human wins"}},
        )
        assert human.status_code == 200, human.text
        assert human.json()["artifact"]["revision"] == 2
        assert human.json()["artifact"]["source"] == "human"
        release.set()
        repair = repair_future.result(timeout=10)

    assert repair.status_code == 409
    assert repair.json()["detail"]["code"] == "build_run_conflict"
    assert len(calls) == 1
    current = service.inspect_graph()
    assert current.tasks["world_model"].current_artifact_revision == 2
    assert store.build_artifact("world_model", 2)["payload"] == {"label": "Human wins"}
    assert store.build_artifact("world_model", 3) is None
    assert store.project()["pipeline_stage"] == "world_ready"
    assert marker_path.read_bytes() == marker_bytes


@pytest.mark.parametrize("initial_status", ["stale", "validation_failed"])
def test_failed_repair_restores_preexisting_noncompleted_task_state(tmp_path, monkeypatch, initial_status):
    store, _graph, service, _marker_path, _marker_bytes = _setup_project(tmp_path, monkeypatch, stage="world_ready")
    if initial_status == "validation_failed":
        service.invalidate_task(
            "world_model",
            (BuildDiagnostic("label_invalid", "label", "preexisting diagnostic"),),
        )
        task_id = "world_model"
    else:
        service.edit_artifact(
            "world_model", {"label": "Edited upstream"}, expected_revision=1, requested_writes=("world.rules",)
        )
        task_id = "downstream_model"
    before = service.inspect_graph().tasks[task_id]

    class Gateway:
        def complete_stage(self, *_args):
            return SimpleNamespace(ok=False, text="", provider="", model="", resolved_model="")

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", Gateway())
    response = TestClient(app, raise_server_exceptions=False).post(
        f"/file-projects/p-synthetic-build-edit/build-graph/tasks/{task_id}/repair",
        json={"expected_revision": before.current_artifact_revision},
    )
    assert response.status_code == 422
    after = service.inspect_graph().tasks[task_id]
    assert after.status == before.status == initial_status
    assert after.validation_status == before.validation_status
    assert after.current_artifact_revision == before.current_artifact_revision
    assert after.diagnostics == before.diagnostics
    assert after.active_run_id is None
    assert store.project()["pipeline_stage"] == "world_ready"


def test_workbench_power_paths_repair_uses_structured_patch_only(tmp_path, monkeypatch):
    _store, service = _setup_power_paths_project(tmp_path, monkeypatch)
    from packages.story_core.world_build import power_repairs

    monkeypatch.setattr(power_repairs, "raw_power_spec_from_artifacts", lambda _service: {})
    monkeypatch.setattr(world_validators, "make_world_validators", lambda _project: {"valid_paths": lambda _payload: ()})
    prompts = []

    class Gateway:
        def complete_stage(self, _stage, request):
            prompts.append(request.prompt)
            return SimpleNamespace(
                ok=True,
                text='{"updates":[{"index":0,"fields":{"name":"Recovered route"}}],"append":[]}',
                provider="test-provider",
                model="test-model",
                resolved_model="test-model",
            )

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", Gateway())
    response = TestClient(app, raise_server_exceptions=False).post(
        "/file-projects/p-synthetic-power-repair/build-graph/tasks/power_system_paths/repair",
        json={"expected_revision": 1},
    )
    assert response.status_code == 200, response.text
    assert len(prompts) == 1
    assert "power-path-repair/v1" in prompts[0]
    assert response.json()["artifact"]["payload"] == {
        "paths": [{"name": "Recovered route", "branches": ["dawn", "dusk"]}]
    }
    assert service.inspect_graph().tasks["power_system_paths"].current_artifact_revision == 2


def test_workbench_ai_repair_rejects_parse_and_scoped_out_of_scope_patch(tmp_path, monkeypatch):
    _store, _graph, service, _marker_path, _marker_bytes = _setup_project(tmp_path, monkeypatch, stage="world_ready")
    service.invalidate_task("world_model", (BuildDiagnostic("label_invalid", "label", "label needs repair"),))
    responses = iter(("not-json", '{"label":"Repaired","unauthorized":"no"}'))
    calls = []

    class Gateway:
        def complete_stage(self, _stage, _request):
            calls.append(1)
            return SimpleNamespace(ok=True, text=next(responses), provider="p", model="m", resolved_model="m")

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", Gateway())
    client = TestClient(app, raise_server_exceptions=False)
    for expected_code in ("task.invalid_json", "task.repair_out_of_scope"):
        response = client.post(
            "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/repair",
            json={"expected_revision": 1},
        )
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["diagnostics"][0]["code"] == expected_code
        assert service.inspect_graph().tasks["world_model"].current_artifact_revision == 1
    assert len(calls) == 2


def test_world_build_start_is_rejected_while_build_graph_run_is_active(tmp_path, monkeypatch):
    _store, _graph, service, _marker_path, _marker_bytes = _setup_project(tmp_path, monkeypatch, stage="world_ready")
    service.invalidate_task("world_model", (BuildDiagnostic("label_invalid", "label", "label needs repair"),))
    service.start_run("world_model")
    repair = TestClient(app, raise_server_exceptions=False).post(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/repair",
        json={"expected_revision": 1},
    )
    assert repair.status_code == 409
    assert repair.json()["detail"]["code"] == "build_run_conflict"
    response = TestClient(app, raise_server_exceptions=False).post(
        "/file-projects/p-synthetic-build-edit/world-build-jobs"
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "build_run_in_progress"

def test_active_world_build_blocks_human_edit(tmp_path, monkeypatch):
    store, _graph, service, _marker_path, _marker_bytes = _setup_project(tmp_path, monkeypatch)
    monkeypatch.setitem(file_projects._active_world_build_jobs, "p-synthetic-build-edit", "job-active")
    monkeypatch.setitem(file_projects._world_build_jobs, "job-active", {"status": "running"})
    client = TestClient(app, raise_server_exceptions=False)
    before = service.inspect_graph().to_dict()

    response = client.patch(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/artifact",
        json={"expected_revision": 1, "payload": {"label": "Edited"}},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "world_build_in_progress"
    repair = client.post(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/world_model/repair",
        json={"expected_revision": 1},
    )
    assert repair.status_code == 409
    assert repair.json()["detail"] == "world_build_in_progress"
    assert service.inspect_graph().to_dict() == before
    assert store.project()["pipeline_stage"] == "environment_ready"


def test_leaf_edit_still_invalidates_environment_readiness_and_old_marker(tmp_path, monkeypatch):
    store, _graph, service, marker_path, marker_bytes = _setup_project(tmp_path, monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.patch(
        "/file-projects/p-synthetic-build-edit/build-graph/tasks/transitive_model/artifact",
        json={"expected_revision": 1, "payload": {"detail": "Leaf edit"}},
    )

    assert response.status_code == 200, response.text
    assert response.json()["pipeline_stage"] == "world_ready"
    assert response.json()["materialization_status"] == "outdated"
    assert service.inspect_graph().tasks["transitive_model"].current_artifact_revision == 2
    assert marker_path.read_bytes() == marker_bytes
