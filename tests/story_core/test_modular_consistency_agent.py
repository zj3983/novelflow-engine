"""Tests for the focused consistency agent.

The consistency agent distinguishes factual contradictions from review
availability. A runtime exception or malformed response must stay visible as
``consistency.unavailable`` / ``consistency.invalid_response`` but is advisory:
not completing a fact check is not proof that the manuscript contradicts canon.
Actual established-fact conflicts remain blocking.

The consistency stage must also have its own gateway-backed
runtime (``GatewayConsistencyRuntime``) instead of reusing
the director runtime — the previous round used
``GatewayDirectorRuntime`` for consistency and the workbench
ended up listing two ``director`` rows per chapter. A
dedicated runtime routes the call through
``complete_stage("consistency", ...)`` and records one
``consistency`` row to ``PromptCallLog`` so the workbench can
audit the third model call separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from packages.story_core.agents.consistency import (
    ConsistencyFinding,
    FocusedConsistencyAgent,
    build_consistency_prompt,
    focused_consistency_review,
)
from packages.story_core.agents.contracts import DirectorArtifact, SceneBeat


@dataclass
class _Response:
    text: str
    payload: dict[str, Any] = field(default_factory=dict)


def _artifact() -> DirectorArtifact:
    return DirectorArtifact(
        chapter_number=2,
        chapter_title="夜奔驿站",
        chapter_goal="天黑前到达驿站",
        opening_state="林照受伤",
        scene_beats=[
            SceneBeat(order=1, location="妖林", action="起身", result="走出密林"),
            SceneBeat(order=2, location="驿站", action="交付情报", result="进入驿站"),
        ],
        ending_state="进入驿站",
        hook="下一章：从驿站出发",
    )


def _canon_snapshot(*, historical: bool = True, available: bool = True) -> dict[str, Any]:
    return {
        "schema_version": "canon-review-snapshot/v1",
        "as_of_chapter": 1,
        "state_source": "continuity_snapshot",
        "historical_rewrite": historical,
        "bounded_state_available": available,
        "facts": [
            {
                "subject": "林照",
                "field": "装备",
                "value": "旧木剑",
                "source": "continuity_snapshot:0001",
                "chapter_number": 1,
                "evidence": "林照把旧木剑系回腰间。",
            }
        ],
        "characters": [{"name": "林照"}],
        "entities": [],
        "relationships": [],
        "timeline": [],
        "world_rules": [],
    }


def test_consistency_prompt_includes_relevant_character_state() -> None:
    prompt = build_consistency_prompt(
        body="夜烬握紧新手短剑。",
        director_artifact=_artifact(),
        active_facts=[],
        character_states=[{"name": "苏叶", "game_state": {"equipment": {"main_hand": "新手法杖"}}}],
    )
    assert "新手法杖" in prompt
    assert "新手短剑" in prompt


def test_consistency_prompt_renders_canon_snapshot_with_provenance() -> None:
    prompt = build_consistency_prompt(
        body="林照说自己从未见过苏婉。",
        director_artifact=_artifact(),
        active_facts=[],
        character_states=[],
        canon_snapshot={
            "schema_version": "canon-review-snapshot/v1",
            "as_of_chapter": 2,
            "state_source": "continuity_snapshot",
            "historical_rewrite": True,
            "bounded_state_available": True,
            "facts": [
                {
                    "subject": "林照",
                    "field": "位置",
                    "value": "山腰",
                    "source": "continuity_snapshot:0002",
                    "chapter_number": 2,
                    "evidence": "林照在山腰停下。",
                }
            ],
            "characters": [
                {
                    "name": "林照",
                    "knowledge_boundary": ["知道苏婉持有旧令牌"],
                    "current_state": {"current": {"location": "山腰"}},
                }
            ],
            "relationships": [
                {
                    "subject_name": "林照",
                    "predicate": "trusts",
                    "object_name": "苏婉",
                    "polarity": "added",
                    "chapter_number": 2,
                    "source_sentence": "林照把旧令牌交给苏婉查看。",
                }
            ],
            "timeline": [
                {
                    "marker": "入夜",
                    "chapter_number": 2,
                    "source_sentence": "山门钟响三声。",
                }
            ],
        },
    )

    assert "Canon 审稿快照（截至第 2 章）" in prompt
    assert "continuity_snapshot:0002" in prompt
    assert "林照在山腰停下" in prompt
    assert "知道苏婉持有旧令牌" in prompt
    assert "林照把旧令牌交给苏婉查看" in prompt
    assert "山门钟响三声" in prompt
    assert "blocking=true 只允许" in prompt


def test_consistency_prompt_warns_when_historical_state_is_unavailable() -> None:
    prompt = build_consistency_prompt(
        body="正文",
        director_artifact=_artifact(),
        active_facts=[],
        canon_snapshot={
            "schema_version": "canon-review-snapshot/v1",
            "as_of_chapter": 2,
            "state_source": "unavailable",
            "historical_rewrite": True,
            "bounded_state_available": False,
        },
    )

    assert "没有可用的章前状态快照" in prompt
    assert "不得用当前项目状态倒推历史事实" in prompt


def test_consistency_runtime_failure_is_visible_but_advisory() -> None:
    class BrokenRuntime:
        def complete(self, request: Any) -> Any:
            raise RuntimeError("offline")

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        runtime=BrokenRuntime(),  # type: ignore[arg-type]
    )
    assert len(findings) == 1
    finding = findings[0]
    assert isinstance(finding, ConsistencyFinding)
    assert finding.code == "consistency.unavailable"
    assert finding.blocking is False


def test_consistency_gateway_failure_preserves_provider_error() -> None:
    class FailedGatewayRuntime:
        def complete(self, request: Any) -> Any:
            return type(
                "FailedResponse",
                (),
                {"ok": False, "error": "rate_limited", "text": "", "payload": {}},
            )()

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        runtime=FailedGatewayRuntime(),  # type: ignore[arg-type]
    )

    assert len(findings) == 1
    assert findings[0].code == "consistency.unavailable"
    assert "rate_limited" in findings[0].message


def test_consistency_invalid_response_is_advisory() -> None:
    class GarbledRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(text="not json at all", payload={})

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        runtime=GarbledRuntime(),  # type: ignore[arg-type]
    )
    assert len(findings) == 1
    assert findings[0].code == "consistency.invalid_response"
    assert findings[0].blocking is False


def test_consistency_accepts_prompt_contract_top_level_issue_list() -> None:
    class ListRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(text="[]", payload={})

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        runtime=ListRuntime(),  # type: ignore[arg-type]
    )

    assert findings == []


def test_consistency_accepts_fenced_json_issue_list() -> None:
    class FencedRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(
                text=(
                    "```json\n"
                    '[{"code":"state.conflict","message":"状态冲突",'
                    '"blocking":true,"source":"角色卡"}]'
                    "\n```"
                ),
                payload={},
            )

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        runtime=FencedRuntime(),  # type: ignore[arg-type]
    )

    assert [finding.code for finding in findings] == ["state.conflict"]


@pytest.mark.parametrize(
    "code",
    ["style.report_voice", "dialogue.unnatural", "exposition.too_dense"],
)
def test_consistency_style_family_is_advisory_not_blocking(code: str) -> None:
    class StyleRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(
                text="",
                payload={
                    "issues": [
                        {
                            "code": code,
                            "message": "文风偏报告体。",
                            "blocking": True,
                            "source": "consistency",
                        }
                    ]
                },
            )

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        runtime=StyleRuntime(),  # type: ignore[arg-type]
    )
    assert len(findings) == 1
    assert findings[0].code == code
    assert findings[0].blocking is False


def test_consistency_factual_finding_defaults_to_blocking() -> None:
    class FactualRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(
                text="",
                payload={
                    "issues": [
                        {
                            "code": "equipment.contradiction",
                            "message": "正文提到新手法杖但角色当前是夜烬短剑。",
                            "source": "continuity_snapshot:0001",
                        }
                    ]
                },
            )

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        runtime=FactualRuntime(),  # type: ignore[arg-type]
        canon_snapshot=_canon_snapshot(),
    )
    assert len(findings) == 1
    assert findings[0].code == "equipment.contradiction"
    assert findings[0].blocking is True


def test_consistency_generic_model_source_without_canon_evidence_is_advisory() -> None:
    class UnverifiedRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(
                text="",
                payload={
                    "issues": [
                        {
                            "code": "equipment.contradiction",
                            "message": "正文提到新手法杖。",
                            "blocking": True,
                            "source": "consistency",
                        }
                    ]
                },
            )

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        runtime=UnverifiedRuntime(),  # type: ignore[arg-type]
        canon_snapshot=_canon_snapshot(),
    )

    assert len(findings) == 1
    assert findings[0].blocking is False


@pytest.mark.parametrize("source", ["deterministic", "writer", "rewrite_guidance"])
def test_consistency_model_cannot_claim_program_source_to_remain_blocking(
    source: str,
) -> None:
    class SpoofedProgramSourceRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(
                text="",
                payload={
                    "issues": [
                        {
                            "code": "canon.location_conflict",
                            "message": "模型伪装成程序级 finding，但没有 Canon 证据。",
                            "blocking": True,
                            "source": source,
                        }
                    ]
                },
            )

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        runtime=SpoofedProgramSourceRuntime(),  # type: ignore[arg-type]
        canon_snapshot=_canon_snapshot(),
    )

    assert len(findings) == 1
    assert findings[0].blocking is False


def test_consistency_forged_canon_source_is_advisory() -> None:
    class ForgedSourceRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(
                text="",
                payload={
                    "issues": [
                        {
                            "code": "equipment.contradiction",
                            "message": "正文提到不存在于快照的装备。",
                            "blocking": True,
                            "source": "canon.fact:999",
                        }
                    ]
                },
            )

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        runtime=ForgedSourceRuntime(),  # type: ignore[arg-type]
        canon_snapshot=_canon_snapshot(),
    )

    assert len(findings) == 1
    assert findings[0].blocking is False


def test_consistency_explicit_snapshot_evidence_keeps_blocking() -> None:
    class EvidenceRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(
                text="",
                payload={
                    "issues": [
                        {
                            "code": "equipment.contradiction",
                            "message": "正文提到新手法杖但 Canon 记录为旧木剑。",
                            "blocking": True,
                            "source": "consistency",
                            "evidence": "林照把旧木剑系回腰间。",
                        }
                    ]
                },
            )

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        runtime=EvidenceRuntime(),  # type: ignore[arg-type]
        canon_snapshot=_canon_snapshot(),
    )

    assert len(findings) == 1
    assert findings[0].blocking is True


def test_consistency_unavailable_historical_snapshot_cannot_make_model_finding_blocking() -> None:
    class HistoricalRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(
                text="",
                payload={
                    "issues": [
                        {
                            "code": "canon.location_conflict",
                            "message": "模型声称历史章节与当前状态冲突。",
                            "blocking": True,
                            "source": "canon.character:林照",
                        }
                    ]
                },
            )

    snapshot = _canon_snapshot(historical=True, available=False)
    snapshot["facts"] = []
    snapshot["characters"] = []
    snapshot["diagnostics"] = {"unsafe_live_state_omitted": True}

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        runtime=HistoricalRuntime(),  # type: ignore[arg-type]
        canon_snapshot=snapshot,
    )

    assert len(findings) == 1
    assert findings[0].blocking is False


def test_consistency_director_execution_deviation_is_advisory() -> None:
    class PlanDeviationRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(
                text="",
                payload={
                    "issues": [
                        {
                            "code": "conflict",
                            "message": "正文调整了角色离开现场的时机。",
                            "blocking": True,
                            "source": "收尾状态",
                        }
                    ]
                },
            )

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        runtime=PlanDeviationRuntime(),  # type: ignore[arg-type]
    )

    assert len(findings) == 1
    assert findings[0].blocking is False


# --- Stage-routed runtime ---------------------------------------------------


def test_gateway_consistency_runtime_routes_through_consistency_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dedicated ``GatewayConsistencyRuntime`` must hand the
    gateway a real :class:`ModelRequest` whose ``operation``
    is ``"consistency"`` and must call
    :meth:`RuntimeModelGateway.complete_stage` with the
    ``"consistency"`` stage — never ``"director"``. The
    previous round reused ``GatewayDirectorRuntime`` for
    consistency and the workbench ended up listing two
    director rows per chapter.
    """

    from packages.story_core.agents.consistency.runtime import (
        GatewayConsistencyRuntime,
    )

    class _FakeGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        def complete_stage(self, stage: str, request: Any) -> Any:
            self.calls.append((stage, request))
            return _Response(text="ok", payload={"issues": []})

    class _FakeSettings:
        provider_id = "openai"
        model = "gpt-consistency"
        temperature = 0.2
        protocol = "openai"

    import packages.story_core.runtime_config as _runtime_config

    monkeypatch.setattr(
        _runtime_config, "resolve_stage_runtime", lambda _stage: _FakeSettings()
    )

    fake_gateway = _FakeGateway()
    runtime = GatewayConsistencyRuntime(gateway=fake_gateway)
    agent = FocusedConsistencyAgent(runtime=runtime)

    findings = agent.review(
        body="夜烬握紧新手法杖。",
        director_artifact=_artifact(),
        active_facts=[],
        character_states=[],
    )

    # No issues in the response — the runtime returned an
    # empty payload so the review is silent.
    assert findings == []
    assert len(fake_gateway.calls) == 1
    stage, request = fake_gateway.calls[0]
    from packages.story_core.model_gateway.contracts import ModelRequest

    assert stage == "consistency"
    assert isinstance(request, ModelRequest)
    assert request.operation == "consistency"
    assert request.provider == "openai"
    assert request.model == "gpt-consistency"


def test_model_gateway_maps_consistency_to_writer_runtime_binding() -> None:
    from packages.story_core.model_gateway import RuntimeModelGateway
    from packages.story_core.model_gateway.contracts import ModelRequest

    class _Settings:
        provider_id = "openai"
        model = "gpt-consistency"
        temperature = 0.2
        protocol = "openai"

    seen: list[str] = []
    gateway = RuntimeModelGateway(
        runtime_resolver=lambda stage: seen.append(stage) or _Settings()
    )
    gateway.complete_resolved = lambda settings, request: "ok"  # type: ignore[method-assign]

    response = gateway.complete_stage(
        "consistency",  # type: ignore[arg-type]
        ModelRequest(
            prompt="检查",
            provider="",
            model="",
            operation="consistency",
        ),
    )

    assert response == "ok"
    assert seen == ["writer"]


def test_gateway_consistency_runtime_records_resolved_provider_model_and_prompt(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dedicated runtime must also write a row to
    :class:`PromptCallLog` so the workbench can show the
    third model call (provider, model, prompt chars, status).
    """

    from packages.story_core.agents.consistency.runtime import (
        GatewayConsistencyRuntime,
    )
    from packages.story_core.prompt_call_log import (
        PromptCallLog,
        prompt_call_recording,
    )

    class _FakeGateway:
        def complete_stage(self, stage: str, request: Any) -> Any:
            return _Response(
                text="",
                payload={
                    "issues": [
                        {
                            "code": "equipment.contradiction",
                            "message": "新手法杖与登记装备矛盾。",
                            "source": "consistency",
                            "blocking": True,
                        }
                    ]
                },
            )

    class _FakeSettings:
        provider_id = "openai"
        model = "gpt-consistency"
        temperature = 0.2
        protocol = "openai"

    import packages.story_core.runtime_config as _runtime_config

    monkeypatch.setattr(
        _runtime_config, "resolve_stage_runtime", lambda _stage: _FakeSettings()
    )

    runtime = GatewayConsistencyRuntime(gateway=_FakeGateway())
    agent = FocusedConsistencyAgent(runtime=runtime)
    recorder = PromptCallLog(tmp_path, project_id="file:consistency-log")

    with prompt_call_recording(recorder):
        findings = agent.review(
            body="夜烬握紧新手法杖。",
            director_artifact=_artifact(),
            active_facts=[],
            character_states=[],
        )

    assert any(f.code == "equipment.contradiction" for f in findings)
    consistency_calls = [
        entry
        for entry in recorder.list(chapter_number=2)
        if entry["agent"] == "consistency"
    ]
    assert len(consistency_calls) == 1
    entry = consistency_calls[0]
    assert entry["stage"] == "consistency"
    assert entry["provider"] == "openai"
    assert entry["model"] == "gpt-consistency"
    assert entry["status"] == "succeeded"
    assert entry["prompt_chars"] > 0


def test_gateway_consistency_runtime_does_not_reuse_director_runtime(
    tmp_path: Path,
) -> None:
    """The pipeline default must use ``GatewayConsistencyRuntime``
    — not the director runtime — so the prompt_call_log shows
    one ``director`` row, one ``writer`` row, and one
    ``consistency`` row per chapter run, never two ``director``
    rows.
    """

    from packages.story_core.agents.consistency.runtime import (
        GatewayConsistencyRuntime,
    )
    from packages.story_core.agents.pipeline import (
        _default_consistency_runtime,
    )

    # A real gateway is the only thing the default factory
    # touches; we only need the type to be the dedicated
    # consistency runtime.
    runtime = _default_consistency_runtime(tmp_path)
    assert isinstance(runtime, GatewayConsistencyRuntime)
