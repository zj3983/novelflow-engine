from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects as file_project_routes
from packages.story_core.file_project_store import FileProjectStore


@pytest.fixture
def volume_api(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, export_root


def _seed_project(export_root: Path, *, current_chapter: int = 50) -> str:
    project_root = export_root / "p-volume-api"
    (project_root / ".story-system" / "chapters").mkdir(parents=True)
    (project_root / ".story-system" / "reviews").mkdir(parents=True)
    (project_root / ".webnovel").mkdir(parents=True)
    (project_root / "chapters").mkdir(parents=True)
    project = {
        "project_id": "p-volume-api",
        "title": "Volume API",
        "active_story_id": "s-volume-api",
        "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        "character_profiles": [],
    }
    state = {
        "story_id": "s-volume-api",
        "current_chapter": current_chapter,
        "world_facts": [],
        "characters": [],
    }
    (project_root / ".webnovel" / "project.json").write_text(
        json.dumps(project), encoding="utf-8"
    )
    (project_root / ".webnovel" / "state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )
    (project_root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": project,
                "state": state,
            }
        ),
        encoding="utf-8",
    )
    return "file:p-volume-api"


def test_get_volume_workflow_returns_store_envelope(volume_api, monkeypatch) -> None:
    client, export_root = volume_api
    project_id = _seed_project(export_root)
    expected = {
        "schema_version": "volume-workflow/v1",
        "target_chapter": 51,
        "status": "volume_plan_ready",
        "detail_status": "missing",
        "next_action": "generate_volume_detail",
        "volume_id": "volume-2",
        "volume_range": [51, 100],
    }
    monkeypatch.setattr(
        FileProjectStore,
        "volume_workflow_status",
        lambda self, target_chapter: {**expected, "target_chapter": target_chapter},
    )

    response = client.get(
        f"/file-projects/{project_id}/outline/volume-workflow",
        params={"target_chapter": 51},
    )

    assert response.status_code == 200, response.text
    assert response.json() == expected


def test_get_volume_workflow_validates_project_and_chapter(volume_api) -> None:
    client, export_root = volume_api
    project_id = _seed_project(export_root)

    assert client.get(
        "/file-projects/file:missing/outline/volume-workflow",
        params={"target_chapter": 1},
    ).status_code == 404
    assert client.get(
        f"/file-projects/{project_id}/outline/volume-workflow",
        params={"target_chapter": 0},
    ).status_code == 422


def test_post_next_volume_uses_planner_without_generating_detail(volume_api, monkeypatch) -> None:
    client, export_root = volume_api
    project_id = _seed_project(export_root)
    planner = object()
    monkeypatch.setattr(file_project_routes, "outline_planning_generator", planner)
    calls: list[dict] = []

    def fake_design(self, generator, *, guidance=""):
        calls.append({"generator": generator, "guidance": guidance})
        return {
            "schema_version": "volume-design/v1",
            "status": "volume_plan_ready",
            "next_action": "generate_volume_detail",
            "volume_id": "volume-2",
            "volume_range": [51, 100],
            "created": True,
        }

    monkeypatch.setattr(FileProjectStore, "design_next_volume", fake_design)
    monkeypatch.setattr(
        FileProjectStore,
        "generate_volume_detail",
        lambda *args, **kwargs: pytest.fail("next-volume endpoint must not generate detail"),
    )

    response = client.post(
        f"/file-projects/{project_id}/outline/volumes/next",
        json={"guidance": "Keep the conflict local."},
    )

    assert response.status_code == 200, response.text
    assert response.json()["created"] is True
    assert calls == [{"generator": planner, "guidance": "Keep the conflict local."}]


def test_post_volume_detail_returns_real_result_and_passes_guidance(volume_api, monkeypatch) -> None:
    client, export_root = volume_api
    project_id = _seed_project(export_root)
    planner = object()
    monkeypatch.setattr(file_project_routes, "outline_planning_generator", planner)
    calls: list[dict] = []

    def fake_detail(self, generator, *, volume_id, guidance=""):
        calls.append(
            {"generator": generator, "volume_id": volume_id, "guidance": guidance}
        )
        return {
            "schema_version": "volume-detail-generation/v1",
            "volume_id": volume_id,
            "volume_range": [51, 100],
            "detail_status": "complete",
            "completed_chapters": 50,
            "total_chapters": 50,
            "batches": [
                {"id": "0051-0065", "status": "completed", "resumed": True}
            ],
        }

    monkeypatch.setattr(FileProjectStore, "generate_volume_detail", fake_detail)
    monkeypatch.setattr(
        FileProjectStore,
        "design_next_volume",
        lambda *args, **kwargs: pytest.fail("detail endpoint must not design a volume"),
    )

    response = client.post(
        f"/file-projects/{project_id}/outline/volumes/volume-2/detail",
        json={"guidance": "Preserve the existing ending."},
    )

    assert response.status_code == 200, response.text
    assert response.json()["batches"] == [
        {"id": "0051-0065", "status": "completed", "resumed": True}
    ]
    assert calls == [
        {
            "generator": planner,
            "volume_id": "volume-2",
            "guidance": "Preserve the existing ending.",
        }
    ]


def test_volume_write_endpoint_preserves_model_failure_detail(volume_api, monkeypatch) -> None:
    client, export_root = volume_api
    project_id = _seed_project(export_root)

    def fail_detail(self, generator, *, volume_id, guidance=""):
        raise ValueError("volume_detail_generation_failed:RuntimeError:quota_exhausted")

    monkeypatch.setattr(FileProjectStore, "generate_volume_detail", fail_detail)
    response = client.post(
        f"/file-projects/{project_id}/outline/volumes/volume-2/detail",
        json={},
    )

    assert response.status_code == 502, response.text
    assert response.json()["detail"] == (
        "volume_detail_generation_failed:RuntimeError:quota_exhausted"
    )


def test_next_volume_endpoint_preserves_non_validation_model_failure(
    volume_api,
    monkeypatch,
) -> None:
    client, export_root = volume_api
    project_id = _seed_project(export_root)

    def fail_design(self, generator, *, guidance=""):
        raise RuntimeError("planner quota exhausted")

    monkeypatch.setattr(FileProjectStore, "design_next_volume", fail_design)
    response = client.post(
        f"/file-projects/{project_id}/outline/volumes/next",
        json={},
    )

    assert response.status_code == 502, response.text
    assert response.json()["detail"] == (
        "next_volume_generation_failed:RuntimeError:planner quota exhausted"
    )


@pytest.mark.parametrize(
    ("status", "expected_detail"),
    [
        ("volume_missing", "next_volume_required:51"),
        ("volume_plan_ready", "volume_detail_required:volume-2"),
        ("detail_partial", "volume_detail_incomplete:volume-2"),
    ],
)
def test_body_generation_job_uses_precise_volume_gate_before_job_creation(
    volume_api,
    monkeypatch,
    status,
    expected_detail,
) -> None:
    client, export_root = volume_api
    project_id = _seed_project(export_root)
    monkeypatch.setattr(
        FileProjectStore,
        "volume_workflow_status",
        lambda self, target_chapter: {
            "schema_version": "volume-workflow/v1",
            "target_chapter": target_chapter,
            "status": status,
            "detail_status": "missing",
            "next_action": "design_next_volume",
            "volume_id": None if status == "volume_missing" else "volume-2",
            "volume_range": None if status == "volume_missing" else [51, 100],
        },
    )

    response = client.post(f"/file-projects/{project_id}/generation-jobs", json={})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == expected_detail
    jobs_dir = export_root / "p-volume-api" / ".story-system" / "generation-jobs"
    assert not jobs_dir.exists() or not list(jobs_dir.glob("fgj-*.json"))


def test_existing_chapter_rewrite_does_not_require_next_volume_detail(
    volume_api,
    monkeypatch,
) -> None:
    client, export_root = volume_api
    project_id = _seed_project(export_root, current_chapter=50)

    def reject_gate(self, chapter_number):
        pytest.fail(
            f"existing chapter rewrite must not check volume detail: {chapter_number}"
        )

    monkeypatch.setattr(
        FileProjectStore,
        "require_volume_detail_for_prose",
        reject_gate,
    )
    monkeypatch.setattr(
        file_project_routes._file_generation_executor,
        "submit",
        lambda *args, **kwargs: None,
    )

    response = client.post(
        f"/file-projects/{project_id}/generation-jobs",
        json={"chapter_number": 50},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"


def test_legacy_generate_next_uses_same_precise_volume_gate(volume_api, monkeypatch) -> None:
    client, export_root = volume_api
    project_id = _seed_project(export_root)
    monkeypatch.setattr(
        FileProjectStore,
        "volume_workflow_status",
        lambda self, target_chapter: {
            "schema_version": "volume-workflow/v1",
            "target_chapter": target_chapter,
            "status": "volume_plan_ready",
            "detail_status": "missing",
            "next_action": "generate_volume_detail",
            "volume_id": "volume-2",
            "volume_range": [51, 100],
        },
    )

    response = client.post(f"/file-projects/{project_id}/generate-next", json={})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "volume_detail_required:volume-2"
