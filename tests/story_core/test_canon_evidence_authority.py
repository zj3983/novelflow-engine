"""Issue #46: deterministic adversarial fixtures, never a real-model benchmark."""

from copy import deepcopy
from dataclasses import dataclass

import pytest

from packages.story_core.agents.consistency import focused_consistency_review
from packages.story_core.agents.contracts import DirectorArtifact
from packages.story_core.canon.registry import CanonRegistry
from packages.story_core.canon.review_snapshot import build_canon_review_snapshot
from packages.story_core.continuity.snapshot import ChapterSnapshot
from packages.story_core.continuity.store import ContinuityStore


@dataclass(frozen=True)
class EvidenceCase:
    name: str
    origin: str
    source: str
    evidence: str
    expected_blocking: bool
    blocking: bool = True
    code: str = "canon.location_conflict"
    bootstrap: bool = False


CASES = [
    EvidenceCase("confirmed_source", "confirmed_snapshot", "canon.fact:0", "", True),
    EvidenceCase("confirmed_quote", "confirmed_snapshot", "consistency", "林照仍在东城修理铺。", True),
    EvidenceCase("author_requirement", "author_requirement", "author_requirement:0", "", True),
    EvidenceCase("writer_summary", "writer_summary", "context:writer_summary", "林照已到码头。", False),
    EvidenceCase("director_summary", "director_summary", "context:director_plan", "林照已到南山。", False),
    EvidenceCase("spoofed_context_source", "writer_summary", "context:spoofed", "林照已到京城。", False),
    EvidenceCase("stale_summary", "stale_summary", "context:stale", "林照仍在旧村。", False),
    EvidenceCase("future_state", "future_state", "continuity_snapshot:0003", "林照抵达未来王城。", False),
    EvidenceCase("subjective_statement", "character_statement", "consistency", "伙计说他相信林照已经到了海边。", False),
    EvidenceCase("director_intent", "director_plan", "director_plan", "林照仍在东城修理铺。", False),
    EvidenceCase("unknown_source", "unknown", "canon.fact:999", "", False),
    EvidenceCase("valid_id_forged_quote", "forged_quote", "canon.fact:0", "林照已到码头。", False),
    EvidenceCase("warning_keeps_warning", "confirmed_snapshot", "canon.fact:0", "林照仍在东城修理铺。", False, blocking=False),
    EvidenceCase("style_keeps_warning", "confirmed_snapshot", "canon.fact:0", "", False, code="style.repetition"),
    EvidenceCase("bootstrap_context", "writer_summary", "context:writer_summary", "林照已到码头。", False, bootstrap=True),
]


def _snapshot(tmp_path, *, bootstrap, confirmed_source=None):
    if not bootstrap:
        ContinuityStore(tmp_path).write_snapshot(ChapterSnapshot(
            chapter_number=1, candidate_id="synthetic-confirmed-1", operation="generate",
            confirmed_at="2026-10-25T00:00:00+08:00", body_sha256="synthetic-only",
            body_chars=3600, state_after={
                "current_chapter": 1, "characters": [], "world_facts": [],
                "continuity_facts": [{"subject": "林照", "field": "位置", "value": "东城修理铺",
                                      **({"source": confirmed_source} if confirmed_source else {}),
                                      "chapter_number": 1, "evidence": "林照仍在东城修理铺。"}],
            },
        ))
    context = [
        {"subject": "林照", "field": "位置", "value": "码头", "source": "writer_summary",
         "chapter_number": 1, "evidence": "林照已到码头。"},
        {"subject": "林照", "field": "位置", "value": "南山", "source": "director_plan",
         "chapter_number": 1, "evidence": "林照已到南山。"},
        {"subject": "林照", "field": "位置", "value": "京城", "source": "continuity_snapshot:0001",
         "chapter_number": 1, "evidence": "林照已到京城。"},
        {"subject": "林照", "field": "位置", "value": "旧村", "source": "continuity_snapshot:0000",
         "chapter_number": 0, "evidence": "林照仍在旧村。"},
        {"subject": "林照", "field": "位置", "value": "未来王城", "source": "continuity_snapshot:0003",
         "chapter_number": 3, "evidence": "林照抵达未来王城。"},
    ]
    snapshot = build_canon_review_snapshot(project_root=tmp_path, chapter_number=2,
                                         registry=CanonRegistry(), continuity_facts=context)
    snapshot["author_requirements"] = ["不得凭空复活已故人物。"]
    return snapshot, context


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_model_findings_require_established_evidence(tmp_path, record_property, case):
    snapshot, context = _snapshot(tmp_path, bootstrap=case.bootstrap)
    source = case.source
    if source.startswith("context:"):
        value = {"writer_summary": "码头", "director_plan": "南山", "spoofed": "京城", "stale": "旧村"}[source.split(":")[1]]
        index = next(i for i, fact in enumerate(snapshot["facts"]) if fact["value"] == value)
        source = f"canon.fact:{index}"
    issue = {"code": case.code, "message": "核对当前位置和证据来源。", "source": source,
             "evidence": case.evidence, "blocking": case.blocking}

    class SyntheticRuntime:
        def complete(self, request):
            return {"issues": [issue]}

    original = deepcopy(snapshot)
    findings = focused_consistency_review(
        "林照仍在东城修理铺。伙计说他相信林照已经到了海边。",
        director_artifact=DirectorArtifact(chapter_number=2, chapter_title="留店", chapter_goal="核对旧账",
                                           opening_state="在店中", ending_state="留在店中", scene_beats=[], hook="明日查账"),
        active_facts=context, canon_snapshot=snapshot, runtime=SyntheticRuntime(),
    )
    assert len(findings) == 1
    record_property("evidence_origin", case.origin)
    record_property("snapshot_version", snapshot["schema_version"])
    record_property("as_of_chapter", snapshot["as_of_chapter"])
    record_property("evidence_source", source)
    record_property("expected_blocking", str(case.expected_blocking))
    record_property("decision_blocking", str(findings[0].blocking))
    assert snapshot == original
    assert "未来王城" not in str(snapshot)
    assert findings[0].blocking is case.expected_blocking


def test_confirmed_legacy_fact_keeps_authority_despite_context_origin(tmp_path):
    snapshot, _ = _snapshot(tmp_path, bootstrap=False, confirmed_source="writer_context")

    class Runtime:
        def complete(self, request):
            return {"issues": [{"code": "canon.location_conflict", "message": "正文与已确认位置冲突。",
                                "source": "canon.fact:0", "blocking": True}]}

    findings = focused_consistency_review(
        "林照已到码头。", director_artifact=DirectorArtifact(chapter_number=2, chapter_title="离店",
            chapter_goal="查账", opening_state="在店中", ending_state="在码头", scene_beats=[], hook="账本"),
        active_facts=[], canon_snapshot=snapshot, runtime=Runtime(),
    )
    assert findings[0].blocking is True
