"""Sanctioned migrations for the genre-scoped WorldBuild graph.

The generic Build Graph store deliberately rejects definition changes.  A
WorldBuild graph is different: its task set is intentionally selected from
the project's genre.  This module is the narrow, explicit bridge for that
one migration.  It archives the old graph before a new genre shape is
initialised; it never mutates a generic graph definition in place.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from packages.story_core.build_graph.contracts import (
    BUILD_GRAPH_STATE_SCHEMA,
    BuildGraphState,
    BuildTaskState,
)
from packages.story_core.persistence.project_locking import project_update_lock

from .definition import WORLD_BUILD_GRAPH_ID, WorldBuildGraph


ARCHIVE_SCHEMA = "world-build-graph-archive/v1"
ARCHIVE_DIRNAME = "build_graph_archives"


def _shape_from_task_ids(task_ids: set[str]) -> tuple[bool, bool]:
    return "power_system_final" in task_ids, "game_ecology" in task_ids


def _archive_root(store: Any) -> Path:
    return store.webnovel_dir / ARCHIVE_DIRNAME


def _read_json(store: Any, path: Path, default: Any = None) -> Any:
    return store.snapshot_store.read_json(path, default)


def _finalize_pending_archives(store: Any) -> None:
    root = _archive_root(store)
    if not root.exists():
        return
    for manifest_path in sorted(root.glob("*/archive.json")):
        manifest = _read_json(store, manifest_path, {})
        if not isinstance(manifest, dict) or not manifest.get("cleanup_pending"):
            continue
        for raw_path in manifest.get("cleanup_paths", []):
            try:
                path = Path(str(raw_path)).resolve()
                path.relative_to(store.webnovel_dir.resolve())
            except (TypeError, ValueError, OSError):
                continue
            path.unlink(missing_ok=True)
        manifest["cleanup_pending"] = False
        store.snapshot_store.replace_json_transaction({manifest_path: manifest})


def _active_files(store: Any) -> list[Path]:
    paths: list[Path] = []
    for directory in (store.build_graph_store().artifacts_dir, store.build_graph_store().runs_dir):
        if directory.exists():
            paths.extend(path for path in directory.rglob("*.json") if path.is_file())
    return sorted(paths)


def _fresh_state(graph: WorldBuildGraph) -> BuildGraphState:
    tasks = {
        task_id: BuildTaskState(
            task_id=task_id,
            status=("ready" if not graph.spec(task_id).task.dependencies else "blocked"),
        )
        for task_id in graph.definition.ordered_task_ids
    }
    return BuildGraphState(
        schema_version=BUILD_GRAPH_STATE_SCHEMA,
        graph_id=graph.definition.graph_id,
        graph_revision=0,
        tasks=tasks,
        runs={},
        definition_fingerprint=graph.definition.definition_fingerprint,
    )


def prepare_world_graph_migration(store: Any, graph: WorldBuildGraph) -> bool:
    """Archive and reset a changed WorldBuild genre shape, if sanctioned.

    Returns ``True`` only when a shape migration was performed.  Same-shape
    definition changes, unknown graph ids, and unsupported state schemas are
    intentionally left to ``BuildGraphStore.initialize`` so its hard-reject
    safety rule remains universal.
    """

    graph_store = store.build_graph_store()
    with project_update_lock(store.root):
        _finalize_pending_archives(store)
        existing = graph_store.read_state()
        if existing is None:
            return False
        if existing.schema_version != BUILD_GRAPH_STATE_SCHEMA:
            return False
        if existing.graph_id != WORLD_BUILD_GRAPH_ID:
            return False
        old_shape = _shape_from_task_ids(set(existing.tasks))
        new_shape = (graph.structured_power, graph.game_world)
        if old_shape == new_shape:
            return False

        archive_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
        archive_dir = _archive_root(store) / archive_id
        old_files = _active_files(store)
        cleanup_paths = [str(path.resolve()) for path in old_files]
        archive_payloads: dict[Path, Any] = {}
        archived_files: list[str] = []
        raw_state = _read_json(store, graph_store.state_path, None)
        if raw_state is not None:
            archive_payloads[archive_dir / "build_graph.json"] = raw_state
            archived_files.append("build_graph.json")
        for path in old_files:
            relative = path.relative_to(store.webnovel_dir)
            target = archive_dir / relative
            raw = _read_json(store, path, None)
            if raw is not None:
                archive_payloads[target] = raw
                archived_files.append(str(relative))

        manifest_path = archive_dir / "archive.json"
        manifest = {
            "schema_version": ARCHIVE_SCHEMA,
            "archive_id": archive_id,
            "graph_id": existing.graph_id,
            "old_definition_fingerprint": existing.definition_fingerprint,
            "new_definition_fingerprint": graph.definition.definition_fingerprint,
            "old_shape": {"structured_power": old_shape[0], "game_world": old_shape[1]},
            "new_shape": {"structured_power": new_shape[0], "game_world": new_shape[1]},
            "archived_files": archived_files,
            "cleanup_paths": cleanup_paths,
            "cleanup_pending": True,
        }
        archive_payloads[manifest_path] = manifest
        archive_payloads[graph_store.state_path] = _fresh_state(graph).to_dict()
        store.snapshot_store.replace_json_transaction(archive_payloads)

        for path in old_files:
            path.unlink(missing_ok=True)
        manifest["cleanup_pending"] = False
        store.snapshot_store.replace_json_transaction({manifest_path: manifest})
        return True


__all__ = ["ARCHIVE_SCHEMA", "prepare_world_graph_migration"]
