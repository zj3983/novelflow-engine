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
5. Every model call enters the project-level prompt_call_log so
   the workbench can audit what the writer asked and what came
   back, with the resolved provider / model / status fields
   filled from the same stage settings the gateway saw.
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
from packages.story_core.agents.writer.prompt import build_writer_prompt
from packages.story_core.agents.writer.runtime import (
    GatewayWriterRuntime,
    WriterRuntime,
)
from packages.story_core.prompt_call_log import (
    PromptCallLog,
    prompt_call_recording,
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


def test_writer_prompt_contains_numeric_length_policy_and_current_character_state() -> None:
    """The writer prompt must include the concrete length policy
    and the active character's current state (including game
    state) so the model can keep prose on the hard production
    target and stop hallucinating equipment or quests.
    """
    request = WriterRequest(
        chapter_number=2,
        director_artifact=_director_artifact(),
        target_chars={"min": 4200, "max": 5500},
        acceptance_chars={"min": 3800, "max": 6000},
        character_cards=[{
            "name": "苏叶",
            "role": "protagonist",
            "lifecycle": "active",
            "real_state": {"current": {"balance": "61.10元"}},
            "game_state": {"current": {
                "game_id": "夜烬",
                "level": "Lv.2",
                "class_path": "见习者（未转职）",
                "equipment": {"main_hand": "新手法杖"},
                "inventory": {"灰狼毒腺": 8},
                "quests": {"active": "清道夫：8/16；未提交"},
            }},
        }],
    )

    prompt = build_writer_prompt(request)

    assert "目标4200至5500字" in prompt
    assert "低于3800字" in prompt
    assert "超过6000字" in prompt
    assert "新手法杖" in prompt
    assert "清道夫：8/16；未提交" in prompt


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


def test_gateway_writer_runtime_translates_lightweight_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gateway-backed writer runtime must hand the gateway a
    real :class:`ModelRequest` — provider / model / operation
    included — even though the agent only knows about the
    lightweight ``_ModelRequest`` shape.

    Without the translation the gateway's ``dataclasses.replace``
    call would raise ``TypeError`` for the missing fields and
    the gateway's broad ``except`` would turn the call into a
    silent model-failure response. The writer agent would then
    raise ``writer_empty_body`` and the orchestrator would crash
    the chapter run. The translation reads the stage-resolved
    runtime settings to fill the missing fields the same way
    the gateway would have done internally.
    """

    class _FakeGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        def complete_stage(self, stage: str, request: Any) -> Any:
            self.calls.append((stage, request))
            return _Response(text="正文")

    class _FakeSettings:
        provider_id = "openai"
        model = "gpt-4o-mini"
        temperature = 0.5

    import packages.story_core.runtime_config as _runtime_config

    monkeypatch.setattr(_runtime_config, "resolve_stage_runtime", lambda _stage: _FakeSettings())

    fake_gateway = _FakeGateway()
    runtime = GatewayWriterRuntime(gateway=fake_gateway)
    agent = WriterAgent(runtime=runtime)

    result = agent.run(_writer_request())

    assert result.body == "正文"
    assert len(fake_gateway.calls) == 1
    stage, request = fake_gateway.calls[0]
    from packages.story_core.model_gateway.contracts import ModelRequest

    assert stage == "writer"
    assert isinstance(request, ModelRequest)
    assert request.provider == "openai"
    assert request.model == "gpt-4o-mini"
    assert request.operation == "writer"


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


def test_gateway_writer_runtime_records_resolved_provider_model_and_prompt(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gateway-backed writer runtime must record every
    successful call to the project-level ``PromptCallLog`` so
    the workbench can audit what the writer asked, which
    provider / model answered, and how long it took. The
    provider / model values come from
    :func:`resolve_stage_runtime` — the same source the
    gateway itself reads internally — so the recorded
    metadata is never a placeholder.
    """

    class _FakeGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        def complete_stage(self, stage: str, request: Any) -> Any:
            self.calls.append((stage, request))
            return _Response(text="正文记录")

    class _FakeSettings:
        provider_id = "openai"
        model = "gpt-test"
        temperature = 0.4
        protocol = "openai"

    import packages.story_core.runtime_config as _runtime_config

    monkeypatch.setattr(
        _runtime_config, "resolve_stage_runtime", lambda _stage: _FakeSettings()
    )

    fake_gateway = _FakeGateway()
    runtime = GatewayWriterRuntime(gateway=fake_gateway)
    agent = WriterAgent(runtime=runtime)
    recorder = PromptCallLog(tmp_path, project_id="file:writer-log")

    with prompt_call_recording(recorder):
        result = agent.run(_writer_request())

    assert result.body == "正文记录"
    writer_calls = [
        entry for entry in recorder.list(chapter_number=7) if entry["agent"] == "writer"
    ]
    assert len(writer_calls) == 1
    entry = writer_calls[0]
    assert entry["stage"] == "writer"
    assert entry["provider"] == "openai"
    assert entry["model"] == "gpt-test"
    assert entry["status"] == "succeeded"
    assert entry["prompt_chars"] > 0
    assert entry["output_chars"] >= len("正文记录")


def test_gateway_writer_runtime_records_failure_with_status_failed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed gateway call must close the prompt_call_log
    entry as ``status="failed"`` and preserve the error
    message. The workbench's stage evidence column depends on
    this so the operator can tell a 401 from a model timeout
    at a glance.
    """

    class _FakeGateway:
        def complete_stage(self, stage: str, request: Any) -> Any:
            from packages.story_core.model_gateway.contracts import ModelRequest
            from packages.story_core.model_gateway.contracts import ModelResponse

            return ModelResponse.failure(
                ModelRequest(
                    prompt=request.prompt,
                    provider="openai",
                    model="gpt-test",
                    operation="writer",
                ),
                "missing_api_key",
            )

    class _FakeSettings:
        provider_id = "openai"
        model = "gpt-test"
        temperature = 0.4
        protocol = "openai"

    import packages.story_core.runtime_config as _runtime_config

    monkeypatch.setattr(
        _runtime_config, "resolve_stage_runtime", lambda _stage: _FakeSettings()
    )

    recorder = PromptCallLog(tmp_path, project_id="file:writer-fail")
    runtime = GatewayWriterRuntime(gateway=_FakeGateway())
    agent = WriterAgent(runtime=runtime)
    # The writer must surface the failure to the agent; the
    # recorder must still capture the failed lifecycle.
    with prompt_call_recording(recorder):
        with pytest.raises(RuntimeError, match="writer_empty_body"):
            agent.run(_writer_request())

    writer_calls = [
        entry for entry in recorder.list(chapter_number=7) if entry["agent"] == "writer"
    ]
    assert len(writer_calls) == 1
    entry = writer_calls[0]
    assert entry["status"] == "failed"
    assert entry["provider"] == "openai"
    assert entry["model"] == "gpt-test"


def test_gateway_writer_runtime_does_not_rewrite_preexisting_prompt_log(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing ``index.jsonl`` (a pre-fix call the user
    already audited) must remain byte-identical after the
    runtime finishes a new call. The new entry is appended,
    not rewritten in place.
    """

    class _FakeGateway:
        def complete_stage(self, stage: str, request: Any) -> Any:
            return _Response(text="正文")

    class _FakeSettings:
        provider_id = "openai"
        model = "gpt-test"
        temperature = 0.4
        protocol = "openai"

    import packages.story_core.runtime_config as _runtime_config

    monkeypatch.setattr(
        _runtime_config, "resolve_stage_runtime", lambda _stage: _FakeSettings()
    )

    recorder = PromptCallLog(tmp_path, project_id="file:writer-append")
    historical_id = recorder.start(
        chapter_number=1,
        stage="writer",
        agent="writer",
        user_prompt="历史 prompt",
        provider="legacy",
        model="legacy-model",
    )
    recorder.finish(historical_id, status="succeeded", output="历史正文")
    historical_detail_bytes = (
        tmp_path / "prompt_calls" / f"{historical_id}.json"
    ).read_bytes()
    historical_index_line = (
        tmp_path / "prompt_calls" / "index.jsonl"
    ).read_text(encoding="utf-8").strip().splitlines()[0]

    runtime = GatewayWriterRuntime(gateway=_FakeGateway())
    agent = WriterAgent(runtime=runtime)
    with prompt_call_recording(recorder):
        agent.run(_writer_request())

    # The historical detail file is byte-identical to the
    # snapshot we took before the new call — the runtime
    # appends, never rewrites.
    assert (
        tmp_path / "prompt_calls" / f"{historical_id}.json"
    ).read_bytes() == historical_detail_bytes
    # The first line of the index (the historical lifecycle
    # row) is preserved verbatim; the new lifecycle rows
    # come after.
    first_line = (
        tmp_path / "prompt_calls" / "index.jsonl"
    ).read_text(encoding="utf-8").strip().splitlines()[0]
    assert first_line == historical_index_line
    # The historical detail is still readable through the
    # public ``get`` API.
    historical_payload = recorder.get(historical_id)
    assert historical_payload["user_prompt"] == "历史 prompt"
    assert historical_payload["status"] == "succeeded"
