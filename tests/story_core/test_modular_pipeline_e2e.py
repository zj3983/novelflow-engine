"""End-to-end test for the modular agent pipeline.

The user feedback after the 9-task review-rewrite plan called out
that the new Director / Writer / FactExtractor agents were never
actually wired into the orchestrator's main flow. Tasks 10-14
prepared the building blocks (FactExtractor, ContinuityDelta,
transactional confirmation, modular agents, pipeline boundary
tests) but the orchestrator kept calling
``resolve_chapter_plan`` / ``generate_chapter_body``.

This test is the proof-of-wiring the migration plan requires. It
drives the new :func:`run_modular_pipeline` through the
orchestrator's public entry point
(``StoryOrchestrator.generate_next_chapter_via_modular_pipeline``)
and asserts the three modules are each called exactly once on a
real on-disk project.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from packages.story_core.agents.pipeline import ModularChapterBundle
from packages.story_core.canon.registry import CanonRegistry
from packages.story_core.orchestrator import StoryOrchestrator


# --- Fixtures ----------------------------------------------------------------


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _seed_legacy_project(root: Path, *, with_outline: bool = True) -> None:
    """Create a minimal ``.webnovel/`` project so the legacy adapter
    has real data to translate. The pipeline falls back to the
    legacy view when the canonical ``.story-system/`` artifacts are
    missing, so this exercises the production fallback path.

    ``with_outline=False`` omits the chapter outline for the target
    chapter so the director's outline-only shortcut is disabled and
    the test can prove the director runtime is actually called.
    """
    chapters: list[dict[str, Any]] = []
    if with_outline:
        chapters.append(
            {
                "chapter_number": 1,
                "title": "初章",
                "goal": "上山",
                "obstacle": "雨",
                "action": "行",
            }
        )
    _write_json(
        root / ".webnovel" / "outline.json",
        {
            "schema_version": "project-outline/v1",
            "chapters": chapters,
            "arcs": [
                {
                    "id": "vol-1",
                    "title": "第一卷",
                    "start_chapter": 1,
                    "end_chapter": 50,
                },
            ],
            "overall": {"story": "概述"},
        },
    )
    _write_json(
        root / ".webnovel" / "state.json",
        {
            "story_id": "s-e2e",
            "current_chapter": 1,
            "characters": [{"name": "林昭", "role": "protagonist"}],
            "world_facts": [],
            "chapter_summaries": [],
        },
    )
    _write_json(
        root / ".webnovel" / "project.json",
        {
            "title": "E2E 项目",
            "character_profiles": [{"name": "林昭", "role": "protagonist"}],
            "enabled_skill_ids": [],
        },
    )


class _StubDirectorRuntime:
    """Record-and-replay director runtime for the e2e test.

    The runtime returns a canned director payload the
    ``parse_director_response`` helper understands, while
    recording every ``complete`` call so the test can assert the
    director ran exactly once. The chapter number is pulled from
    the request metadata so the artifact matches whatever
    chapter the test asked for.
    """

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def complete(self, request: Any) -> dict[str, Any]:
        self.calls.append(request)
        metadata = getattr(request, "metadata", None) or {}
        chapter_number = int(metadata.get("chapter_number", 1) or 1)
        return {
            "chapter_number": chapter_number,
            "chapter_goal": "上山",
            "opening_state": "天将暮",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "山脚",
                    "action": "林昭决定上山",
                    "result": "进入山路",
                },
            ],
            "ending_state": "夜宿山腰",
            "hook": "远处传来钟声",
            "entity_requirements": [
                {
                    "kind": "character",
                    "name": "林昭",
                    "importance": 7,
                    "inline_minor": False,
                    "notes": "主角",
                },
            ],
        }


class _StubWriterRuntime:
    """Record-and-replay writer runtime for the e2e test."""

    def __init__(self, body: str = "天色已晚，林昭提灯上山。") -> None:
        self.body = body
        self.calls: list[Any] = []

    def complete(self, request: Any) -> Any:
        self.calls.append(request)

        class _Resp:
            def __init__(self, text: str) -> None:
                self.text = text
                self.raw: dict[str, Any] = {}

        return _Resp(self.body)


# --- Tests -------------------------------------------------------------------


def test_orchestrator_wires_director_writer_and_fact_extractor(tmp_path: Path):
    """The orchestrator's modular entry point calls all three new agents.

    Asserts:

    * the director runtime is hit exactly once and its response
      is parsed into a :class:`DirectorArtifact`;
    * the writer runtime is hit exactly once and its body lands
      on the bundle;
    * the canon preflight runs (the :class:`CanonService` is asked
      to honour the director's entity requirements);
    * the :class:`FactExtractor` produces a
      :class:`ContinuityDelta` for the body.
    """
    project_root = tmp_path
    # ``with_outline=False`` disables the director's outline-only
    # shortcut so the director runtime is the only path the
    # artifact can come from. The test would otherwise observe
    # zero director calls even though the director agent itself
    # ran.
    _seed_legacy_project(project_root, with_outline=False)

    director_runtime = _StubDirectorRuntime()
    writer_runtime = _StubWriterRuntime(body="林昭提灯上山，夜宿山腰。")

    # The new pipeline accepts an optional canon registry so the
    # workbench (and the e2e test) can inspect preflight side
    # effects without writing to a real on-disk registry.
    canon_registry = CanonRegistry()

    orchestrator = StoryOrchestrator(use_modular_agents=True)
    bundle = orchestrator.generate_next_chapter_via_modular_pipeline(
        project_root=project_root,
        chapter_number=1,
        director_runtime=director_runtime,
        writer_runtime=writer_runtime,
        canon_registry=canon_registry,
    )

    # The director runtime ran exactly once and the artifact
    # carries the chapter goal we returned.
    assert len(director_runtime.calls) == 1
    assert isinstance(bundle, ModularChapterBundle)
    assert bundle.director_artifact.chapter_number == 1
    assert bundle.director_artifact.chapter_goal == "上山"
    # The artifact's entity requirements came through the parser.
    assert any(
        req.name == "林昭" for req in bundle.director_artifact.entity_requirements
    )

    # The writer runtime ran exactly once and the body matches.
    assert len(writer_runtime.calls) == 1
    assert bundle.body == "林昭提灯上山，夜宿山腰。"

    # The canon preflight ran with the director's requirements.
    # The preflight is side-effect-free: it counts existing /
    # missing / inline-minor roles so the candidate flow knows
    # how many cards the confirmation step would need to create.
    preflight = bundle.canon_preflight or {}
    assert preflight.get("requested", 0) >= 1
    assert preflight.get("missing", 0) >= 1  # 林昭 not yet in the registry

    # The fact extractor produced a delta scoped to the chapter.
    assert bundle.continuity_delta is not None
    assert bundle.continuity_delta.chapter_number == 1

    # Per-stage trace ids are surfaced for the workbench.
    assert bundle.director_trace_id.startswith("director:")
    assert bundle.writer_trace_id.startswith("writer:")
    assert bundle.fact_extractor_trace_id.startswith("fact-extractor:")


def test_orchestrator_modular_path_works_without_legacy_project(tmp_path: Path):
    """The modular pipeline still runs on an empty project.

    The pipeline falls back to an empty canonical view when no
    ``.webnovel/`` data exists. The director runtime is then
    responsible for the entire plan; the writer and fact
    extractor still run and produce a coherent bundle.
    """
    director_runtime = _StubDirectorRuntime()
    writer_runtime = _StubWriterRuntime()

    orchestrator = StoryOrchestrator(use_modular_agents=True)
    bundle = orchestrator.generate_next_chapter_via_modular_pipeline(
        project_root=tmp_path,
        chapter_number=2,
        director_runtime=director_runtime,
        writer_runtime=writer_runtime,
    )

    assert isinstance(bundle, ModularChapterBundle)
    assert bundle.chapter_number == 2
    assert bundle.director_artifact.chapter_number == 2
    assert bundle.body == writer_runtime.body
    assert bundle.continuity_delta is not None
    assert bundle.continuity_delta.chapter_number == 2


def test_orchestrator_legacy_path_unchanged_when_flag_off():
    """The legacy constructor still defaults to ``use_modular_agents=False``."""
    orchestrator = StoryOrchestrator()
    assert orchestrator.use_modular_agents is False
