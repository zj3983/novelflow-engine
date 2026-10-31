from threading import Event
from types import SimpleNamespace

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

import apps.api.services.ending_planning as jobs_module
import apps.api.routes.file_project_outline as routes_module
from apps.api.services.ending_planning import EndingPlanningJobs
from packages.story_core.persistence.snapshot_store import SnapshotStore


def store_at(root):
    return SimpleNamespace(root=root, story_system_dir=root / ".story-system", webnovel_dir=root / ".webnovel")


def test_job_is_idempotent_and_progress_survives_page_reload(tmp_path, monkeypatch):
    entered, finish = Event(), Event()
    calls = []
    def run(store, generator, *, progress, **kwargs):
        calls.append(1)
        progress("正在生成细纲")
        entered.set()
        assert finish.wait(5)
        return {"base_chapter": 50, "chapter_range": [51, 53], "chapter_count": 3}
    monkeypatch.setattr(jobs_module, "plan_ending", run)
    jobs = EndingPlanningJobs()
    store = store_at(tmp_path)
    try:
        first = jobs.start(store, object(), draft=None, guidance="", assert_mutation_allowed=lambda: None)
        assert entered.wait(5)
        second = jobs.start(store, object(), draft=None, guidance="", assert_mutation_allowed=lambda: None)
        assert first["job_id"] == second["job_id"]
        assert jobs.current(store)["progress"] == "正在生成细纲"
        finish.set()
        jobs._runs[first["job_id"]].result(timeout=5)
        assert jobs.current(store)["status"] == "completed"
        assert jobs.current(store)["result"]["chapter_range"] == [51, 53]
        assert len(calls) == 1
    finally:
        finish.set()
        jobs._executor.shutdown(wait=True)


def test_restart_turns_orphaned_running_job_into_retryable_failure(tmp_path):
    jobs = EndingPlanningJobs()
    store = store_at(tmp_path)
    SnapshotStore().write_json_atomic(jobs._path(store), {"job_id": "old", "status": "running"})
    try:
        assert jobs.current(store)["status"] == "failed"
        assert jobs.current(store)["error"] == "ending_planning_interrupted"
    finally:
        jobs._executor.shutdown(wait=True)


def test_routes_start_and_read_job_and_reject_unknown_parameters(tmp_path, monkeypatch):
    jobs = EndingPlanningJobs()
    monkeypatch.setattr(routes_module, "ending_planning_jobs", jobs)
    monkeypatch.setattr(jobs_module, "plan_ending", lambda *args, **kwargs:
                        {"base_chapter": 50, "chapter_range": [51, 53], "chapter_count": 3})
    router = APIRouter()
    routes_module.register_file_project_outline_routes(router, store_for=lambda _: store_at(tmp_path), planning_generator=lambda: object())
    app = FastAPI()
    app.include_router(router)
    try:
        with TestClient(app) as client:
            assert client.get("/file-projects/test/outline/ending-plan").json() == {"job": None}
            assert client.post("/file-projects/test/outline/ending-plan", json={"prose": True}).status_code == 422
            response = client.post("/file-projects/test/outline/ending-plan", json={"guidance": "保留伤势"})
            assert response.status_code == 200
            jobs._runs[response.json()["job_id"]].result(timeout=5)
            assert client.get("/file-projects/test/outline/ending-plan").json()["job"]["status"] == "completed"
    finally:
        jobs._executor.shutdown(wait=True)
