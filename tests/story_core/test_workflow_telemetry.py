import json

from packages.story_core.workflow_telemetry import append_workflow_telemetry, workflow_telemetry_record


def test_workflow_telemetry_record_extracts_layered_review_signals():
    quality_report = {
        "ok": False,
        "writing_review": {"pass": False, "issues": ["draft issue"]},
        "critical_review": {
            "profile_id": "game_webnovel",
            "issues": ["hard issue", "soft issue"],
            "scores": {"pov_boundary": 5, "protagonist_speech": 6, "npc_boundary": 8},
        },
        "hook_review": {
            "hook_meta": {"type": "choice", "strength": "strong", "content": "choose now"},
            "scores": {"hook_landed": 8},
        },
        "pacing_review": {"scores": {"pacing_stagnation": 4}, "issues": ["stalled"]},
        "beats_review": {"diagnostics": {"total_beats": 4, "covered": 2, "partial": 1, "missing": 1}},
        "ai_flavor_review": {
            "scores": {"ai_flavor": 6},
            "metrics": {"formula_count": 2, "abstract_count": 4, "concrete_density": 0.21},
            "issues": ["AI味偏重"],
        },
    }

    record = workflow_telemetry_record(
        chapter=3,
        chapter_title="Boundary Test",
        operation="generate",
        project_id="p-file",
        story_id="s-file",
        quality_report=quality_report,
        timestamp="2026-05-09T00:00:00Z",
    )

    assert record["schema_version"] == "workflow-log/v1"
    assert record["chapter"] == 3
    assert record["profile"] == "game_webnovel"
    assert record["requires_revision"] is True
    assert record["hard_count"] == 2
    assert record["soft_count"] == 2
    assert record["failed_scores"] == ["ai_flavor", "pacing_stagnation", "pov_boundary", "protagonist_speech"]
    assert record["beats_completion"] == 0.625
    assert record["hook_type"] == "choice"
    assert record["ai_flavor_score"] == 6
    assert record["ai_formula_count"] == 2
    assert record["ai_abstract_count"] == 4
    assert record["ai_concrete_density"] == 0.21


def test_append_workflow_telemetry_writes_jsonl(tmp_path):
    output_path = tmp_path / "chapter_exports" / "workflow_log.jsonl"

    path = append_workflow_telemetry(
        chapter=1,
        chapter_title="First",
        operation="rewrite",
        project_id="p-file",
        story_id="s-file",
        output_path=output_path,
        quality_report={"ok": True, "writing_review": {"pass": True, "issues": []}},
    )

    assert path == output_path
    lines = output_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["chapter"] == 1
    assert record["operation"] == "rewrite"
    assert record["requires_revision"] is False
