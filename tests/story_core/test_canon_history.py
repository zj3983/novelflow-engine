"""Focused tests for the forward-only Canon history/replay authority."""

from __future__ import annotations

from packages.story_core.canon.history import (
    CanonBaseline,
    CanonHistory,
    CanonHistoryEvent,
    delta_semantic_hash,
    registry_to_payload,
    replay_canon_history,
    semantic_registry_hash,
)
from packages.story_core.canon.registry import CanonRegistry
from packages.story_core.canon.service import CanonService
from packages.story_core.continuity.delta import (
    ContinuityDelta,
    EntityAddition,
    EntityUpdate,
    ForeshadowingChange,
    LocationMovement,
    RelationshipChange,
    TimelineAdvance,
)


def _event(delta: ContinuityDelta, candidate_id: str, sequence: int) -> CanonHistoryEvent:
    return CanonHistoryEvent.from_delta(
        delta,
        candidate_id=candidate_id,
        sequence=sequence,
        confirmed_at="2026-09-13T00:00:00+00:00",
    )


def _baseline() -> CanonRegistry:
    registry = CanonRegistry()
    registry.add_character(name="林昭", entity_id="char-main", lifecycle="active")
    registry.add_location(name="山脚", entity_id="loc-foothill", lifecycle="active")
    return registry


def test_baseline_and_history_round_trip_preserve_full_delta() -> None:
    delta = ContinuityDelta(
        chapter_number=2,
        entity_additions=[
            EntityAddition(
                chapter_number=2,
                source_sentence="赵六登场",
                entity_id="char-zhao",
                kind="character",
                canonical_name="赵六",
                aliases=["老赵"],
                attributes={"role": "商人"},
            )
        ],
        location_movements=[
            LocationMovement(
                chapter_number=2,
                source_sentence="林昭走到山腰",
                entity_id="char-main",
                from_location="山脚",
                to_location="山腰",
            )
        ],
    )
    baseline = CanonBaseline(registry=registry_to_payload(_baseline()))
    history = CanonHistory.empty()
    history.events.append(_event(delta, "candidate-2", 1))
    history.confirmed_candidates["candidate-2"] = history.events[0].event_id

    restored = CanonHistory.from_dict(history.to_dict())
    assert restored.events[0].continuity_delta["entity_additions"][0]["attributes"] == {"role": "商人"}
    assert restored.events[0].delta_semantic_hash == delta_semantic_hash(delta)
    assert CanonBaseline.from_dict(baseline.to_dict()).registry["by_id"]["char-main"]["display_name"] == "林昭"


def test_forward_replay_is_deterministic_and_preserves_effect_order() -> None:
    baseline = registry_to_payload(_baseline())
    chapter_two = ContinuityDelta(
        chapter_number=2,
        entity_additions=[
            EntityAddition(
                chapter_number=2,
                source_sentence="赵六登场",
                entity_id="char-zhao",
                kind="character",
                canonical_name="赵六",
            )
        ],
        relationship_changes=[
            RelationshipChange(
                chapter_number=2,
                source_sentence="林昭与赵六结盟",
                subject_id="char-main",
                predicate="trusts",
                object_id="char-zhao",
                polarity="added",
            )
        ],
        timeline_advances=[
            TimelineAdvance(chapter_number=2, source_sentence="入夜", marker="入夜"),
            TimelineAdvance(chapter_number=2, source_sentence="钟响", marker="钟响"),
        ],
        foreshadowing_changes=[
            ForeshadowingChange(
                chapter_number=2,
                source_sentence="黑匣子出现",
                foreshadowing_id="f-box",
                action="planted",
                detail="黑匣子",
            )
        ],
    )
    events = [_event(chapter_two, "candidate-2", 1)]
    first = replay_canon_history(baseline, events)
    second = replay_canon_history(baseline, events)
    assert first.status == second.status == "CLEAR"
    assert first.registry is not None and second.registry is not None
    assert semantic_registry_hash(first.registry) == semantic_registry_hash(second.registry)
    assert [item["marker"] for item in first.registry.timeline()] == ["入夜", "钟响"]
    assert first.registry.relationships()[0]["object_id"] == "char-zhao"


def test_replacement_replays_forward_without_inverse_operations() -> None:
    baseline = registry_to_payload(_baseline())
    original = ContinuityDelta(
        chapter_number=2,
        entity_additions=[
            EntityAddition(
                chapter_number=2,
                source_sentence="赵六登场",
                entity_id="char-zhao",
                kind="character",
                canonical_name="赵六",
                attributes={"title": "掌柜"},
            )
        ],
    )
    downstream = ContinuityDelta(
        chapter_number=3,
        entity_updates=[
            EntityUpdate(
                chapter_number=3,
                source_sentence="赵六改名",
                entity_id="char-zhao",
                changes={"title": "掌柜"},
            )
        ],
    )
    replacement = ContinuityDelta(
        chapter_number=2,
        entity_additions=[
            EntityAddition(
                chapter_number=2,
                source_sentence="重写后赵六登场",
                entity_id="char-zhao",
                kind="character",
                canonical_name="赵六",
                attributes={"title": "执事"},
            )
        ],
    )
    replay = replay_canon_history(
        baseline,
        [_event(original, "original", 1), _event(downstream, "candidate-3", 2)],
    )
    assert replay.status == "CLEAR"
    assert replay.registry is not None
    assert replay.registry.get("char-zhao").extensions["title"] == "掌柜"

    replaced = replay_canon_history(
        baseline,
        [_event(replacement, "replacement", 1), _event(downstream, "candidate-3", 2)],
        as_of_chapter=3,
    )
    assert replaced.status == "CLEAR"
    assert replaced.registry is not None
    assert replaced.registry.get("char-zhao").extensions["title"] == "掌柜"


def test_replacing_entity_addition_breaks_downstream_dependency() -> None:
    baseline = registry_to_payload(_baseline())
    replacement = ContinuityDelta(
        chapter_number=2,
        entity_additions=[
            EntityAddition(
                chapter_number=2,
                source_sentence="新版本引入钱七",
                entity_id="char-qian",
                kind="character",
                canonical_name="钱七",
            )
        ],
    )
    downstream = ContinuityDelta(
        chapter_number=3,
        entity_updates=[
            EntityUpdate(
                chapter_number=3,
                source_sentence="赵六改名",
                entity_id="char-zhao",
                changes={"title": "掌柜"},
            )
        ],
    )
    result = replay_canon_history(
        baseline,
        [_event(replacement, "replacement", 1), _event(downstream, "candidate-3", 2)],
    )
    assert result.status == "CONFLICT"
    assert result.first_conflict_chapter == 3
    assert result.first_finding.code == "CANON_RECONCILIATION_ENTITY_MISSING"


def test_downstream_missing_entity_is_first_conflict() -> None:
    baseline = registry_to_payload(_baseline())
    delta = ContinuityDelta(
        chapter_number=4,
        entity_updates=[
            EntityUpdate(
                chapter_number=4,
                source_sentence="未知角色变化",
                entity_id="char-missing",
                changes={"title": "未知"},
            )
        ],
    )
    result = replay_canon_history(baseline, [_event(delta, "candidate-4", 1)])
    assert result.status == "CONFLICT"
    assert result.first_finding is not None
    assert result.first_finding.code == "CANON_RECONCILIATION_ENTITY_MISSING"
    assert result.first_conflict_chapter == 4
    assert result.registry is None


def test_downstream_relationship_and_foreshadow_dependencies_are_strict() -> None:
    baseline = registry_to_payload(_baseline())
    relationship = ContinuityDelta(
        chapter_number=2,
        relationship_changes=[
            RelationshipChange(
                chapter_number=2,
                source_sentence="断裂关系",
                subject_id="char-main",
                predicate="trusts",
                object_id="char-missing",
                polarity="added",
            )
        ],
    )
    relationship_result = replay_canon_history(baseline, [_event(relationship, "candidate-2", 1)])
    assert relationship_result.status == "CONFLICT"
    assert relationship_result.first_finding.code == "CANON_RECONCILIATION_RELATIONSHIP_ENDPOINT_MISSING"

    foreshadow = ContinuityDelta(
        chapter_number=2,
        foreshadowing_changes=[
            ForeshadowingChange(
                chapter_number=2,
                source_sentence="直接揭示",
                foreshadowing_id="f-missing",
                action="resolved",
                detail="没有铺垫",
            )
        ],
    )
    foreshadow_result = replay_canon_history(baseline, [_event(foreshadow, "candidate-2", 1)])
    assert foreshadow_result.status == "CONFLICT"
    assert foreshadow_result.first_finding.code == "CANON_RECONCILIATION_FORESHADOWING_INVALID"


def test_location_replay_detects_from_location_mismatch() -> None:
    registry = _baseline()
    registry.update_attributes("char-main", changes={"location": "山脚"})
    baseline = registry_to_payload(registry)
    movement = ContinuityDelta(
        chapter_number=2,
        location_movements=[
            LocationMovement(
                chapter_number=2,
                source_sentence="林昭从山腰离开",
                entity_id="char-main",
                from_location="山腰",
                to_location="山顶",
            )
        ],
    )
    result = replay_canon_history(baseline, [_event(movement, "candidate-2", 1)])
    assert result.status == "CONFLICT"
    assert result.first_finding.code == "CANON_RECONCILIATION_LOCATION_STATE_MISMATCH"


def test_location_replay_validates_multiple_movements_in_delta_order() -> None:
    registry = _baseline()
    registry.update_attributes("char-main", changes={"location": "山脚"})
    baseline = registry_to_payload(registry)
    movement = ContinuityDelta(
        chapter_number=2,
        location_movements=[
            LocationMovement(
                chapter_number=2,
                source_sentence="林昭从山脚走到山腰",
                entity_id="char-main",
                from_location="山脚",
                to_location="山腰",
            ),
            LocationMovement(
                chapter_number=2,
                source_sentence="林昭从山腰走到山顶",
                entity_id="char-main",
                from_location="山腰",
                to_location="山顶",
            ),
        ],
    )

    result = replay_canon_history(baseline, [_event(movement, "candidate-2", 1)])

    assert result.status == "CLEAR"
    assert result.registry is not None
    assert result.registry.get("char-main").extensions["location"] == "山顶"


def test_location_replay_reports_second_ordered_movement_mismatch() -> None:
    registry = _baseline()
    registry.update_attributes("char-main", changes={"location": "山脚"})
    baseline = registry_to_payload(registry)
    movement = ContinuityDelta(
        chapter_number=2,
        location_movements=[
            LocationMovement(
                chapter_number=2,
                source_sentence="林昭从山脚走到山腰",
                entity_id="char-main",
                from_location="山脚",
                to_location="山腰",
            ),
            LocationMovement(
                chapter_number=2,
                source_sentence="林昭从别处走到山顶",
                entity_id="char-main",
                from_location="别处",
                to_location="山顶",
            ),
        ],
    )

    result = replay_canon_history(baseline, [_event(movement, "candidate-2", 1)])

    assert result.status == "CONFLICT"
    assert result.first_finding is not None
    assert result.first_finding.code == "CANON_RECONCILIATION_LOCATION_STATE_MISMATCH"
    assert "山腰" in result.first_finding.message


def test_location_entity_update_precedes_ordered_movement_validation() -> None:
    registry = _baseline()
    registry.update_attributes("char-main", changes={"location": "山脚"})
    baseline = registry_to_payload(registry)
    delta = ContinuityDelta(
        chapter_number=2,
        entity_updates=[
            EntityUpdate(
                chapter_number=2,
                source_sentence="林昭转移到山腰",
                entity_id="char-main",
                changes={"location": "山腰"},
            )
        ],
        location_movements=[
            LocationMovement(
                chapter_number=2,
                source_sentence="林昭从山腰走到山顶",
                entity_id="char-main",
                from_location="山腰",
                to_location="山顶",
            )
        ],
    )

    result = replay_canon_history(baseline, [_event(delta, "candidate-2", 1)])

    assert result.status == "CLEAR"
    assert result.registry is not None
    assert result.registry.get("char-main").extensions["location"] == "山顶"


def test_existing_entity_addition_does_not_stage_unapplied_location_attributes() -> None:
    registry = _baseline()
    registry.update_attributes("char-main", changes={"location": "A"})
    baseline = registry_to_payload(registry)
    delta = ContinuityDelta(
        chapter_number=2,
        entity_additions=[
            EntityAddition(
                chapter_number=2,
                source_sentence="林昭再次出现",
                entity_id="char-main",
                kind="character",
                canonical_name="林昭",
                attributes={"location": "B"},
            )
        ],
        location_movements=[
            LocationMovement(
                chapter_number=2,
                source_sentence="林昭从B走到C",
                entity_id="char-main",
                from_location="B",
                to_location="C",
            )
        ],
    )

    result = replay_canon_history(baseline, [_event(delta, "candidate-2", 1)])

    assert result.status == "CONFLICT"
    assert result.first_finding is not None
    assert result.first_finding.code == "CANON_RECONCILIATION_LOCATION_STATE_MISMATCH"


def test_new_entity_addition_location_can_seed_following_movement() -> None:
    registry = _baseline()
    baseline = registry_to_payload(registry)
    delta = ContinuityDelta(
        chapter_number=2,
        entity_additions=[
            EntityAddition(
                chapter_number=2,
                source_sentence="赵六登场",
                entity_id="char-zhao",
                kind="character",
                canonical_name="赵六",
                attributes={"location": "B"},
            )
        ],
        location_movements=[
            LocationMovement(
                chapter_number=2,
                source_sentence="赵六从B走到C",
                entity_id="char-zhao",
                from_location="B",
                to_location="C",
            )
        ],
    )

    result = replay_canon_history(baseline, [_event(delta, "candidate-2", 1)])

    assert result.status == "CLEAR"
    assert result.registry is not None
    assert result.registry.get("char-zhao").extensions["location"] == "C"
