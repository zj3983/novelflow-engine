from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from apps.api.main import app
from apps.api.routes import file_projects
from packages.story_core.build_graph.contracts import BuildDiagnostic
from packages.story_core.candidate_draft import CandidateDraft
from tests.api.test_build_workbench_edit_route import _setup_project

BASE = "/file-projects/p-synthetic-build-edit/public-build"
SECRET = "PRIVATE_PROSE_API_KEY_PROMPT_RESPONSE"


def tree(store):
    return {str(p.relative_to(store.root)): p.read_bytes() for p in store.root.rglob("*") if p.is_file()}


def setup(tmp_path, monkeypatch):
    store, graph, service, *_ = _setup_project(tmp_path, monkeypatch)
    return store, graph, service, TestClient(app, raise_server_exceptions=False)


def test_read_only_projection_and_candidate_authority(tmp_path, monkeypatch):
    store, graph, service, client = setup(tmp_path, monkeypatch)
    for project_id in ("p-synthetic-build-edit", "other-project"):
        candidate = CandidateDraft.create(project_id=project_id, chapter_number=1, body=SECRET,
                                          quality_report={"raw_response": SECRET})
        store.candidate_store.save(candidate)
    service.edit_artifact("world_model", {"label": SECRET}, expected_revision=1)
    before = tree(store)
    monkeypatch.setattr(store, "build_graph_service", lambda *a, **k: pytest.fail("read initialized service"))
    result = client.get(BASE)
    assert result.status_code == 200, result.text
    assert SECRET not in result.text
    snapshot = result.json()
    assert {t["status"] for t in snapshot["tasks"]} == {"completed", "stale"}
    assert all("forbidden_writes" in t for t in snapshot["tasks"])
    candidates = snapshot["readiness"]["human_confirmation"]
    assert len(candidates) == 1
    assert candidates[0]["requires_human_confirmation"]
    for path in ("/readiness", "/next-actions", "/tasks/world_model", "/tasks/world_model/artifacts/1"):
        response = client.get(BASE + path)
        assert response.status_code == 200, response.text
        assert SECRET not in response.text
    assert tree(store) == before
    assert client.post(BASE + "/candidates/anything/confirm", json={}).status_code == 404


def test_edit_reuses_workbench_validation_and_revision_conflicts(tmp_path, monkeypatch):
    store, graph, service, client = setup(tmp_path, monkeypatch)
    revision = service.inspect_graph().graph_revision
    before = tree(store)
    body = {"expected_graph_revision": revision, "expected_revision": 1, "payload": {"label": SECRET}}
    conflict = client.patch(BASE + "/tasks/world_model/artifact", json={**body, "expected_graph_revision": revision - 1})
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["code"] == "build_revision_conflict"
    assert tree(store) == before
    conflict = client.patch(BASE + "/tasks/world_model/artifact", json={**body, "expected_revision": 2})
    assert conflict.status_code == 409, conflict.text
    invalid = client.patch(BASE + "/tasks/world_model/artifact", json={**body, "payload": {"raw_prompt": SECRET}})
    assert invalid.status_code == 422, invalid.text
    assert invalid.json()["detail"]["code"] == "validation_failed"
    assert SECRET not in invalid.text
    assert tree(store) == before
    success = client.patch(BASE + "/tasks/world_model/artifact", json=body)
    assert success.status_code == 200, success.text
    assert SECRET not in success.text
    assert service.inspect_artifact("world_model").revision == 2
    assert service.inspect_task("transitive_model").status == "stale"
    assert store.project()["pipeline_stage"] == "world_ready"
    assert client.patch(BASE + "/tasks/world_model/artifact", json=body).status_code == 409


@pytest.mark.parametrize("task_id", ["world_input", "power_system_final"])
def test_forbidden_task_write_preserves_files(tmp_path, monkeypatch, task_id):
    store, graph, service, client = setup(tmp_path, monkeypatch)
    before = tree(store)
    response = client.patch(BASE + f"/tasks/{task_id}/artifact", json={
        "expected_graph_revision": service.inspect_graph().graph_revision,
        "expected_revision": 1, "payload": {"label": SECRET}})
    assert response.status_code == 403, response.text
    assert tree(store) == before


@pytest.mark.parametrize("status", ["stale", "review_required", "validation_failed", "running", "blocked"])
def test_exception_states_and_diagnostics_are_structured(tmp_path, monkeypatch, status):
    store, graph, service, client = setup(tmp_path, monkeypatch)
    state = service.inspect_graph()
    tasks = dict(state.tasks)
    tasks["world_model"] = replace(tasks["world_model"], status=status,
                                    diagnostics=(BuildDiagnostic("missing_label", SECRET, SECRET, details={"body": SECRET}),))
    store.build_graph_store().persist(replace(state, tasks=tasks))
    response = client.get(BASE)
    assert response.status_code == 200, response.text
    assert SECRET not in response.text
    task = next(t for t in response.json()["tasks"] if t["task_id"] == "world_model")
    assert task["status"] == status
    assert task["diagnostics"] == [{"code": "missing_label", "severity": "blocking"}]
    if status == "review_required":
        assert response.json()["readiness"]["human_confirmation"][0]["kind"] == "task_review"
        assert all(a["task_id"] != "world_model" for a in response.json()["next_actions"])


def test_bad_request_does_not_echo_payload(tmp_path, monkeypatch):
    store, graph, service, client = setup(tmp_path, monkeypatch)
    response = client.patch(BASE + "/tasks/world_model/artifact", json={"expected_revision": SECRET, "payload": SECRET})
    assert response.status_code == 422
    assert SECRET not in response.text


def test_next_requires_current_revision_and_delegates(tmp_path, monkeypatch):
    store, graph, service, client = setup(tmp_path, monkeypatch)
    service.edit_artifact("world_model", {"label": "edited"}, expected_revision=1)
    snapshot = client.get(BASE).json()
    action = next(a for a in snapshot["next_actions"] if a["action"] == "run_next")
    assert action["task_id"] == "downstream_model"
    calls = []
    monkeypatch.setattr(file_projects._build_orchestration_executor, "submit", lambda *args: calls.append(args))
    old = client.post(BASE + "/next", json={"expected_graph_revision": snapshot["graph_revision"] - 1, "task_id": action["task_id"]})
    assert old.status_code == 409
    assert not calls
    response = client.post(BASE + "/next", json=action["preconditions"])
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert response.json()["job_id"].startswith("wbo-")
    # Release fixture's queued job so it cannot affect subsequent synthetic projects.
    normalized = "p-synthetic-build-edit"
    file_projects._active_build_orchestration_jobs.pop(normalized, None)
    file_projects._build_orchestration_jobs.pop(response.json()["job_id"], None)


def test_capabilities_follow_bound_stage_without_secrets(tmp_path, monkeypatch):
    from packages.story_core import runtime_config
    from packages.story_core.model_gateway import capabilities
    store, graph, service, client = setup(tmp_path, monkeypatch)
    # Fixture has no stage; use its current definition with one stage solely for this read.
    definition = replace(graph.definition, tasks=tuple(replace(t, model_stage="planner") for t in graph.definition.tasks))
    graph.definition = definition
    state = service.inspect_graph()
    store.build_graph_store().persist(replace(state, definition_fingerprint=definition.definition_fingerprint))
    settings = SimpleNamespace(provider_id="openai", protocol="openai", model="custom-model",
        base_url="https://user:password@private.test/secret-path?token=secret", api_key=SECRET,
        user_declared_capabilities={"streaming": False})
    monkeypatch.setattr(runtime_config, "resolve_stage_runtime", lambda stage: settings)
    original = capabilities.resolve_model_profile
    monkeypatch.setattr(capabilities, "resolve_model_profile", lambda *a, **k: original(*a, **k,
        store=capabilities.ModelCapabilityStore(tmp_path / "empty-cache.json")))
    before = tree(store)
    response = client.get(BASE + "/capabilities")
    assert response.status_code == 200, response.text
    binding = response.json()["bindings"][0]
    assert binding["model"] == "custom-model"
    assert binding["capabilities"]["streaming"]["state"] == "unsupported"
    assert binding["capabilities"]["streaming"]["source"] == "user_declared"
    assert all(token not in response.text for token in (SECRET, "private.test", "secret-path", "password", "base_url", "api_key"))
    assert tree(store) == before


def test_review_cannot_be_accepted_by_edit(tmp_path, monkeypatch):
    store, graph, service, client = setup(tmp_path, monkeypatch)
    state = service.inspect_graph()
    tasks = dict(state.tasks)
    tasks["world_model"] = replace(tasks["world_model"], status="review_required")
    store.build_graph_store().persist(replace(state, tasks=tasks))
    before = tree(store)
    response = client.patch(BASE + "/tasks/world_model/artifact", json={
        "expected_graph_revision": state.graph_revision, "expected_revision": 1, "payload": {"label": "approved"}})
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "human_review_required"
    assert tree(store) == before


def test_consumed_opening_keeps_planning_and_candidate_authority(tmp_path, monkeypatch):
    from tests.story_core.test_opening_prose import prepared_store, FakeEngine
    store = prepared_store(tmp_path)
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    candidate = store.generate_next_chapter(engine=FakeEngine(), persist=False)["candidate"]
    store.confirm_candidate(candidate["candidate_id"])
    client = TestClient(app, raise_server_exceptions=False)
    before = tree(store)
    response = client.get(BASE)
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert snapshot["next_actions"] == []
    task = next(t for t in snapshot["tasks"] if t["task_id"] == "story_core")
    denied = client.patch(BASE + "/tasks/story_core/artifact", json={
        "expected_graph_revision": snapshot["graph_revision"], "expected_revision": task["artifact_revision"],
        "payload": {"label": "cannot overwrite accepted planning"}})
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["code"] == "opening_consumed_planning_locked"
    assert tree(store) == before


def test_missing_state_is_read_only_and_writes_fail_closed(tmp_path, monkeypatch):
    store, graph, service, client = setup(tmp_path, monkeypatch)
    build_store = store.build_graph_store()
    monkeypatch.setattr(build_store, "read_state", lambda: None)
    monkeypatch.setattr(store, "build_graph_store", lambda: build_store)
    before = tree(store)
    response = client.get(BASE)
    assert response.status_code == 200, response.text
    assert not response.json()["initialized"]
    assert not response.json()["readiness"]["ready"]
    assert not response.json()["next_actions"]
    response = client.patch(BASE + "/tasks/world_model/artifact", json={
        "expected_graph_revision": 0, "expected_revision": 1, "payload": {}})
    assert response.status_code == 409
    assert tree(store) == before


def test_concurrent_edit_has_one_winner(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    store, graph, service, client = setup(tmp_path, monkeypatch)
    body = {"expected_graph_revision": service.inspect_graph().graph_revision, "expected_revision": 1,
            "payload": {"label": "one winner"}}
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: client.patch(BASE + "/tasks/world_model/artifact", json=body).status_code, range(2)))
    assert sorted(results) == [200, 409]
    assert service.inspect_artifact("world_model").revision == 2


def test_future_handler_dependencies_fail_closed(tmp_path, monkeypatch):
    store, graph, service, client = setup(tmp_path, monkeypatch)
    route = next(route for route in app.routes if route.name == "edit_file_project_build_graph_task")
    monkeypatch.setattr(route.dependant, "dependencies", [object()])
    before = tree(store)
    response = client.patch(BASE + "/tasks/world_model/artifact", json={
        "expected_graph_revision": service.inspect_graph().graph_revision, "expected_revision": 1, "payload": {"label": "edit"}})
    assert response.status_code == 503, response.text
    assert tree(store) == before
