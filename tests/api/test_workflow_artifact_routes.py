"""Tests for the workflow artifact API routes.

The user feedback after Task 13 flagged that
``WorkflowArtifactStore`` was implemented and unit-tested
but the API did not expose it. These tests pin the new
``/file-projects/<id>/workflow-artifacts`` routes that let
the workbench list and read per-stage records from
``.story-system/workflow/<job_id>/`` so the audit panel
shows the user what each modular-agent stage saw and
produced.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from packages.story_core.persistence.workflow_artifact_store import (
    StageArtifactRecord,
    WorkflowArtifactStore,
)


client = TestClient(app)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _create_project(tmp_path: Path, monkeypatch, project_id: str) -> Path:
    export_root = tmp_path / "exported-projects"
    project_root = export_root / project_id
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    _write_json(
        project_root / ".story-system" / "MASTER_SETTING.json",
        {"project": {"title": project_id}},
    )
    _write_json(project_root / ".webnovel" / "project.json", {"project_id": project_id})
    _write_json(project_root / ".webnovel" / "state.json", {"story_id": project_id})
    return project_root


def _seed_workflow_artifacts(project_root: Path, job_id: str) -> None:
    workflow_store = WorkflowArtifactStore(project_root)
    workflow_store.write_stage(
        job_id,
        StageArtifactRecord(
            stage_id="director",
            agent_id="DirectorAgent",
            status="done",
            elapsed_ms=1234,
            artifact_path=str(
                project_root / ".story-system" / "director" / "0001.json"
            ),
            artifact_sha256="deadbeef",
            reads=[
                {"kind": "volume", "id": "vol-1"},
                {"kind": "outline", "id": "chapter-0001"},
            ],
            selected_entity_ids=["char-linzhao"],
            selected_module_ids=[],
            provider="gateway",
            model="planner/v1",
            prompt_template_id="director-plan",
            prompt_template_version="v1",
            output_summary="chapter_goal='上山' beats=1 requirements=1",
            error="",
        ),
    )
    workflow_store.write_stage(
        job_id,
        StageArtifactRecord(
            stage_id="writer",
            agent_id="WriterAgent",
            status="done",
            elapsed_ms=4567,
            artifact_path="",
            artifact_sha256="cafebabe",
            reads=[
                {"kind": "director-artifact", "id": "chapter-0001"},
                {"kind": "character", "id": "林昭"},
            ],
            selected_entity_ids=[],
            selected_module_ids=["craft_modules/dialogue"],
            provider="gateway",
            model="writer/v1",
            prompt_template_id="writer-body",
            prompt_template_version="v2",
            output_summary="body_chars=1234",
            error="",
        ),
    )
    workflow_store.write_stage(
        job_id,
        StageArtifactRecord(
            stage_id="fact-extractor",
            agent_id="FactExtractor",
            status="done",
            elapsed_ms=89,
            artifact_path="",
            artifact_sha256="",
            reads=[],
            selected_entity_ids=[],
            selected_module_ids=[],
            provider="",
            model="",
            prompt_template_id="",
            prompt_template_version="",
            output_summary="entity_additions=0",
            error="",
        ),
    )


# --- Tests ---------------------------------------------------------------


def test_list_workflow_artifacts_returns_per_stage_records(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = _create_project(
        tmp_path, monkeypatch, "workflow-list"
    )
    _seed_workflow_artifacts(project_root, "job-list-1")

    response = client.get(
        "/file-projects/file:workflow-list/workflow-artifacts"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "file-workflow-artifacts/v1"
    assert payload["project_id"] == "file:workflow-list"
    assert len(payload["items"]) == 1
    job = payload["items"][0]
    assert job["job_id"] == "job-list-1"
    stage_ids = [stage["stage_id"] for stage in job["stages"]]
    assert stage_ids == ["director", "fact-extractor", "writer"]
    director = next(
        stage for stage in job["stages"] if stage["stage_id"] == "director"
    )
    assert director["agent_id"] == "DirectorAgent"
    assert director["status"] == "done"
    assert director["elapsed_ms"] == 1234
    assert director["selected_entity_ids"] == ["char-linzhao"]
    assert director["reads"] == [
        {"kind": "volume", "id": "vol-1"},
        {"kind": "outline", "id": "chapter-0001"},
    ]
    assert director["output_summary"].startswith("chapter_goal=")


def test_list_workflow_artifacts_filters_by_job_id(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = _create_project(
        tmp_path, monkeypatch, "workflow-filter"
    )
    _seed_workflow_artifacts(project_root, "job-keep")
    _seed_workflow_artifacts(project_root, "job-skip")

    response = client.get(
        "/file-projects/file:workflow-filter/workflow-artifacts?job_id=job-keep"
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    assert payload["items"][0]["job_id"] == "job-keep"


def test_list_workflow_artifacts_empty_when_no_jobs(
    tmp_path: Path, monkeypatch
) -> None:
    _create_project(tmp_path, monkeypatch, "workflow-empty")

    response = client.get(
        "/file-projects/file:workflow-empty/workflow-artifacts"
    )
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_get_workflow_artifact_returns_full_record(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = _create_project(
        tmp_path, monkeypatch, "workflow-get"
    )
    _seed_workflow_artifacts(project_root, "job-get-1")

    response = client.get(
        "/file-projects/file:workflow-get/workflow-artifacts/job-get-1/writer"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "file-workflow-artifact/v1"
    assert payload["project_id"] == "file:workflow-get"
    assert payload["job_id"] == "job-get-1"
    assert payload["stage_id"] == "writer"
    stage = payload["stage"]
    assert stage["agent_id"] == "WriterAgent"
    assert stage["elapsed_ms"] == 4567
    assert stage["artifact_sha256"] == "cafebabe"
    assert stage["selected_module_ids"] == ["craft_modules/dialogue"]
    assert stage["output_summary"].startswith("body_chars=")


def test_get_workflow_artifact_returns_404_for_missing_stage(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = _create_project(
        tmp_path, monkeypatch, "workflow-missing"
    )
    _seed_workflow_artifacts(project_root, "job-missing-1")

    response = client.get(
        "/file-projects/file:workflow-missing"
        "/workflow-artifacts/job-missing-1/does-not-exist"
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "workflow_artifact_not_found"


def test_workflow_artifact_routes_return_404_for_unknown_project(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR",
        str(tmp_path / "exported-projects"),
    )

    list_response = client.get(
        "/file-projects/file:missing/workflow-artifacts"
    )
    get_response = client.get(
        "/file-projects/file:missing/workflow-artifacts/job-1/writer"
    )
    assert list_response.status_code == 404
    assert list_response.json()["detail"] == "file_project_not_found"
    assert get_response.status_code == 404
    assert get_response.json()["detail"] == "file_project_not_found"


def test_workflow_artifact_store_rejects_path_traversal_ids(tmp_path: Path) -> None:
    """The on-disk store must reject ids that escape the workflow dir."""
    from packages.story_core.persistence.workflow_artifact_store import (
        _validate_id,
        WorkflowArtifactStore,
    )

    store = WorkflowArtifactStore(tmp_path)
    record = StageArtifactRecord(stage_id="writer", agent_id="WriterAgent", status="done")

    for bad in ("..", "../etc", "with/slash", "with\\slash", "abs/path", ""):
        with pytest.raises(ValueError):
            _validate_id("job_id", bad)

    with pytest.raises(ValueError):
        store.write_stage("../../etc/passwd", record)
    with pytest.raises(ValueError):
        store.write_stage("job-1", StageArtifactRecord(stage_id="../escape", agent_id="x", status="done"))


def test_workflow_artifact_routes_reject_path_traversal_job_id(
    tmp_path: Path, monkeypatch
) -> None:
    """The list route must 400 on a job_id that escapes the workflow dir."""
    _create_project(tmp_path, monkeypatch, "file-traversal-fixture")

    # ``..`` is a path component FastAPI will normally route;
    # percent-encoding the dot is enough to slip the request
    # through path parsing and into the handler.
    response = client.get(
        "/file-projects/file-traversal-fixture/workflow-artifacts?job_id=..%2Fetc"
    )
    assert response.status_code == 400
    assert response.json()["detail"].startswith("workflow_artifact_invalid_job_id")
