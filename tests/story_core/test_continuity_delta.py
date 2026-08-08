"""Tests for the ContinuityDelta schema.

The delta is a structured proposal of facts the writer introduced in
this chapter. Every section defaults to empty so a chapter with no
detected changes still produces a valid (empty) delta. The schema
stays strict (no extra keys) so a malformed writer output cannot leak
into canon.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.story_core.continuity.delta import (
    ContinuityDelta,
    EntityAddition,
    EntityUpdate,
    ForeshadowingChange,
    InventoryChange,
    LocationMovement,
    RelationshipChange,
    TaskProgression,
    TimelineAdvance,
)


def test_continuity_delta_defaults_to_empty_for_a_chapter_with_no_changes():
    delta = ContinuityDelta(chapter_number=7)

    assert delta.chapter_number == 7
    assert delta.entity_additions == []
    assert delta.entity_updates == []
    assert delta.relationship_changes == []
    assert delta.inventory_changes == []
    assert delta.task_progressions == []
    assert delta.location_movements == []
    assert delta.timeline_advances == []
    assert delta.foreshadowing_changes == []
    assert delta.reference_validation == []
    assert delta.schema_version == "continuity-delta/v1"


def test_entity_addition_carries_provenance_and_required_kind():
    addition = EntityAddition(
        chapter_number=3,
        source_sentence="门口站着一个黑衣人",
        confidence=1.0,
        entity_id="char-1a2b3c4d",
        kind="character",
        canonical_name="黑衣人",
        aliases=["神秘人"],
        attributes={"occupation_or_role": "未知"},
    )

    assert addition.kind == "character"
    assert addition.canonical_name == "黑衣人"
    assert addition.aliases == ["神秘人"]
    assert addition.attributes["occupation_or_role"] == "未知"


def test_inventory_change_records_delta_and_optional_resulting_quantity():
    change = InventoryChange(
        chapter_number=4,
        source_sentence="林昭收下了三枚金币",
        confidence=1.0,
        entity_id="char-linzhao",
        item="金币",
        delta=3,
        resulting_quantity=15,
    )

    assert change.delta == 3
    assert change.resulting_quantity == 15


def test_relationship_change_polarity_must_be_a_known_value():
    RelationshipChange(
        chapter_number=1,
        source_sentence="林昭与苏婉结为盟友",
        confidence=0.9,
        subject_id="char-linzhao",
        predicate="盟友",
        object_id="char-suwan",
        polarity="added",
    )

    with pytest.raises(ValidationError):
        RelationshipChange(
            chapter_number=1,
            source_sentence="x",
            confidence=0.5,
            subject_id="char-linzhao",
            predicate="盟友",
            object_id="char-suwan",
            polarity="slightly_added",  # invalid
        )


def test_task_progression_status_is_restricted_to_known_actions():
    TaskProgression(
        chapter_number=5,
        source_sentence="主线任务推进",
        confidence=1.0,
        task_id="quest-main",
        status="advanced",
    )

    with pytest.raises(ValidationError):
        TaskProgression(
            chapter_number=5,
            source_sentence="x",
            confidence=1.0,
            task_id="quest-main",
            status="paused",  # not allowed
        )


def test_foreshadowing_action_must_be_planted_advanced_or_resolved():
    ForeshadowingChange(
        chapter_number=6,
        source_sentence="远处传来钟声",
        confidence=0.8,
        foreshadowing_id="fs-bell",
        action="planted",
        detail="钟声首次出现",
    )

    with pytest.raises(ValidationError):
        ForeshadowingChange(
            chapter_number=6,
            source_sentence="x",
            confidence=0.8,
            foreshadowing_id="fs-bell",
            action="almost_resolved",  # not allowed
        )


def test_location_movement_supports_partial_origin():
    move = LocationMovement(
        chapter_number=2,
        source_sentence="林昭抵达驿站",
        confidence=1.0,
        entity_id="char-linzhao",
        from_location="官道",
        to_location="驿站",
    )

    assert move.from_location == "官道"

    new_only = LocationMovement(
        chapter_number=2,
        source_sentence="一个旅人走进客栈",
        confidence=1.0,
        entity_id="char-traveler",
        to_location="客栈",
    )

    assert new_only.from_location is None


def test_timeline_advance_records_a_marker():
    advance = TimelineAdvance(
        chapter_number=3,
        source_sentence="入夜时分",
        confidence=1.0,
        marker="入夜",
    )

    assert advance.marker == "入夜"


def test_continuity_delta_round_trips_via_dict_with_typed_sections():
    delta = ContinuityDelta(
        chapter_number=9,
        entity_additions=[
            EntityAddition(
                chapter_number=9,
                source_sentence="他腰间挂着一枚旧玉佩",
                confidence=0.7,
                entity_id="item-jade",
                kind="item",
                canonical_name="旧玉佩",
            )
        ],
        inventory_changes=[
            InventoryChange(
                chapter_number=9,
                source_sentence="苏婉失去了一支笔",
                confidence=1.0,
                entity_id="char-suwan",
                item="笔",
                delta=-1,
            )
        ],
    )

    payload = delta.model_dump(mode="json")
    restored = ContinuityDelta.model_validate(payload)

    assert restored == delta
    assert restored.entity_additions[0].canonical_name == "旧玉佩"
    assert restored.inventory_changes[0].delta == -1


def test_continuity_delta_rejects_extra_keys():
    with pytest.raises(ValidationError):
        ContinuityDelta.model_validate(
            {"chapter_number": 1, "phantom_section": [{"x": 1}]}
        )


def test_entity_update_uses_a_changes_dict_not_a_typed_attribute_set():
    update = EntityUpdate(
        chapter_number=4,
        source_sentence="林昭的伤已痊愈",
        confidence=1.0,
        entity_id="char-linzhao",
        changes={"status": "healthy"},
    )

    assert update.changes["status"] == "healthy"
