from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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
            "model", ("world_rules",),
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
