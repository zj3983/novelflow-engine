"""Craft module selector.

The selector is the answer to "given the project, the stage,
and the genre, which craft modules actually go into the
writer prompt?". It applies the four selection rules in
order:

1. **Stage**: the module must list the requested stage.
2. **Genre scope**: empty ``genre_ids`` means "all genres";
   otherwise the project's genres must intersect.
3. **Conflict resolution**: a higher-priority module
   suppresses every module in its ``conflicts_with`` list.
4. **Exclusive purpose**: at most one module per exclusive
   purpose survives — the highest-priority one.
5. **Budget cap**: the total ``max_chars`` must fit under
   ``total_max_chars``; lower-priority modules are dropped
   first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .module_registry import CraftModule, CraftModuleRegistry, CraftPurposeRegistry


@dataclass(frozen=True)
class ProjectCraftSettings:
    """The per-project craft module configuration.

    The selector only loads modules the project has explicitly
    enabled; ``enabled_by_default`` on the manifest is a hint
    for the install UI, not a silent opt-in.
    """

    enabled_ids: tuple[str, ...] = field(default_factory=tuple)
    total_max_chars: int = 3200


class CraftModuleSelector:
    """Pick the craft modules that go into one writer context."""

    def __init__(
        self,
        *,
        registry: CraftModuleRegistry,
        total_max_chars: int = 3200,
    ) -> None:
        self._registry = registry
        self._default_budget = total_max_chars

    def select(
        self,
        *,
        stage: str,
        project: ProjectCraftSettings,
        genre_ids: Iterable[str] = (),
    ) -> list[CraftModule]:
        candidates = [
            module
            for module in self._registry.list_for_project(project)
            if stage in module.stages
            and _genre_overlaps(module.genre_ids, list(genre_ids))
        ]
        # Conflict resolution: walk in priority order. The
        # registry already sorts the candidates so the highest
        # priority module is processed first. The new module is
        # always lower or equal priority than the survivors.
        # The new module loses if any survivor (higher priority)
        # has it in its conflicts list. The survivors keep their
        # slot unless the new module explicitly targets them in
        # its own conflicts list (in which case the new module's
        # priority is strictly higher, because priority-desc
        # ordering only ever reaches the new module after every
        # higher-priority survivor has been considered).
        survivors: list[CraftModule] = []
        for module in candidates:
            if any(module.id in set(existing.conflicts_with) for existing in survivors):
                # A higher-priority survivor already excludes
                # the new module; the new module loses.
                continue
            new_conflicts = set(module.conflicts_with)
            survivors = [
                existing
                for existing in survivors
                if existing.id not in new_conflicts
            ]
            survivors.append(module)
        # Exclusive purpose: keep at most one per exclusive
        # purpose — the highest-priority one.
        filtered: list[CraftModule] = []
        for module in survivors:
            if not CraftPurposeRegistry.is_exclusive(module.purpose):
                filtered.append(module)
                continue
            if any(
                existing.purpose == module.purpose
                for existing in filtered
            ):
                continue
            filtered.append(module)
        filtered.sort(key=lambda module: (-module.priority, module.id))
        # Budget cap: drop the lowest-priority module until the
        # total fits under the cap. (sorted descending by priority,
        # so iterate from the tail.)
        budget = project.total_max_chars or self._default_budget
        while filtered and sum(module.max_chars for module in filtered) > budget:
            filtered.pop()
        return filtered


def _genre_overlaps(module_genres: tuple[str, ...], project_genres: list[str]) -> bool:
    if not module_genres:
        return True
    if not project_genres:
        return False
    module_set = set(module_genres)
    return any(genre in module_set for genre in project_genres)


def select_craft_modules(
    *,
    stage: str,
    project: ProjectCraftSettings,
    genre_ids: Iterable[str] = (),
    registry: CraftModuleRegistry,
    total_max_chars: int = 3200,
) -> list[CraftModule]:
    """Convenience entry point: build a one-shot selector and run it."""
    selector = CraftModuleSelector(registry=registry, total_max_chars=total_max_chars)
    return selector.select(stage=stage, project=project, genre_ids=genre_ids)


__all__ = ["CraftModuleSelector", "ProjectCraftSettings", "select_craft_modules"]
