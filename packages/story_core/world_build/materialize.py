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
from packages.story_core.persistence.project_locking import project_update_lock
from packages.story_core.world_enrichment import _merge_enrichment

from .definition import WorldBuildGraph
from .tasks import bounded_json_projection, task_payload_from_project


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

    payload = {
        "schema_version": MATERIALIZATION_SCHEMA,
        "graph_id": graph.definition.graph_id,
        "artifact_revisions": graph_artifact_revisions(service, graph),
        "domain_hashes": _domain_hashes(project, graph),
    }
    with project_update_lock(store.root):
        store.snapshot_store.replace_json_transaction({materialization_path(store): payload})
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
    "materialization_path",
    "materialize_project",
    "read_materialization",
    "reconcile_project_to_graph",
    "write_materialization_marker",
]
