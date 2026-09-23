"""Small deterministic validators for production WorldBuild tasks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, Callable

from packages.story_core.build_graph.contracts import BuildDiagnostic
from packages.story_core.models import NovelProject
from packages.story_core.power_system_spec import (
    CLASS_ADVANCEMENT_TIER_FIELDS,
    GAME_CLASS_ADVANCEMENT_LEVELS,
    PATH_FIELDS,
    PowerSystemValidationError,
    contains_placeholder_content,
    effective_power_system_template,
    is_placeholder_content,
    normalize_power_path,
    validate_power_system_spec,
)
from packages.story_core.power_systems import legacy_power_summary
from packages.story_core.world_enrichment import (
    _power_spec_for_genre,
    _selected_novel_type_plugin,
)
from .power_contract import PowerProgressionMode, select_power_progression_mode


Validator = Callable[[Any], Any]


def _diagnostic(code: str, path: str, message: str) -> BuildDiagnostic:
    return BuildDiagnostic(code=code, path=path, message=message, severity="blocking")


def _finish(diagnostics: list[BuildDiagnostic]) -> Any:
    return True if not diagnostics else tuple(diagnostics)


def _is_placeholder(value: Any) -> bool:
    return is_placeholder_content(value)


def _contains_placeholder(value: Any) -> bool:
    return contains_placeholder_content(value)


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not _is_placeholder(value)


def _nonempty_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and not _contains_placeholder(value)
    )


def _required_lists(
    payload: Any,
    fields: tuple[str, ...],
    *,
    prefix: str,
) -> list[BuildDiagnostic]:
    diagnostics: list[BuildDiagnostic] = []
    if not isinstance(payload, Mapping):
        return [_diagnostic(f"{prefix}.invalid", prefix, "task output must be an object")]
    for field in fields:
        value = payload.get(field)
        if not _nonempty_list(value):
            diagnostics.append(
                _diagnostic(
                    f"{prefix}.{field}.missing",
                    field,
                    f"{field} must be a non-empty list without placeholders",
                )
            )
    return diagnostics


def _entry_list(
    payload: Any,
    field: str,
    *,
    prefix: str,
    minimum: int = 1,
) -> list[BuildDiagnostic]:
    diagnostics: list[BuildDiagnostic] = []
    if not isinstance(payload, Mapping):
        return [_diagnostic(f"{prefix}.invalid", prefix, "task output must be an object")]
    values = payload.get(field)
    if not isinstance(values, list) or len(values) < minimum:
        diagnostics.append(
            _diagnostic(
                f"{prefix}.missing",
                field,
                f"{field} must contain at least {minimum} item(s)",
            )
        )
        return diagnostics
    for index, item in enumerate(values):
        if not isinstance(item, Mapping):
            diagnostics.append(_diagnostic(f"{prefix}.invalid_item", f"{field}[{index}]", "item must be an object"))
            continue
        for required in ("name", "description"):
            if not _nonempty_text(item.get(required)):
                diagnostics.append(
                    _diagnostic(
                        f"{prefix}.missing_{required}",
                        f"{field}[{index}].{required}",
                        f"{required} is required",
                    )
                )
    return diagnostics


def _reject_unowned_fields(payload: Any, allowed: tuple[str, ...], prefix: str) -> list[BuildDiagnostic]:
    if not isinstance(payload, Mapping):
        return [_diagnostic(f"{prefix}.invalid", prefix, "task output must be an object")]
    return [
        _diagnostic(
            f"{prefix}.unowned_field",
            str(key),
            "field is outside this task's output ownership",
        )
        for key in payload
        if str(key) not in allowed
    ]


def _validate_world_input(payload: Any) -> Any:
    diagnostics: list[BuildDiagnostic] = []
    if not isinstance(payload, Mapping):
        return (_diagnostic("world.input.invalid", "world_input", "world_input must be an object"),)
    if not _nonempty_text(payload.get("title")):
        diagnostics.append(_diagnostic("world.input.missing_title", "title", "title is required"))
    if not isinstance(payload.get("genre_plugin_ids"), list):
        diagnostics.append(_diagnostic("world.input.missing_genre", "genre_plugin_ids", "genre_plugin_ids must be a list"))
    if not isinstance(payload.get("story_core"), Mapping):
        diagnostics.append(_diagnostic("world.input.missing_story_core", "story_core", "story_core projection is required"))
    if payload.get("power_progression_mode") not in {"custom", "traditional_class"}:
        diagnostics.append(_diagnostic("world.input.invalid_power_progression_mode", "power_progression_mode", "power progression mode must be locked to a supported contract"))
    return _finish(diagnostics)


def _validate_core_rules(payload: Any) -> Any:
    diagnostics = _reject_unowned_fields(payload, ("premise", "world_rules", "constraints"), "world.core_rules")
    if isinstance(payload, Mapping):
        if not _nonempty_text(payload.get("premise")):
            diagnostics.append(_diagnostic("world.core_rules.missing_premise", "premise", "premise is required"))
        diagnostics.extend(_required_lists(payload, ("world_rules", "constraints"), prefix="world.core_rules"))
    return _finish(diagnostics)


def _validate_power_foundation(payload: Any) -> Any:
    diagnostics = _reject_unowned_fields(payload, ("name", "origin"), "power.foundation")
    if isinstance(payload, Mapping):
        if not _nonempty_text(payload.get("name")):
            diagnostics.append(_diagnostic("power.foundation.missing_name", "name", "name is required"))
        if not _nonempty_list(payload.get("origin")):
            diagnostics.append(_diagnostic("power.foundation.missing_origin", "origin", "origin must be a non-empty list"))
    return _finish(diagnostics)


def _validate_power_attributes(payload: Any) -> Any:
    diagnostics = _reject_unowned_fields(payload, ("attributes",), "power.attributes")
    if isinstance(payload, Mapping):
        values = payload.get("attributes")
        if not isinstance(values, list) or not values:
            diagnostics.append(_diagnostic("power.attributes.missing", "attributes", "attributes must be a non-empty list"))
        else:
            for index, item in enumerate(values):
                if not isinstance(item, Mapping):
                    diagnostics.append(_diagnostic("power.attributes.invalid_item", f"attributes[{index}]", "attribute must be an object"))
                    continue
                if not _nonempty_text(item.get("name")):
                    diagnostics.append(_diagnostic("power.attributes.missing_name", f"attributes[{index}].name", "attribute name is required"))
                if not _nonempty_text(item.get("effect")):
                    diagnostics.append(_diagnostic("power.attributes.missing_effect", f"attributes[{index}].effect", "attribute effect is required"))
    return _finish(diagnostics)


def _minimum_path_count(plugin: Any, spec: Any = None) -> int:
    template = effective_power_system_template(
        plugin.plugin_id,
        getattr(plugin, "power_system_template", {}) or {},
        spec,
    )
    value = template.get("minimum_path_count", 2) if isinstance(template, Mapping) else 2
    return max(1, int(value)) if isinstance(value, int) and not isinstance(value, bool) else 2


def _validate_power_paths(
    payload: Any,
    project: NovelProject,
    progression_mode: PowerProgressionMode,
) -> Any:
    diagnostics = _reject_unowned_fields(payload, ("paths",), "power.paths")
    plugin = _selected_novel_type_plugin(project)
    values = payload.get("paths") if isinstance(payload, Mapping) else None
    existing_spec = (
        (project.world_blueprint or {}).get("power_system_spec")
        if isinstance(project.world_blueprint, Mapping)
        else None
    )
    if not isinstance(values, list):
        if plugin.plugin_id == "game_webnovel":
            minimum = 6 if progression_mode == "traditional_class" else 1
        else:
            minimum = _minimum_path_count(plugin, existing_spec)
        diagnostics.append(_diagnostic("power.paths.minimum_count", "paths", f"paths requires at least {minimum} item(s)"))
        return _finish(diagnostics)
    candidate_spec = dict(existing_spec) if isinstance(existing_spec, Mapping) else {}
    candidate_spec["paths"] = values
    if plugin.plugin_id == "game_webnovel":
        minimum = 6 if progression_mode == "traditional_class" else 1
    else:
        minimum = _minimum_path_count(plugin, candidate_spec)
    if len(values) < minimum:
        diagnostics.append(_diagnostic("power.paths.minimum_count", "paths", f"paths requires at least {minimum} item(s)"))
    traditional_game = plugin.plugin_id == "game_webnovel" and progression_mode == "traditional_class"
    if traditional_game:
        minimum = max(minimum, 6)
    elif plugin.plugin_id == "game_webnovel" and isinstance(values, list):
        for index, item in enumerate(values):
            if isinstance(item, Mapping) and (
                _nonempty_text(item.get("transfer_task"))
                or (isinstance(item.get("advancement_tree"), list) and bool(item.get("advancement_tree")))
            ):
                diagnostics.append(_diagnostic("power.paths.mode_switch_field", f"paths[{index}]", "custom game mode cannot be upgraded by path output"))
    # The canonical power validator is the authority for rich path
    # semantics.  The section validator only checks the shape needed to
    # safely carry a path through the graph.  In particular, an imported
    # canonical-valid non-traditional path is not rejected merely because it
    # lacks game-only or optional descriptive fields.
    required = ("name", "branches")
    if traditional_game:
        required = PATH_FIELDS
    for index, item in enumerate(values):
        if not isinstance(item, Mapping):
            diagnostics.append(_diagnostic("power.paths.invalid_item", f"paths[{index}]", "path must be an object"))
            continue
        if _contains_placeholder(item):
            diagnostics.append(
                _diagnostic(
                    "power.paths.placeholder",
                    f"paths[{index}]",
                    "path contains placeholder content",
                )
            )
        canonical_item = normalize_power_path(item)
        for field in required:
            value = canonical_item.get(field)
            if isinstance(value, list):
                valid = _nonempty_list(value)
            elif field == "advancement_tree":
                valid = isinstance(value, list) and bool(value)
            else:
                valid = _nonempty_text(value)
            if not valid:
                diagnostics.append(_diagnostic(f"power.paths.missing_{field}", f"paths[{index}].{field}", f"{field} is required"))
    names = [
        path["name"].casefold()
        for item in values
        if isinstance(item, Mapping)
        and (path := normalize_power_path(item)).get("name")
    ]
    if len(names) != len(set(names)):
        diagnostics.append(_diagnostic("paths.duplicate_names", "paths", "path names must be distinct"))
    if any(
        isinstance(item, Mapping)
        and len({branch.casefold() for branch in normalize_power_path(item).get("branches", [])}) < 2
        for item in values
    ):
        diagnostics.append(_diagnostic("paths.distinct_branches", "paths", "each path needs distinct branches"))
    return _finish(diagnostics)


def _validate_power_stages(payload: Any) -> Any:
    diagnostics = _reject_unowned_fields(payload, ("stages",), "power.stages")
    values = payload.get("stages") if isinstance(payload, Mapping) else None
    if not isinstance(values, list):
        diagnostics.append(_diagnostic("stages.minimum_count", "stages", "at least three stages are required"))
        return _finish(diagnostics)
    if len(values) < 3:
        diagnostics.append(_diagnostic("stages.minimum_count", "stages", "at least three stages are required"))
    for index, item in enumerate(values):
        if not isinstance(item, Mapping):
            diagnostics.append(_diagnostic("stages.invalid_item", f"stages[{index}]", "stage must be an object"))
            continue
        for field in ("name", "entry", "change", "failure"):
            if not _nonempty_text(item.get(field)):
                diagnostics.append(_diagnostic(f"stages.missing_{field}", f"stages[{index}].{field}", f"{field} is required"))
        if "level" in item and item.get("level") is not None and (isinstance(item.get("level"), bool) or not isinstance(item.get("level"), (int, float))):
            diagnostics.append(_diagnostic("stages.invalid_level", f"stages[{index}].level", "level must be numeric or null"))
    levels = [
        item.get("level")
        for item in values
        if isinstance(item, Mapping)
        and isinstance(item.get("level"), (int, float))
        and not isinstance(item.get("level"), bool)
    ]
    if any(current <= previous for previous, current in zip(levels, levels[1:])):
        diagnostics.append(_diagnostic("stages.levels_not_increasing", "stages", "numeric stage levels must increase"))
    return _finish(diagnostics)


def _validate_power_resources(payload: Any) -> Any:
    allowed = ("skills", "equipment", "resources", "advancement")
    diagnostics = _reject_unowned_fields(payload, allowed, "power.resources")
    diagnostics.extend(_required_lists(payload, allowed, prefix="power.resources"))
    return _finish(diagnostics)


def _validate_power_constraints(payload: Any, progression_mode: PowerProgressionMode, *, game_world: bool) -> Any:
    allowed = (
        "costs",
        "counters",
        "boundaries",
        "social_impact",
        "visibility",
        "continuity_ledger",
        "attribute_allocation",
    )
    traditional_game = game_world and progression_mode == "traditional_class"
    class_tiers_allowed = traditional_game or not game_world
    if class_tiers_allowed:
        allowed = (*allowed, "class_advancement_tiers")
    diagnostics = _reject_unowned_fields(payload, allowed, "power.constraints")
    if game_world and not traditional_game and isinstance(payload, Mapping) and "class_advancement_tiers" in payload:
        diagnostics = [item for item in diagnostics if not (item.code == "power.constraints.unowned_field" and item.path == "class_advancement_tiers")]
        diagnostics.append(_diagnostic("power.constraints.mode_switch_field", "class_advancement_tiers", "custom game mode cannot be upgraded by constraints output"))
    diagnostics.extend(
        _required_lists(
            payload,
            ("costs", "counters", "boundaries", "social_impact", "visibility", "continuity_ledger"),
            prefix="power.constraints",
        )
    )
    if isinstance(payload, Mapping):
        for field in ("attribute_allocation", *(('class_advancement_tiers',) if class_tiers_allowed else ())):
            if field in payload and not isinstance(payload[field], (list, dict)):
                diagnostics.append(_diagnostic(f"power.constraints.invalid_{field}", field, f"{field} must be JSON structured data"))
            elif field in payload and _contains_placeholder(payload[field]):
                diagnostics.append(_diagnostic(f"power.constraints.{field}.placeholder", field, f"{field} contains placeholder content"))
        if traditional_game:
            tiers = payload.get("class_advancement_tiers")
            if "class_advancement_tiers" not in payload:
                diagnostics.append(_diagnostic("power.constraints.missing_class_advancement_tiers", "class_advancement_tiers", "traditional class tiers are required"))
            elif not isinstance(tiers, list) or tuple(
                tier.get("level") for tier in tiers if isinstance(tier, Mapping)
            ) != GAME_CLASS_ADVANCEMENT_LEVELS or len(tiers) != len(GAME_CLASS_ADVANCEMENT_LEVELS):
                diagnostics.append(_diagnostic("power.constraints.invalid_class_advancement_tiers", "class_advancement_tiers", "traditional class tiers must cover levels 10, 30, and 60"))
            else:
                for index, tier in enumerate(tiers):
                    for field in CLASS_ADVANCEMENT_TIER_FIELDS:
                        value = tier.get(field)
                        valid = _nonempty_list(value) if field == "common_requirements" else value is not None and not isinstance(value, bool) if field == "level" else _nonempty_text(value)
                        if not valid:
                            diagnostics.append(_diagnostic("power.constraints.incomplete_class_advancement_tier", f"class_advancement_tiers[{index}].{field}", f"{field} is required"))
    return _finish(diagnostics)


def _validate_power_final(payload: Any, project: NovelProject, progression_mode: PowerProgressionMode) -> Any:
    diagnostics = _reject_unowned_fields(payload, ("power_system_spec", "power_system"), "power.final")
    if not isinstance(payload, Mapping):
        return _finish(diagnostics)
    spec = payload.get("power_system_spec")
    try:
        plugin = _selected_novel_type_plugin(project)
        validate_power_system_spec(
            _power_spec_for_genre(spec, plugin.plugin_id),
            novel_type_id=plugin.plugin_id,
            template=plugin.power_system_template,
            progression_mode=progression_mode,
        )
    except PowerSystemValidationError as exc:
        for section in exc.missing_sections:
            diagnostics.append(_diagnostic(f"power.final.missing_{section}", section, f"final power spec is missing {section}"))
        for violation in exc.violations:
            diagnostics.append(_diagnostic(f"power.final.{violation}", violation, f"final power spec violates {violation}"))
    if not isinstance(payload.get("power_system"), list):
        diagnostics.append(_diagnostic("power.final.missing_summary", "power_system", "legacy power summary must be a list"))
    return _finish(diagnostics)


def _validate_economy(payload: Any) -> Any:
    diagnostics = _reject_unowned_fields(payload, ("economy_rules",), "world.economy")
    diagnostics.extend(_required_lists(payload, ("economy_rules",), prefix="world.economy"))
    return _finish(diagnostics)


def _validate_locations(payload: Any) -> Any:
    diagnostics = _reject_unowned_fields(payload, ("locations",), "world.locations")
    diagnostics.extend(_entry_list(payload, "locations", prefix="world.locations"))
    return _finish(diagnostics)


def _validate_factions(payload: Any) -> Any:
    diagnostics = _reject_unowned_fields(payload, ("factions",), "world.factions")
    diagnostics.extend(_entry_list(payload, "factions", prefix="world.factions"))
    return _finish(diagnostics)


def _validate_society(payload: Any) -> Any:
    diagnostics = _reject_unowned_fields(payload, ("world_systems", "living_world", "faction_rules"), "world.society")
    if isinstance(payload, Mapping):
        for field in ("world_systems", "living_world"):
            if not isinstance(payload.get(field), Mapping) or not payload.get(field):
                diagnostics.append(_diagnostic(f"world.society.missing_{field}", field, f"{field} must be a non-empty object"))
        diagnostics.extend(_required_lists(payload, ("faction_rules",), prefix="world.society"))
    return _finish(diagnostics)


def _validate_game_ecology(payload: Any) -> Any:
    allowed = ("quest_rules", "panel_rules", "npc_system", "quest_network", "server_runtime", "map_ecology")
    diagnostics = _reject_unowned_fields(payload, allowed, "world.game_ecology")
    if isinstance(payload, Mapping):
        diagnostics.extend(_required_lists(payload, ("quest_rules", "panel_rules"), prefix="world.game_ecology"))
        for field in ("npc_system", "quest_network", "server_runtime", "map_ecology"):
            if not isinstance(payload.get(field), Mapping) or not payload.get(field):
                diagnostics.append(_diagnostic(f"world.game_ecology.missing_{field}", field, f"{field} must be a non-empty object"))
    return _finish(diagnostics)


def _validate_story_engine(payload: Any) -> Any:
    allowed = (
        "current_arc",
        "progression_rules",
        "chapter_formula",
        "forbidden_breaks",
        "opening_arc",
        "volume_plan",
        "longform_framework",
        "progression_ledger",
    )
    diagnostics = _reject_unowned_fields(payload, allowed, "world.story_engine_compat")
    if isinstance(payload, Mapping):
        if not _nonempty_text(payload.get("current_arc")):
            diagnostics.append(_diagnostic("world.story_engine_compat.missing_current_arc", "current_arc", "current_arc is required"))
        for field in ("opening_arc", "volume_plan", "longform_framework"):
            if not isinstance(payload.get(field), Mapping) or not payload.get(field):
                diagnostics.append(_diagnostic(f"world.story_engine_compat.missing_{field}", field, f"{field} must be a non-empty object"))
        for field in ("progression_rules", "chapter_formula", "forbidden_breaks"):
            if not _nonempty_list(payload.get(field)):
                diagnostics.append(_diagnostic(f"world.story_engine_compat.missing_{field}", field, f"{field} must be a non-empty list"))
        if "progression_ledger" in payload and not isinstance(payload.get("progression_ledger"), Mapping):
            diagnostics.append(_diagnostic("world.story_engine_compat.invalid_progression_ledger", "progression_ledger", "progression_ledger must be an object"))
    return _finish(diagnostics)


def make_world_validators(
    project: NovelProject,
    progression_mode: PowerProgressionMode | None = None,
) -> dict[str, Validator]:
    """Return validators closed over the selected genre/template."""

    selected_mode = progression_mode or select_power_progression_mode(project)
    plugin = _selected_novel_type_plugin(project)
    game_world = plugin.plugin_id == "game_webnovel"
    return {
        "world.input": _validate_world_input,
        "world.core_rules": _validate_core_rules,
        "power.foundation": _validate_power_foundation,
        "power.attributes": _validate_power_attributes,
        "power.paths": lambda payload: _validate_power_paths(payload, project, selected_mode),
        "power.stages": _validate_power_stages,
        "power.resources": _validate_power_resources,
        "power.constraints": lambda payload: _validate_power_constraints(payload, selected_mode, game_world=game_world),
        "power.final": lambda payload: _validate_power_final(payload, project, selected_mode),
        "world.economy": _validate_economy,
        "world.locations": _validate_locations,
        "world.factions": _validate_factions,
        "world.society": _validate_society,
        "world.game_ecology": _validate_game_ecology,
        "world.story_engine_compat": _validate_story_engine,
    }


def assemble_power_candidate(
    *,
    foundation: Mapping[str, Any],
    attributes: Mapping[str, Any],
    paths: Mapping[str, Any],
    stages: Mapping[str, Any],
    resources: Mapping[str, Any],
    constraints: Mapping[str, Any],
    project: NovelProject,
    progression_mode: PowerProgressionMode | None = None,
    existing_summary: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the full spec from committed section payloads only."""

    spec: dict[str, Any] = {}
    for section in (foundation, attributes, paths, stages, resources, constraints):
        spec.update(deepcopy(dict(section)))
    plugin = _selected_novel_type_plugin(project)
    selected_mode = progression_mode or select_power_progression_mode(project)
    normalized = validate_power_system_spec(
        _power_spec_for_genre(spec, plugin.plugin_id),
        novel_type_id=plugin.plugin_id,
        template=plugin.power_system_template,
        progression_mode=selected_mode,
    )
    summary = deepcopy(existing_summary) if isinstance(existing_summary, list) and existing_summary else legacy_power_summary(normalized)
    return {"power_system_spec": normalized, "power_system": summary}


POWER_SECTION_FIELDS: dict[str, tuple[str, ...]] = {
    "power_system_foundation": ("name", "origin"),
    "power_system_attributes": ("attributes",),
    "power_system_paths": ("paths",),
    "power_system_stages": ("stages",),
    "power_system_resources": ("skills", "equipment", "resources", "advancement"),
    "power_system_constraints": (
        "costs",
        "counters",
        "boundaries",
        "social_impact",
        "visibility",
        "continuity_ledger",
        "attribute_allocation",
        "class_advancement_tiers",
    ),
}


def decompose_power_spec(spec: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Split a canonical full spec without applying section-only policy."""

    return {
        task_id: {
            field: deepcopy(spec[field])
            for field in fields
            if field in spec
        }
        for task_id, fields in POWER_SECTION_FIELDS.items()
    }


def power_final_owner_task(diagnostic: BuildDiagnostic) -> str | None:
    """Route residual full-spec diagnostics back to one section owner."""

    code = diagnostic.code.removeprefix("power.final.")
    if code.startswith("stages.") or code in {
        "game.invalid_milestones",
        "game.missing_milestones",
        "game.level20_second_transfer",
    }:
        return "power_system_stages"
    if code.startswith("paths.") or code.startswith("game.path_") or code in {
        "game.invalid_classes",
        "game.missing_classes",
    }:
        return "power_system_paths"
    if code.startswith("continuity_ledger.") or code.startswith("game.class_advancement") or code in {
        "game.invalid_class_advancement_tiers",
        "game.incomplete_class_advancement_tier",
    }:
        return "power_system_constraints"
    missing_section_owner = {
        "missing_name": "power_system_foundation",
        "missing_origin": "power_system_foundation",
        "missing_attributes": "power_system_attributes",
        "missing_paths": "power_system_paths",
        "missing_stages": "power_system_stages",
        "missing_skills": "power_system_resources",
        "missing_equipment": "power_system_resources",
        "missing_resources": "power_system_resources",
        "missing_advancement": "power_system_resources",
        "missing_costs": "power_system_constraints",
        "missing_counters": "power_system_constraints",
        "missing_boundaries": "power_system_constraints",
        "missing_social_impact": "power_system_constraints",
        "missing_visibility": "power_system_constraints",
        "missing_continuity_ledger": "power_system_constraints",
        "missing_attribute_allocation": "power_system_constraints",
        "missing_class_advancement_tiers": "power_system_constraints",
    }
    if code in missing_section_owner:
        return missing_section_owner[code]
    for section, task_id in (
        ("foundation", "power_system_foundation"),
        ("attributes", "power_system_attributes"),
        ("resources", "power_system_resources"),
        ("constraints", "power_system_constraints"),
        ("paths", "power_system_paths"),
        ("stages", "power_system_stages"),
    ):
        if code.endswith(section) or code.startswith(f"missing_{section}"):
            return task_id
    return None


__all__ = [
    "POWER_SECTION_FIELDS",
    "assemble_power_candidate",
    "decompose_power_spec",
    "make_world_validators",
    "power_final_owner_task",
]
