from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects as file_project_routes
from apps.api.services.continuous_generation import ContinuousGenerationJobStore
from packages.story_core.candidate_draft import CandidateDraft
from packages.story_core.character_inspection import ConsistencyWarning
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.generation_consistency_gate import (
    ConsistencyGateRequired,
    GenerationConsistencyGate,
)


@pytest.fixture
def continuous_api(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    file_project_routes._file_generation_jobs.clear()
    file_project_routes._active_file_generation_jobs.clear()
    file_project_routes._active_continuous_generation_jobs.clear()
    submitted: list[tuple[object, tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        file_project_routes._continuous_generation_executor,
        "submit",
        lambda fn, *args, **kwargs: submitted.append((fn, args, kwargs)),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, export_root, submitted
    file_project_routes._file_generation_jobs.clear()
    file_project_routes._active_file_generation_jobs.clear()
    file_project_routes._active_continuous_generation_jobs.clear()


def _seed_project(export_root: Path, name: str = "p-continuous") -> str:
    root = export_root / name
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    project = {
        "project_id": name,
        "active_story_id": name,
        "title": "连续生成测试",
        "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        "character_profiles": [],
    }
    state = {
        "story_id": name,
        "current_chapter": 10,
        "world_facts": [],
        "characters": [],
    }
    (root / ".webnovel" / "project.json").write_text(
        json.dumps(project, ensure_ascii=False), encoding="utf-8"
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": project,
                "state": state,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return f"file:{name}"


def test_start_continuous_generation_job_persists_and_submits(continuous_api) -> None:
    client, export_root, submitted = continuous_api
    project_id = _seed_project(export_root)

    response = client.post(
        f"/file-projects/{project_id}/continuous-generation-jobs",
        json={"count": 5},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema_version"] == "continuous-generation-job/v1"
    assert payload["requested_count"] == 5
    assert payload["start_chapter"] == 11
    assert payload["status"] == "queued"
    assert len(submitted) == 1
    assert (
        export_root
        / "p-continuous"
        / ".story-system"
        / "continuous-generation-jobs"
        / f"{payload['job_id']}.json"
    ).exists()


def test_start_rejects_unsupported_count(continuous_api) -> None:
    client, export_root, submitted = continuous_api
    project_id = _seed_project(export_root)

    response = client.post(
        f"/file-projects/{project_id}/continuous-generation-jobs",
        json={"count": 3},
    )

    assert response.status_code == 422
    assert submitted == []


def test_second_continuous_job_returns_conflict(continuous_api) -> None:
    client, export_root, _submitted = continuous_api
    project_id = _seed_project(export_root)
    first = client.post(
        f"/file-projects/{project_id}/continuous-generation-jobs",
        json={"count": 2},
    )
    assert first.status_code == 200

    second = client.post(
        f"/file-projects/{project_id}/continuous-generation-jobs",
        json={"count": 5},
    )

    assert second.status_code == 409
    assert second.json()["detail"] == "project_generation_in_progress"


def test_normal_generation_is_blocked_while_continuous_job_is_active(
    continuous_api,
) -> None:
    client, export_root, _submitted = continuous_api
    project_id = _seed_project(export_root)
    assert client.post(
        f"/file-projects/{project_id}/continuous-generation-jobs",
        json={"count": 2},
    ).status_code == 200

    response = client.post(f"/file-projects/{project_id}/generation-jobs", json={})

    assert response.status_code == 409
    assert response.json()["detail"] == "project_generation_in_progress"


def test_continuous_generation_is_blocked_by_normal_job(continuous_api) -> None:
    client, export_root, submitted = continuous_api
    project_id = _seed_project(export_root)
    file_project_routes._active_file_generation_jobs["file:p-continuous"] = "fgj-live"
    file_project_routes._file_generation_jobs["fgj-live"] = {
        "job_id": "fgj-live",
        "story_id": "file:p-continuous",
        "status": "running",
        "updated_at": "2099-01-01T00:00:00+00:00",
    }

    response = client.post(
        f"/file-projects/{project_id}/continuous-generation-jobs",
        json={"count": 2},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "project_generation_in_progress"
    assert submitted == []


@pytest.mark.parametrize("action", ["confirm", "discard"])
def test_manual_candidate_mutation_is_blocked_while_continuous_job_runs(
    continuous_api,
    action: str,
) -> None:
    client, export_root, _submitted = continuous_api
    project_id = _seed_project(export_root)
    store = FileProjectStore(export_root / "p-continuous")
    candidate = CandidateDraft.create(
        project_id="p-continuous",
        chapter_number=11,
        body="候选正文",
    )
    store.candidate_store.save(candidate)
    assert client.post(
        f"/file-projects/{project_id}/continuous-generation-jobs",
        json={"count": 2},
    ).status_code == 200

    response = client.post(
        f"/file-projects/{project_id}/candidates/{candidate.candidate_id}/{action}"
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "project_generation_in_progress"


def test_current_job_loads_from_disk_and_resubmits_safe_queued_job(
    continuous_api,
) -> None:
    client, export_root, submitted = continuous_api
    project_id = _seed_project(export_root)
    created = client.post(
        f"/file-projects/{project_id}/continuous-generation-jobs",
        json={"count": 2},
    ).json()
    submitted.clear()
    file_project_routes._active_continuous_generation_jobs.clear()

    response = client.get(
        f"/file-projects/{project_id}/continuous-generation-jobs/current"
    )

    assert response.status_code == 200, response.text
    assert response.json()["job_id"] == created["job_id"]
    assert len(submitted) == 1


def test_polling_registered_inflight_job_does_not_run_crash_recovery(
    continuous_api,
) -> None:
    client, export_root, _submitted = continuous_api
    project_id = _seed_project(export_root)
    created = client.post(
        f"/file-projects/{project_id}/continuous-generation-jobs",
        json={"count": 2},
    ).json()
    jobs = ContinuousGenerationJobStore(export_root / "p-continuous")
    inflight = jobs.load(created["job_id"])
    assert inflight is not None
    inflight.update(
        {
            "status": "running",
            "phase": "generating",
            "current_chapter": 11,
            "progress": "正在生成第 11 章",
        }
    )
    jobs.save(inflight)

    response = client.get(
        f"/file-projects/{project_id}/continuous-generation-jobs/{created['job_id']}"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["phase"] == "generating"


def test_stop_endpoint_is_idempotent_and_durable(continuous_api) -> None:
    client, export_root, _submitted = continuous_api
    project_id = _seed_project(export_root)
    created = client.post(
        f"/file-projects/{project_id}/continuous-generation-jobs",
        json={"count": 2},
    ).json()

    first = client.post(
        f"/file-projects/{project_id}/continuous-generation-jobs/{created['job_id']}/stop"
    )
    second = client.post(
        f"/file-projects/{project_id}/continuous-generation-jobs/{created['job_id']}/stop"
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "stopping"
    assert second.json()["stop_requested"] is True


def test_job_lookup_rejects_job_from_another_project(continuous_api) -> None:
    client, export_root, _submitted = continuous_api
    first_id = _seed_project(export_root, "p-first")
    second_id = _seed_project(export_root, "p-second")
    created = client.post(
        f"/file-projects/{first_id}/continuous-generation-jobs", json={"count": 2}
    ).json()

    response = client.get(
        f"/file-projects/{second_id}/continuous-generation-jobs/{created['job_id']}"
    )

    assert response.status_code == 404


def _generation_gate() -> GenerationConsistencyGate:
    return GenerationConsistencyGate(
        target_chapter=11,
        status="blocking",
        warnings=[
            ConsistencyWarning(
                code="SKILL_NOT_YET_ACQUIRED",
                severity="error",
                character_name="林照",
                target_chapter=11,
                message="技能尚未获得",
                expected="FUTURE_SKILL_999",
                observed={"acquired_chapter": 25},
            )
        ],
        checked_characters=["林照"],
        checked_at_boundary=10,
    )


def test_file_generation_job_pauses_before_writer_and_resumes_only_after_override(
    continuous_api,
    monkeypatch,
) -> None:
    client, export_root, submitted = continuous_api
    project_id = _seed_project(export_root)
    generation_submitted: list[tuple[object, tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        file_project_routes._file_generation_executor,
        "submit",
        lambda fn, *args, **kwargs: generation_submitted.append((fn, args, kwargs)),
    )
    monkeypatch.setattr(
        FileProjectStore,
        "rolling_fill_status",
        lambda self, target_chapter: {"status": "present", "target_chapter": target_chapter},
    )
    monkeypatch.setattr(FileProjectStore, "require_volume_detail_for_prose", lambda self, target: None)
    calls: list[bool] = []
    gate = _generation_gate()

    def fake_generate(self, *args, **kwargs):
        override = bool(kwargs.get("consistency_override"))
        calls.append(override)
        if not override:
            raise ConsistencyGateRequired(gate)
        return {"chapter_number": 11, "candidate": {"candidate_id": "candidate-11"}}

    monkeypatch.setattr(FileProjectStore, "generate_next_chapter", fake_generate)

    started = client.post(f"/file-projects/{project_id}/generation-jobs", json={})
    assert started.status_code == 200, started.text
    assert len(generation_submitted) == 1
    worker, args, kwargs = generation_submitted.pop(0)
    worker(*args, **kwargs)

    paused = client.get(
        f"/file-projects/{project_id}/generation-jobs/{started.json()['job_id']}"
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "awaiting_consistency_override"
    assert paused.json()["consistency_gate"]["target_chapter"] == 11
    assert calls == [False]

    resumed = client.post(
        f"/file-projects/{project_id}/generation-jobs/{started.json()['job_id']}/continue"
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["consistency_override"] is True
    assert len(generation_submitted) == 1
    worker, args, kwargs = generation_submitted.pop(0)
    worker(*args, **kwargs)

    completed = client.get(
        f"/file-projects/{project_id}/generation-jobs/{started.json()['job_id']}"
    )
    assert completed.json()["status"] == "completed"
    assert calls == [False, True]


def test_file_generation_consistency_cancel_releases_job_without_writer(
    continuous_api,
    monkeypatch,
) -> None:
    client, export_root, _submitted = continuous_api
    project_id = _seed_project(export_root)
    generation_submitted: list[tuple[object, tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        file_project_routes._file_generation_executor,
        "submit",
        lambda fn, *args, **kwargs: generation_submitted.append((fn, args, kwargs)),
    )
    monkeypatch.setattr(
        FileProjectStore,
        "rolling_fill_status",
        lambda self, target_chapter: {"status": "present", "target_chapter": target_chapter},
    )
    monkeypatch.setattr(FileProjectStore, "require_volume_detail_for_prose", lambda self, target: None)
    writer_calls: list[object] = []

    def fail_generate(self, *args, **kwargs):
        writer_calls.append((args, kwargs))
        raise ConsistencyGateRequired(_generation_gate())

    monkeypatch.setattr(FileProjectStore, "generate_next_chapter", fail_generate)
    started = client.post(f"/file-projects/{project_id}/generation-jobs", json={})
    worker, args, kwargs = generation_submitted.pop(0)
    worker(*args, **kwargs)

    cancelled = client.post(
        f"/file-projects/{project_id}/generation-jobs/{started.json()['job_id']}/cancel"
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["progress"] == "已返回修改，未启动写手"
    assert len(writer_calls) == 1
    assert generation_submitted == []
