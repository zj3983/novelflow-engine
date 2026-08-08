"""Tests for the focused consistency agent.

The plan rule for the consistency review is *fail closed*: a
runtime exception or a malformed response becomes a blocking
finding instead of a silent ``[]`` that lets a contradicted
draft reach the confirmation gate. These tests pin the new
contract — the prompt renders the current character state, a
broken runtime surfaces ``consistency.unavailable``, and a
malformed response surfaces ``consistency.invalid_response``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
