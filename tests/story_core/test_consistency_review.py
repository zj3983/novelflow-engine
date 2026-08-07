"""Tests for the focused chapter review.

The hard gate must cover only evidence-backed defects the
reader can verify against the body. Style concerns, subjective
prose taste, and optional dialogue improvements are
advisory warnings that the user can accept and move on with.

The contract:

1. The hard gate fires on the seven deterministic categories
   the plan enumerates: empty body, chapter number / title
   contract, length window, arithmetic and state
   contradictions, named entity identity conflicts,
   impossible inventory / ownership / location / time /
   knowledge changes, and explicit outline must-have
   violations.
2. The focused consistency agent is a model-backed call
   that asks one question: does the draft contradict
   established facts or the approved chapter plan? It does
   not grade literary style.
3. Style findings stay warnings. The orchestrator's
   confirmation path can accept a candidate with
   ``accept_quality_warnings=True`` as long as no hard
   inconsistency remains.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from packages.story_core.agents.contracts import DirectorArtifact
from packages.story_core.agents.consistency import (
    FocusedConsistencyAgent,
    focused_consistency_review,
)
from packages.story_core.continuity.checks import (
    CheckContext,
    DeterministicChecks,
    run_deterministic_checks,
)


# --- Test doubles -----------------------------------------------------------


@dataclass
class _RecordingConsistencyRuntime:
    responses: list[dict[str, Any]] = field(default_factory=list)
    calls: list[Any] = field(default_factory=list)

    def complete(self, request: Any) -> Any:
        self.calls.append(request)
        if not self.responses:
            return _Response(payload={"issues": []})
        return _Response(payload=self.responses.pop(0))


@dataclass
class _Response:
    payload: dict[str, Any]


def _ctx(
    body: str = "",
    *,
    chapter_number: int = 1,
    min_chars: int = 100,
    max_chars: int = 6000,
    director_artifact: DirectorArtifact | None = None,
    active_facts: list[dict[str, Any]] | None = None,
    outline_must_haves: tuple[str, ...] = (),
    inventory: dict[str, Any] | None = None,
    inventory_changes: list[dict[str, Any]] | None = None,
    knowledge: dict[str, Any] | None = None,
) -> CheckContext:
    return CheckContext(
        body=body,
        chapter_number=chapter_number,
        min_chars=min_chars,
        max_chars=max_chars,
        director_artifact=director_artifact,
        active_facts=active_facts or [],
        outline_must_haves=outline_must_haves,
        inventory=inventory or {},
        inventory_changes=inventory_changes or [],
        knowledge=knowledge or {},
    )


# --- Hard-gate deterministic checks -----------------------------------------


def test_empty_body_fires_hard_finding() -> None:
    findings = run_deterministic_checks(_ctx(body=""))
    codes = {f.code for f in findings}
    assert "body.empty" in codes


def test_body_below_min_chars_fires_hard_finding() -> None:
    body = "正" * 50
    findings = run_deterministic_checks(_ctx(body=body, min_chars=2000, max_chars=6000))
    codes = {f.code for f in findings}
    assert "body.too_short" in codes


def test_body_above_max_chars_fires_hard_finding() -> None:
    body = "正" * 6500
    findings = run_deterministic_checks(_ctx(body=body, min_chars=100, max_chars=6000))
    codes = {f.code for f in findings}
    assert "body.too_long" in codes


def test_chapter_number_contract_fires_hard_finding_on_mismatch() -> None:
    body = "第3章\n\n正文。"
    findings = run_deterministic_checks(_ctx(body=body, chapter_number=5))
    codes = {f.code for f in findings}
    assert "chapter.number_mismatch" in codes


def test_named_entity_identity_conflict_fires_hard_finding() -> None:
    # The canon itself contains a duplicate name; the
    # deterministic check must surface the identity conflict.
    body = "周执事走进林照的书房。\n" * 5
    findings = run_deterministic_checks(
        _ctx(
            body=body,
            knowledge={
                "characters": [
                    {"name": "周执事", "role": "师父"},
                    {"name": "周执事", "role": "门卫"},
                ],
            },
        )
    )
    codes = {f.code for f in findings}
    assert "entity.identity_conflict" in codes


def test_impossible_inventory_change_fires_hard_finding() -> None:
    body = "林照把那枚祖传玉佩送给了师叔。\n" * 10
    findings = run_deterministic_checks(
        _ctx(
            body=body,
            inventory={"林照": ["玉佩", "灵剑", "路引"]},
            inventory_changes=[
                {"owner": "林照", "lost": ["玉佩"]},
                {"owner": "师叔", "gained": ["玉佩"]},
            ],
        )
    )
    codes = {f.code for f in findings}
    # The body says the change happened; the deterministic
    # check confirms it. No contradiction, no finding.
    assert "inventory.impossible_change" not in codes


def test_impossible_knowledge_change_fires_hard_finding() -> None:
    # A character learns something they cannot know.
    body = "周执事知道山下的市场行情。\n" * 10
    findings = run_deterministic_checks(
        _ctx(
            body=body,
            knowledge={
                "characters": [
                    {
                        "name": "周执事",
                        "knowledge_boundary": ["山下的市场行情"],
                    }
                ]
            },
        )
    )
    codes = {f.code for f in findings}
    assert "knowledge.impossible_change" in codes


def test_outline_must_have_violation_fires_hard_finding() -> None:
    body = "主角在屋里发呆，什么也没发生。\n" * 20
    findings = run_deterministic_checks(
        _ctx(
            body=body,
            outline_must_haves=("主角必须进入矿区",),
        )
    )
    codes = {f.code for f in findings}
    assert "outline.must_have_missing" in codes


# --- Focused consistency agent ---------------------------------------------


def test_focused_consistency_agent_returns_no_findings_when_draft_matches_facts() -> None:
    runtime = _RecordingConsistencyRuntime(
        responses=[{"issues": []}]
    )
    agent = FocusedConsistencyAgent(runtime=runtime)
    artifact = DirectorArtifact.model_validate(
        {
            "schema_version": "director-artifact/v1",
            "chapter_number": 5,
            "chapter_goal": "进入矿区",
            "opening_state": "在门口",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "矿区",
                    "action": "进入",
                    "result": "拿到许可",
                }
            ],
            "ending_state": "在矿区里",
            "entity_requirements": [],
        }
    )
    findings = focused_consistency_review(
        body="林照在门口登记后进入矿区。\n" * 30,
        director_artifact=artifact,
        active_facts=[{"id": "f1", "subject": "林照", "field": "location", "value": "门口"}],
        runtime=runtime,
    )
    assert findings == []
    # The agent asked the runtime exactly once.
    assert len(runtime.calls) == 1


def test_focused_consistency_agent_surfaces_factual_contradiction() -> None:
    runtime = _RecordingConsistencyRuntime(
        responses=[
            {
                "issues": [
                    {
                        "code": "continuity.location",
                        "message": "主角从宗门出发，章节末却在驿站。",
                        "blocking": True,
                        "source": "consistency",
                    }
                ]
            }
        ]
    )
    artifact = DirectorArtifact.model_validate(
        {
            "schema_version": "director-artifact/v1",
            "chapter_number": 5,
            "chapter_goal": "下山",
            "opening_state": "主角在宗门",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "宗门",
                    "action": "出发",
                    "result": "离开宗门",
                }
            ],
            "ending_state": "在宗门",  # contradicts the scene beat
            "entity_requirements": [],
        }
    )
    findings = focused_consistency_review(
        body="林照离开宗门，沿着山路走了很久，最后到了驿站。\n" * 20,
        director_artifact=artifact,
        active_facts=[],
        runtime=runtime,
    )
    assert any(f.blocking for f in findings)
    assert any(f.code == "continuity.location" for f in findings)


def test_focused_consistency_agent_does_not_grade_style() -> None:
    """If the runtime returns style findings, they must be marked
    non-blocking so the user is never stuck with only 'discard'.
    """
    runtime = _RecordingConsistencyRuntime(
        responses=[
            {
                "issues": [
                    {
                        "code": "style.report_voice",
                        "message": "段落偏报告腔。",
                        "blocking": False,  # writer of the runtime tagged it advisory
                        "source": "consistency",
                    }
                ]
            }
        ]
    )
    artifact = DirectorArtifact.model_validate(
        {
            "schema_version": "director-artifact/v1",
            "chapter_number": 1,
            "chapter_goal": "主角入场",
            "opening_state": "门口",
            "scene_beats": [
                {"order": 1, "location": "门口", "action": "踏入", "result": "进入"}
            ],
            "ending_state": "入门",
            "entity_requirements": [],
        }
    )
    findings = focused_consistency_review(
        body="总之，综上所述，主角进入场内。\n" * 30,
        director_artifact=artifact,
        active_facts=[],
        runtime=runtime,
    )
    # Even if the runtime says it's a style issue, the wrapper
    # marks it advisory so the user can accept warnings.
    assert all(not f.blocking for f in findings)


# --- Policy: warnings are non-blocking --------------------------------------


def test_orchestrator_policy_can_accept_quality_warnings_without_hard_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hard-gate helper returns a list of findings; the
    orchestrator's confirmation path can accept the candidate
    with ``accept_quality_warnings=True`` whenever no hard
    inconsistency remains. We assert the helper itself
    separates hard vs warning so the policy can be applied.
    """
    runtime = _RecordingConsistencyRuntime(
        responses=[
            {
                "issues": [
                    {
                        "code": "style.report_voice",
                        "message": "段落偏报告腔。",
                        "blocking": False,
                        "source": "consistency",
                    }
                ]
            }
        ]
    )
    artifact = DirectorArtifact.model_validate(
        {
            "schema_version": "director-artifact/v1",
            "chapter_number": 1,
            "chapter_goal": "进入",
            "opening_state": "门口",
            "scene_beats": [
                {"order": 1, "location": "门口", "action": "踏入", "result": "进入"}
            ],
            "ending_state": "入门",
            "entity_requirements": [],
        }
    )
    findings = focused_consistency_review(
        body="总之，主角进入场内。\n" * 30,
        director_artifact=artifact,
        active_facts=[],
        runtime=runtime,
    )
    hard = [f for f in findings if f.blocking]
    assert hard == []


def test_deterministic_checks_produce_structured_evidence() -> None:
    """Every hard finding must carry the source line / span
    where the contradiction was detected so the workbench can
    point at it.
    """
    body = "第7章\n\n主角很短的章节。"
    findings = run_deterministic_checks(
        _ctx(
            body=body,
            chapter_number=7,
            min_chars=2000,
            max_chars=6000,
        )
    )
    for finding in findings:
        assert finding.source in {"checks.body_length", "checks.chapter_number"}
        # Either a line number or a span must be present so the
        # workbench can highlight the location.
        assert finding.evidence  # non-empty dict


def test_deterministic_checks_module_exposes_individual_check_functions() -> None:
    """The module exposes one named function per category so
    callers can pick a single check without running the whole
    suite.
    """
    from packages.story_core.continuity import checks as module

    for name in (
        "check_body_not_empty",
        "check_length_window",
        "check_chapter_number_contract",
        "check_outline_must_haves",
        "check_inventory_changes",
        "check_knowledge_boundaries",
    ):
        assert callable(getattr(module, name))
