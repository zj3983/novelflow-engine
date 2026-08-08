"""Tests for the focused consistency agent.

The plan rule for the consistency review is *fail closed*: a
runtime exception or a malformed response becomes a blocking
finding instead of a silent ``[]`` that lets a contradicted
draft reach the confirmation gate. These tests pin the new
contract — the prompt renders the current character state, a
broken runtime surfaces ``consistency.unavailable``, and a
malformed response surfaces ``consistency.invalid_response``.

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


def test_consistency_prompt_includes_relevant_character_state() -> None:
    prompt = build_consistency_prompt(
        body="夜烬握紧新手短剑。",
        director_artifact=_artifact(),
        active_facts=[],
        character_states=[{"name": "苏叶", "game_state": {"equipment": {"main_hand": "新手法杖"}}}],
    )
    assert "新手法杖" in prompt
    assert "新手短剑" in prompt


def test_consistency_runtime_failure_is_not_silent_pass() -> None:
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
    assert finding.blocking is True


def test_consistency_invalid_response_is_blocking() -> None:
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
    assert findings[0].blocking is True


def test_consistency_style_finding_is_advisory_not_blocking() -> None:
    class StyleRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(
                text="",
                payload={
                    "issues": [
                        {
                            "code": "style.report_voice",
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
    assert findings[0].code == "style.report_voice"
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
                            "source": "consistency",
                        }
                    ]
                },
            )

    findings = focused_consistency_review(
        "正文",
        director_artifact=_artifact(),
        active_facts=[],
        runtime=FactualRuntime(),  # type: ignore[arg-type]
    )
    assert len(findings) == 1
    assert findings[0].code == "equipment.contradiction"
    assert findings[0].blocking is True


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
