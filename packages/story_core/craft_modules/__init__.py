"""Selective craft module registry and selector.

Skills are optional craft knowledge — not replacement agents
and not workflow stages. This package owns the manifest,
the project-level enablement, the per-stage and per-genre
filtering, the exclusive-purpose conflict resolution, and
the budget cap that protects the writer prompt from blowing
its token budget.
"""

from .module_registry import (
    CraftModule,
    CraftModuleRegistry,
    CraftPurposeRegistry,
)
from .selector import CraftModuleSelector, ProjectCraftSettings, select_craft_modules

__all__ = [
    "CraftModule",
    "CraftModuleRegistry",
    "CraftModuleSelector",
    "CraftPurposeRegistry",
    "ProjectCraftSettings",
    "select_craft_modules",
]
