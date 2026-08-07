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
    runtime = _RecordingRuntime()
    agent = DirectorAgent(runtime=runtime, project_root=tmp_path)
    context = _context_with_outline(chapter_number=7)

    artifact = agent.plan(context)

    assert isinstance(artifact, DirectorArtifact)
    assert artifact.chapter_number == 7
    # Prose would be a long Chinese paragraph; the artifact body
    # is structured fields only.
    assert not hasattr(artifact, "body")


def test_director_agent_skips_model_call_when_outline_is_complete(tmp_path: Path) -> None:
    runtime = _RecordingRuntime()  # no canned responses
    agent = DirectorAgent(runtime=runtime, project_root=tmp_path)
    context = _context_with_outline(chapter_number=7, include_target=True)

    artifact = agent.plan(context)

    # The outline is already present in the director's view, so
    # the agent must NOT call the runtime.
    assert runtime.call_count == 0
    assert artifact.chapter_goal == "本章目标：天黑前离开妖林。"


def test_director_agent_calls_runtime_when_outline_is_missing(tmp_path: Path) -> None:
    runtime = _RecordingRuntime(
        responses=[
            {
                "chapter_goal": "天黑前到达驿站",
                "opening_state": "林照受伤",
                "scene_beats": [
                    {"order": 1, "location": "妖林", "action": "起身", "result": "走出密林"}
                ],
                "ending_state": "进入驿站",
                "entity_requirements": [
                    {"kind": "location", "name": "妖林"},
                ],
                "hook": "下一章：从驿站出发",
            }
        ]
    )
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
            {
                "chapter_goal": "探索旧神龛",
                "opening_state": "林照抵达神龛前",
                "scene_beats": [
                    {
                        "order": 1,
                        "location": "旧神龛",
                        "action": "进入",
                        "result": "发现地下通道",
                    }
                ],
                "ending_state": "决定深入调查",
                "entity_requirements": [
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
            }
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
    runtime = _RecordingRuntime()
    agent = DirectorAgent(runtime=runtime, project_root=project)
    context = _context_with_outline(chapter_number=7, include_target=True)

    artifact = agent.plan(context)

    target = project / ".story-system" / "director" / "0007.json"
    assert target.exists()
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["status"] == "outline_only"  # no model call
    assert loaded["provider"] == "outline"  # the outline-derived path
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
            return _Response(
                payload={
                    "chapter_goal": "目标",
                    "opening_state": "开场",
                    "scene_beats": [
                        {"order": 1, "location": "驿站", "action": "休息", "result": "恢复体力"}
                    ],
                    "ending_state": "收尾",
                    "entity_requirements": [],
                }
            )

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
            return _Response(
                payload={
                    "chapter_goal": "目标",
                    "opening_state": "开场",
                    "scene_beats": [
                        {"order": 1, "location": "驿站", "action": "休息", "result": "恢复"}
                    ],
                    "ending_state": "收尾",
                    "entity_requirements": [],
                }
            )

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


def test_director_runtime_protocol_accepts_custom_runtime(tmp_path: Path) -> None:
    """Anything that implements ``complete(request)`` is a
    valid ``DirectorRuntime`` — the agent only depends on the
    protocol, not the concrete type.
    """

    @dataclass
    class CustomRuntime:
        def complete(self, request: Any) -> Any:
            return _Response(
                payload={
                    "chapter_goal": "目标",
                    "opening_state": "开场",
                    "scene_beats": [
                        {"order": 1, "location": "驿站", "action": "休息", "result": "恢复"}
                    ],
                    "ending_state": "收尾",
                    "entity_requirements": [],
                }
            )

    agent: DirectorAgent = DirectorAgent(
        runtime=CustomRuntime(),  # type: ignore[arg-type]
        project_root=tmp_path,
    )
    context = _context_with_outline(chapter_number=2, include_target=False)

    artifact = agent.plan(context)
    assert artifact.chapter_goal == "目标"
