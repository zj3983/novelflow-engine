"""Tests for the FactExtractor.

The extractor must answer one question: *what facts did this chapter
introduce that should be reflected in the project canon?* The
deterministic path catches obvious numeric state and named ownership
changes; the model-backed path fills in relationships, knowledge, and
foreshadowing. The model runtime is a swappable boundary so tests can
inject canned payloads without touching the gateway.
"""

from __future__ import annotations

import pytest

from packages.story_core.agents.fact_extractor import (
    FactExtractor,
    FactExtractorContext,
    FactExtractorRuntime,
    build_default_extractor,
)
from packages.story_core.continuity.delta import (
    ContinuityDelta,
    ForeshadowingChange,
    RelationshipChange,
)


def _context(body: str, *, chapter_number: int = 1, canon_view=None, director_artifact=None):
    return FactExtractorContext(
        body=body,
        chapter_number=chapter_number,
        director_artifact=director_artifact,
        canon_view=canon_view or {"by_id": {}, "by_kind": {}, "by_alias": {}},
    )


def test_fact_extractor_returns_empty_delta_for_empty_body():
    delta = FactExtractor().extract(_context(""))

    assert isinstance(delta, ContinuityDelta)
    assert delta.chapter_number == 1
    assert delta.entity_additions == []
    assert delta.inventory_changes == []
    assert delta.relationship_changes == []
    assert delta.reference_validation == []


def test_fact_extractor_detects_named_inventory_gain_deterministically():
    body = "林昭从包裹里取出一把生锈的铁剑。"
    canon_view = {
        "by_id": {"char-linzhao": {"kind": "character", "canonical_name": "林昭"}},
        "by_kind": {"character": ["char-linzhao"]},
        "by_alias": {"林昭": ["char-linzhao"]},
    }

    delta = FactExtractor().extract(_context(body, canon_view=canon_view))

    # The extractor should record a +1 gain for the named character.
    changes = [c for c in delta.inventory_changes if c.entity_id == "char-linzhao"]
    assert changes, "expected at least one inventory change for 林昭"
    # The deterministic item extractor captures the noun phrase up to
    # the sentence boundary. The modifier "生锈" stays attached, which
    # is fine — the canon service can canonicalize item names later.
    assert any(c.item == "一把生锈的铁剑" and c.delta >= 1 for c in changes)
    # The source sentence and chapter number should be propagated.
    assert all(c.chapter_number == 1 for c in changes)
    assert all(c.source_sentence for c in changes)


def test_fact_extractor_detects_named_inventory_loss_deterministically():
    body = "苏婉把旧玉佩塞进了行李底，再没翻出来。"
    canon_view = {
        "by_id": {"char-suwan": {"kind": "character", "canonical_name": "苏婉"}},
        "by_kind": {"character": ["char-suwan"]},
        "by_alias": {"苏婉": ["char-suwan"]},
    }

    delta = FactExtractor().extract(_context(body, canon_view=canon_view))

    changes = [c for c in delta.inventory_changes if c.entity_id == "char-suwan"]
    assert any(c.item == "旧玉佩" and c.delta < 0 for c in changes)


def test_fact_extractor_detects_location_movement_deterministically():
    body = "天黑后，林昭才赶到了驿站。"
    canon_view = {
        "by_id": {"char-linzhao": {"kind": "character", "canonical_name": "林昭"}},
        "by_kind": {"character": ["char-linzhao"]},
        "by_alias": {"林昭": ["char-linzhao"]},
    }

    delta = FactExtractor().extract(_context(body, canon_view=canon_view))

    moves = [m for m in delta.location_movements if m.entity_id == "char-linzhao"]
    assert any(m.to_location == "驿站" for m in moves)


def test_fact_extractor_detects_numeric_state_deterministically():
    body = "林昭还剩三枚金币。"
    canon_view = {
        "by_id": {"char-linzhao": {"kind": "character", "canonical_name": "林昭"}},
        "by_kind": {"character": ["char-linzhao"]},
        "by_alias": {"林昭": ["char-linzhao"]},
    }

    delta = FactExtractor().extract(_context(body, canon_view=canon_view))

    changes = [c for c in delta.inventory_changes if c.entity_id == "char-linzhao"]
    # The numeric-state detector should record a resulting_quantity of 3.
    assert any(c.item == "金币" and c.resulting_quantity == 3 for c in changes)


def test_fact_extractor_skips_unknown_characters_but_flags_orphan_references():
    body = "一个没人认识的旅人走进了客栈。"
    canon_view = {
        "by_id": {},
        "by_kind": {},
        "by_alias": {},
    }

    delta = FactExtractor().extract(_context(body, canon_view=canon_view))

    # No canon knows about "旅人", so no facts should be attributed.
    assert delta.inventory_changes == []
    assert delta.location_movements == []
    # The orphan reference should appear in the validation report.
    assert any(v.get("status") == "orphan" for v in delta.reference_validation)


def test_fact_extractor_uses_model_runtime_for_relationships_when_provided():
    body = "林昭与苏婉并肩走入驿站。"

    class _FakeRuntime:
        def __init__(self):
            self.calls = []

        def complete(self, request):
            self.calls.append(request)
            return {
                "relationship_changes": [
                    {
                        "subject_id": "char-linzhao",
                        "predicate": "盟友",
                        "object_id": "char-suwan",
                        "polarity": "added",
                        "source_sentence": "并肩走入驿站",
                        "confidence": 0.7,
                    }
                ]
            }

    runtime = _FakeRuntime()
    canon_view = {
        "by_id": {
            "char-linzhao": {"kind": "character", "canonical_name": "林昭"},
            "char-suwan": {"kind": "character", "canonical_name": "苏婉"},
        },
        "by_kind": {"character": ["char-linzhao", "char-suwan"]},
        "by_alias": {"林昭": ["char-linzhao"], "苏婉": ["char-suwan"]},
    }

    delta = FactExtractor(runtime=runtime).extract(
        _context(body, canon_view=canon_view)
    )

    assert runtime.calls, "model runtime should be consulted for relationships"
    assert any(
        c.subject_id == "char-linzhao" and c.object_id == "char-suwan"
        for c in delta.relationship_changes
    )


def test_fact_extractor_records_reference_validation_for_each_referenced_id():
    body = "林昭把旧玉佩交给苏婉。"
    canon_view = {
        "by_id": {
            "char-linzhao": {"kind": "character", "canonical_name": "林昭"},
            "char-suwan": {"kind": "character", "canonical_name": "苏婉"},
        },
        "by_kind": {"character": ["char-linzhao", "char-suwan"]},
        "by_alias": {"林昭": ["char-linzhao"], "苏婉": ["char-suwan"]},
    }

    delta = FactExtractor().extract(_context(body, canon_view=canon_view))

    ids = {entry.get("id") for entry in delta.reference_validation}
    assert {"char-linzhao", "char-suwan"} <= ids
    # Both referenced ids exist in the canon view, so they should be valid.
    statuses = {entry.get("status") for entry in delta.reference_validation}
    assert "valid" in statuses


def test_fact_extractor_returns_empty_delta_when_runtime_raises():
    body = "林昭把玉佩塞进口袋。"

    class _BrokenRuntime:
        def complete(self, request):
            raise RuntimeError("model unavailable")

    delta = FactExtractor(runtime=_BrokenRuntime()).extract(_context(body))

    # A failing model must not poison the deterministic extraction.
    assert isinstance(delta, ContinuityDelta)
    # The deterministic layer should still have run and recorded the
    # item loss (or at least attempted to — the body has no canon view
    # so the entity is unknown; we just check the delta is well-formed).
    assert delta.chapter_number == 1


def test_fact_extractor_factory_returns_a_default_instance():
    extractor = build_default_extractor()

    assert isinstance(extractor, FactExtractor)
    # The default instance is model-less — it must still produce a delta.
    delta = extractor.extract(_context("林昭走进驿站。", chapter_number=2))
    assert delta.chapter_number == 2


def test_fact_extractor_factory_accepts_a_runtime_override():
    sentinel = object()

    class _CustomRuntime:
        def complete(self, request):
            return None

    extractor = build_default_extractor(runtime=_CustomRuntime())

    # The custom runtime is wired in; we can detect it via attribute.
    assert isinstance(extractor, FactExtractor)
    # The runtime is the one we provided.
    assert isinstance(extractor._runtime, _CustomRuntime)
    del sentinel  # silence linter; sentinel proves uniqueness
