"""Tests for the modular pipeline artifact records.

The user feedback after Round 5 called out that the
workbench's stage evidence column was empty because the
workflow artifacts never carried the resolved provider /
model and the consistency findings the writer stage
surfaced. The :mod:`packages.story_core.agents.pipeline_artifacts`
helpers now thread the resolved metadata through, and the
``StageArtifactRecord`` carries a ``blocking_issues`` field
so the workbench can render the same contradiction the
candidate card shows before the user clicks confirm.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from packages.story_core.agents.contracts import (
    DirectorArtifact,
    SceneBeat,
    WriterRequest,
    WriterResult,
)
from packages.story_core.agents.pipeline_artifacts import (
    record_writer_stage,
)
from packages.story_core.context.writer_context import WriterContext
from packages.story_core.persistence.workflow_artifact_store import (
    StageArtifactRecord,
    WorkflowArtifactStore,
)


def _director_artifact() -> DirectorArtifact:
    return DirectorArtifact.model_validate(
        {
            "schema_version": "director-artifact/v1",
            "chapter_number": 3,
            "chapter_title": "工整测试章",
            "chapter_goal": "测试阶段产物",
            "opening_state": "林照轻伤",
            "scene_beats": [
                {"order": 1, "location": "妖林", "action": "起身", "result": "离开"},
                {"order": 2, "location": "驿站", "action": "交付", "result": "进入"},
            ],
            "ending_state": "夜宿驿站",
            "hook": "下一章",
            "entity_requirements": [
                {"kind": "character", "name": "林昭"},
            ],
        }
    )


def _writer_context() -> WriterContext:
    return WriterContext(
        chapter_number=3,
        director_artifact=_director_artifact(),
        previous_tail="林照按住左肩喘息。",
        continuity_facts=[],
        character_cards=[{"name": "林昭", "role": "主角"}],
        entity_cards=[],
        world_rules=["时间倒流不可逆。"],
        craft_modules=[],
    )


def _writer_result(body: str = "正文。" * 1000) -> WriterResult:
    return WriterResult(body=body, notes="")


def test_writer_stage_record_carries_resolved_provider_and_model(tmp_path: Path) -> None:
    """The writer stage artifact must record the resolved
    provider / model so the workbench's stage evidence
    column shows the same metadata the prompt call log has.
    The previous round hard-coded ``"gateway"`` /
    ``"runtime/writer"`` placeholders; the workbench column
    then stayed empty in production.
    """
    store = WorkflowArtifactStore(tmp_path)
    path = record_writer_stage(
        store=store,
        job_id="chapter-3",
        result=_writer_result(),
        context=_writer_context(),
        provider="antigravity",
        model="gemini-3.1-pro-high",
    )
    loaded = StageArtifactRecord.from_dict(
        __import__("json").loads(path.read_text(encoding="utf-8"))
    )
    assert loaded.provider == "antigravity"
    assert loaded.model == "gemini-3.1-pro-high"
    assert loaded.stage_id == "writer"
    assert loaded.agent_id == "WriterAgent"
    assert loaded.status == "done"


def test_writer_stage_record_carries_blocking_consistency_findings(
    tmp_path: Path,
) -> None:
    """The writer stage artifact must record the focused
    consistency review's blocking findings so the workbench
    can render the same contradiction the candidate card
    shows before the user clicks confirm.

    The user feedback after Round 5 called out that the
    workbench's stage evidence column was empty even when
    the candidate card correctly said "通过失败" — the
    operator had no way to tell whether the failure came
    from a length gate, a fact contradiction, or a missing
    review. The new ``blocking_issues`` field lists each
    blocking finding with its code and message.
    """
    import json

    store = WorkflowArtifactStore(tmp_path)
    findings = [
        {
            "code": "chapter.length_too_short",
            "message": "正文约 200 字，低于 3800 字硬门槛。",
            "source": "deterministic",
            "blocking": True,
        },
        {
            "code": "consistency.unavailable",
            "message": "事实审稿未完成：timeout",
            "source": "consistency",
            "blocking": True,
        },
        {
            "code": "style.report_voice",
            "message": "文风偏报告体。",
            "source": "consistency",
            "blocking": False,
        },
    ]
    path = record_writer_stage(
        store=store,
        job_id="chapter-3",
        result=_writer_result(),
        context=_writer_context(),
        provider="antigravity",
        model="gemini-3.1-pro-high",
        consistency_findings=findings,
    )
    loaded = StageArtifactRecord.from_dict(
        json.loads(path.read_text(encoding="utf-8"))
    )
    codes = [issue["code"] for issue in loaded.blocking_issues]
    assert codes == [
        "chapter.length_too_short",
        "consistency.unavailable",
    ]
    messages = {issue["code"]: issue["message"] for issue in loaded.blocking_issues}
    assert "低于 3800 字" in messages["chapter.length_too_short"]
    assert "timeout" in messages["consistency.unavailable"]
    # The advisory style finding is filtered out — only
    # blocking findings belong on the workflow artifact.
    assert all(
        issue["code"] != "style.report_voice" for issue in loaded.blocking_issues
    )


def test_writer_stage_record_survives_round_trip_through_to_dict(
    tmp_path: Path,
) -> None:
    """The new ``blocking_issues`` field round-trips through
    ``to_dict`` and ``from_dict`` so the API route does not
    silently drop it on read.
    """
    import json

    store = WorkflowArtifactStore(tmp_path)
    path = record_writer_stage(
        store=store,
        job_id="chapter-3",
        result=_writer_result(),
        context=_writer_context(),
        provider="openai",
        model="gpt-5",
        consistency_findings=[
            {
                "code": "equipment.contradiction",
                "message": "新手法杖与登记装备矛盾。",
                "source": "consistency",
                "blocking": True,
            }
        ],
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["blocking_issues"] == [
        {
            "code": "equipment.contradiction",
            "message": "新手法杖与登记装备矛盾。",
            "source": "consistency",
        }
    ]
    assert payload["provider"] == "openai"
    assert payload["model"] == "gpt-5"
    # ``StageArtifactRecord.from_dict`` rebuilds the same
    # structure from the on-disk payload.
    rebuilt = StageArtifactRecord.from_dict(payload)
    assert rebuilt.blocking_issues == payload["blocking_issues"]
