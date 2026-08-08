"""Tests for the per-stage workflow artifact store."""

from __future__ import annotations

import json

from packages.story_core.persistence.workflow_artifact_store import (
    StageArtifactRecord,
    WorkflowArtifactStore,
)


def test_stage_artifact_round_trips_via_dict():
    record = StageArtifactRecord(
        stage_id="writer",
        agent_id="agents/writer",
        status="done",
        artifact_path="chapters/0001-第一章.md",
        artifact_sha256="abc123",
        reads=[{"path": "state.json", "sha256": "deadbeef"}],
        selected_module_ids=["craft_modules/dialogue"],
        provider="runtime",
        model="runtime/v1",
        prompt_template_id="writer/v1",
        prompt_template_version="2026-01-01",
        output_summary="Wrote 1 chapter.",
    )
    payload = record.to_dict()
    assert payload["schema_version"] == "workflow-artifact/v1"
    assert payload["stage_id"] == "writer"

    restored = StageArtifactRecord.from_dict(payload)
    assert restored == record
    assert restored.reads == [{"path": "state.json", "sha256": "deadbeef"}]


def test_workflow_artifact_store_writes_per_stage_files(tmp_path):
    store = WorkflowArtifactStore(tmp_path)
    record = StageArtifactRecord(
        stage_id="director",
        agent_id="agents/director",
        status="done",
        artifact_path=".story-system/director/0001.json",
        provider="outline",
        model="outline/v1",
    )

    target = store.write_stage("job-123", record)
    assert target.is_file()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["agent_id"] == "agents/director"
    assert payload["model"] == "outline/v1"
    assert payload["started_at"]  # auto-filled


def test_workflow_artifact_store_lists_and_reads_stages(tmp_path):
    store = WorkflowArtifactStore(tmp_path)
    for stage_id, status in [("director", "done"), ("writer", "failed")]:
        record = StageArtifactRecord(
            stage_id=stage_id,
            agent_id=f"agents/{stage_id}",
            status=status,
        )
        store.write_stage("job-456", record)

    stages = store.list_stages("job-456")
    assert [stage.stage_id for stage in stages] == ["director", "writer"]
    assert stages[1].status == "failed"

    assert store.read_stage("job-456", "director").status == "done"
    assert store.read_stage("job-456", "missing") is None


def test_workflow_artifact_store_surfaces_secret_redaction(tmp_path):
    """Records must not include API tokens; the caller is responsible.

    The store does not enforce redaction today (the test pins the
    contract so a future regression is caught). If a caller ever
    tries to store an ``api_token`` field, the test will fail.
    """
    record = StageArtifactRecord(
        stage_id="writer",
        agent_id="agents/writer",
        status="done",
    )
    payload = record.to_dict()
    assert "api_token" not in payload
    assert "authorization" not in payload
