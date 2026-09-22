"""Structured repair contracts for residual power-system validation failures."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any

from packages.story_core.build_graph.contracts import BuildDiagnostic
from packages.story_core.models import NovelProject
from packages.story_core.power_system_spec import (
    contains_placeholder_content,
    GAME_CLASS_ADVANCEMENT_LEVELS,
    PATH_FIELDS,
    effective_power_system_template,
    is_placeholder_content,
    uses_traditional_game_class_advancement,
)
from packages.story_core.world_enrichment import _selected_novel_type_plugin


POWER_PATH_REPAIR_SCHEMA = {
    "updates": "{index:int,fields:object}[]",
    "append": "object[]",
}


@dataclass(frozen=True)
class PowerPathRepairScope:
    """Deterministic limits for one final residual path repair."""

    update_fields: Mapping[int, tuple[str, ...]]
    append_count: int
    append_fields: tuple[str, ...]
    append_required_fields: tuple[str, ...] = ()
    replace_indices: tuple[int, ...] = ()

    @property
    def append_allowed_fields(self) -> tuple[str, ...]:
        """Expose the allowed/required distinction without breaking old callers."""

        return self.append_fields

    def as_prompt_payload(self) -> dict[str, Any]:
        return {
            "updates": [
                {"index": index, "fields": list(fields)}
                for index, fields in sorted(self.update_fields.items())
            ],
            "append_count": self.append_count,
            "append_allowed_fields": list(self.append_allowed_fields),
            "append_required_fields": list(self.append_required_fields),
            "replace_indices": list(self.replace_indices),
        }


_POWER_SECTION_TASKS = (
    "power_system_foundation",
    "power_system_attributes",
    "power_system_paths",
    "power_system_stages",
    "power_system_resources",
    "power_system_constraints",
)


def raw_power_spec_from_artifacts(service: Any) -> dict[str, Any]:
    """Assemble committed power sections without canonical validation."""

    raw_spec: dict[str, Any] = {}
    for task_id in _POWER_SECTION_TASKS:
        artifact = service.inspect_artifact(task_id)
        if isinstance(artifact, Mapping):
            payload = artifact.get("payload")
        else:
            payload = getattr(artifact, "payload", None)
        if isinstance(payload, Mapping):
            raw_spec.update(deepcopy(dict(payload)))
    return raw_spec


def _nonempty(value: Any) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return False
    if isinstance(value, str) and is_placeholder_content(value):
        return False
    return True


def _path_field_missing(path: Mapping[str, Any], field: str) -> bool:
    return not _nonempty(path.get(field))


def _traditional_game_contract(
    project: NovelProject,
    paths: Sequence[Any],
    raw_spec: Mapping[str, Any] | None = None,
) -> bool:
    plugin = _selected_novel_type_plugin(project)
    if plugin.plugin_id != "game_webnovel":
        return False
    blueprint = project.world_blueprint if isinstance(project.world_blueprint, Mapping) else {}
    existing = blueprint.get("power_system_spec") if isinstance(blueprint.get("power_system_spec"), Mapping) else {}
    candidate = dict(raw_spec) if isinstance(raw_spec, Mapping) else dict(existing)
    candidate["paths"] = list(paths)
    return uses_traditional_game_class_advancement(candidate)


def _minimum_path_count(
    project: NovelProject,
    paths: Sequence[Any],
    raw_spec: Mapping[str, Any] | None = None,
) -> int:
    plugin = _selected_novel_type_plugin(project)
    blueprint = project.world_blueprint if isinstance(project.world_blueprint, Mapping) else {}
    existing = blueprint.get("power_system_spec") if isinstance(blueprint.get("power_system_spec"), Mapping) else {}
    candidate = dict(raw_spec) if isinstance(raw_spec, Mapping) else dict(existing)
    candidate["paths"] = list(paths)
    template = effective_power_system_template(
        plugin.plugin_id,
        plugin.power_system_template,
        candidate,
    )
    value = template.get("minimum_path_count", 2)
    return max(1, int(value)) if isinstance(value, int) and not isinstance(value, bool) else 2


def _add_field(targets: dict[int, set[str]], index: int, field: str) -> None:
    if field in PATH_FIELDS:
        targets.setdefault(index, set()).add(field)


def _indices_missing(paths: Sequence[Any], field: str) -> set[int]:
    return {
        index
        for index, path in enumerate(paths)
        if isinstance(path, Mapping) and _path_field_missing(path, field)
    }


_PATH_INDEX_RE = re.compile(r"^paths\[(\d+)\](?:\.|$)")


def _diagnostic_path_index(path: Any) -> int | None:
    match = _PATH_INDEX_RE.match(str(path or "").strip())
    return int(match.group(1)) if match else None


def _path_fields_with_placeholder(path: Any) -> tuple[str, ...]:
    if not isinstance(path, Mapping):
        return ()
    return tuple(
        field
        for field in PATH_FIELDS
        if field in path and contains_placeholder_content(path[field])
    )


def _path_required_fields(traditional_game: bool) -> tuple[str, ...]:
    return tuple(PATH_FIELDS) if traditional_game else ("name", "branches")


def _advancement_tree_has_diagnostic(path: Any, code: str) -> bool:
    tree = path.get("advancement_tree") if isinstance(path, Mapping) else None
    if code == "game.path_invalid_advancement_tree":
        if not isinstance(tree, list) or any(not isinstance(node, Mapping) for node in tree):
            return True
        levels = tuple(node.get("level") for node in tree)
        return levels != GAME_CLASS_ADVANCEMENT_LEVELS
    if not isinstance(tree, list):
        return True
    if code == "game.path_incomplete_advancement_node":
        return any(
            not isinstance(node, Mapping)
            or not node.get("tier_name")
            or not isinstance(node.get("options"), list)
            or not node.get("options")
            for node in tree
        )
    if code == "game.path_incomplete_advancement_option":
        for node in tree:
            options = node.get("options") if isinstance(node, Mapping) else None
            if not isinstance(options, list):
                return True
            for option in options:
                if not isinstance(option, Mapping) or any(
                    not option.get(field)
                    for field in ("name", "transfer_task", "ability_changes")
                ):
                    return True
        return False
    return False


def power_path_repair_scope(
    payload: Mapping[str, Any],
    diagnostics: Sequence[BuildDiagnostic],
    project: NovelProject,
    *,
    raw_spec: Mapping[str, Any] | None = None,
) -> PowerPathRepairScope:
    """Translate final diagnostics into item/field-level path repair limits."""

    raw_paths = payload.get("paths") if isinstance(payload, Mapping) else None
    paths = list(raw_paths) if isinstance(raw_paths, list) else []
    targets: dict[int, set[str]] = {}
    replace_indices: set[int] = set()
    append_count = 0
    traditional_game = _traditional_game_contract(project, paths, raw_spec)

    for diagnostic in diagnostics:
        code = diagnostic.code
        for prefix in ("power.final.", "power."):
            if code.startswith(prefix):
                code = code.removeprefix(prefix)
                break
        if code == "paths.minimum_count":
            append_count = max(
                append_count,
                _minimum_path_count(project, paths, raw_spec) - len(paths),
            )
            continue
        if code == "game.missing_classes":
            append_count = max(append_count, 6 - len(paths))
            continue
        if code == "paths.duplicate_names" or code == "game.invalid_classes":
            seen: set[str] = set()
            for index, path in enumerate(paths):
                name = str(path.get("name") or "").casefold() if isinstance(path, Mapping) else ""
                if name and name in seen:
                    _add_field(targets, index, "name")
                elif name:
                    seen.add(name)
            continue
        if code == "paths.distinct_branches":
            for index, path in enumerate(paths):
                branches = path.get("branches") if isinstance(path, Mapping) else None
                if not isinstance(branches, list) or len({str(item).casefold() for item in branches}) < 2:
                    _add_field(targets, index, "branches")
            continue
        if code == "paths.missing_name":
            index = _diagnostic_path_index(diagnostic.path)
            indices = {index} if index is not None else _indices_missing(paths, "name")
            for index in indices:
                _add_field(targets, index, "name")
            continue
        if code.startswith("paths.missing_"):
            field = code.removeprefix("paths.missing_")
            if field in PATH_FIELDS:
                index = _diagnostic_path_index(diagnostic.path)
                indices = {index} if index is not None else _indices_missing(paths, field)
                for index in indices:
                    _add_field(targets, index, field)
            continue
        if code == "paths.placeholder":
            index = _diagnostic_path_index(diagnostic.path)
            if index is not None and index < len(paths):
                for field in _path_fields_with_placeholder(paths[index]):
                    _add_field(targets, index, field)
            continue
        if code == "paths.invalid_item":
            index = _diagnostic_path_index(diagnostic.path)
            if index is not None:
                replace_indices.add(index)
                for field in _path_required_fields(traditional_game):
                    _add_field(targets, index, field)
            continue
        if code.startswith("game.path_missing_"):
            missing = code.removeprefix("game.path_missing_")
            field = {
                "weapon_affinity": "weapons",
                "armor_affinity": "armor",
            }.get(missing, missing)
            for index in _indices_missing(paths, field):
                _add_field(targets, index, field)
            continue
        if code in {
            "game.path_invalid_advancement_tree",
            "game.path_incomplete_advancement_node",
            "game.path_incomplete_advancement_option",
        }:
            for index, path in enumerate(paths):
                if _advancement_tree_has_diagnostic(path, code):
                    _add_field(targets, index, "advancement_tree")

    if traditional_game:
        append_fields = tuple(PATH_FIELDS)
        append_required_fields = tuple(PATH_FIELDS)
    else:
        append_fields = tuple(PATH_FIELDS)
        append_required_fields = ("name", "branches")
    return PowerPathRepairScope(
        update_fields={index: tuple(sorted(fields)) for index, fields in sorted(targets.items())},
        append_count=max(0, append_count),
        append_fields=append_fields,
        append_required_fields=append_required_fields,
        replace_indices=tuple(sorted(replace_indices)),
    )


def merge_power_path_repair(
    base_payload: Mapping[str, Any] | None,
    patch: Mapping[str, Any],
    scope: PowerPathRepairScope,
) -> tuple[dict[str, Any] | None, tuple[BuildDiagnostic, ...]]:
    """Apply only allowed item/field updates and exact bounded appends."""

    if not isinstance(base_payload, Mapping) or not isinstance(base_payload.get("paths"), list):
        return None, (_repair_diagnostic("task.repair_base_missing", "paths", "path repair requires the committed paths payload"),)
    if not isinstance(patch, Mapping):
        return None, (_repair_diagnostic("task.invalid_json", "payload", "path repair must be an object"),)
    unknown = sorted(set(patch).difference({"updates", "append"}))
    if unknown:
        return None, (_repair_diagnostic("task.repair_out_of_scope", "payload", "path repair only allows updates and append"),)

    updates = patch.get("updates", [])
    appends = patch.get("append", [])
    if not isinstance(updates, list) or not isinstance(appends, list):
        return None, (_repair_diagnostic("task.repair_out_of_scope", "payload", "updates and append must be arrays"),)
    if len(appends) < scope.append_count:
        return None, (
            _repair_diagnostic(
                "task.repair_incomplete",
                "append",
                f"path repair requires exactly {scope.append_count} appended path(s)",
            ),
        )
    if len(appends) > scope.append_count:
        return None, (
            _repair_diagnostic(
                "task.repair_out_of_scope",
                "append",
                f"path repair allows exactly {scope.append_count} appended path(s)",
            ),
        )

    expected_indices = set(scope.update_fields)
    actual_indices: set[int] = set()
    for item in updates:
        if not isinstance(item, Mapping):
            return None, (_repair_diagnostic("task.repair_out_of_scope", "updates", "each update must contain index and fields"),)
        index = item.get("index")
        if isinstance(index, bool) or not isinstance(index, int) or index not in expected_indices:
            return None, (_repair_diagnostic("task.repair_out_of_scope", "updates", "update index is not an allowed diagnostic target"),)
        if index in actual_indices:
            return None, (_repair_diagnostic("task.repair_out_of_scope", f"updates[{index}]", "update index may appear only once"),)
        actual_indices.add(index)
    missing_indices = sorted(expected_indices.difference(actual_indices))
    if missing_indices:
        return None, (
            _repair_diagnostic(
                "task.repair_incomplete",
                "updates",
                "path repair omitted diagnostic target index(es): " + ", ".join(map(str, missing_indices)),
            ),
        )

    merged_paths = deepcopy(base_payload["paths"])
    for item in updates:
        if not isinstance(item, Mapping):
            return None, (_repair_diagnostic("task.repair_out_of_scope", "updates", "each update must contain only index and fields"),)
        if set(item).difference({"index", "fields"}):
            return None, (_repair_diagnostic("task.repair_out_of_scope", "updates", "each update must contain only index and fields"),)
        index = item.get("index")
        fields = item.get("fields")
        if isinstance(index, bool) or not isinstance(index, int) or index not in scope.update_fields:
            return None, (_repair_diagnostic("task.repair_out_of_scope", "updates", "update index is not an allowed diagnostic target"),)
        if "fields" not in item or fields is None:
            return None, (_repair_diagnostic("task.repair_incomplete", f"updates[{index}].fields", "update fields are required for every diagnostic target"),)
        if not isinstance(fields, Mapping) or not fields:
            return None, (_repair_diagnostic("task.repair_incomplete", f"updates[{index}].fields", "update fields are required for every diagnostic target"),)
        allowed = set(scope.update_fields[index])
        unexpected = sorted(set(fields).difference(allowed))
        if unexpected:
            return None, (_repair_diagnostic("task.repair_out_of_scope", f"updates[{index}].fields", "update field is outside the diagnostic scope"),)
        missing_fields = sorted(allowed.difference(fields))
        if missing_fields:
            return None, (
                _repair_diagnostic(
                    "task.repair_incomplete",
                    f"updates[{index}].fields",
                    "update omitted diagnostic field(s): " + ", ".join(missing_fields),
                ),
            )
        if index >= len(merged_paths):
            return None, (_repair_diagnostic("task.repair_out_of_scope", f"updates[{index}]", "update index is not present in the committed paths"),)
        if index in scope.replace_indices:
            merged_paths[index] = deepcopy(dict(fields))
        else:
            if not isinstance(merged_paths[index], Mapping):
                return None, (_repair_diagnostic("task.repair_out_of_scope", f"updates[{index}]", "update index is not a repairable path object"),)
            merged_paths[index].update(deepcopy(dict(fields)))

    for index, item in enumerate(appends):
        if not isinstance(item, Mapping) or not item:
            return None, (_repair_diagnostic("task.repair_out_of_scope", f"append[{index}]", "appended path must be an object"),)
        unexpected = sorted(set(item).difference(scope.append_fields))
        if unexpected:
            return None, (_repair_diagnostic("task.repair_out_of_scope", f"append[{index}]", "appended path contains an undeclared field"),)
        missing_required = sorted(set(scope.append_required_fields).difference(item))
        if missing_required:
            return None, (
                _repair_diagnostic(
                    "task.repair_incomplete",
                    f"append[{index}]",
                    "appended path omitted required field(s): " + ", ".join(missing_required),
                ),
            )
        merged_paths.append(deepcopy(dict(item)))
    return {"paths": merged_paths}, ()


def _repair_diagnostic(code: str, path: str, message: str) -> BuildDiagnostic:
    return BuildDiagnostic(code=code, path=path, message=message, severity="blocking")


__all__ = [
    "POWER_PATH_REPAIR_SCHEMA",
    "PowerPathRepairScope",
    "merge_power_path_repair",
    "power_path_repair_scope",
    "raw_power_spec_from_artifacts",
]
