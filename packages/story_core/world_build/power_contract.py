"""Deterministic power progression contract selection for WorldBuild."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from packages.story_core.models import NovelProject
from packages.story_core.power_system_spec import PowerSystemValidationError, validate_power_system_spec
from packages.story_core.world_enrichment import _selected_novel_type_plugin


PowerProgressionMode = Literal["custom", "traditional_class"]
POWER_PROGRESSION_MODES = frozenset({"custom", "traditional_class"})


def select_power_progression_mode(
    project: NovelProject,
    *,
    locked_mode: Any = None,
    locked_novel_type_id: Any = None,
) -> PowerProgressionMode:
    """Select custom/traditional once from author configuration or valid import.

    A persisted explicit setting is author authority. Otherwise a previous
    world_input selection is preserved; only initial bootstrap may infer the
    traditional contract from a canonical-valid imported game spec.
    """

    plugin = _selected_novel_type_plugin(project)
    if plugin.plugin_id != "game_webnovel":
        return "custom"

    blueprint = project.world_blueprint if isinstance(project.world_blueprint, Mapping) else {}
    explicit = blueprint.get("power_progression_mode")
    if explicit in POWER_PROGRESSION_MODES:
        return explicit  # type: ignore[return-value]
    if locked_mode in POWER_PROGRESSION_MODES and locked_novel_type_id == plugin.plugin_id:
        return locked_mode  # type: ignore[return-value]

    candidate = blueprint.get("power_system_spec")
    if isinstance(candidate, Mapping) and candidate.get("class_advancement_tiers"):
        try:
            validate_power_system_spec(candidate, novel_type_id=plugin.plugin_id, template=plugin.power_system_template)
        except (PowerSystemValidationError, TypeError, ValueError, KeyError, AttributeError):
            pass
        else:
            return "traditional_class"
    return "custom"
