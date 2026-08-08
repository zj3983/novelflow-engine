"""Tests for ``CanonService.apply_delta``.

The user feedback after Tasks 10-14 called out that the
``ContinuityDelta`` produced by the fact-extractor was only
written as a snapshot summary — never actually applied to
characters, items, relationships, or facts. This test module
pins the new ``CanonService.apply_delta`` behaviour: every
operation type on the delta must translate into a real change
on the registry so the next chapter's director context sees
the world the user actually confirmed.
"""

from __future__ import annotations

import pytest

from packages.story_core.agents.contracts import EntityRequirement
from packages.story_core.canon.entity_designer import EntityDesigner
from packages.story_core.canon.registry import CanonRegistry
from packages.story_core.canon.service import CanonService, EntityPreflightFailed
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


class _RecordingDesigner:
    """Return a stub ``CanonEntity`` with the requested id and name.

    The designer is the production seam for a real model call;
    the apply_delta tests only need a designer that does not
    raise so the service can be constructed cleanly. They
    never call ``ensure_requirements`` so the designer's
    return value never matters.
    """

    def design(
        self, requirement: EntityRequirement, registry: CanonRegistry
    ):  # pragma: no cover - unused
        raise AssertionError("apply_delta tests must not call the designer")


@pytest.fixture
def service() -> CanonService:
    registry = CanonRegistry()
    return CanonService(registry=registry, designer=_RecordingDesigner())


def test_apply_delta_none_returns_zero_counts(service: CanonService) -> None:
    """A ``None`` delta is a no-op the orchestrator can pass through."""
    counts = service.apply_delta(None)
    assert counts == {
        "entity_additions": 0,
        "entity_updates": 0,
        "relationship_changes": 0,
        "inventory_changes": 0,
        "task_progressions": 0,
        "location_movements": 0,
        "timeline_advances": 0,
        "foreshadowing_changes": 0,
    }


def test_apply_delta_rejects_non_delta_input(service: CanonService) -> None:
    """Anything that is not a ``ContinuityDelta`` raises ``TypeError``."""
    with pytest.raises(TypeError, match="apply_delta_expected_continuity_delta"):
        service.apply_delta({"chapter_number": 1})  # type: ignore[arg-type]


def test_apply_delta_adds_new_entities(service: CanonService) -> None:
    """``EntityAddition`` entries land in the registry as new active cards."""
    delta = ContinuityDelta(
        chapter_number=3,
        entity_additions=[
            EntityAddition(
                chapter_number=3,
                source_sentence="林昭第一次出场",
                entity_id="char-aaaa1111",
                kind="character",
                canonical_name="林昭",
                aliases=["林公子"],
            ),
            EntityAddition(
                chapter_number=3,
                source_sentence="一枚古玉佩",
                entity_id="item-bbbb2222",
                kind="item",
                canonical_name="古玉佩",
                attributes={"material": "jade"},
            ),
        ],
    )
    counts = service.apply_delta(delta)
    assert counts["entity_additions"] == 2

    char = service.registry.get("char-aaaa1111")
    assert char is not None
    assert char.display_name == "林昭"
    assert char.lifecycle == "active"
    assert "林公子" in char.aliases

    item = service.registry.get("item-bbbb2222")
    assert item is not None
    assert (item.extensions or {}).get("material") == "jade"


def test_apply_delta_is_idempotent_for_entity_additions(service: CanonService) -> None:
    """Re-applying the same addition promotes the existing entity without error."""
    addition = EntityAddition(
        chapter_number=1,
        source_sentence="首次出场",
        entity_id="char-aaaa1111",
        kind="character",
        canonical_name="林昭",
    )
    delta = ContinuityDelta(chapter_number=1, entity_additions=[addition])
    first = service.apply_delta(delta)
    second = service.apply_delta(delta)
    assert first["entity_additions"] == 1
    assert second["entity_additions"] == 1
    char = service.registry.get("char-aaaa1111")
    assert char is not None
    assert char.lifecycle == "active"


def test_apply_delta_patches_existing_entity_extensions(service: CanonService) -> None:
    """``EntityUpdate`` shallow-patches the entity's ``extensions`` field."""
    # Seed an entity with an initial extension.
    service.registry.add(
        kind="character",
        name="林昭",
        entity_id="char-aaaa1111",
        lifecycle="active",
        extensions={"location": "山脚"},
    )
    delta = ContinuityDelta(
        chapter_number=2,
        entity_updates=[
            EntityUpdate(
                chapter_number=2,
                source_sentence="林昭继续上山",
                entity_id="char-aaaa1111",
                changes={"location": "山腰", "mood": "疲惫"},
            )
        ],
    )
    counts = service.apply_delta(delta)
    assert counts["entity_updates"] == 1
    char = service.registry.get("char-aaaa1111")
    assert char is not None
    assert char.extensions["location"] == "山腰"
    assert char.extensions["mood"] == "疲惫"


def test_apply_delta_records_relationship_edges(service: CanonService) -> None:
    """``RelationshipChange`` stores edges with chapter + provenance."""
    delta = ContinuityDelta(
        chapter_number=4,
        relationship_changes=[
            RelationshipChange(
                chapter_number=4,
                source_sentence="林昭与苏婉对视",
                subject_id="char-aaaa1111",
                predicate="trusts",
                object_id="char-bbbb2222",
                polarity="added",
            ),
        ],
    )
    counts = service.apply_delta(delta)
    assert counts["relationship_changes"] == 1
    edges = service.registry.relationships(subject_id="char-aaaa1111")
    assert len(edges) == 1
    assert edges[0]["predicate"] == "trusts"
    assert edges[0]["polarity"] == "added"
    assert edges[0]["chapter_number"] == 4


def test_apply_delta_patches_inventory_quantity(service: CanonService) -> None:
    """``InventoryChange`` accumulates the signed delta into ``extensions.inventory``."""
    service.registry.add(
        kind="character",
        name="林昭",
        entity_id="char-aaaa1111",
        lifecycle="active",
        extensions={"inventory": {"古玉佩": {"quantity": 1}}},
    )
    delta = ContinuityDelta(
        chapter_number=5,
        inventory_changes=[
            InventoryChange(
                chapter_number=5,
                source_sentence="林昭拾得另一枚",
                entity_id="char-aaaa1111",
                item="古玉佩",
                delta=1,
            ),
            InventoryChange(
                chapter_number=5,
                source_sentence="林昭送出一枚",
                entity_id="char-aaaa1111",
                item="古玉佩",
                delta=-1,
            ),
        ],
    )
    counts = service.apply_delta(delta)
    assert counts["inventory_changes"] == 2
    char = service.registry.get("char-aaaa1111")
    inventory = (char.extensions or {}).get("inventory") or {}
    assert inventory["古玉佩"]["quantity"] == 1
    assert inventory["古玉佩"]["last_chapter"] == 5


def test_apply_delta_marks_task_status(service: CanonService) -> None:
    """``TaskProgression`` patches the quest entity's status field."""
    service.registry.add(
        kind="quest",
        name="寻找古玉佩",
        entity_id="quest-aaaa1111",
        lifecycle="active",
        extensions={"status": "planted"},
    )
    delta = ContinuityDelta(
        chapter_number=6,
        task_progressions=[
            TaskProgression(
                chapter_number=6,
                source_sentence="林昭找到了第一枚",
                task_id="quest-aaaa1111",
                status="advanced",
                notes="进度：25%",
            )
        ],
    )
    counts = service.apply_delta(delta)
    assert counts["task_progressions"] == 1
    quest = service.registry.get("quest-aaaa1111")
    assert quest is not None
    assert quest.extensions["status"] == "advanced"
    assert quest.extensions["notes"] == "进度：25%"


def test_apply_delta_records_location_movement(service: CanonService) -> None:
    """``LocationMovement`` patches the entity's current location."""
    service.registry.add(
        kind="character",
        name="林昭",
        entity_id="char-aaaa1111",
        lifecycle="active",
        extensions={"location": "山脚"},
    )
    delta = ContinuityDelta(
        chapter_number=7,
        location_movements=[
            LocationMovement(
                chapter_number=7,
                source_sentence="林昭抵达山腰",
                entity_id="char-aaaa1111",
                from_location="山脚",
                to_location="山腰",
            )
        ],
    )
    counts = service.apply_delta(delta)
    assert counts["location_movements"] == 1
    char = service.registry.get("char-aaaa1111")
    assert char is not None
    assert char.extensions["location"] == "山腰"
    assert char.extensions["previous_location"] == "山脚"


def test_apply_delta_appends_timeline_markers(service: CanonService) -> None:
    """``TimelineAdvance`` appends markers in chapter order."""
    delta = ContinuityDelta(
        chapter_number=8,
        timeline_advances=[
            TimelineAdvance(
                chapter_number=8,
                source_sentence="入夜",
                marker="入夜",
            ),
            TimelineAdvance(
                chapter_number=8,
                source_sentence="第三天清晨",
                marker="第三天清晨",
            ),
        ],
    )
    counts = service.apply_delta(delta)
    assert counts["timeline_advances"] == 2
    timeline = service.registry.timeline()
    assert [item["marker"] for item in timeline] == ["入夜", "第三天清晨"]


def test_apply_delta_records_foreshadowing_actions(service: CanonService) -> None:
    """``ForeshadowingChange`` records the latest action per id."""
    delta = ContinuityDelta(
        chapter_number=9,
        foreshadowing_changes=[
            ForeshadowingChange(
                chapter_number=9,
                source_sentence="钟声在远处响起",
                foreshadowing_id="f-bell",
                action="planted",
                detail="山腰寺庙的钟",
            ),
            ForeshadowingChange(
                chapter_number=10,
                source_sentence="钟声更近了",
                foreshadowing_id="f-bell",
                action="advanced",
                detail="声音来源逐渐清晰",
            ),
        ],
    )
    first = service.apply_delta(
        ContinuityDelta(
            chapter_number=9,
            foreshadowing_changes=delta.foreshadowing_changes[:1],
        )
    )
    second = service.apply_delta(
        ContinuityDelta(
            chapter_number=10,
            foreshadowing_changes=delta.foreshadowing_changes[1:],
        )
    )
    assert first["foreshadowing_changes"] == 1
    assert second["foreshadowing_changes"] == 1
    entries = service.registry.foreshadowing()
    assert len(entries) == 1
    assert entries[0]["action"] == "advanced"
    assert entries[0]["chapter_number"] == 10


def test_apply_delta_handles_missing_entity_silently(service: CanonService) -> None:
    """Updates that target unknown entities are silently skipped.

    The candidate confirmation path already wrote the delta to
    the snapshot's reference-validation list, so the workbench
    surfaces the orphan. ``apply_delta`` therefore treats
    unknown ids as best-effort: the registry state is left
    alone, and the count is *not* bumped so the workbench can
    report "applied N facts" without re-reading the delta.
    """
    delta = ContinuityDelta(
        chapter_number=11,
        entity_updates=[
            EntityUpdate(
                chapter_number=11,
                source_sentence="林昭...",
                entity_id="char-doesnotexist",
                changes={"location": "山腰"},
            )
        ],
    )
    counts = service.apply_delta(delta)
    assert counts["entity_updates"] == 0
    # The unknown entity was not silently created.
    assert service.registry.get("char-doesnotexist") is None
