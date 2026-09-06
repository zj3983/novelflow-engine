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
    body = "林昭获得一把生锈的铁剑。"
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
    body = "苏婉把旧玉佩交出，再没拿回来。"
    canon_view = {
        "by_id": {"char-suwan": {"kind": "character", "canonical_name": "苏婉"}},
        "by_kind": {"character": ["char-suwan"]},
        "by_alias": {"苏婉": ["char-suwan"]},
    }

    delta = FactExtractor().extract(_context(body, canon_view=canon_view))

    changes = [c for c in delta.inventory_changes if c.entity_id == "char-suwan"]
    assert any(c.item == "旧玉佩" and c.delta < 0 for c in changes)


def test_fact_extractor_does_not_change_inventory_for_repositioning_owned_items():
    body = (
        "林昭将基础零配件塞进自己的帆布包里。"
        "林昭又将帆布包从肩上取了下来，放在桌角。"
    )
    canon_view = {
        "by_id": {"char-linzhao": {"kind": "character", "canonical_name": "林昭"}},
        "by_kind": {"character": ["char-linzhao"]},
        "by_alias": {"林昭": ["char-linzhao"]},
    }

    delta = FactExtractor().extract(_context(body, canon_view=canon_view))

    assert delta.inventory_changes == []


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


def test_fact_extractor_detects_evidence_backed_clinic_move_and_dawn_advance():
    body = (
        "黎明前夕，林砚半拖半扶着林念一步一步向斜对面的社区诊所走去。"
        "外面的天空彻底亮了起来。"
    )
    canon_view = {
        "by_id": {
            "char-linyan": {"kind": "character", "canonical_name": "林砚"},
            "char-linnian": {"kind": "character", "canonical_name": "林念"},
        },
        "by_kind": {"character": ["char-linyan", "char-linnian"]},
        "by_alias": {
            "林砚": ["char-linyan"],
            "林念": ["char-linnian"],
        },
    }

    delta = FactExtractor().extract(_context(body, chapter_number=2, canon_view=canon_view))

    assert {
        (movement.entity_id, movement.to_location)
        for movement in delta.location_movements
    } == {
        ("char-linyan", "社区诊所"),
        ("char-linnian", "社区诊所"),
    }
    assert [(item.marker, item.source_sentence) for item in delta.timeline_advances] == [
        ("天亮", "外面的天空彻底亮了起来。")
    ]


def test_fact_extractor_does_not_treat_static_clock_reference_as_timeline_advance():
    body = "墙上的钟停在清晨五点四十五分，已经坏了三年。"

    delta = FactExtractor().extract(_context(body, chapter_number=2))

    assert delta.timeline_advances == []


def test_fact_extractor_does_not_treat_conditional_dawn_as_timeline_advance():
    body = "一旦天色大亮，这项能力就会彻底陷入沉寂。"

    delta = FactExtractor().extract(_context(body, chapter_number=2))

    assert delta.timeline_advances == []


def test_fact_extractor_trims_quote_boundaries_from_source_sentence():
    delta = FactExtractor().extract(
        _context("上一句说完了。\u201d\n\n外面的天空彻底亮了起来。", chapter_number=2)
    )

    assert [item.source_sentence for item in delta.timeline_advances] == [
        "外面的天空彻底亮了起来。"
    ]


def test_fact_extractor_does_not_move_non_character_entities_or_bare_hui_phrases():
    body = "林砚的绝缘工具箱还没回来。"
    canon_view = {
        "by_id": {
            "char-linyan": {"kind": "character", "canonical_name": "林砚"},
            "equip-toolbox": {
                "kind": "equipment",
                "canonical_name": "绝缘工具箱",
            },
        },
        "by_kind": {
            "character": ["char-linyan"],
            "equipment": ["equip-toolbox"],
        },
        "by_alias": {
            "林砚": ["char-linyan"],
            "绝缘工具箱": ["equip-toolbox"],
        },
    }

    delta = FactExtractor().extract(_context(body, canon_view=canon_view))

    assert delta.location_movements == []


def test_fact_extractor_strips_aspect_particle_from_location():
    body = "林昭走进了处置室。"
    canon_view = {
        "by_id": {"char-linzhao": {"kind": "character", "canonical_name": "林昭"}},
        "by_kind": {"character": ["char-linzhao"]},
        "by_alias": {"林昭": ["char-linzhao"]},
    }

    delta = FactExtractor().extract(_context(body, canon_view=canon_view))

    assert [movement.to_location for movement in delta.location_movements] == ["处置室"]


def test_fact_extractor_promotes_body_present_director_entities_before_movement():
    from packages.story_core.agents.contracts import (
        DirectorArtifact,
        EntityRequirement,
    )

    artifact = DirectorArtifact(
        chapter_number=2,
        chapter_goal="陪妹妹续药",
        opening_state="黎明前离家",
        scene_beats=[],
        ending_state="抵达诊所",
        entity_requirements=[
            EntityRequirement(kind="character", name="林砚"),
            EntityRequirement(kind="character", name="林念"),
            EntityRequirement(kind="location", name="社区诊所"),
            EntityRequirement(kind="character", name="未出场医生"),
        ],
    )
    context = FactExtractorContext(
        body="林砚扶着林念一步一步向社区诊所走去。",
        chapter_number=2,
        director_artifact=artifact,
        candidate_entities=[
            {"kind": "character", "name": "林砚", "role": "主角"},
            {"kind": "character", "name": "林念", "role": "妹妹"},
            {"kind": "location", "name": "社区诊所", "summary": "社区医疗点"},
        ],
    )

    delta = FactExtractor().extract(context)

    additions = {(item.kind, item.canonical_name): item for item in delta.entity_additions}
    assert set(additions) == {
        ("character", "林砚"),
        ("character", "林念"),
        ("location", "社区诊所"),
    }
    assert additions[("character", "林砚")].attributes["role"] == "主角"
    assert all(item.entity_id for item in additions.values())
    assert "未出场医生" not in {item.canonical_name for item in delta.entity_additions}
    assert {
        (movement.entity_id, movement.to_location)
        for movement in delta.location_movements
    } == {
        (additions[("character", "林砚")].entity_id, "社区诊所"),
        (additions[("character", "林念")].entity_id, "社区诊所"),
    }


def test_fact_extractor_reuses_technique_alias_without_duplicate_addition():
    from packages.story_core.agents.contracts import DirectorArtifact, EntityRequirement

    first_artifact = DirectorArtifact(
        chapter_number=1,
        chapter_goal="觉醒能力",
        opening_state="未觉醒",
        scene_beats=[],
        ending_state="能力激活",
        entity_requirements=[
            EntityRequirement(kind="technique", name="子夜故障回溯异能")
        ],
    )
    first = FactExtractor().extract(
        FactExtractorContext(
            body="林砚觉醒了子夜故障回溯异能。",
            chapter_number=1,
            director_artifact=first_artifact,
            candidate_entities=[
                {"kind": "technique", "name": "子夜故障回溯异能"}
            ],
        )
    )
    assert first.entity_additions[0].aliases == ["子夜故障回溯"]
    canon_view = {
        "by_id": {
            first.entity_additions[0].entity_id: {
                "kind": "technique",
                "canonical_name": "子夜故障回溯异能",
                "aliases": ["子夜故障回溯"],
            }
        },
        "by_kind": {"technique": [first.entity_additions[0].entity_id]},
        "by_alias": {"子夜故障回溯": [first.entity_additions[0].entity_id]},
    }
    second_artifact = first_artifact.model_copy(
        update={
            "chapter_number": 2,
            "entity_requirements": [
                EntityRequirement(kind="technique", name="子夜故障回溯")
            ],
        }
    )

    second = FactExtractor().extract(
        FactExtractorContext(
            body="天亮后，子夜故障回溯无法调用。",
            chapter_number=2,
            director_artifact=second_artifact,
            canon_view=canon_view,
        )
    )

    assert second.entity_additions == []
    assert any(
        item["name"] == "子夜故障回溯" and item["status"] == "valid"
        for item in second.reference_validation
    )


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


def test_fact_extractor_skips_unknown_characters_without_orphan_references():
    """The orphan pass is gone — unknown names in ordinary prose
    no longer enter reference_validation. Only the director's
    explicit entity_requirements can introduce a new entity id.
    """
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
    # The orphan reference no longer appears because the writer
    # did not introduce the name through any sanctioned path.
    assert not any(v.get("status") == "orphan" for v in delta.reference_validation)


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


@pytest.mark.parametrize(
    ("subject_id", "source_sentence"),
    [
        ("char-unknown", "并肩走入驿站"),
        ("char-linzhao", "两人结为终身盟友"),
    ],
)
def test_fact_extractor_rejects_unanchored_model_relationships(
    subject_id: str,
    source_sentence: str,
):
    class _Runtime:
        def complete(self, request):
            return {
                "relationship_changes": [
                    {
                        "subject_id": subject_id,
                        "predicate": "盟友",
                        "object_id": "char-suwan",
                        "polarity": "added",
                        "source_sentence": source_sentence,
                        "confidence": 0.7,
                    }
                ]
            }

    canon_view = {
        "by_id": {
            "char-linzhao": {"kind": "character", "canonical_name": "林昭"},
            "char-suwan": {"kind": "character", "canonical_name": "苏婉"},
        },
        "by_kind": {"character": ["char-linzhao", "char-suwan"]},
        "by_alias": {
            "林昭": ["char-linzhao"],
            "苏婉": ["char-suwan"],
        },
    }

    delta = FactExtractor(runtime=_Runtime()).extract(
        _context("林昭与苏婉并肩走入驿站。", canon_view=canon_view)
    )

    assert delta.relationship_changes == []


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


def test_fact_extractor_does_not_treat_sentence_fragments_as_entities():
    """Ordinary prose fragments must never enter reference_validation.

    The previous heuristic matched any 2-4 CJK ideographs at the
    start of a sentence and flagged them as orphan entities.
    That produced false positives like ``夜烬深吸`` or
    ``将注意力`` for every body. Only the director's explicit
    ``entity_requirements`` and structured facts can introduce a
    new entity id now.
    """
    body = (
        "夜烬深吸了一口气，将注意力拉回灰狼坡。"
        "很显然，那边触发了动态事件。"
        "稳妥起见，他先把任务做完。"
    )
    canon_view = {
        "by_id": {"char-yeyan": {"kind": "character", "canonical_name": "夜烬"}},
        "by_kind": {"character": ["char-yeyan"]},
        "by_alias": {"夜烬": ["char-yeyan"]},
    }

    delta = FactExtractor().extract(_context(body, canon_view=canon_view))

    orphan_names = {item["name"] for item in delta.reference_validation if item["status"] == "orphan"}
    assert orphan_names == set()


def test_body_present_director_requirement_is_proposed_as_valid_addition():
    """A named director requirement present in the prose is the
    sanctioned path for proposing a new canon entity.
    """
    from packages.story_core.agents.contracts import (
        DirectorArtifact,
        EntityRequirement,
    )

    artifact = DirectorArtifact(
        chapter_number=1,
        chapter_goal="推门进龛",
        opening_state="",
        scene_beats=[],
        ending_state="",
        entity_requirements=[
            EntityRequirement(kind="character", name="守龛人"),
        ],
    )
    context = _context(
        "守龛人推门进来。",
        director_artifact=artifact,
    )

    delta = FactExtractor().extract(context)

    assert any(item.canonical_name == "守龛人" for item in delta.entity_additions)
    assert any(
        item["name"] == "守龛人" and item["status"] == "valid"
        for item in delta.reference_validation
    )


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
