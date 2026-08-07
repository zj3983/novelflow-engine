"""Tests for the entity preflight.

Before the writer runs, every named entity the director asked
for must already have a concrete card in the canonical
registry. The preflight is the only path that:

1. Resolves existing entities when the director reused a
   previously introduced name.
2. Calls the ``EntityDesigner`` to flesh out a card for
   each *named* requirement that has no canonical entry yet.
3. Leaves disposable unnamed minor roles as inline mentions;
   they never enter the registry.
4. Validates the generated card before persisting it.
5. Stops the chapter run with ``entity_preflight_failed``
   when the designer returns an invalid card.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from packages.story_core.agents.contracts import EntityRequirement
from packages.story_core.canon.registry import CanonEntity, CanonRegistry
from packages.story_core.canon.service import (
    CanonService,
    EntityPreflightFailed,
    preflight_requirements,
)


# --- Test doubles -----------------------------------------------------------


@dataclass
class _RecordingDesigner:
    """Return canned cards keyed by (kind, name)."""

    cards: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    calls: list[EntityRequirement] = field(default_factory=list)
    invalid_for: set[tuple[str, str]] = field(default_factory=set)

    def design(self, requirement: EntityRequirement, registry: CanonRegistry) -> CanonEntity:
        self.calls.append(requirement)
        key = (requirement.kind, requirement.name)
        if key in self.invalid_for:
            return CanonEntity(
                entity_id="",
                kind=requirement.kind,  # type: ignore[arg-type]
                display_name="",
                aliases=(),
                lifecycle="proposed",
            )
        payload = self.cards.get(key)
        if payload is None:
            # Default: a minimally valid character card.
            payload = {
                "entity_id": f"char-{requirement.name}",
                "kind": requirement.kind,
                "display_name": requirement.name,
                "aliases": [],
                "lifecycle": "active",
            }
        else:
            payload = dict(payload)
            # The fixture uses the short ``id`` key for readability;
            # promote it to ``entity_id`` before the default kicks in.
            if "entity_id" not in payload and "id" in payload:
                payload["entity_id"] = payload.pop("id")
            payload.setdefault("entity_id", f"{requirement.kind}-{requirement.name}")
            payload.setdefault("display_name", requirement.name)
        return CanonEntity.model_validate(payload)


# --- 1. Named new character gets a concrete card ---------------------------


def test_named_new_character_gets_a_concrete_card_before_writer_context() -> None:
    registry = CanonRegistry.empty()
    designer = _RecordingDesigner(
        cards={
            (
                "character",
                "守龛人",
            ): {
                "id": "char-shoukanren",
                "kind": "character",
                "display_name": "守龛人",
                "aliases": [],
                "lifecycle": "active",
                "extensions": {
                    "identity": "旧神龛的守龛人",
                    "origin": "神龛世代",
                    "occupation_or_role": "守龛",
                    "present_goal": "守护旧神龛",
                    "fear_or_weakness": "神龛失守",
                    "behavioral_habits": "沉默寡言",
                    "speech_tendency": "古语",
                    "relationships": [],
                    "knowledge_boundary": ["旧神龛的秘密"],
                    "current_state": "值班",
                    "change_arc": "从不信任外人到接受主角",
                },
            }
        }
    )
    service = CanonService(registry=registry, designer=designer)

    results = service.ensure_requirements(
        [
            EntityRequirement(
                kind="character",
                name="守龛人",
                importance=8,
            )
        ]
    )

    assert len(results) == 1
    new_card = results[0]
    assert new_card.entity_id == "char-shoukanren"
    assert new_card.kind == "character"
    # The card is now in the registry and the director's
    # writer context can resolve it by name.
    resolved = registry.resolve("守龛人", "character")
    assert resolved is not None
    assert resolved.entity_id == "char-shoukanren"


# --- 2. Important weapon or technique gets mechanics, limits, ownership ---


def test_important_weapon_or_technique_receives_full_card() -> None:
    registry = CanonRegistry.empty()
    designer = _RecordingDesigner(
        cards={
            (
                "equipment",
                "灵剑",
            ): {
                "id": "equip-lingjian",
                "kind": "equipment",
                "display_name": "灵剑",
                "aliases": ["灵锋"],
                "lifecycle": "active",
                "extensions": {
                    "effect": "灵力加成 +20%",
                    "limitation": "无灵力时等同废铁",
                    "cost": "每次使用消耗持有者 1 点灵力",
                    "owner": "林照",
                    "provenance": "师父传下",
                    "plot_function": "主角近战的根本装备",
                },
            },
            (
                "technique",
                "灵视",
            ): {
                "id": "tech-lingshi",
                "kind": "technique",
                "display_name": "灵视",
                "aliases": [],
                "lifecycle": "active",
                "extensions": {
                    "effect": "短时间内看穿灵力流动",
                    "limitation": "持续不超过十息",
                    "cost": "使用后短暂眩晕",
                    "owner": "林照",
                    "provenance": "入门时师父口传",
                    "plot_function": "破解封印 / 辨认真伪",
                },
            },
        }
    )
    service = CanonService(registry=registry, designer=designer)

    results = service.ensure_requirements(
        [
            EntityRequirement(kind="equipment", name="灵剑", importance=8),
            EntityRequirement(kind="technique", name="灵视", importance=7),
        ]
    )

    equip, tech = results
    assert equip.extensions["owner"] == "林照"
    assert equip.extensions["limitation"] == "无灵力时等同废铁"
    assert tech.extensions["effect"] == "短时间内看穿灵力流动"
    assert tech.extensions["plot_function"] == "破解封印 / 辨认真伪"


# --- 3. Inline minor entities stay out of the registry ---------------------


def test_disposable_unnamed_minor_entity_does_not_enter_registry() -> None:
    registry = CanonRegistry.empty()
    designer = _RecordingDesigner()  # nothing canned
    service = CanonService(registry=registry, designer=designer)

    results = service.ensure_requirements(
        [
            EntityRequirement(
                kind="character",
                name="路过的香客",
                importance=2,
                inline_minor=True,
            )
        ]
    )

    assert results == []
    # No entity was added to the registry, and the designer's
    # ``design`` callback was never called.
    assert designer.calls == []
    assert registry.resolve("路过的香客", "character") is None


# --- 4. Reusing an alias resolves the existing entity ----------------------


def test_reusing_alias_resolves_existing_entity_instead_of_creating_duplicate() -> None:
    registry = CanonRegistry.empty()
    existing = registry.add_character(name="苏叶", aliases=["夜烬"])
    designer = _RecordingDesigner()  # must NOT be called
    service = CanonService(registry=registry, designer=designer)

    results = service.ensure_requirements(
        [
            # The director reused the alias "夜烬" without knowing
            # it is the same person.
            EntityRequirement(kind="character", name="夜烬", importance=8)
        ]
    )

    assert len(results) == 0
    assert designer.calls == []  # alias hit, no design call
    resolved = registry.resolve("夜烬", "character")
    assert resolved is not None
    assert resolved.entity_id == existing.entity_id
    # The new name did not register a fresh entity.
    assert registry.resolve("苏叶", "character").entity_id == existing.entity_id


def test_resolve_existing_entity_promotes_lifecycle_to_active() -> None:
    """If the director demands an entity the registry already
    has but only as ``proposed`` or ``approved``, the
    preflight promotes it to ``active`` so the writer context
    actually sees it.
    """
    registry = CanonRegistry.empty()
    entity = registry.add_character(name="林照")
    registry.approve(entity.entity_id)
    designer = _RecordingDesigner()  # must NOT be called
    service = CanonService(registry=registry, designer=designer)

    results = service.ensure_requirements(
        [EntityRequirement(kind="character", name="林照", importance=8)]
    )

    assert results == []
    refreshed = registry.get(entity.entity_id)
    assert refreshed is not None
    assert refreshed.lifecycle == "active"


# --- 5. Invalid cards raise entity_preflight_failed -----------------------


def test_invalid_generated_card_raises_entity_preflight_failed() -> None:
    registry = CanonRegistry.empty()
    designer = _RecordingDesigner(invalid_for={("character", "野妖")})
    service = CanonService(registry=registry, designer=designer)

    with pytest.raises(EntityPreflightFailed) as excinfo:
        service.ensure_requirements(
            [EntityRequirement(kind="character", name="野妖", importance=7)]
        )

    # The failure must mention which requirement caused it so
    # the workbench can point at the exact problem.
    assert "野妖" in str(excinfo.value) or "character" in str(excinfo.value)


# --- 6. Module-level convenience function -------------------------------


def test_preflight_requirements_uses_default_registry() -> None:
    designer = _RecordingDesigner(
        cards={
            (
                "location",
                "旧神龛",
            ): {
                "id": "loc-oldshenkan",
                "kind": "location",
                "display_name": "旧神龛",
                "aliases": [],
                "lifecycle": "active",
            }
        }
    )
    registry = preflight_requirements(
        [EntityRequirement(kind="location", name="旧神龛", importance=8)],
        designer=designer,
    )
    assert registry.resolve("旧神龛", "location") is not None
