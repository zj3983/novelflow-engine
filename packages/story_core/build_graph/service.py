"""Service primitives for concurrent, versioned Build Graph execution."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from packages.story_core.persistence.project_locking import project_update_lock

from .contracts import (
    ARTIFACT_SOURCES,
    BuildArtifact,
    BuildCommitResult,
    BuildDiagnostic,
    BuildGraphState,
    BuildReadiness,
    BuildRevisionConflict,
    BuildRun,
    BuildRunConflict,
    BuildTaskState,
    BuildTaskStateError,
    BuildValidationResult,
)
from .definition import BuildGraphDefinition, BuildTaskDefinition, validate_task_id
from .store import BuildGraphStore
from .validation import Validator, disposition_for, validate_candidate


_UNSET = object()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BuildGraphService:
    """One state machine used by human edits and future AI task runners."""

    def __init__(
        self,
        definition: BuildGraphDefinition,
        *,
        store: BuildGraphStore,
        validators: Mapping[str, Validator] | None = None,
        clock: Callable[[], str] = _now,
        run_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.definition = definition
        self.store = store
        self.validators = dict(validators or {})
        self.clock = clock
        self.run_id_factory = run_id_factory or (lambda: str(uuid4()))
        with project_update_lock(self.store.root):
            self.store.initialize(definition)

    # ------------------------------------------------------------------
    # Read and state helpers
    # ------------------------------------------------------------------
    def _read_state(self) -> BuildGraphState:
        return self.store.initialize(self.definition)

    def _task(self, task_id: str) -> BuildTaskDefinition:
        safe_task_id = validate_task_id(task_id)
        try:
            return self.definition.tasks_by_id[safe_task_id]
        except KeyError as exc:
            raise BuildTaskStateError(
                "build_task_not_found",
                f"unknown Build Graph task: {safe_task_id}",
                path="task_id",
            ) from exc

    @staticmethod
    def _replace_state(
        state: BuildGraphState,
        *,
        tasks: Mapping[str, BuildTaskState] | None = None,
        runs: Mapping[str, BuildRun] | None = None,
    ) -> BuildGraphState:
        return BuildGraphState(
            schema_version=state.schema_version,
            graph_id=state.graph_id,
            graph_revision=state.graph_revision + 1,
            tasks=dict(tasks if tasks is not None else state.tasks),
            runs=dict(runs if runs is not None else state.runs),
            definition_fingerprint=state.definition_fingerprint,
        )

    def _dependency_revisions(
        self,
        state: BuildGraphState,
        task: BuildTaskDefinition,
    ) -> dict[str, int]:
        revisions: dict[str, int] = {}
        blocked: list[str] = []
        for dependency in task.dependencies:
            dependency_state = state.tasks[dependency]
            if dependency_state.status != "completed" or dependency_state.current_artifact_revision is None:
                blocked.append(dependency)
            else:
                revisions[dependency] = dependency_state.current_artifact_revision
        if blocked:
            raise BuildTaskStateError(
                "build_dependencies_incomplete",
                "all task dependencies must be completed before execution",
                details={"task_id": task.task_id, "blocked_by": blocked},
            )
        return revisions

    def _assert_expected_revision(
        self,
        task_id: str,
        current_revision: int | None,
        expected_revision: int | None | object,
    ) -> None:
        if expected_revision is _UNSET:
            if current_revision is not None:
                raise BuildRevisionConflict(
                    "build_revision_conflict",
                    "expected_revision is required when replacing an artifact",
                    details={"task_id": task_id, "current_revision": current_revision},
                )
            return
        expected = None if expected_revision is None else int(expected_revision)
        if expected != current_revision and not (expected == 0 and current_revision is None):
            raise BuildRevisionConflict(
                "build_revision_conflict",
                "artifact revision no longer matches expected_revision",
                details={
                    "task_id": task_id,
                    "expected_revision": expected,
                    "current_revision": current_revision,
                },
            )

    def _set_task(
        self,
        tasks: dict[str, BuildTaskState],
        task_id: str,
        **changes: Any,
    ) -> None:
        tasks[task_id] = replace(tasks[task_id], updated_at=self.clock(), **changes)

    def _mark_descendants_stale(
        self,
        tasks: dict[str, BuildTaskState],
        task_id: str,
    ) -> None:
        children: dict[str, list[str]] = {item.task_id: [] for item in self.definition.tasks}
        for item in self.definition.tasks:
            for dependency in item.dependencies:
                children[dependency].append(item.task_id)
        queue = list(sorted(children.get(task_id, [])))
        visited: set[str] = set()
        while queue:
            child_id = queue.pop(0)
            if child_id in visited:
                continue
            visited.add(child_id)
            child_state = tasks[child_id]
            if child_state.current_artifact_revision is not None:
                self._set_task(
                    tasks,
                    child_id,
                    status="stale",
                    validation_status="unknown",
                )
            elif child_state.status != "running":
                self._set_task(tasks, child_id, status="blocked", validation_status="unknown")
            queue.extend(sorted(children.get(child_id, [])))

    def _refresh_unmaterialized_tasks(self, tasks: dict[str, BuildTaskState]) -> None:
        """Unlock tasks whose dependencies are now completed.

        A task with an artifact is never silently returned to ``completed``;
        upstream changes have already marked it stale and it must be
        revalidated or regenerated explicitly.
        """

        for task_id in self.definition.ordered_task_ids:
            state = tasks[task_id]
            if state.current_artifact_revision is not None or state.active_run_id:
                continue
            if state.status in {"validation_failed", "review_required", "completed", "stale"}:
                continue
            dependencies_ready = all(
                tasks[dependency].status == "completed"
                and tasks[dependency].current_artifact_revision is not None
                for dependency in self.definition.tasks_by_id[task_id].dependencies
            )
            self._set_task(
                tasks,
                task_id,
                status="ready" if dependencies_ready else "blocked",
            )

    def _mark_active_run_conflict(
        self,
        tasks: dict[str, BuildTaskState],
        runs: dict[str, BuildRun],
        task_id: str,
        *,
        code: str = "build_run_superseded",
        message: str = "an active run was superseded by a newer edit",
    ) -> BuildRun | None:
        active_run_id = tasks[task_id].active_run_id
        if not active_run_id:
            return None
        run = runs.get(active_run_id)
        conflicted_run: BuildRun | None = None
        if run and run.status == "running":
            conflicted_run = replace(
                run,
                status="conflict",
                finished_at=self.clock(),
                diagnostics=(BuildDiagnostic(code, f"tasks.{task_id}", message),),
            )
            runs[active_run_id] = conflicted_run
        self._set_task(tasks, task_id, active_run_id=None)
        return conflicted_run

    def _validate(
        self,
        task: BuildTaskDefinition,
        payload: Any,
        requested_writes: Iterable[str] | None,
    ) -> tuple[BuildValidationResult, tuple[str, ...]]:
        return validate_candidate(
            task,
            payload,
            requested_writes=requested_writes,
            validators=self.validators,
        )

    # ------------------------------------------------------------------
    # Inspection and validation
    # ------------------------------------------------------------------
    def inspect_graph(self) -> BuildGraphState:
        with project_update_lock(self.store.root):
            return self._read_state()

    def inspect_task(self, task_id: str) -> BuildTaskState:
        self._task(task_id)
        with project_update_lock(self.store.root):
            state = self._read_state()
            return state.tasks[validate_task_id(task_id)]

    def inspect_artifact(self, task_id: str, revision: int | None = None) -> BuildArtifact | None:
        self._task(task_id)
        with project_update_lock(self.store.root):
            return self.store.read_artifact(validate_task_id(task_id), revision)

    def artifact_history(self, task_id: str) -> tuple[BuildArtifact, ...]:
        self._task(task_id)
        with project_update_lock(self.store.root):
            return self.store.artifact_history(validate_task_id(task_id))

    def validate(
        self,
        task_id: str,
        payload: Any,
        *,
        requested_writes: Iterable[str] | None = None,
    ) -> BuildValidationResult:
        task = self._task(task_id)
        validation, _ = self._validate(task, payload, requested_writes)
        return validation.with_disposition(disposition_for(validation, task.review_policy))

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------
    def start_run(
        self,
        task_id: str,
        *,
        input_fingerprint: str | None = None,
        read_projection: Mapping[str, Any] | None = None,
    ) -> BuildRun:
        task = self._task(task_id)
        with project_update_lock(self.store.root):
            state = self._read_state()
            current = state.tasks[task.task_id]
            if current.active_run_id:
                raise BuildTaskStateError(
                    "build_run_active",
                    "task already has an active run",
                    details={"task_id": task.task_id, "run_id": current.active_run_id},
                )
            if current.status not in {"ready", "stale", "validation_failed"}:
                raise BuildTaskStateError(
                    "build_task_not_runnable",
                    "task must be ready, stale, or validation_failed before starting a run",
                    details={"task_id": task.task_id, "status": current.status},
                )
            dependency_revisions = self._dependency_revisions(state, task)
            run_id = str(self.run_id_factory())
            validate_task_id(run_id)
            if run_id in state.runs:
                raise BuildTaskStateError("build_run_id_duplicate", "run_id already exists")
            run = BuildRun(
                run_id=run_id,
                task_id=task.task_id,
                base_artifact_revision=current.current_artifact_revision,
                dependency_revisions=dependency_revisions,
                started_at=self.clock(),
                input_fingerprint=str(input_fingerprint) if input_fingerprint else None,
                read_projection=read_projection,
            )
            tasks = dict(state.tasks)
            runs = dict(state.runs)
            self._set_task(tasks, task.task_id, status="running", active_run_id=run_id)
            runs[run_id] = run
            next_state = self._replace_state(state, tasks=tasks, runs=runs)
            self.store.persist(next_state, runs=(run,))
            return run

    def _run_conflict_locked(
        self,
        state: BuildGraphState,
        run: BuildRun,
        *,
        message: str,
    ) -> None:
        tasks = dict(state.tasks)
        runs = dict(state.runs)
        runs[run.run_id] = replace(
            run,
            status="conflict",
            finished_at=self.clock(),
            diagnostics=(BuildDiagnostic("build_run_conflict", f"runs.{run.run_id}", message),),
        )
        if run.task_id in tasks and tasks[run.task_id].active_run_id == run.run_id:
            self._set_task(tasks, run.task_id, active_run_id=None, status="stale")
        self.store.persist(self._replace_state(state, tasks=tasks, runs=runs), runs=(runs[run.run_id],))
        raise BuildRunConflict(
            "build_run_conflict",
            message,
            details={"run_id": run.run_id, "task_id": run.task_id},
        )

    def _assert_run_current_locked(
        self,
        state: BuildGraphState,
        run: BuildRun,
    ) -> dict[str, int]:
        """Verify that an async run still owns its original input snapshot."""

        task = self._task(run.task_id)
        current = state.tasks[task.task_id]
        if current.active_run_id != run.run_id:
            self._run_conflict_locked(state, run, message="active run ownership no longer matches")
        try:
            dependency_revisions = self._dependency_revisions(state, task)
        except BuildTaskStateError as exc:
            self._run_conflict_locked(state, run, message=str(exc))
            raise AssertionError("unreachable")
        if current.current_artifact_revision != run.base_artifact_revision:
            self._run_conflict_locked(state, run, message="task artifact revision changed during the run")
        if dependency_revisions != dict(run.dependency_revisions):
            self._run_conflict_locked(state, run, message="dependency revision changed during the run")
        return dependency_revisions

    def _commit_candidate_locked(
        self,
        state: BuildGraphState,
        task: BuildTaskDefinition,
        payload: Any,
        *,
        expected_revision: int | None | object,
        source: str,
        requested_writes: Iterable[str] | None,
        provider: str | None,
        model: str | None,
        prompt_call_id: str | None,
        parent_revision: int | None,
        run_id: str | None = None,
        additional_runs: Iterable[BuildRun] = (),
    ) -> BuildCommitResult:
        if source not in ARTIFACT_SOURCES:
            raise BuildTaskStateError("build_artifact_source_invalid", "unsupported artifact source")
        current = state.tasks[task.task_id]
        self._assert_expected_revision(task.task_id, current.current_artifact_revision, expected_revision)
        if current.active_run_id and current.active_run_id != run_id:
            raise BuildRunConflict(
                "build_run_conflict",
                "another run is active for this task",
                details={"task_id": task.task_id, "run_id": current.active_run_id},
            )
        dependency_revisions = self._dependency_revisions(state, task)
        validation, written_paths = self._validate(task, payload, requested_writes)
        disposition = disposition_for(validation, task.review_policy)
        tasks = dict(state.tasks)
        runs = dict(state.runs)
        additional_run_records = tuple(additional_runs)
        if disposition == "FAIL":
            self._set_task(
                tasks,
                task.task_id,
                status="validation_failed",
                validation_status="failed",
                diagnostics=validation.diagnostics,
                active_run_id=None,
            )
            committed_validation = validation.with_disposition("FAIL")
            finished_run: BuildRun | None = None
            if run_id and run_id in runs:
                finished_run = replace(
                    runs[run_id],
                    status="failed",
                    finished_at=self.clock(),
                    diagnostics=validation.diagnostics,
                )
                runs[run_id] = finished_run
            next_state = self._replace_state(state, tasks=tasks, runs=runs)
            run_records = {
                item.run_id: item
                for item in additional_run_records
            }
            if finished_run is not None:
                run_records[finished_run.run_id] = finished_run
            self.store.persist(next_state, runs=tuple(run_records.values()))
            return BuildCommitResult(
                artifact=None,
                validation=committed_validation,
                disposition="FAIL",
                task_state=tasks[task.task_id],
            )
        revision = (current.current_artifact_revision or 0) + 1
        artifact = BuildArtifact(
            artifact_id=f"{task.task_id}:{revision}",
            task_id=task.task_id,
            schema_version="build-artifact/v1",
            revision=revision,
            payload=payload,
            source=source,  # type: ignore[arg-type]
            dependency_revisions=dependency_revisions,
            validation=validation.with_disposition(disposition),
            created_at=self.clock(),
            provider=provider,
            model=model,
            prompt_call_id=prompt_call_id,
            parent_revision=parent_revision if parent_revision is not None else current.current_artifact_revision,
            written_paths=written_paths,
        )
        status = "review_required" if disposition == "PASS_REVIEW" else "completed"
        validation_status = "review_required" if disposition == "PASS_REVIEW" else "passed"
        self._set_task(
            tasks,
            task.task_id,
            status=status,
            current_artifact_revision=revision,
            active_run_id=None,
            dependency_revisions=dependency_revisions,
            validation_status=validation_status,
            diagnostics=validation.diagnostics,
        )
        if run_id and run_id in runs:
            committed_run = replace(runs[run_id], status="committed", finished_at=self.clock())
            runs[run_id] = committed_run
        self._mark_descendants_stale(tasks, task.task_id)
        self._refresh_unmaterialized_tasks(tasks)
        next_state = self._replace_state(state, tasks=tasks, runs=runs)
        run_records = {
            item.run_id: item
            for item in additional_run_records
        }
        if run_id and run_id in runs:
            run_records[run_id] = runs[run_id]
        self.store.persist(next_state, artifacts=(artifact,), runs=tuple(run_records.values()))
        return BuildCommitResult(
            artifact=artifact,
            validation=artifact.validation,
            disposition=disposition,
            task_state=tasks[task.task_id],
        )

    # ------------------------------------------------------------------
    # Commit, edit, failure, review, and revalidation
    # ------------------------------------------------------------------
    def commit_candidate(
        self,
        task_id: str,
        payload: Any,
        *,
        expected_revision: int | None | object = _UNSET,
        source: str = "llm",
        requested_writes: Iterable[str] | None = None,
        provider: str | None = None,
        model: str | None = None,
        prompt_call_id: str | None = None,
    ) -> BuildCommitResult:
        task = self._task(task_id)
        with project_update_lock(self.store.root):
            state = self._read_state()
            return self._commit_candidate_locked(
                state,
                task,
                payload,
                expected_revision=expected_revision,
                source=source,
                requested_writes=requested_writes,
                provider=provider,
                model=model,
                prompt_call_id=prompt_call_id,
                parent_revision=None,
            )

    def commit_run(
        self,
        run_id: str,
        payload: Any,
        *,
        requested_writes: Iterable[str] | None = None,
        source: str = "llm",
        provider: str | None = None,
        model: str | None = None,
        prompt_call_id: str | None = None,
    ) -> BuildCommitResult:
        with project_update_lock(self.store.root):
            state = self._read_state()
            run = state.runs.get(str(run_id))
            if run is None or run.status != "running":
                raise BuildRunConflict("build_run_conflict", "run is not active", details={"run_id": str(run_id)})
            task = self._task(run.task_id)
            self._assert_run_current_locked(state, run)
            return self._commit_candidate_locked(
                state,
                task,
                payload,
                expected_revision=run.base_artifact_revision,
                source=source,
                requested_writes=requested_writes,
                provider=provider,
                model=model,
                prompt_call_id=prompt_call_id,
                parent_revision=run.base_artifact_revision,
                run_id=run.run_id,
            )

    def fail_run(
        self,
        run_id: str,
        diagnostics: Iterable[BuildDiagnostic | Mapping[str, Any]],
    ) -> BuildRun:
        with project_update_lock(self.store.root):
            state = self._read_state()
            run = state.runs.get(str(run_id))
            if run is None or run.status != "running":
                raise BuildRunConflict("build_run_conflict", "run is not active", details={"run_id": str(run_id)})
            self._assert_run_current_locked(state, run)
            parsed = tuple(
                item if isinstance(item, BuildDiagnostic) else BuildDiagnostic.from_dict(item)
                for item in diagnostics
            )
            tasks = dict(state.tasks)
            runs = dict(state.runs)
            runs[run.run_id] = replace(run, status="failed", finished_at=self.clock(), diagnostics=parsed)
            self._set_task(
                tasks,
                run.task_id,
                status="validation_failed",
                validation_status="failed",
                diagnostics=parsed,
                active_run_id=None,
            )
            next_state = self._replace_state(state, tasks=tasks, runs=runs)
            self.store.persist(next_state, runs=(runs[run.run_id],))
            return runs[run.run_id]

    def conflict_run(
        self,
        run_id: str,
        *,
        message: str = "run was superseded by a newer project revision",
    ) -> BuildRun:
        """Mark an active run as conflicted without committing its payload.

        Background domain runners use this narrow primitive when their
        surrounding job detects cancellation or an author edit between the
        model call and the Build Graph commit.  It deliberately delegates to
        the same private transition used by ``commit_run``/``fail_run`` so a
        stale run cannot remain ``running`` in the manifest or its run file.
        """

        with project_update_lock(self.store.root):
            state = self._read_state()
            run = state.runs.get(str(run_id))
            if run is None or run.status != "running":
                raise BuildRunConflict(
                    "build_run_conflict",
                    "run is not active",
                    details={"run_id": str(run_id)},
                )
            self._run_conflict_locked(state, run, message=message)
            raise AssertionError("_run_conflict_locked must raise")

    def edit_artifact(
        self,
        task_id: str,
        payload: Any,
        *,
        expected_revision: int | None | object = _UNSET,
        requested_writes: Iterable[str] | None = None,
    ) -> BuildCommitResult:
        task = self._task(task_id)
        with project_update_lock(self.store.root):
            state = self._read_state()
            current = state.tasks[task.task_id]
            self._assert_expected_revision(task.task_id, current.current_artifact_revision, expected_revision)
            tasks = dict(state.tasks)
            runs = dict(state.runs)
            conflicted_run = self._mark_active_run_conflict(tasks, runs, task.task_id)
            superseded_state = BuildGraphState(
                schema_version=state.schema_version,
                graph_id=state.graph_id,
                graph_revision=state.graph_revision,
                tasks=tasks,
                runs=runs,
                definition_fingerprint=state.definition_fingerprint,
            )
            return self._commit_candidate_locked(
                superseded_state,
                task,
                payload,
                expected_revision=expected_revision,
                source="human",
                requested_writes=requested_writes,
                provider=None,
                model=None,
                prompt_call_id=None,
                parent_revision=current.current_artifact_revision,
                additional_runs=(conflicted_run,) if conflicted_run else (),
            )

    def revalidate_current(self, task_id: str) -> BuildCommitResult:
        task = self._task(task_id)
        with project_update_lock(self.store.root):
            state = self._read_state()
            current = state.tasks[task.task_id]
            if current.current_artifact_revision is None:
                raise BuildTaskStateError("build_artifact_missing", "cannot revalidate a task without an artifact")
            artifact = self.store.read_artifact(task.task_id, current.current_artifact_revision)
            if artifact is None:
                raise BuildTaskStateError("build_artifact_missing", "current artifact file is missing")
            if current.active_run_id:
                raise BuildRunConflict("build_run_conflict", "cannot revalidate while a run is active")
            return self._commit_candidate_locked(
                state,
                task,
                artifact.payload,
                expected_revision=current.current_artifact_revision,
                source="deterministic",
                requested_writes=artifact.written_paths,
                provider=None,
                model=None,
                prompt_call_id=None,
                parent_revision=current.current_artifact_revision,
            )

    def accept_review(
        self,
        task_id: str,
        *,
        expected_revision: int | None | object = _UNSET,
    ) -> BuildTaskState:
        task = self._task(task_id)
        with project_update_lock(self.store.root):
            state = self._read_state()
            current = state.tasks[task.task_id]
            self._assert_expected_revision(task.task_id, current.current_artifact_revision, expected_revision)
            if current.status != "review_required":
                raise BuildTaskStateError(
                    "build_review_not_required",
                    "task is not waiting for review",
                    details={"task_id": task.task_id, "status": current.status},
                )
            tasks = dict(state.tasks)
            self._set_task(tasks, task.task_id, status="completed", validation_status="passed")
            self._refresh_unmaterialized_tasks(tasks)
            next_state = self._replace_state(state, tasks=tasks)
            self.store.persist(next_state)
            return tasks[task.task_id]

    # ------------------------------------------------------------------
    # Readiness
    # ------------------------------------------------------------------
    def build_readiness(self) -> BuildReadiness:
        with project_update_lock(self.store.root):
            state = self._read_state()
            required = [
                task for task in self.definition.tasks if task.required_for_readiness
            ]
            blocked_by: list[str] = []
            stale_tasks: list[str] = []
            failed_tasks: list[str] = []
            review_required_tasks: list[str] = []
            for task in required:
                task_state = state.tasks[task.task_id]
                if task_state.status in {"pending", "blocked", "running"}:
                    blocked_by.append(task.task_id)
                elif task_state.status == "stale":
                    stale_tasks.append(task.task_id)
                elif task_state.status == "validation_failed":
                    failed_tasks.append(task.task_id)
                elif task_state.status == "review_required":
                    review_required_tasks.append(task.task_id)
                elif task_state.status != "completed":
                    blocked_by.append(task.task_id)
            return BuildReadiness(
                ready=not any((blocked_by, stale_tasks, failed_tasks, review_required_tasks)),
                blocked_by=tuple(sorted(blocked_by)),
                stale_tasks=tuple(sorted(stale_tasks)),
                failed_tasks=tuple(sorted(failed_tasks)),
                review_required_tasks=tuple(sorted(review_required_tasks)),
            )


__all__ = ["BuildGraphService"]
