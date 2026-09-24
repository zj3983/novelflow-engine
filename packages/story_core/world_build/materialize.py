"""Materialize committed WorldBuild artifacts into the legacy project shape.

The Build Graph is the source of truth.  This module is intentionally the
only compatibility boundary that turns a ready graph into ``NovelProject``
fields and the old ``world_build_artifacts`` progress projection.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
from typing import Any

from packages.story_core.models import NovelProject
from packages.story_core.power_system_spec import (
    PowerSystemValidationError,
    validate_power_system_spec,
)
from packages.story_core.persistence.project_locking import project_update_lock
from packages.story_core.world_enrichment import (
    _merge_enrichment,
    _power_spec_for_genre,
    _selected_novel_type_plugin,
)

from .definition import WorldBuildGraph
from .tasks import bounded_json_projection, task_payload_from_project
from .validators import decompose_power_spec


MATERIALIZATION_SCHEMA = "build-graph-materialization/v1"
MATERIALIZATION_FILENAME = "build_graph_materialization.json"


def materialization_path(store: Any):
    return store.webnovel_dir / MATERIALIZATION_FILENAME


def read_materialization(store: Any) -> dict[str, Any] | None:
    raw = store.snapshot_store.read_json(materialization_path(store), None)
    return dict(raw) if isinstance(raw, Mapping) else None


def _json_hash(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError):
        encoded = json.dumps(
            bounded_json_projection(value, chars=1200, items=32, depth=8),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _path_value(project: NovelProject, path: str) -> Any:
    tokens = str(path).split(".")
    if not tokens:
        return None
    current: Any = project.model_dump(mode="json")
    for token in tokens:
        if isinstance(current, Mapping):
            current = current.get(token)
        else:
            return None
    return current


def _domain_hashes(project: NovelProject, graph: WorldBuildGraph) -> dict[str, str]:
    paths = sorted(
        {
            path
            for spec in graph.specs.values()
            for path in spec.domain_paths
        }
    )
    return {path: _json_hash(_path_value(project, path)) for path in paths}


def materialized_domain_conflicts(
    project: NovelProject, graph: WorldBuildGraph, marker: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    """Find project fields edited since the last graph materialization."""

    if not marker or marker.get("graph_id") != graph.definition.graph_id:
        return ()
    recorded = marker.get("domain_hashes")
    if not isinstance(recorded, Mapping):
        return ()
    current = _domain_hashes(project, graph)
    return tuple(sorted(
        path for path, old_hash in recorded.items()
        if path in current and old_hash != current[path]
    ))


def graph_artifact_revisions(service: Any, graph: WorldBuildGraph) -> dict[str, int]:
    state = service.inspect_graph()
    revisions: dict[str, int] = {}
    for task_id in graph.definition.ordered_task_ids:
        task_state = state.tasks[task_id]
        if task_state.status != "completed" or task_state.current_artifact_revision is None:
            continue
        revisions[task_id] = int(task_state.current_artifact_revision)
    return revisions


def write_materialization_marker(
    store: Any,
    graph: WorldBuildGraph,
    service: Any,
    project: NovelProject,
) -> dict[str, Any]:
    """Record the exact graph revisions and domain hashes used for materialization."""

    payload = materialization_payload(graph, service, project)
    with project_update_lock(store.root):
        store.snapshot_store.replace_json_transaction({materialization_path(store): payload})
    return payload


def materialization_payload(
    graph: WorldBuildGraph,
    service: Any,
    project: NovelProject,
) -> dict[str, Any]:
    """Build the marker payload without performing a filesystem write."""

    payload = {
        "schema_version": MATERIALIZATION_SCHEMA,
        "graph_id": graph.definition.graph_id,
        "power_progression_mode": graph.power_progression_mode,
        "artifact_revisions": graph_artifact_revisions(service, graph),
        "domain_hashes": _domain_hashes(project, graph),
    }
    return payload


def _project_world(project: NovelProject) -> dict[str, Any]:
    return deepcopy(project.world_blueprint) if isinstance(project.world_blueprint, Mapping) else {}


def _assembled_payload(service: Any, graph: WorldBuildGraph) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for task_id in graph.definition.ordered_task_ids:
        if task_id == "world_input":
            continue
        artifact = service.inspect_artifact(task_id)
        if artifact is None:
            continue
        if isinstance(artifact.payload, Mapping):
            payload.update(deepcopy(dict(artifact.payload)))
    return payload


def legacy_artifacts_projection(service: Any, graph: WorldBuildGraph) -> list[dict[str, Any]]:
    """Return the bounded legacy progress view from current committed artifacts."""

    rows: list[dict[str, Any]] = []
    for task_id in graph.definition.ordered_task_ids:
        if task_id == "world_input":
            continue
        spec = graph.spec(task_id)
        artifact = service.inspect_artifact(task_id)
        if artifact is None:
            continue
        payload = artifact.payload if isinstance(artifact.payload, Mapping) else {}
        fields = [str(key) for key in payload.keys()]
        if not fields:
            fields = list(spec.output_fields)
        rows.append(
            {
                "module_id": task_id,
                "title": spec.task.title,
                "status": "completed",
                "fields": fields,
                "output": bounded_json_projection(payload, chars=280, items=16, depth=5),
            }
        )
    return rows


def _graph_owned_project(project: NovelProject, graph: WorldBuildGraph) -> NovelProject:
    """Clear graph-owned values before applying the committed projection.

    Clearing is important because ``_merge_enrichment`` intentionally keeps
    existing values authoritative.  The values are reintroduced from graph
    artifacts below, so this does not discard an author value that was first
    imported into the graph; it prevents an untracked legacy field from
    silently winning over the graph's current revision.
    """

    candidate = project.model_copy(deep=True)
    blueprint = _project_world(candidate)
    # A genre migration can remove tasks.  Clear all known WorldBuild-owned
    # fields that are not owned by the new graph so an old power/game output
    # cannot survive merely because the new graph has no task for it.
    known_paths = {
        "premise", "world_rules", "constraints", "economy_rules", "locations",
        "factions", "world_systems", "living_world", "faction_rules",
        "power_system_spec", "power_system", "quest_rules", "panel_rules",
        "npc_system", "quest_network", "server_runtime", "map_ecology",
        "current_arc", "progression_rules", "chapter_formula", "forbidden_breaks",
        "opening_arc", "volume_plan", "longform_framework", "progression_ledger",
    }
    owned_fields = {
        path.split(".", 1)[1]
        for spec in graph.specs.values()
        for path in spec.domain_paths
        if path.startswith("world_blueprint.") and "." not in path.split(".", 1)[1]
    }
    for field in known_paths - owned_fields:
        blueprint.pop(field, None)
    for spec in graph.specs.values():
        for path in spec.domain_paths:
            parts = path.split(".")
            if len(parts) == 2 and parts[0] == "world_blueprint":
                blueprint.pop(parts[1], None)
    candidate.world_blueprint = blueprint
    for spec in graph.specs.values():
        if "world_blueprint.premise" in spec.domain_paths:
            candidate.world_summary = ""
        if "world_blueprint.current_arc" in spec.domain_paths:
            candidate.current_focus = ""
    return candidate


def materialize_project(
    project: NovelProject,
    graph: WorldBuildGraph,
    service: Any,
) -> NovelProject:
    """Build a project candidate solely from completed graph artifacts."""

    payload = _assembled_payload(service, graph)
    base = _graph_owned_project(project, graph)
    result = _merge_enrichment(
        base,
        {"world_blueprint": payload},
        rules_only=False,
    )
    # ``author_constraints`` is an input boundary, not a generated mirror.
    # The legacy merge helper also derives constraints from the blueprint; do
    # not let those derived values change the next world_input revision.
    result.author_constraints = deepcopy(project.author_constraints)
    # ``_merge_enrichment`` historically derives a new legacy summary when a
    # power spec is supplied.  The graph final artifact already carries the
    # canonical summary (including an author's imported summary), so the
    # compatibility projection must use that committed value verbatim.
    if isinstance(payload.get("power_system"), list) and payload.get("power_system"):
        result.world_blueprint["power_system"] = deepcopy(payload["power_system"])
    result.world_blueprint["power_progression_mode"] = graph.power_progression_mode
    result.world_blueprint["world_build_artifacts"] = legacy_artifacts_projection(service, graph)
    return result


def reconcile_project_to_graph(
    project: NovelProject,
    graph: WorldBuildGraph,
    service: Any,
    *,
    store: Any,
) -> bool:
    """Detect an author edit made after the last graph materialization.

    The marker stores hashes rather than a second copy of project content.  A
    changed hash is treated as a human artifact edit and goes through the
    normal ownership/validator/revision boundary.  ``True`` means the graph
    changed and the caller should continue its normal stale/resume loop.
    """

    marker = read_materialization(store)
    if not marker or marker.get("schema_version") != MATERIALIZATION_SCHEMA:
        return False
    if marker.get("graph_id") != graph.definition.graph_id:
        return False
    current_revisions = graph_artifact_revisions(service, graph)
    if dict(marker.get("artifact_revisions") or {}) != current_revisions:
        return False
    saved_hashes = marker.get("domain_hashes")
    if not isinstance(saved_hashes, Mapping):
        return False
    current_hashes = _domain_hashes(project, graph)
    changed_paths = [
        path
        for path in sorted(saved_hashes)
        if str(saved_hashes.get(path)) != current_hashes.get(path)
    ]
    if not changed_paths:
        return False

    changed_set = set(changed_paths)

    # A whole power-spec edit is a domain-level edit, not an edit to the
    # deterministic finalizer.  Validate the canonical spec first, split it
    # into section-owned artifacts, and let the finalizer create the new
    # official aggregate.  This keeps section provenance truthful.
    full_power_edit = bool(
        {"world_blueprint.power_system_spec", "world_blueprint.power_system"}
        & changed_set
    )
    if full_power_edit and graph.structured_power:
        raw_spec = _project_world(project).get("power_system_spec")
        plugin = _selected_novel_type_plugin(project)
        try:
            normalized_spec = validate_power_system_spec(
                _power_spec_for_genre(raw_spec, plugin.plugin_id),
                novel_type_id=plugin.plugin_id,
                template=plugin.power_system_template,
                progression_mode=graph.power_progression_mode,
            )
        except PowerSystemValidationError as exc:
            detail = ",".join((*exc.missing_sections, *exc.violations)) or "invalid_power_system_spec"
            raise ValueError(f"world_build_external_power_spec_invalid:{detail}") from exc

        section_payloads = decompose_power_spec(normalized_spec)
        section_ids = tuple(section_payloads)
        changed_section = False
        changed_sections: set[str] = set()
        for task_id in section_ids:
            task_state = service.inspect_task(task_id)
            candidate = section_payloads[task_id]
            current_artifact = service.inspect_artifact(task_id)
            if current_artifact is not None and current_artifact.payload == candidate:
                continue
            result = service.edit_artifact(
                task_id,
                candidate,
                expected_revision=task_state.current_artifact_revision,
                requested_writes=graph.spec(task_id).task.owns,
            ) if current_artifact is not None else service.commit_candidate(
                task_id,
                candidate,
                expected_revision=None,
                source="human",
                requested_writes=graph.spec(task_id).task.owns,
            )
            if result.artifact is None:
                diagnostics = ", ".join(item.code for item in result.validation.diagnostics)
                raise ValueError(
                    f"world_build_external_power_spec_invalid:{task_id}:{diagnostics or 'validation_failed'}"
                )
            changed_section = True
            changed_sections.add(task_id)

        # Editing an upstream section makes dependent section artifacts stale
        # by design.  A canonical full-spec edit already supplies those
        # dependent values, so revalidate their unchanged payloads
        # deterministically instead of issuing fresh model calls.
        if changed_section:
            for task_id in section_ids:
                if task_id in changed_sections:
                    continue
                task_state = service.inspect_task(task_id)
                if task_state.status != "stale" or task_state.current_artifact_revision is None:
                    continue
                result = service.revalidate_current(task_id)
                if result.artifact is None:
                    diagnostics = ", ".join(item.code for item in result.validation.diagnostics)
                    raise ValueError(
                        f"world_build_external_power_spec_invalid:{task_id}:{diagnostics or 'validation_failed'}"
                    )

        if not changed_section and "world_blueprint.power_system" in changed_set:
            # The summary is still part of the final artifact's compatibility
            # projection.  Force a deterministic reassembly without inventing
            # a human-owned final artifact.
            service.invalidate_task(
                "power_system_final",
                [
                    {
                        "code": "power.summary.human_edit",
                        "path": "power_system",
                        "message": "legacy power summary changed; deterministic finalization required",
                        "severity": "blocking",
                    }
                ],
            )
        changed_set -= {
            "world_blueprint.power_system_spec",
            "world_blueprint.power_system",
        }
    for task_id in graph.definition.ordered_task_ids:
        spec = graph.spec(task_id)
        owned_paths = set(spec.domain_paths)
        if not owned_paths.intersection(changed_set):
            continue
        task_state = service.inspect_task(task_id)
        if task_state.current_artifact_revision is None:
            continue
        candidate = task_payload_from_project(project, task_id)
        result = service.edit_artifact(
            task_id,
            candidate,
            expected_revision=task_state.current_artifact_revision,
            requested_writes=spec.task.owns,
        )
        if result.artifact is None:
            diagnostics = ", ".join(item.code for item in result.validation.diagnostics)
            raise ValueError(
                f"world_build_external_edit_invalid:{task_id}:{diagnostics or 'validation_failed'}"
            )
    return True


__all__ = [
    "MATERIALIZATION_FILENAME",
    "MATERIALIZATION_SCHEMA",
    "graph_artifact_revisions",
    "legacy_artifacts_projection",
    "materialization_payload",
    "materialization_path",
    "materialize_project",
    "materialized_domain_conflicts",
    "read_materialization",
    "reconcile_project_to_graph",
    "write_materialization_marker",
]
