from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects as file_project_routes
from apps.api.routes import stories as story_routes
from apps.api.services.continuous_generation import ContinuousGenerationJobStore
from packages.story_core.character_inspection import ConsistencyWarning
from packages.story_core.generation_consistency_gate import (
    GenerationConsistencyGate,
    evaluate_generation_consistency,
)
from packages.story_core.models import StoryState


def _story() -> dict:
    return {
        "story_id": "story-route",
        "outline": "本章调查旧案。",
        "genre": "都市",
        "style": "白描",
        "current_chapter": 19,
        "characters": [
            {
                "name": "林照",
                "role": "protagonist",
                "current_state": {
                    "history": [{"chapter": 1, "current": {"location": "北岸"}}]
                },
            }
        ],
        "progression_ledger": {
            "protagonist": {
                "history": [
                    {"chapter": 25, "current": {"skills": ["FUTURE_SKILL_999"]}}
                ]
            }
        },
        "knowledge_ledger": [],
        "equipment_cards": [],
        "relationship_graph": [],
    }


def _plan() -> dict:
    return {
        "chapter_number": 20,
        "character_moves": [
            {"name": "林照", "location": "北岸", "skills_used": ["FUTURE_SKILL_999"]}
        ],
    }


def _gate() -> GenerationConsistencyGate:
    return evaluate_generation_consistency(_story(), _plan(), target_chapter=20)


def _job(job_id: str, story_id: str) -> dict[str, object]:
    gate = _gate().model_dump(mode="json")
    return {
        "job_id": job_id,
        "story_id": story_id,
        "status": "awaiting_consistency_override",
        "progress": "等待作者决定",
        "chapter_number": None,
        "target_chapter": 20,
        "operation": "generate",
        "steps": [],
        "error": "",
        "consistency_gate": gate,
        "consistency_override": False,
        "original_plan": deepcopy(_plan()),
        "revised_plan": None,
        "original_consistency_gate": gate,
        "revised_consistency_gate": None,
        "replan_status": "",
        "replan_attempts": 0,
        "replan_result": None,
        "created_at": "2026-09-12T00:00:00+00:00",
        "updated_at": "2026-09-12T00:00:00+00:00",
    }


def test_regular_story_replan_ignores_client_findings_and_rechecks_server_side(monkeypatch) -> None:
    record = SimpleNamespace(
        story=StoryState.model_validate(_story()),
        initial_story=StoryState.model_validate(_story()),
        history=[],
    )
    requests = []
    revised = {
        "chapter_number": 20,
        "character_moves": [{"name": "林照", "location": "北岸"}],
    }

    monkeypatch.setattr(story_routes.store, "get", lambda _story_id: record)

    def fake_replan(_source, request):
        requests.append(request)
        return revised

    monkeypatch.setattr(story_routes.engine.orchestrator, "replan_consistency_plan", fake_replan)
    story_routes._generation_jobs.clear()
    story_routes._active_generation_jobs.clear()
    story_routes._generation_jobs["gj-route"] = _job("gj-route", "story-route")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/stories/story-route/generation-jobs/gj-route/replan-consistency",
            json={"warnings": []},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "awaiting_replanned_confirmation"
    assert payload["replan_status"] == "replanned_clear"
    assert payload["revised_consistency_gate"]["status"] == "clear"
    assert payload["original_plan"]["character_moves"][0]["skills_used"] == [
        "FUTURE_SKILL_999"
    ]
    assert requests[0].target_chapter == 20
    assert requests[0].historical_boundary == 19
    assert [item.code for item in requests[0].blocking_findings] == [
        "SKILL_NOT_YET_ACQUIRED"
    ]

    with TestClient(app, raise_server_exceptions=False) as client:
        limited = client.post(
            "/stories/story-route/generation-jobs/gj-route/replan-consistency",
            json={"warnings": []},
        )
    assert limited.status_code == 409
    assert limited.json()["detail"] == "consistency_replan_not_available"


class _FakeFileProjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.requests = []

    def project(self) -> dict[str, str]:
        return {"project_id": "p-route"}

    def generation_story_for_target(self, target_chapter: int) -> dict:
        assert target_chapter == 20
        return _story()

    def replan_consistency_plan(self, request) -> dict:
        self.requests.append(request)
        return {
            "chapter_number": 20,
            "character_moves": [{"name": "林照", "location": "北岸"}],
        }


def test_file_project_replan_preserves_plan_and_passes_revised_plan_to_continue(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = _FakeFileProjectStore(tmp_path)
    job = _job("fgj-route", "file:p-route")
    file_project_routes._file_generation_jobs.clear()
    file_project_routes._active_file_generation_jobs.clear()
    file_project_routes._file_generation_jobs[job["job_id"]] = job
    file_project_routes._active_file_generation_jobs["file:p-route"] = str(job["job_id"])
    monkeypatch.setattr(file_project_routes, "_store_for", lambda _project_id: store)
    submitted = []
    monkeypatch.setattr(
        file_project_routes._file_generation_executor,
        "submit",
        lambda fn, *args, **kwargs: submitted.append((fn, args, kwargs)),
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/file-projects/file:p-route/generation-jobs/fgj-route/replan-consistency",
            json={"warnings": []},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "awaiting_replanned_confirmation"
    assert payload["revised_plan"]["character_moves"][0]["location"] == "北岸"
    assert payload["original_plan"]["character_moves"][0]["skills_used"] == [
        "FUTURE_SKILL_999"
    ]
    assert store.requests[0].blocking_findings[0].code == "SKILL_NOT_YET_ACQUIRED"
    assert submitted == []

    with TestClient(app, raise_server_exceptions=False) as client:
        continued = client.post(
            "/file-projects/file:p-route/generation-jobs/fgj-route/continue"
        )

    assert continued.status_code == 200, continued.text
    assert continued.json()["status"] == "queued"
    assert continued.json()["consistency_override"] is False
    assert len(submitted) == 1
    assert submitted[0][2]["director_plan_override"] == payload["revised_plan"]


def test_continuous_replan_exposes_revised_gate_without_starting_runner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "p-route"
    project_root.mkdir()
    store = _FakeFileProjectStore(project_root)
    jobs = ContinuousGenerationJobStore(project_root)
    created = jobs.create(
        project_id="p-route",
        story_id="file:p-route",
        count=2,
        start_chapter=20,
    )
    paused = jobs.update(
        str(created["job_id"]),
        status="awaiting_consistency_override",
        phase="awaiting_consistency_override",
        current_chapter=20,
        consistency_gate=_gate().model_dump(mode="json"),
        original_plan=_plan(),
        original_consistency_gate=_gate().model_dump(mode="json"),
    )
    file_project_routes._active_continuous_generation_jobs.clear()
    file_project_routes._active_continuous_generation_jobs["file:p-route"] = str(
        paused["job_id"]
    )
    monkeypatch.setattr(file_project_routes, "_store_for", lambda _project_id: store)
    submitted = []
    monkeypatch.setattr(
        file_project_routes._continuous_generation_executor,
        "submit",
        lambda fn, *args, **kwargs: submitted.append((fn, args, kwargs)),
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/file-projects/file:p-route/continuous-generation-jobs/{paused['job_id']}/replan-consistency",
            json={"warnings": []},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "awaiting_replanned_confirmation"
    assert payload["replan_status"] == "replanned_clear"
    assert payload["revised_consistency_gate"]["status"] == "clear"
    assert submitted == []
