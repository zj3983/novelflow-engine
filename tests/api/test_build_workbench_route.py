from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects
from packages.story_core.build_graph.contracts import BuildDiagnostic
from packages.story_core.build_graph.definition import BuildGraphDefinition, BuildTaskDefinition
from packages.story_core.world_build import definition as world_definition


class ReadOnlyBuildStore:
    def __init__(self, project: dict, state: SimpleNamespace, artifacts: dict):
        self._project = project
        self._state = state
        self._artifacts = artifacts

    def project(self):
        return self._project

    def build_graph_store(self):
        return self

    def read_state(self):
        return self._state

    def read_artifact(self, task_id: str, revision: int | None = None):
        return self._artifacts.get(task_id) if revision is not None else None

    def build_graph_service(self, *args, **kwargs):
        raise AssertionError("read-only projection must not initialize the BuildGraphService")


def _client_for_projection(monkeypatch, tasks: tuple[BuildTaskDefinition, ...], states: dict, artifacts: dict):
    graph_definition = BuildGraphDefinition(graph_id="novelflow-project-build", tasks=tasks)
    graph = SimpleNamespace(definition=graph_definition)
    state = SimpleNamespace(
        graph_id=graph_definition.graph_id,
        graph_revision=33,
        definition_fingerprint=graph_definition.definition_fingerprint,
        tasks=states,
    )
    store = ReadOnlyBuildStore(
        {"project_id": "p-readonly", "title": "Readonly", "pipeline_stage": "environment_ready"},
        state,
        artifacts,
    )
    monkeypatch.setattr(file_projects, "_store_for", lambda _project_id: store)
    monkeypatch.setattr(world_definition, "build_world_build_graph", lambda _project: graph)
    return TestClient(app, raise_server_exceptions=False)


def test_build_workbench_projects_formal_state_in_definition_order(monkeypatch):
    tasks = tuple(
        BuildTaskDefinition(
            task_id=f"task_{index:02d}",
            title=f"Task {index:02d}",
            dependencies=(f"task_{index - 1:02d}",) if index else (),
            reads=(f"input_{index}",),
            owns=(f"output_{index}",),
        )
        for index in range(15)
    )
    sources = ["llm", "ai_repair", "deterministic"]
    states = {
        task.task_id: SimpleNamespace(
            status="completed",
            current_artifact_revision=1,
            validation_status="passed",
            diagnostics=(),
        )
        for task in tasks
    }
    artifacts = {
        task.task_id: SimpleNamespace(
            source=sources[index] if index < len(sources) else "llm",
            provider="provider-x" if index == 0 else None,
            model="model-y" if index == 0 else None,
            prompt_call_id="call-z" if index == 0 else None,
        )
        for index, task in enumerate(tasks)
    }
    client = _client_for_projection(monkeypatch, tasks, states, artifacts)

    response = client.get("/file-projects/p-readonly/build-graph")

    assert response.status_code == 200
    body = response.json()
    assert body["pipeline_stage"] == "environment_ready"
    assert body["graph_revision"] == 33
    assert len(body["tasks"]) == 15
    assert all(task["status"] == "completed" for task in body["tasks"])
    assert [task["task_id"] for task in body["tasks"]] == [task.task_id for task in tasks]
    assert {task["artifact_revision"] for task in body["tasks"]} == {1}
    assert [body["tasks"][index]["artifact_source"] for index in range(3)] == sources
    assert body["tasks"][0]["provider"] == "provider-x"
    assert body["tasks"][0]["model"] == "model-y"
    assert body["tasks"][0]["prompt_call_id"] == "call-z"
    assert body["tasks"][1]["dependencies"] == ["task_00"]
    assert body["tasks"][1]["reads"] == ["input_1"]
    assert body["tasks"][1]["owns"] == ["output_1"]


def test_build_workbench_preserves_formal_exception_states_and_diagnostics(monkeypatch):
    statuses = ("validation_failed", "blocked", "stale", "running", "review_required")
    tasks = tuple(
        BuildTaskDefinition(task_id=status, title=status, dependencies=("validation_failed",) if status == "blocked" else ())
        for status in statuses
    )
    diagnostic = BuildDiagnostic("missing_field", "world.rules[0]", "required field is missing")
    states = {
        status: SimpleNamespace(
            status=status,
            current_artifact_revision=1 if status in {"validation_failed", "stale", "review_required"} else None,
            validation_status="failed" if status == "validation_failed" else "unknown",
            diagnostics=(diagnostic,) if status == "validation_failed" else (),
        )
        for status in statuses
    }
    artifacts = {
        status: SimpleNamespace(source="llm", provider=None, model=None, prompt_call_id=None)
        for status in statuses
        if states[status].current_artifact_revision is not None
    }
    client = _client_for_projection(monkeypatch, tasks, states, artifacts)

    response = client.get("/file-projects/p-readonly/build-graph")

    assert response.status_code == 200
    body = response.json()
    assert [task["status"] for task in body["tasks"]] == list(statuses)
    assert body["tasks"][0]["diagnostics"] == [
        {"code": "missing_field", "path": "world.rules[0]", "message": "required field is missing", "severity": "blocking"}
    ]
    assert body["tasks"][1]["dependencies"] == ["validation_failed"]


def test_build_workbench_does_not_initialize_missing_graph_state(monkeypatch):
    task = BuildTaskDefinition(task_id="world_input", title="世界输入")
    graph_definition = BuildGraphDefinition(graph_id="novelflow-project-build", tasks=(task,))
    graph = SimpleNamespace(definition=graph_definition)
    store = ReadOnlyBuildStore(
        {"project_id": "p-readonly", "title": "Readonly", "pipeline_stage": "draft"},
        None,
        {},
    )
    monkeypatch.setattr(file_projects, "_store_for", lambda _project_id: store)
    monkeypatch.setattr(world_definition, "build_world_build_graph", lambda _project: graph)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/file-projects/p-readonly/build-graph")
        detail = client.get("/file-projects/p-readonly/build-graph/tasks/world_input")
        validation = client.post(
            "/file-projects/p-readonly/build-graph/tasks/world_input/validate",
            json={"payload": {"value": "candidate"}},
        )

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "build-workbench/v1",
        "initialized": False,
        "graph_id": "novelflow-project-build",
        "graph_revision": None,
        "pipeline_stage": "draft",
        "tasks": [],
    }
    assert detail.status_code == 409
    assert detail.json()["detail"] == "build_graph_not_initialized"
    assert validation.status_code == 409
    assert validation.json()["detail"] == "build_graph_not_initialized"
