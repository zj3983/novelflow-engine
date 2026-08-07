"""Tests for the selective craft module registry and selector.

Skills are optional craft knowledge, not replacement agents
and not workflow stages. The contract is:

* each module declares its own manifest (id, purpose, genre
  scope, stage, priority, max budget, conflict list, default
  on/off);
* the selector picks modules that the project has explicitly
  enabled, that match the requested stage, and that respect
  the genre scope;
* at most one module per exclusive purpose loads;
* a project that has not enabled a module must never see it
  in the writer context, even if it is installed;
* uninstalling one module does not break the others.
"""

from __future__ import annotations

import pytest

from packages.story_core.craft_modules.module_registry import (
    CraftModule,
    CraftModuleRegistry,
    CraftPurposeRegistry,
)
from packages.story_core.craft_modules.selector import (
    CraftModuleSelector,
    ProjectCraftSettings,
    select_craft_modules,
)


# --- Helpers ---------------------------------------------------------------


def _module(
    module_id: str,
    *,
    purpose: str = "dialogue",
    genre_ids: tuple[str, ...] = (),
    stages: tuple[str, ...] = ("writer",),
    priority: int = 50,
    max_chars: int = 800,
    conflicts_with: tuple[str, ...] = (),
    enabled_by_default: bool = False,
    exclusive_purpose: bool = False,
) -> CraftModule:
    return CraftModule(
        id=module_id,
        purpose=CraftPurposeRegistry.register(purpose, exclusive=exclusive_purpose),
        genre_ids=genre_ids,
        stages=stages,
        priority=priority,
        max_chars=max_chars,
        conflicts_with=conflicts_with,
        enabled_by_default=enabled_by_default,
        content=f"content for {module_id}",
    )


# --- Registry behaviour ---------------------------------------------------


def test_registry_only_returns_explicitly_enabled_modules() -> None:
    registry = CraftModuleRegistry()
    registry.register(_module("dialogue-natural", enabled_by_default=False))
    registry.register(_module("exposition-marker", enabled_by_default=False))

    enabled = registry.list_for_project(
        ProjectCraftSettings(enabled_ids=("dialogue-natural",))
    )

    assert {m.id for m in enabled} == {"dialogue-natural"}


def test_registry_uninstalling_one_module_leaves_others_intact() -> None:
    registry = CraftModuleRegistry()
    registry.register(_module("dialogue-natural"))
    registry.register(_module("exposition-marker"))
    registry.register(_module("pacing-soft"))

    # Uninstall the middle one.
    registry.unregister("exposition-marker")

    enabled = registry.list_for_project(
        ProjectCraftSettings(
            enabled_ids=("dialogue-natural", "pacing-soft")
        )
    )

    assert {m.id for m in enabled} == {"dialogue-natural", "pacing-soft"}


def test_registry_never_auto_enables_newly_installed_module() -> None:
    """Installing a new module must not silently start loading it
    for projects that have not opted in.
    """
    registry = CraftModuleRegistry()
    registry.register(_module("dialogue-natural"))

    # First project does not enable the module.
    project_a = registry.list_for_project(ProjectCraftSettings(enabled_ids=()))
    assert project_a == []

    # A new module is installed after the fact.
    registry.register(_module("exposition-marker"))

    project_a_again = registry.list_for_project(ProjectCraftSettings(enabled_ids=()))
    assert project_a_again == []


# --- Selector behaviour ---------------------------------------------------


def test_selector_returns_only_modules_matching_stage() -> None:
    registry = CraftModuleRegistry()
    registry.register(_module("dialogue-natural", stages=("writer",)))
    registry.register(_module("director-planner-only", stages=("director",)))
    selector = CraftModuleSelector(registry=registry)

    writer_modules = selector.select(
        stage="writer",
        project=ProjectCraftSettings(enabled_ids=("dialogue-natural", "director-planner-only")),
        genre_ids=(),
    )
    assert {m.id for m in writer_modules} == {"dialogue-natural"}


def test_selector_filters_by_genre_scope() -> None:
    registry = CraftModuleRegistry()
    registry.register(
        _module("xuanhuan-only", genre_ids=("xuanhuan",), priority=80)
    )
    registry.register(_module("urban-only", genre_ids=("urban",), priority=70))
    registry.register(_module("general", genre_ids=(), priority=60))
    selector = CraftModuleSelector(registry=registry)

    xuanhuan = selector.select(
        stage="writer",
        project=ProjectCraftSettings(enabled_ids=("xuanhuan-only", "urban-only", "general")),
        genre_ids=("xuanhuan",),
    )
    assert {m.id for m in xuanhuan} == {"xuanhuan-only", "general"}

    urban = selector.select(
        stage="writer",
        project=ProjectCraftSettings(enabled_ids=("xuanhuan-only", "urban-only", "general")),
        genre_ids=("urban",),
    )
    assert {m.id for m in urban} == {"urban-only", "general"}


def test_selector_loads_at_most_one_module_per_exclusive_purpose() -> None:
    registry = CraftModuleRegistry()
    registry.register(
        _module(
            "dialogue-natural",
            purpose="dialogue",
            priority=80,
            exclusive_purpose=True,
        )
    )
    registry.register(
        _module(
            "dialogue-stiff",
            purpose="dialogue",
            priority=60,
            exclusive_purpose=True,
        )
    )
    selector = CraftModuleSelector(registry=registry)

    selected = selector.select(
        stage="writer",
        project=ProjectCraftSettings(enabled_ids=("dialogue-natural", "dialogue-stiff")),
        genre_ids=(),
    )

    # The higher-priority module wins; the second is dropped.
    assert {m.id for m in selected} == {"dialogue-natural"}


def test_selector_respects_conflicts_with() -> None:
    registry = CraftModuleRegistry()
    registry.register(
        _module(
            "exposition-minimal",
            priority=80,
            conflicts_with=("exposition-rich",),
        )
    )
    registry.register(
        _module("exposition-rich", priority=60)
    )
    selector = CraftModuleSelector(registry=registry)

    selected = selector.select(
        stage="writer",
        project=ProjectCraftSettings(enabled_ids=("exposition-minimal", "exposition-rich")),
        genre_ids=(),
    )
    # The higher-priority module suppresses its conflict target.
    assert {m.id for m in selected} == {"exposition-minimal"}


def test_selector_does_not_exceed_total_budget() -> None:
    registry = CraftModuleRegistry()
    registry.register(_module("a", priority=80, max_chars=600))
    registry.register(_module("b", priority=60, max_chars=600))
    registry.register(_module("c", priority=40, max_chars=600))
    selector = CraftModuleSelector(registry=registry, total_max_chars=1200)

    selected = selector.select(
        stage="writer",
        project=ProjectCraftSettings(
            enabled_ids=("a", "b", "c"),
            total_max_chars=1200,
        ),
        genre_ids=(),
    )

    # The top two fit the 1200-char budget; the third is dropped
    # to keep under the cap.
    assert {m.id for m in selected} == {"a", "b"}


def test_selector_skips_modules_with_exclusive_purpose_violation() -> None:
    """If two modules share a non-exclusive purpose (e.g. two
    'style' modules), the selector keeps both — exclusivity is
    opt-in per purpose registration.
    """
    registry = CraftModuleRegistry()
    registry.register(_module("style-a", purpose="style", priority=80))
    registry.register(_module("style-b", purpose="style", priority=60))
    selector = CraftModuleSelector(registry=registry)

    selected = selector.select(
        stage="writer",
        project=ProjectCraftSettings(enabled_ids=("style-a", "style-b")),
        genre_ids=(),
    )
    assert {m.id for m in selected} == {"style-a", "style-b"}


# --- Module-level convenience ---------------------------------------------


def test_select_craft_modules_uses_default_selector(tmp_path) -> None:
    registry = CraftModuleRegistry()
    registry.register(_module("dialogue-natural", priority=50))

    selected = select_craft_modules(
        stage="writer",
        project=ProjectCraftSettings(enabled_ids=("dialogue-natural",)),
        genre_ids=(),
        registry=registry,
    )
    assert {m.id for m in selected} == {"dialogue-natural"}


def test_module_manifest_validation_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        CraftModule.model_validate(
            {
                "id": "x",
                "purpose": CraftPurposeRegistry.register("dialogue"),
                "genre_ids": [],
                "stages": ["writer"],
                "priority": 10,
                "max_chars": 100,
                "conflicts_with": [],
                "enabled_by_default": False,
                "bogus_extra_field": True,
            }
        )
