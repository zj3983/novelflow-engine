"""Tests for the modular writer agent boundary.

The writer agent is the only path that turns a director-approved
chapter plan into prose. The boundary contract is:

1. One ``WriterRequest`` in, one ``WriterResult`` out.
2. The agent must not know whether the backing runtime is
   Codex CLI, Gemini CLI, or an HTTP API — it talks to a
   ``WriterRuntime`` protocol only.
3. The rendered prompt must contain the director artifact and
   the selected context the request asked for, but not internal
   trace hashes, unrelated character cards, or retired entities.
4. Empty model output must surface as ``writer_empty_body``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from packages.story_core.agents.contracts import (
    DirectorArtifact,
    EntityRequirement,
    SceneBeat,
    WriterRequest,
    WriterResult,
)
from packages.story_core.agents.writer import WriterAgent
from packages.story_core.agents.writer.runtime import (
    GatewayWriterRuntime,
    WriterRuntime,
)


# --- Test doubles -----------------------------------------------------------


@dataclass
class _RecordingRuntime:
    """Capture every ModelRequest the writer sends through."""

    responses: list[str]
    requests: list[Any] = field(default_factory=list)
    error: Exception | None = None
    call_count: int = 0

    def complete(self, request: Any) -> Any:
        self.call_count += 1
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        text = self.responses.pop(0) if self.responses else ""
        return _Response(text=text)


@dataclass
class _Response:
    text: str
    finish_reason: str = "stop"
    raw: dict[str, Any] = field(default_factory=dict)


def _director_artifact() -> DirectorArtifact:
    return DirectorArtifact.model_validate(
        {
            "schema_version": "director-artifact/v1",
            "chapter_number": 7,
            "chapter_goal": "天黑前离开妖林深处",
            "opening_state": "林照左肩受伤。",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "妖林",
                    "action": "起身",
                    "result": "沿溪流走出密林",
                }
            ],
            "ending_state": "抵达驿站。",
            "entity_requirements": [
                {"kind": "character", "name": "林照"},
            ],
        }
    )


def _writer_request(**overrides: Any) -> WriterRequest:
    payload: dict[str, Any] = {
        "chapter_number": 7,
        "director_artifact": _director_artifact(),
        "previous_tail": "林照按住左肩喘息。",
        "continuity_facts": [{"id": "f1", "subject": "林照", "field": "left_shoulder", "value": "抓伤"}],
        "character_cards": [
            {"id": "char-lin", "name": "林照", "role": "主角", "lifecycle": "active"},
            {"id": "char-zhou", "name": "周执事", "role": "师父", "lifecycle": "retired"},
        ],
        "entity_cards": [
            {"id": "loc-yao", "name": "妖林", "lifecycle": "active"},
            {"id": "loc-old", "name": "旧神龛", "lifecycle": "retired"},
        ],
        "world_rules": ["时间倒流不可逆。", "灵力以丹田为核心。"],
        "craft_modules": [
            {"id": "dialogue-natural", "content": "对话先回应再表态。"},
        ],
    }
    payload.update(overrides)
    return WriterRequest.model_validate(payload)


# --- Boundary contract -----------------------------------------------------


def test_writer_agent_takes_one_request_and_returns_one_result() -> None:
    runtime = _RecordingRuntime(responses=["林照起身，离开妖林。"])
    agent = WriterAgent(runtime=runtime)

    result = agent.run(_writer_request())

    assert isinstance(result, WriterResult)
    assert result.body == "林照起身，离开妖林。"
    assert runtime.call_count == 1
    # The agent must consume exactly one model call per request —
    # no hidden expansion or rewrite passes.
    assert result.notes == ""


def test_writer_agent_uses_same_request_contract_for_cli_and_api_runtimes() -> None:
    cli_runtime = _RecordingRuntime(responses=["body-cli"])
    api_runtime = _RecordingRuntime(responses=["body-api"])

    cli_agent = WriterAgent(runtime=cli_runtime)
    api_agent = WriterAgent(runtime=api_runtime)

    request = _writer_request()
    cli_result = cli_agent.run(request)
    api_result = api_agent.run(request)

    # The same WriterRequest must produce a WriterResult regardless
    # of which runtime is plugged in; only the body text differs.
    assert cli_result.body == "body-cli"
    assert api_result.body == "body-api"
    assert isinstance(cli_result, WriterResult)
    assert isinstance(api_result, WriterResult)


def test_writer_agent_prompt_contains_director_artifact_and_context() -> None:
    runtime = _RecordingRuntime(responses=["正文"])
    agent = WriterAgent(runtime=runtime)
    request = _writer_request()

    agent.run(request)

    prompt = runtime.requests[0].prompt
    assert "天黑前离开妖林" in prompt
    assert "林照按住左肩" in prompt
    assert "时间倒流不可逆" in prompt
    # Selected craft module content must make it into the prompt.
    assert "对话先回应" in prompt


def test_writer_agent_prompt_excludes_unrelated_cards_and_retired_entities() -> None:
    runtime = _RecordingRuntime(responses=["正文"])
    agent = WriterAgent(runtime=runtime)
    request = _writer_request()

    agent.run(request)

    prompt = runtime.requests[0].prompt
    # The retired entity must not leak into the writer view.
    assert "旧神龛" not in prompt
    # Internal trace markers the runtime would never see must
    # not be in the prompt either.
    assert "ctx-trace" not in prompt
    assert "sha256:" not in prompt


def test_writer_agent_raises_writer_empty_body_on_blank_response() -> None:
    runtime = _RecordingRuntime(responses=["   "])
    agent = WriterAgent(runtime=runtime)

    with pytest.raises(RuntimeError, match="writer_empty_body"):
        agent.run(_writer_request())


def test_writer_agent_raises_writer_empty_body_on_empty_response() -> None:
    runtime = _RecordingRuntime(responses=[""])
    agent = WriterAgent(runtime=runtime)

    with pytest.raises(RuntimeError, match="writer_empty_body"):
        agent.run(_writer_request())


def test_writer_agent_records_proposed_facts_when_runtime_returns_them() -> None:
    @dataclass
    class FactAwareRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(
                text="正文",
                raw={
                    "proposed_facts": [
                        {"subject_id": "char-lin", "field": "left_shoulder", "value": "已包扎"}
                    ]
                },
            )

    agent = WriterAgent(runtime=FactAwareRuntime())
    result = agent.run(_writer_request())

    assert result.proposed_facts == [
        {"subject_id": "char-lin", "field": "left_shoulder", "value": "已包扎"}
    ]


# --- Runtime protocol -----------------------------------------------------


def test_gateway_writer_runtime_uses_complete_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gateway-backed runtime must route through the
    canonical ``RuntimeModelGateway.complete_stage("writer", ...)``
    so the writer agent has no knowledge of the transport
    (Codex CLI, Gemini CLI, HTTP API).
    """

    class _FakeGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        def complete_stage(self, stage: str, request: Any) -> Any:
            self.calls.append((stage, request))
            return _Response(text="正文")

    fake_gateway = _FakeGateway()
    runtime = GatewayWriterRuntime(gateway=fake_gateway)
    agent = WriterAgent(runtime=runtime)

    result = agent.run(_writer_request())

    assert result.body == "正文"
    assert len(fake_gateway.calls) == 1
    stage, request = fake_gateway.calls[0]
    assert stage == "writer"


def test_writer_runtime_protocol_accepts_custom_runtime() -> None:
    """Any object that implements ``complete(request)`` must be
    usable as a ``WriterRuntime`` — the agent only depends on
    the protocol, not on the concrete type.
    """

    @dataclass
    class CustomRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(text="custom-body")

    agent: WriterAgent = WriterAgent(runtime=CustomRuntime())  # type: ignore[arg-type]
    result = agent.run(_writer_request())
    assert result.body == "custom-body"
