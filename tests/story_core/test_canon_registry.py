"""Tests for the canonical entity registry.

The registry is the source of truth for every named thing the
project introduces. The contract is:

1. Stable IDs — once an entity is added, its ``entity_id`` is
   permanent even if the display name changes.
2. Alias resolution — one person can be known by a real name
   and a game ID and still resolve to the same entity.
3. Alias uniqueness per kind — two characters cannot share
   an alias (or a primary name).
4. Lifecycle transitions — ``proposed`` -> ``approved`` ->
   ``active`` -> ``retired``; only ``active`` entities are
   considered for downstream contexts.
5. Kind isolation — organizations, anonymous roles, and
   generic rules are not auto-promoted to characters just
   because a name shows up in prose.
"""

from __future__ import annotations

import pytest

from packages.story_core.canon.registry import CanonEntity, CanonRegistry


# --- ID stability and alias resolution ------------------------------------


def test_real_name_and_game_id_resolve_to_one_character() -> None:
    registry = CanonRegistry.empty()
    entity = registry.add_character(name="苏叶", aliases=["夜烬"])

    assert registry.resolve("苏叶", "character").entity_id == entity.entity_id
    assert registry.resolve("夜烬", "character").entity_id == entity.entity_id


def test_entity_id_is_stable_when_display_name_changes() -> None:
    registry = CanonRegistry.empty()
    entity = registry.add_character(name="苏叶", aliases=[])

    original_id = entity.entity_id
    registry.rename(entity.entity_id, display_name="夜烬")

    refreshed = registry.resolve("夜烬", "character")
    assert refreshed.entity_id == original_id
    # The old name no longer resolves — renaming detaches it.
    assert registry.resolve("苏叶", "character") is None


def test_aliases_are_unique_within_a_kind() -> None:
    registry = CanonRegistry.empty()
    registry.add_character(name="苏叶", aliases=["夜烬"])

    with pytest.raises(ValueError, match="alias_conflict"):
        registry.add_character(name="林照", aliases=["夜烬"])


def test_primary_names_are_unique_within_a_kind() -> None:
    registry = CanonRegistry.empty()
    registry.add_character(name="苏叶")

    with pytest.raises(ValueError, match="alias_conflict"):
        registry.add_character(name="苏叶", aliases=["叶"])


def test_resolve_returns_none_for_unknown_name() -> None:
    registry = CanonRegistry.empty()
    assert registry.resolve("路人甲", "character") is None


# --- Kind isolation --------------------------------------------------------


def test_organizations_and_anonymous_buyers_are_not_characters() -> None:
    """An organization, a market buyer, or a generic rule must
    not silently become a character just because the name
    looks like a person. The kind scope is explicit.
    """
    registry = CanonRegistry.empty()
    registry.add_organization(name="守龛人组织", aliases=["Old Keepers"])
    registry.add_rule(name="市场匿名买家", aliases=[])

    assert registry.resolve("守龛人组织", "character") is None
    assert registry.resolve("守龛人组织", "organization") is not None
    assert registry.resolve("市场匿名买家", "rule") is not None


def test_same_name_in_different_kinds_does_not_collide() -> None:
    """A location and a character can share a name (e.g.
    "旧神龛" the place vs. a person nicknamed "旧神龛") without
    alias-conflict errors.
    """
    registry = CanonRegistry.empty()
    place = registry.add_location(name="旧神龛")
    registry.add_character(name="林照", aliases=["旧神龛"])

    assert registry.resolve("旧神龛", "location").entity_id == place.entity_id
    assert registry.resolve("旧神龛", "character").entity_id != place.entity_id


# --- Lifecycle -------------------------------------------------------------


def test_lifecycle_progresses_proposed_approved_active_retired() -> None:
    registry = CanonRegistry.empty()
    entity = registry.add_character(name="苏叶")
    assert entity.lifecycle == "proposed"

    approved = registry.approve(entity.entity_id)
    assert approved.lifecycle == "approved"

    activated = registry.activate(entity.entity_id)
    assert activated.lifecycle == "active"

    retired = registry.retire(entity.entity_id)
    assert retired.lifecycle == "retired"


def test_lifecycle_transitions_are_validated() -> None:
    registry = CanonRegistry.empty()
    entity = registry.add_character(name="苏叶")
    # Cannot skip proposed -> active; must approve first.
    with pytest.raises(ValueError, match="lifecycle_transition_invalid"):
        registry.activate(entity.entity_id)


def test_only_active_entities_enter_writer_context() -> None:
    registry = CanonRegistry.empty()
    active = registry.add_character(name="林照")
    registry.add_character(name="周执事")  # stays proposed
    registry.approve(active.entity_id)
    registry.activate(active.entity_id)

    active_characters = registry.list_active("character")

    assert {entity.entity_id for entity in active_characters} == {active.entity_id}


def test_retired_entity_does_not_enter_writer_context() -> None:
    registry = CanonRegistry.empty()
    entity = registry.add_character(name="林照")
    registry.approve(entity.entity_id)
    registry.activate(entity.entity_id)
    registry.retire(entity.entity_id)

    assert registry.list_active("character") == []


# --- Kind coverage ---------------------------------------------------------


@pytest.mark.parametrize(
    "adder, kind",
    [
        ("add_character", "character"),
        ("add_item", "item"),
        ("add_equipment", "equipment"),
        ("add_technique", "technique"),
        ("add_location", "location"),
        ("add_organization", "organization"),
        ("add_quest", "quest"),
        ("add_monster", "monster"),
        ("add_rule", "rule"),
    ],
)
def test_each_kind_round_trips_through_resolve(adder: str, kind: str) -> None:
    registry = CanonRegistry.empty()
    getattr(registry, adder)(name=f"示例-{kind}")

    assert registry.resolve(f"示例-{kind}", kind) is not None


def test_entity_constructor_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="entity_kind_invalid"):
        CanonEntity(
            entity_id="x",
            kind="bogus",  # type: ignore[arg-type]
            display_name="x",
            aliases=(),
            lifecycle="proposed",
        )
