"""Tests for the modular director agent.

The director decides *what* happens. It never writes prose.
The agent boundary is:

* the agent takes a ``DirectorContext`` (from Task 3) and
  produces a ``DirectorArtifact`` (from Task 1);
* when the context already has the structural outline for
  the target chapter, the agent must skip the model call and
  derive the artifact directly;
* when the outline is missing, the agent calls a
  ``DirectorRuntime`` to fill the operational detail;
* every run persists a record to
  ``.story-system/director/NNNN.json`` with the input trace,
  the output, the provider, the model, and the status;
* the artifact's ``entity_requirements`` list must surface
  every new person, item, equipment, technique, location,
  organization, quest, or monster the director approved.
* every model call enters the project-level prompt_call_log
  with the resolved provider / model so the workbench can
  audit which runtime answered the director's call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from packages.story_core.agents.contracts import DirectorArtifact
from packages.story_core.agents.director import DirectorAgent
from packages.story_core.agents.director.runtime import (
    DirectorRuntime,
    GatewayDirectorRuntime,
)
from packages.story_core.context.director_context import DirectorContext
from packages.story_core.prompt_call_log import (
    PromptCallLog,
    prompt_call_recording,
)


# --- Test doubles -----------------------------------------------------------


@dataclass
class _RecordingRuntime:
    responses: list[dict[str, Any]] = field(default_factory=list)
    requests: list[Any] = field(default_factory=list)
    call_count: int = 0

    def complete(self, request: Any) -> Any:
        self.call_count += 1
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("runtime ran out of canned responses")
        return _Response(payload=self.responses.pop(0))


@dataclass
class _Response:
    payload: dict[str, Any]


@dataclass
class _TextResponse:
    text: str


def _executable_director_payload(
    *,
    chapter_goal: str = "天黑前到达驿站",
    opening_state: str = "林照受伤",
    ending_state: str = "进入驿站",
    scene_beats: list[dict[str, Any]] | None = None,
    entity_requirements: list[dict[str, Any]] | None = None,
    chapter_title: str = "夜奔驿站",
    hook: str = "下一章：从驿站出发",
) -> dict[str, Any]:
    """Return a director response payload that satisfies the
    production validator (≥ 2 beats, all beats fully populated,
    chapter_goal / ending_state non-empty). Tests that need an
    intentionally bad artifact build their own payload instead.
    """
    beats = scene_beats or [
        {"order": 1, "location": "妖林", "action": "起身", "result": "走出密林"},
        {"order": 2, "location": "驿站", "action": "交付情报", "result": "进入驿站"},
    ]
    return {
        "chapter_title": chapter_title,
        "chapter_goal": chapter_goal,
        "opening_state": opening_state,
        "scene_beats": beats,
        "ending_state": ending_state,
        "entity_requirements": entity_requirements or [
            {"kind": "location", "name": "妖林"},
        ],
        "hook": hook,
    }


def _context_with_outline(
    chapter_number: int,
    *,
    include_target: bool = True,
) -> DirectorContext:
    nearby = [
        {"number": chapter_number - 1, "title": f"第{chapter_number - 1}章", "summary": "前情"},
    ]
    if include_target:
        nearby.append(
            {
                "number": chapter_number,
                "title": f"第{chapter_number}章",
                "summary": "本章目标：天黑前离开妖林。",
                "goal": "林照要在天黑前离开妖林",
                "obstacle": "妖林密布，肩伤未愈",
                "action": "沿东侧小径急行",
            }
        )
    nearby.append(
        {"number": chapter_number + 1, "title": f"第{chapter_number + 1}章", "summary": "下一章"},
    )
    return DirectorContext(
        chapter_number=chapter_number,
        volume={"id": "vol-2", "title": "第二卷", "chapter_range": [6, 10], "summary": ""},
        book_outline_summary="测试书",
        nearby_outline=nearby,
        previous_chapter_summary="前章总结：主角进入妖林。",
        previous_chapter_tail="林照按住左肩喘息。",
        continuity_ledger=[{"id": "f1", "subject": "林照", "field": "left_shoulder", "value": "抓伤"}],
        foreshadowing=[],
        character_cards=[
            {"id": "char-lin", "name": "林照", "role": "主角", "lifecycle": "active"},
        ],
        inventory=[],
        active_entity_names=["林照"],
    )


# --- Agent boundary ---------------------------------------------------------


def test_director_agent_returns_director_artifact_not_prose(tmp_path: Path) -> None:
    runtime = _RecordingRuntime(
        responses=[_executable_director_payload()]
    )
    agent = DirectorAgent(runtime=runtime, project_root=tmp_path)
    context = _context_with_outline(chapter_number=7)

    artifact = agent.plan(context)

    assert isinstance(artifact, DirectorArtifact)
    assert artifact.chapter_number == 7
    # Prose would be a long Chinese paragraph; the artifact body
    # is structured fields only.
    assert not hasattr(artifact, "body")
    assert "每项都要填写 notes" in runtime.requests[0].prompt


def test_director_agent_accepts_json_fenced_text_response(tmp_path: Path) -> None:
    payload = _executable_director_payload()

    @dataclass
    class _FencedRuntime:
        def complete(self, request: Any) -> Any:
            return _TextResponse(
                text="```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"
            )

    agent = DirectorAgent(runtime=_FencedRuntime(), project_root=tmp_path)

    artifact = agent.plan(_context_with_outline(chapter_number=7))

    assert artifact.chapter_number == 7
    assert len(artifact.scene_beats) == 2


def test_director_agent_retries_once_after_transient_provider_failure(
    tmp_path: Path,
) -> None:
    @dataclass
    class _TransientRuntime:
        call_count: int = 0

        def complete(self, request: Any) -> Any:
            self.call_count += 1
            if self.call_count == 1:
                return type(
                    "FailedResponse",
                    (),
                    {
                        "ok": False,
                        "error": "provider_unavailable",
                        "text": "",
                        "payload": {},
                    },
                )()
            return _Response(payload=_executable_director_payload())

    runtime = _TransientRuntime()
    agent = DirectorAgent(runtime=runtime, project_root=tmp_path)

    artifact = agent.plan(_context_with_outline(chapter_number=7))

    assert runtime.call_count == 2
    assert len(artifact.scene_beats) == 2


def test_director_uses_target_outline_as_input_instead_of_returning_it_verbatim(
    tmp_path: Path,
) -> None:
    """The director must always call the runtime, even when the
    target outline is present. The outline is an *input* the
    runtime has to expand into an executable plan; it is not a
    substitute for the plan itself. Earlier rounds short-circuited
    this and the writer then had to improvise against an empty
    ``scene_beats`` list.
    """
    runtime = _RecordingRuntime(
        responses=[
            _executable_director_payload(
                chapter_title="灰狼坡的红光",
                chapter_goal="交付清道夫任务后赶到动态事件外围",
                opening_state="夜烬为Lv.2，任务进度8/16",
                ending_state="夜烬留在事件外围",
                scene_beats=[
                    {
                        "order": 1,
                        "location": "灰狼坡",
                        "action": "补齐八份毒腺",
                        "result": "任务达到16/16",
                    },
                    {
                        "order": 2,
                        "location": "灰烬村",
                        "action": "提交清道夫任务",
                        "result": "升到Lv.3",
                    },
                    {
                        "order": 3,
                        "location": "灰狼坡北侧",
                        "action": "观察动态事件",
                        "result": "确认首领机制",
                    },
                ],
                entity_requirements=[{"kind": "character", "name": "流霜"}],
                hook="流霜打断狼王冲锋",
            )
        ]
    )
    agent = DirectorAgent(runtime=runtime, project_root=tmp_path)
    # The target outline is in the context — the runtime is still
    # called, and the artifact fields are NOT the outline summary.
    context = _context_with_outline(chapter_number=2, include_target=True)

    artifact = agent.plan(context)

    assert runtime.call_count == 1
    assert artifact.chapter_title == "灰狼坡的红光"
    assert len(artifact.scene_beats) == 3
    assert artifact.chapter_goal != "本章目标：天黑前离开妖林。"


def test_director_agent_calls_runtime_when_outline_is_missing(tmp_path: Path) -> None:
    runtime = _RecordingRuntime(responses=[_executable_director_payload()])
    agent = DirectorAgent(runtime=runtime, project_root=tmp_path)
    context = _context_with_outline(chapter_number=7, include_target=False)

    artifact = agent.plan(context)

    assert runtime.call_count == 1
    assert artifact.chapter_goal == "天黑前到达驿站"
    assert artifact.scene_beats[0].location == "妖林"
    assert artifact.entity_requirements[0].name == "妖林"


def test_director_agent_extracts_entity_requirements_from_runtime_response(
    tmp_path: Path,
) -> None:
    runtime = _RecordingRuntime(
        responses=[
            _executable_director_payload(
                chapter_goal="探索旧神龛",
                opening_state="林照抵达神龛前",
                ending_state="决定深入调查",
                scene_beats=[
                    {
                        "order": 1,
                        "location": "旧神龛",
                        "action": "进入",
                        "result": "发现地下通道",
                    },
                    {
                        "order": 2,
                        "location": "地下通道",
                        "action": "点灯",
                        "result": "看清通道壁画",
                    },
                ],
                entity_requirements=[
                    {"kind": "character", "name": "林照"},
                    {"kind": "character", "name": "守龛人"},
                    {"kind": "item", "name": "旧钥匙"},
                    {"kind": "equipment", "name": "灵剑"},
                    {"kind": "technique", "name": "灵视"},
                    {"kind": "location", "name": "旧神龛"},
                    {"kind": "organization", "name": "守龛人组织"},
                    {"kind": "quest", "name": "探索神龛"},
                    {"kind": "monster", "name": "石像守卫"},
                ],
            )
        ]
    )
    agent = DirectorAgent(runtime=runtime, project_root=tmp_path)
    context = _context_with_outline(chapter_number=8, include_target=False)

    artifact = agent.plan(context)

    kinds = {req.kind for req in artifact.entity_requirements}
    assert kinds == {
        "character",
        "item",
        "equipment",
        "technique",
        "location",
        "organization",
        "quest",
        "monster",
    }
    names = {req.name for req in artifact.entity_requirements}
    assert {"林照", "守龛人", "旧钥匙", "灵剑", "灵视", "旧神龛", "守龛人组织", "探索神龛", "石像守卫"} <= names


def test_director_agent_persists_artifact_under_story_system_director(tmp_path: Path) -> None:
    project = tmp_path / "story"
    project.mkdir()
    (project / ".story-system").mkdir()
    runtime = _RecordingRuntime(responses=[_executable_director_payload()])
    agent = DirectorAgent(runtime=runtime, project_root=project)
    context = _context_with_outline(chapter_number=7, include_target=True)

    artifact = agent.plan(context)

    target = project / ".story-system" / "director" / "0007.json"
    assert target.exists()
    loaded = json.loads(target.read_text(encoding="utf-8"))
    # The shortcut is gone — the runtime is always called and
    # the persisted envelope records a real provider / model.
    assert loaded["status"] == "ok"
    assert loaded["provider"] == "outline"
    assert loaded["model"] == "outline/v1"
    assert loaded["output"]["chapter_number"] == 7
    assert loaded["input_trace"]["reads"]  # the context reads were recorded


def test_director_agent_persists_provider_and_model_when_runtime_was_called(
    tmp_path: Path,
) -> None:
    project = tmp_path / "story"
    project.mkdir()
    (project / ".story-system").mkdir()

    @dataclass
    class ProviderAwareRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(payload=_executable_director_payload())

    agent = DirectorAgent(
        runtime=ProviderAwareRuntime(),  # type: ignore[arg-type]
        project_root=project,
        provider="openai",
        model="gpt-5",
    )
    context = _context_with_outline(chapter_number=5, include_target=False)

    agent.plan(context)

    loaded = json.loads(
        (project / ".story-system" / "director" / "0005.json").read_text(encoding="utf-8")
    )
    assert loaded["status"] == "ok"
    assert loaded["provider"] == "openai"
    assert loaded["model"] == "gpt-5"


# --- Runtime protocol -----------------------------------------------------


def test_gateway_director_runtime_routes_through_complete_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gateway-backed runtime must call
    ``RuntimeModelGateway.complete_stage("director", ...)`` so
    the agent stays transport-agnostic.
    """

    class _FakeGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        def complete_stage(self, stage: str, request: Any) -> Any:
            self.calls.append((stage, request))
            return _Response(payload=_executable_director_payload())

    fake_gateway = _FakeGateway()
    runtime = GatewayDirectorRuntime(gateway=fake_gateway)
    project = Path("/tmp/story_director_protocol")
    project.mkdir(parents=True, exist_ok=True)
    agent = DirectorAgent(runtime=runtime, project_root=project)
    context = _context_with_outline(chapter_number=3, include_target=False)

    agent.plan(context)

    assert len(fake_gateway.calls) == 1
    stage, _ = fake_gateway.calls[0]
    assert stage == "director"


def test_gateway_director_runtime_translates_lightweight_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gateway-backed runtime must hand the gateway a fully
    populated :class:`ModelRequest` — provider / model /
    operation included — even though the agent only knows about
    a lightweight ``_ModelRequest`` shape.

    The user feedback after Round 5 flagged that the runtime
    used to forward the lightweight request verbatim, the
    gateway's ``dataclasses.replace`` call then raised
    ``TypeError`` for the missing fields, the gateway's broad
    ``except`` swallowed the failure, and the consistency review
    silently returned no findings. The new translation reads
    the stage-resolved runtime settings exactly the way the
    gateway would have done internally so the replace never sees
    a missing field.
    """

    class _FakeGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        def complete_stage(self, stage: str, request: Any) -> Any:
            self.calls.append((stage, request))
            return _Response(payload=_executable_director_payload())

    class _FakeSettings:
        provider_id = "openai"
        model = "gpt-4o-mini"
        temperature = 0.3

    # The runtime imports ``resolve_stage_runtime`` lazily inside
    # ``complete``; patch the symbol on the source module so the
    # lazy import sees our fake.
    import packages.story_core.runtime_config as _runtime_config

    monkeypatch.setattr(_runtime_config, "resolve_stage_runtime", lambda _stage: _FakeSettings())

    fake_gateway = _FakeGateway()
    runtime = GatewayDirectorRuntime(gateway=fake_gateway)
    project = Path("/tmp/story_director_translate")
    project.mkdir(parents=True, exist_ok=True)
    agent = DirectorAgent(runtime=runtime, project_root=project)
    context = _context_with_outline(chapter_number=4, include_target=False)

    agent.plan(context)

    assert len(fake_gateway.calls) == 1
    stage, request = fake_gateway.calls[0]
    assert stage == "director"
    # The gateway now receives a real ``ModelRequest`` with
    # provider / model / operation filled from the stage
    # settings. ``dataclasses.replace`` on this object must not
    # raise.
    from packages.story_core.model_gateway.contracts import ModelRequest

    assert isinstance(request, ModelRequest)
    assert request.provider == "openai"
    assert request.model == "gpt-4o-mini"
    assert request.operation == "director"


def test_director_runtime_protocol_accepts_custom_runtime(tmp_path: Path) -> None:
    """Anything that implements ``complete(request)`` is a
    valid ``DirectorRuntime`` — the agent only depends on the
    protocol, not the concrete type.
    """

    @dataclass
    class CustomRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(payload=_executable_director_payload())

    agent: DirectorAgent = DirectorAgent(
        runtime=CustomRuntime(),  # type: ignore[arg-type]
        project_root=tmp_path,
    )
    context = _context_with_outline(chapter_number=2, include_target=False)

    artifact = agent.plan(context)
    assert artifact.chapter_goal == "天黑前到达驿站"


def test_gateway_director_runtime_records_resolved_provider_model_and_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gateway-backed director runtime must record every
    successful call to the project-level ``PromptCallLog`` so
    the workbench can audit which runtime answered the
    director's call. The provider / model values come from
    :func:`resolve_stage_runtime` — the same source the
    gateway itself reads internally.
    """

    class _FakeGateway:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Any]] = []

        def complete_stage(self, stage: str, request: Any) -> Any:
            self.calls.append((stage, request))
            return _Response(payload=_executable_director_payload())

    class _FakeSettings:
        provider_id = "openai"
        model = "gpt-director"
        temperature = 0.3
        protocol = "openai"

    import packages.story_core.runtime_config as _runtime_config

    monkeypatch.setattr(
        _runtime_config, "resolve_stage_runtime", lambda _stage: _FakeSettings()
    )

    project = tmp_path / "story-director-log"
    project.mkdir(parents=True, exist_ok=True)
    fake_gateway = _FakeGateway()
    runtime = GatewayDirectorRuntime(gateway=fake_gateway)
    agent = DirectorAgent(runtime=runtime, project_root=project)
    context = _context_with_outline(chapter_number=4, include_target=False)
    recorder = PromptCallLog(tmp_path, project_id="file:director-log")

    with prompt_call_recording(recorder):
        artifact = agent.plan(context)

    assert artifact.chapter_goal == "天黑前到达驿站"
    director_calls = [
        entry for entry in recorder.list(chapter_number=4) if entry["agent"] == "director"
    ]
    assert len(director_calls) == 1
    entry = director_calls[0]
    assert entry["stage"] == "director"
    assert entry["provider"] == "openai"
    assert entry["model"] == "gpt-director"
    assert entry["status"] == "succeeded"
    assert entry["prompt_chars"] > 0
