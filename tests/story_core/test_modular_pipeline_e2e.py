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

from packages.story_core.agents.pipeline import (
    ModularChapterBundle,
    _ensure_director_context,
    _ensure_writer_context,
)
from packages.story_core.agents.contracts import DirectorArtifact
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
            "chapter_title": "夜奔山腰",
            "chapter_goal": "上山",
            "opening_state": "天将暮",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "山脚",
                    "action": "林昭决定上山",
                    "result": "进入山路",
                },
                {
                    "order": 2,
                    "location": "山腰",
                    "action": "寻得避雨处",
                    "result": "夜宿山腰",
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


class _StubConsistencyRuntime:
    """Record-and-replay consistency runtime for the e2e test.

    Returns a canned contradiction payload the focused
    consistency agent understands. The test asserts the
    orchestrator actually invoked this runtime and surfaced the
    blocking finding on the bundle (the previous round
    hard-coded ``pass=True`` and the body was passing review
    silently).
    """

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def complete(self, request: Any) -> dict[str, Any]:
        self.calls.append(request)
        return {
            "issues": [
                {
                    "code": "canon_violation",
                    "message": "铜牌不该出现在山腰草棚。",
                    "source": "consistency",
                    "blocking": True,
                }
            ]
        }


def test_director_context_falls_back_to_legacy_when_story_system_is_partial(
    tmp_path: Path,
):
    """Runtime artifacts must not masquerade as a completed migration.

    Real legacy projects already have ``.story-system`` because candidate,
    workflow, and director records are written there.  Until canonical
    ``outline.json`` and ``volume.json`` exist, the director must still read
    the established ``.webnovel`` outline and character state.
    """
    _seed_legacy_project(tmp_path, with_outline=True)
    (tmp_path / ".story-system" / "workflow").mkdir(parents=True)
    state_path = tmp_path / ".webnovel" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["chapter_summaries"] = [
        {
            "chapter_number": 1,
            "summary": "主角进入游戏。",
            "facts": ["主角仍是一级。"],
        }
    ]
    _write_json(state_path, state)

    context = _ensure_director_context(project_root=tmp_path, chapter_number=2)

    assert context.book_outline_summary == "概述"
    assert context.nearby_outline[0]["number"] == 1
    assert context.character_cards[0]["role"] == "protagonist"
    assert context.continuity_ledger == [
        {"subject": "", "field": "fact", "value": "主角仍是一级。"}
    ]


def test_writer_context_falls_back_to_legacy_when_story_system_is_partial(
    tmp_path: Path,
):
    _seed_legacy_project(tmp_path, with_outline=True)
    (tmp_path / ".story-system" / "workflow").mkdir(parents=True)
    state_path = tmp_path / ".webnovel" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["world_facts"] = ["鍔涢噺浣撶郴浜嬪疄"]
    state["progression_ledger"] = {
        "continuity_ledger": [
            {"subject": "主角", "field": "level", "value": 1}
        ]
    }
    _write_json(state_path, state)
    artifact = DirectorArtifact(
        chapter_number=1,
        chapter_goal="涓婂北",
        opening_state="",
        scene_beats=[],
        ending_state="",
        hook="",
        entity_requirements=[],
    )

    context = _ensure_writer_context(
        project_root=tmp_path,
        chapter_number=1,
        director_artifact=artifact,
    )

    assert context.character_cards[0]["role"] == "protagonist"
    assert context.world_rules == ["鍔涢噺浣撶郴浜嬪疄"]
    assert context.continuity_facts == [
        {"subject": "主角", "field": "level", "value": 1}
    ]


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


def test_orchestrator_writes_per_stage_artifacts_to_workflow_store(tmp_path: Path):
    """The orchestrator records every stage in the workflow store.

    The user feedback after Task 13 flagged that the
    :class:`WorkflowArtifactStore` was implemented and unit-tested
    but never actually called by the generation flow. This test
    drives the orchestrator's modular entry point with a real
    project and asserts all three stage artifacts land on disk
    under ``.story-system/workflow/{job_id}/``.

    The workbench reads these files on page refresh to show the
    operator what each agent saw and produced without re-running
    the pipeline.
    """
    project_root = tmp_path
    _seed_legacy_project(project_root, with_outline=False)

    director_runtime = _StubDirectorRuntime()
    writer_runtime = _StubWriterRuntime(body="林昭提灯上山，夜宿山腰。")

    orchestrator = StoryOrchestrator(use_modular_agents=True)
    job_id = "test-job-chapter-1"
    bundle = orchestrator.generate_next_chapter_via_modular_pipeline(
        project_root=project_root,
        chapter_number=1,
        director_runtime=director_runtime,
        writer_runtime=writer_runtime,
        job_id=job_id,
    )

    assert isinstance(bundle, ModularChapterBundle)

    # All three stage artifacts must be on disk under the job
    # directory the orchestrator picks.
    workflow_dir = project_root / ".story-system" / "workflow" / job_id
    assert workflow_dir.is_dir(), workflow_dir
    stage_files = sorted(path.name for path in workflow_dir.glob("*.json"))
    assert stage_files == ["director.json", "fact-extractor.json", "writer.json"]

    # The director record carries the artifact path so the
    # workbench can link to it.
    director_record = json.loads(
        (workflow_dir / "director.json").read_text(encoding="utf-8")
    )
    assert director_record["stage_id"] == "director"
    assert director_record["agent_id"] == "DirectorAgent"
    assert director_record["status"] == "done"
    # ``artifact_path`` uses native separators on Windows; the
    # workbench normalises to posix so we just check the tail.
    assert director_record["artifact_path"].replace("\\", "/").endswith(
        "director/0001.json"
    )
    assert director_record["output_summary"].startswith("chapter_goal='上山'")

    # The writer record carries the body sha256 so the
    # workbench can prove the prose is what the model produced.
    writer_record = json.loads(
        (workflow_dir / "writer.json").read_text(encoding="utf-8")
    )
    assert writer_record["stage_id"] == "writer"
    assert writer_record["agent_id"] == "WriterAgent"
    assert writer_record["artifact_sha256"] != ""
    assert writer_record["output_summary"].startswith("body_chars=")

    # The fact-extractor record is small but always lands.
    extractor_record = json.loads(
        (workflow_dir / "fact-extractor.json").read_text(encoding="utf-8")
    )
    assert extractor_record["stage_id"] == "fact-extractor"
    assert extractor_record["agent_id"] == "FactExtractor"
    assert extractor_record["status"] == "done"


def test_orchestrator_runs_focused_consistency_review(tmp_path: Path):
    """The writer stage must run the focused consistency review
    and surface the findings on the bundle, not hard-code pass=True.
    """
    project_root = tmp_path
    _seed_legacy_project(project_root, with_outline=False)

    director_runtime = _StubDirectorRuntime()
    writer_runtime = _StubWriterRuntime(body="林昭提灯上山，夜宿山腰。")
    consistency_runtime = _StubConsistencyRuntime()

    orchestrator = StoryOrchestrator(use_modular_agents=True)
    bundle = orchestrator.generate_next_chapter_via_modular_pipeline(
        project_root=project_root,
        chapter_number=1,
        director_runtime=director_runtime,
        writer_runtime=writer_runtime,
        consistency_runtime=consistency_runtime,
    )

    # The consistency runtime was hit exactly once during the
    # writer stage and the blocking finding came through.
    assert len(consistency_runtime.calls) == 1
    assert isinstance(bundle, ModularChapterBundle)
    assert len(bundle.consistency_findings) == 1
    finding = bundle.consistency_findings[0]
    assert finding["code"] == "canon_violation"
    assert finding["blocking"] is True

    # The bundle's writing_review reflects the real finding
    # (pass=False) instead of the old hard-coded True.
    legacy_bundle = orchestrator._generate_next_chapter_bundle_via_modular_agents(
        _make_stub_story_state(current_chapter=0),
        project_root=project_root,
        director_runtime=director_runtime,
        writer_runtime=writer_runtime,
        consistency_runtime=consistency_runtime,
    )
    writing_review = legacy_bundle.quality_report["writing_review"]
    assert writing_review["pass"] is False
    assert "canon_violation" in writing_review["issues"]


def _make_stub_story_state(*, current_chapter: int) -> Any:
    """Build a minimal :class:`StoryState` the orchestrator accepts
    in the new ``_generate_next_chapter_bundle_via_modular_agents``
    path. The function only needs the field the orchestrator reads
    (current_chapter) so we can build a one-off via the model's
    validators.
    """
    from packages.story_core.models import (
        AgentRuntimeState,
        AgentSettings,
        StoryState,
    )

    return StoryState(
        story_id="s-test",
        title="测试",
        outline="",
        genre="",
        style="",
        current_chapter=current_chapter,
        characters=[],
        world_facts=[],
        agent_settings=AgentSettings(),
        agent_runtime=AgentRuntimeState(),
    )


def test_orchestrator_loads_canon_registry_from_project_root(tmp_path: Path):
    """The pipeline must see the on-disk canon registry.

    The user feedback after Round 4 flagged that the production
    flow was extracting facts against an empty canon, so
    long-running projects silently lost every entity the user
    had confirmed. This test seeds a registry file under
    ``.story-system/canon/registry.json`` and asserts the next
    chapter's pipeline sees it.
    """
    from packages.story_core.canon.registry import CanonRegistry
    from packages.story_core.orchestrator import _load_canon_registry_for_project_root

    project_root = tmp_path
    canon_dir = project_root / ".story-system" / "canon"
    canon_dir.mkdir(parents=True, exist_ok=True)
    seed_registry = CanonRegistry()
    seed_registry.add_character(name="林昭", aliases=["主角"])
    (canon_dir / "registry.json").write_text(
        json.dumps(
            {
                "schema_version": "canon-registry/v1",
                "by_id": {
                    entity.entity_id: {
                        "entity_id": entity.entity_id,
                        "kind": entity.kind,
                        "display_name": entity.display_name,
                        "aliases": list(entity.aliases),
                        "lifecycle": entity.lifecycle,
                        "extensions": dict(entity.extensions or {}),
                    }
                    for entity in seed_registry.list_all()
                },
                "relationships": [],
                "timeline": [],
                "foreshadowing": [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # The orchestrator's loader surfaces the seeded entity.
    loaded = _load_canon_registry_for_project_root(project_root)
    assert loaded.resolve("林昭", "character") is not None
    assert loaded.resolve("主角", "character") is not None

    # And a brand-new project (no registry file) returns an
    # empty registry, never raises.
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    empty = _load_canon_registry_for_project_root(fresh)
    assert empty.list_all("character") == []


def test_modular_orchestrator_carries_continuity_delta_onto_legacy_bundle(
    tmp_path: Path,
) -> None:
    """The legacy ``ChapterBundle`` produced by the modular
    orchestrator must carry the new pipeline's ``ContinuityDelta``
    so ``_save_candidate_from_bundle`` can skip the parallel
    re-extract against an empty canon.

    The user feedback after Round 5 flagged that the delta was
    silently dropped at the conversion boundary — the candidate
    then re-extracted against the same empty canon the modular
    pipeline just produced findings for, and the new agents'
    findings never made it into the snapshot or the
    confirmation transaction.
    """
    from packages.story_core.engine import ChapterBundle

    project_root = tmp_path
    _seed_legacy_project(project_root, with_outline=False)

    director_runtime = _StubDirectorRuntime()
    writer_runtime = _StubWriterRuntime(body="林昭提灯上山。")

    orchestrator = StoryOrchestrator(use_modular_agents=True)
    legacy_bundle = orchestrator._generate_next_chapter_bundle_via_modular_agents(
        _make_stub_story_state(current_chapter=0),
        project_root=project_root,
        director_runtime=director_runtime,
        writer_runtime=writer_runtime,
    )
    assert isinstance(legacy_bundle, ChapterBundle)
    # The new ``continuity_delta`` field is set; legacy code that
    # checks ``getattr(bundle, "continuity_delta", None)`` will
    # pick it up instead of re-extracting.
    assert legacy_bundle.continuity_delta is not None
    assert legacy_bundle.continuity_delta.chapter_number == 1
    # The fact-extractor's chapter number is also surfaced on the
    # quality_report so the workbench renders the new trace id.
    modular_meta = legacy_bundle.quality_report["modular_pipeline"]
    assert modular_meta["fact_extractor_chapter"] == 1
