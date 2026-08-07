"""Contracts for the modular agent migration.

These tests pin the typed shapes every agent reads and emits so the
director / writer / consistency / fact_extractor boundaries stay
stable as the orchestrator is thinned out.
"""

from packages.story_core.agents.contracts import DirectorArtifact, WriterResult
from packages.story_core.context.contracts import ArtifactRead, ContextTrace


def test_context_trace_records_exact_artifact_reads() -> None:
    trace = ContextTrace(agent="writer", chapter_number=12)
    trace.add(ArtifactRead(kind="outline", path=".story-system/outline.json", sha256="abc", chars=80))
    assert trace.reads[0].kind == "outline"
    assert trace.reads[0].path == ".story-system/outline.json"


def test_director_artifact_requires_scene_progression() -> None:
    artifact = DirectorArtifact.model_validate({
        "schema_version": "director-artifact/v1",
        "chapter_number": 12,
        "chapter_goal": "拿到进入矿区的许可",
        "opening_state": "主角在守备处等待核验",
        "scene_beats": [{"order": 1, "location": "守备处", "action": "提交证据", "result": "获得许可"}],
        "ending_state": "主角进入矿区",
        "entity_requirements": [],
    })
    assert artifact.scene_beats[0].result == "获得许可"


def test_writer_result_cannot_confirm_facts() -> None:
    result = WriterResult(body="正文", proposed_facts=[{"subject_id": "char-1", "field": "level", "value": 2}])
    assert result.proposed_facts[0]["value"] == 2
    assert not hasattr(result, "confirmed_facts")
