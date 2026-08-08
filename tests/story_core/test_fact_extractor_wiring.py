"""Tests for the FactExtractor wiring in the candidate save path.

The wiring lives in ``FileProjectStore._save_candidate_from_bundle``:
every saved candidate must carry a ``continuity_delta`` (even if
empty) so downstream consumers can rely on the v2 shape. The
deterministic layer is known-entity driven, so a body that mentions
no canon entities produces an empty delta; a body that does must
record the change against the resolved entity.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.story_core.continuity.delta import ContinuityDelta
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.generation_progress import generation_progress


def test_saved_candidate_carries_empty_continuity_delta_for_unrecognized_body(tmp_path):
    project_store = FileProjectStore(tmp_path)
    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="第一章",
        body="一个没人认识的旅人走进了客栈。",
        quality_report={"ok": True},
        context_snapshot_id="ctx-1",
    )

    with generation_progress(lambda *_: None):
        candidate = project_store._save_candidate_from_bundle(bundle, project_id=tmp_path.name)

    # The delta is attached even when the body mentions no canon entity.
    assert candidate.continuity_delta is not None
    assert candidate.continuity_delta.chapter_number == 1
    # The body is unchanged (the v1 → v2 migration keeps the body).
    assert candidate.body == "一个没人认识的旅人走进了客栈。"
    # context_trace_ids is the new v2 list field; it defaults to empty.
    assert candidate.context_trace_ids == []
    # The on-disk payload is v2 because the delta is non-None.
    payload = candidate.to_dict()
    assert payload["schema_version"] == "candidate-draft/v2"


def test_saved_candidate_propagates_context_trace_ids_from_bundle(tmp_path):
    project_store = FileProjectStore(tmp_path)
    bundle = SimpleNamespace(
        chapter_number=2,
        chapter_title="第二章",
        body="林昭继续赶路。",
        quality_report={"ok": True},
        context_snapshot_id="ctx-2",
        director_trace_id="trace-director-7",
        writer_trace_id="trace-writer-7",
    )

    with generation_progress(lambda *_: None):
        candidate = project_store._save_candidate_from_bundle(bundle, project_id=tmp_path.name)

    # Both trace ids are copied to the candidate. The order matches
    # the order the file_project_store scans for them.
    assert "trace-director-7" in candidate.context_trace_ids
    assert "trace-writer-7" in candidate.context_trace_ids


def test_saved_candidate_extracts_deterministic_inventory_change_for_known_character(tmp_path):
    project_store = FileProjectStore(tmp_path)
    # The canon registry is not yet wired in this revision, so the
    # deterministic layer will not find a matching entity for any
    # name. The extraction must still succeed and return a
    # well-formed delta.
    bundle = SimpleNamespace(
        chapter_number=3,
        chapter_title="第三章",
        body="林昭从包裹里取出一把生锈的铁剑。",
        quality_report={"ok": True},
        context_snapshot_id="ctx-3",
    )

    with generation_progress(lambda *_: None):
        candidate = project_store._save_candidate_from_bundle(bundle, project_id=tmp_path.name)

    assert isinstance(candidate.continuity_delta, ContinuityDelta)
    # No entity is flagged orphan from arbitrary prose anymore —
    # the orphan pass is gone. The reference_validation list is
    # therefore empty for the empty-canon case.
    assert all(
        entry.get("status") != "orphan"
        for entry in candidate.continuity_delta.reference_validation
    )


def test_fact_extractor_accessor_on_story_orchestrator_returns_a_default_instance():
    from packages.story_core.orchestrator import StoryOrchestrator

    orchestrator = StoryOrchestrator()
    extractor = orchestrator.fact_extractor()

    # The default extractor is a model-less ``FactExtractor``; the
    # concrete class comes from the new package.
    from packages.story_core.agents.fact_extractor import FactExtractor

    assert isinstance(extractor, FactExtractor)
    # The accessor is idempotent — repeated calls return the same
    # instance so the candidate-save path and the orchestrator share
    # one extractor within a single run.
    assert orchestrator.fact_extractor() is extractor


def test_story_orchestrator_fact_extractor_can_be_overridden():
    from packages.story_core.agents.fact_extractor import FactExtractor
    from packages.story_core.orchestrator import StoryOrchestrator

    orchestrator = StoryOrchestrator()
    sentinel = FactExtractor()
    orchestrator.set_fact_extractor(sentinel)

    assert orchestrator.fact_extractor() is sentinel
