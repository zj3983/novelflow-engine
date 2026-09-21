"""Atomic file persistence for Build Graph manifests and artifact history."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from packages.story_core.persistence.snapshot_store import SnapshotStore
from packages.story_core.persistence.project_locking import project_update_lock

from .contracts import (
    BUILD_GRAPH_STATE_SCHEMA,
    BuildArtifact,
    BuildDefinitionError,
    BuildGraphState,
    BuildRun,
)
from .definition import BuildGraphDefinition, validate_task_id


class BuildGraphStore:
    """Persist graph state and immutable artifact revisions under ``.webnovel``.

    The store intentionally knows nothing about a project's domain model.  A
    service supplies the complete next state and this class commits the state,
    newly-created artifacts, and mutable run records through the existing
    :class:`SnapshotStore` transaction primitive.
    """

    def __init__(self, root: str | Path, *, snapshot_store: SnapshotStore | None = None):
        self.root = Path(root).resolve()
        self.webnovel_dir = self.root / ".webnovel"
        self.state_path = self.webnovel_dir / "build_graph.json"
        self.artifacts_dir = self.webnovel_dir / "build_artifacts"
        self.runs_dir = self.webnovel_dir / "build_runs"
        self.snapshot_store = snapshot_store or SnapshotStore()

    @staticmethod
    def _safe_file_id(value: str, *, label: str) -> str:
        try:
            return validate_task_id(value)
        except BuildDefinitionError as exc:
            raise BuildDefinitionError(
                "build_unsafe_path",
                f"{label} is not safe for Build Graph persistence",
                path=label,
                details={"value": str(value)},
            ) from exc

    def artifact_path(self, task_id: str, revision: int) -> Path:
        safe_task_id = self._safe_file_id(task_id, label="task_id")
        if int(revision) < 1:
            raise ValueError("build_artifact_revision_invalid")
        return self.artifacts_dir / safe_task_id / f"{int(revision)}.json"

    def run_path(self, run_id: str) -> Path:
        safe_run_id = self._safe_file_id(run_id, label="run_id")
        return self.runs_dir / f"{safe_run_id}.json"

    def read_state(self) -> BuildGraphState | None:
        raw = self.snapshot_store.read_json(self.state_path, None)
        if not isinstance(raw, dict):
            return None
        return BuildGraphState.from_dict(raw)

    def read_artifact(self, task_id: str, revision: int | None = None) -> BuildArtifact | None:
        safe_task_id = self._safe_file_id(task_id, label="task_id")
        target_revision = revision
        if target_revision is None:
            state = self.read_state()
            task = state.tasks.get(safe_task_id) if state else None
            target_revision = task.current_artifact_revision if task else None
        if target_revision is None:
            return None
        path = self.artifact_path(safe_task_id, int(target_revision))
        raw = self.snapshot_store.read_json(path, None)
        return BuildArtifact.from_dict(raw) if isinstance(raw, dict) else None

    def artifact_history(self, task_id: str) -> tuple[BuildArtifact, ...]:
        safe_task_id = self._safe_file_id(task_id, label="task_id")
        directory = self.artifacts_dir / safe_task_id
        if not directory.exists():
            return ()
        artifacts: list[BuildArtifact] = []
        for path in sorted(directory.glob("*.json"), key=lambda item: item.stem):
            if not path.stem.isdigit():
                continue
            raw = self.snapshot_store.read_json(path, None)
            if isinstance(raw, dict):
                artifacts.append(BuildArtifact.from_dict(raw))
        return tuple(sorted(artifacts, key=lambda item: item.revision))

    def read_run(self, run_id: str) -> BuildRun | None:
        raw = self.snapshot_store.read_json(self.run_path(run_id), None)
        return BuildRun.from_dict(raw) if isinstance(raw, dict) else None

    def initialize(self, definition: BuildGraphDefinition) -> BuildGraphState:
        with project_update_lock(self.root):
            existing = self.read_state()
            if existing is not None:
                expected = set(definition.tasks_by_id)
                actual = set(existing.tasks)
                if existing.graph_id != definition.graph_id or actual != expected:
                    raise BuildDefinitionError(
                        "build_graph_state_mismatch",
                        "persisted Build Graph state does not match the code definition",
                        details={
                            "graph_id": existing.graph_id,
                            "expected_graph_id": definition.graph_id,
                            "missing_tasks": sorted(expected - actual),
                            "unknown_tasks": sorted(actual - expected),
                        },
                    )
                return existing
            task_states = {}
            for task_id in definition.ordered_task_ids:
                task = definition.tasks_by_id[task_id]
                task_states[task_id] = self._initial_task_state(task_id, task.dependencies)
            state = BuildGraphState(
                schema_version=BUILD_GRAPH_STATE_SCHEMA,
                graph_id=definition.graph_id,
                graph_revision=0,
                tasks=task_states,
                runs={},
            )
            self.persist(state)
            return state

    @staticmethod
    def _initial_task_state(task_id: str, dependencies: Iterable[str]):
        from .contracts import BuildTaskState

        return BuildTaskState(
            task_id=task_id,
            status="ready" if not tuple(dependencies) else "blocked",
        )

    def persist(
        self,
        state: BuildGraphState,
        *,
        artifacts: Iterable[BuildArtifact] = (),
        runs: Iterable[BuildRun] = (),
    ) -> None:
        """Atomically write the manifest and any new artifact/run records."""

        with project_update_lock(self.root):
            payloads: dict[Path, Any] = {self.state_path: state.to_dict()}
            for artifact in artifacts:
                path = self.artifact_path(artifact.task_id, artifact.revision)
                if path.exists():
                    existing_raw = self.snapshot_store.read_json(path, None)
                    existing = BuildArtifact.from_dict(existing_raw) if isinstance(existing_raw, dict) else None
                    if existing is None or existing.to_dict() != artifact.to_dict():
                        raise BuildDefinitionError(
                            "build_artifact_immutable",
                            "an artifact revision cannot be overwritten",
                            path=str(path),
                        )
                    continue
                payloads[path] = artifact.to_dict()
            for run in runs:
                payloads[self.run_path(run.run_id)] = run.to_dict()
            self.snapshot_store.replace_json_transaction(payloads)


__all__ = ["BuildGraphStore"]
