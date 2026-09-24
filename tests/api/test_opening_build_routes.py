import json
from collections import Counter
from threading import Event
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects
from packages.story_core.opening_build import runtime
from tests.story_core.test_opening_build import opening_payloads
from tests.story_core.test_world_build_graph import _store
from tests.api.test_build_workbench_edit_route import _wait_orchestration


BASE = "/file-projects/generic_webnovel/build-graph"


def setup(tmp_path, monkeypatch):
    store = _store(tmp_path, plugin_id="generic_webnovel")
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    return store, TestClient(app)


def tree(store):
    return {str(path.relative_to(store.root)): path.read_bytes() for path in store.root.rglob("*") if path.is_file()}


def test_browsing_never_initializes_and_explicit_activation_reload(tmp_path, monkeypatch):
    store, client = setup(tmp_path, monkeypatch)
    before = tree(store)
    assert client.get(BASE).json()["initialized"] is False
    assert client.get(BASE + "/tasks/story_core").status_code == 409
    assert tree(store) == before
    result = client.post(BASE + "/opening", json={"expected_graph_revision": None})
    assert result.status_code == 200, result.text
    graph = result.json()
    assert graph["opening_graph"]
    assert "outline_execution_contract" in {task["task_id"] for task in graph["tasks"]}
    before = tree(store)
    assert client.get(BASE).json() == graph
    assert client.get(BASE + "/tasks/story_core").status_code == 200
    assert tree(store) == before


def test_continue_opening_one_call_per_model_and_reload_from_backend(tmp_path, monkeypatch):
    store, client = setup(tmp_path, monkeypatch)
    payloads = opening_payloads()
    calls = []

    class Gateway:
        def complete_stage(self, _stage, request):
            task_id = request.metadata["world_build_task"]
            calls.append(task_id)
            return SimpleNamespace(ok=True, text=json.dumps(payloads[task_id], ensure_ascii=False), provider="test", model="test", resolved_model="test")

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", Gateway())
    assert client.post(BASE + "/opening", json={}).status_code == 200
    start = client.post(BASE + "/orchestrations", json={"mode": "continue"})
    assert start.status_code == 200, start.text
    job = _wait_orchestration(client, "generic_webnovel", start.json()["job_id"])
    assert job["status"] == "completed", job
    assert job["materialized"]
    assert set(calls) == set(payloads)
    assert all(count == 1 for count in Counter(calls).values())
    graph = client.get(BASE).json()
    assert graph["materialization_status"] == "current"
    assert graph["pipeline_stage"] == "environment_ready"
    assert len(json.loads((store.webnovel_dir / "outline.json").read_text(encoding="utf-8"))["chapters"]) == 3
    again = client.post(BASE + "/orchestrations", json={"mode": "continue"})
    assert again.status_code == 200, again.text
    assert _wait_orchestration(client, "generic_webnovel", again.json()["job_id"])["status"] == "completed"
    assert len(calls) == len(payloads)
    marker = (store.webnovel_dir / "build_graph_materialization.json").read_bytes()
    original = store.build_artifact("story_core")
    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", SimpleNamespace(
        complete_stage=lambda *_: SimpleNamespace(ok=False),
    ))
    failure = client.post(BASE + "/tasks/story_core/rerun", json={"expected_revision": 1})
    assert failure.status_code == 422
    assert store.build_artifact("story_core") == original
    assert store.project()["pipeline_stage"] == "environment_ready"
    assert (store.webnovel_dir / "build_graph_materialization.json").read_bytes() == marker
    changed = payloads["story_core"]
    changed["story_core"]["main_conflict"] = "作者调整为公开名册的归属争议"
    edited = client.patch(BASE + "/tasks/story_core/artifact", json={"expected_revision": 1, "payload": changed})
    assert edited.status_code == 200, edited.text
    assert edited.json()["artifact"]["revision"] == 2
    assert edited.json()["artifact"]["source"] == "human"
    assert edited.json()["pipeline_stage"] == "world_ready"
    assert edited.json()["materialization_status"] == "outdated"
    assert store.build_graph_store().read_state().tasks["outline_execution_contract"].status == "stale"
    assert (store.webnovel_dir / "build_graph_materialization.json").read_bytes() == marker


def test_opening_source_change_during_provider_never_commits_candidate(tmp_path, monkeypatch):
    store, client = setup(tmp_path, monkeypatch)
    entered, release = Event(), Event()

    class Gateway:
        def complete_stage(self, _stage, _request):
            entered.set()
            assert release.wait(10)
            return SimpleNamespace(ok=True, text=json.dumps(opening_payloads()["story_core"]), provider="test", model="test", resolved_model="test")

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", Gateway())
    client.post(BASE + "/opening", json={})
    start = client.post(BASE + "/orchestrations", json={"mode": "continue"})
    try:
        assert entered.wait(5)
        store.update_project({"seed_outline": "作者在调用期间修改输入"})
    finally:
        release.set()
    job = _wait_orchestration(client, "generic_webnovel", start.json()["job_id"])
    assert job["status"] == "conflicted", job
    assert job["error_code"] == "project_world_changed"
    assert store.build_artifact("story_core") is None
    assert store.build_graph_store().artifact_history("story_core") == ()
    state = store.build_graph_store().read_state()
    assert state.tasks["story_core"].status == "ready"
    assert any(run.status == "conflict" for run in state.runs.values())
    assert not (store.webnovel_dir / "outline.json").exists()
    assert client.post(BASE + "/orchestrations", json={"mode": "continue"}).status_code == 409
    assert client.post(BASE + "/opening/input", json={"expected_graph_revision": state.graph_revision}).status_code == 200
    runtime.assert_sources_current(store)


def test_activation_rejects_written_projects_and_stale_revision(tmp_path, monkeypatch):
    store, client = setup(tmp_path, monkeypatch)
    before = tree(store)
    assert client.post(BASE + "/opening", json={"expected_graph_revision": 5}).status_code == 409
    assert tree(store) == before
    store.snapshot_store.replace_json_transaction({store.webnovel_dir / "state.json": {"current_chapter": 1}})
    before = tree(store)
    response = client.post(BASE + "/opening", json={})
    assert response.status_code == 409
    assert response.json()["detail"] == "opening_requires_unwritten_project"
    assert tree(store) == before
