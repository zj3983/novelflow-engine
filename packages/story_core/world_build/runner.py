"""Production runner for the WorldBuild Build Graph slice.

The runner owns orchestration only.  Task state, validation, revision checks,
artifact history, and run races remain the responsibility of
``BuildGraphService``.  A model task gets one first pass and at most one
focused repair pass.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from packages.story_core.build_graph.contracts import (
    BuildDiagnostic,
    BuildRunConflict,
    BuildTaskStateError,
)
from packages.story_core.model_gateway import ModelRequest, RuntimeModelGateway
from packages.story_core.models import NovelProject
from packages.story_core.power_system_spec import PowerSystemValidationError
from packages.story_core.prompt_call_log import PromptCallLog
from packages.story_core.runtime_config import resolve_stage_runtime

from .definition import WorldBuildGraph, WorldBuildTaskSpec, build_world_build_graph
from .materialize import (
    materialize_project,
    reconcile_project_to_graph,
)
from .migration import POWER_REPAIR_BUDGET_FILENAME, prepare_world_graph_migration
from .tasks import (
    build_input_contract,
    build_power_path_repair_prompt,
    build_task_prompt,
    canonical_world_input,
    input_fingerprint,
    merge_repair_patch,
    parse_power_path_repair_payload,
    parse_task_payload,
    preserve_existing_non_power_values,
    repair_fields_for_diagnostics,
    run_read_projection,
    task_payload_from_project,
)
from .validators import assemble_power_candidate, make_world_validators
from .validators import power_final_owner_task
from .power_repairs import (
    merge_power_path_repair,
    power_path_repair_scope,
    raw_power_spec_from_artifacts,
)
from .power_contract import select_power_progression_mode


class WorldBuildGraphFailure(RuntimeError):
    """A safe, structured production graph failure."""

    code = "world_build_graph_failed"

    def __init__(
        self,
        task_id: str,
        diagnostics: Sequence[BuildDiagnostic] = (),
        *,
        message: str = "world Build Graph task failed",
    ) -> None:
        self.task_id = str(task_id)
        self.diagnostics = tuple(diagnostics)
        super().__init__(message)


class WorldBuildGraphCancelled(WorldBuildGraphFailure):
    """The enclosing legacy job was superseded or reached a terminal state."""

    code = "world_build_conflict"


def _unresolved_path_repair_scope() -> tuple[BuildDiagnostic, ...]:
    return (
        BuildDiagnostic(
            "task.repair_scope_unresolved",
            "paths",
            "path validation failed but no safe repair target could be resolved",
        ),
    )


def power_candidate_from_dependencies(
    project: NovelProject, service: Any, progression_mode: str,
) -> dict[str, Any]:
    """Assemble the deterministic final task from committed power artifacts."""

    payloads: dict[str, Mapping[str, Any]] = {}
    for task_id in (
        "power_system_foundation", "power_system_attributes", "power_system_paths",
        "power_system_stages", "power_system_resources", "power_system_constraints",
    ):
        artifact = service.inspect_artifact(task_id)
        if artifact is None or not isinstance(artifact.payload, Mapping):
            raise BuildTaskStateError(
                "build_dependencies_incomplete",
                "power final task requires all committed power sections",
                details={"task_id": "power_system_final", "dependency": task_id},
            )
        payloads[task_id] = artifact.payload
    existing = project.world_blueprint.get("power_system") if isinstance(project.world_blueprint, Mapping) else None
    return assemble_power_candidate(
        foundation=payloads["power_system_foundation"],
        attributes=payloads["power_system_attributes"],
        paths=payloads["power_system_paths"],
        stages=payloads["power_system_stages"],
        resources=payloads["power_system_resources"],
        constraints=payloads["power_system_constraints"],
        project=project,
        progression_mode=progression_mode,
        existing_summary=existing if isinstance(existing, list) else None,
    )


class WorldBuildGraphRunner:
    """Execute the genre-scoped production graph for one file project."""

    def __init__(
        self,
        project: NovelProject,
        *,
        store: Any,
        model_gateway: Any | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.project = project.model_copy(deep=True)
        self.store = store
        from packages.story_core.opening_build.runtime import enabled
        if enabled(store):
            raise ValueError("opening_build_use_workbench")
        previous_input: Mapping[str, Any] | None = None
        try:
            prior = self.store.build_artifact("world_input")
            candidate = prior.get("payload") if isinstance(prior, Mapping) else None
            if isinstance(candidate, Mapping):
                previous_input = candidate
        except Exception:
            previous_input = None
        self.power_progression_mode = select_power_progression_mode(
            self.project,
            locked_mode=(previous_input or {}).get("power_progression_mode"),
            locked_novel_type_id=(previous_input or {}).get("novel_type_id"),
        )
        self.graph: WorldBuildGraph = build_world_build_graph(
            self.project,
            progression_mode=self.power_progression_mode,
        )
        # WorldBuild is the one sanctioned dynamic graph: its task shape is
        # selected by genre.  Perform an explicit archive/reset migration
        # before the generic BuildGraphService applies its hard definition
        # compatibility check.
        prepare_world_graph_migration(self.store, self.graph)
        self.validators = make_world_validators(self.project, self.power_progression_mode)
        self.service = store.build_graph_service(
            self.graph.definition,
            validators=self.validators,
        )
        self.gateway = model_gateway or RuntimeModelGateway(
            runtime_resolver=resolve_stage_runtime,
        )
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check
        self._active_run_id: str | None = None

    # ------------------------------------------------------------------
    # Safe progress/cancellation helpers
    # ------------------------------------------------------------------
    def _progress(self, task_id: str, status: str, message: str) -> None:
        if self.progress_callback is None:
            return
        spec = self.graph.spec(task_id)
        # Deliberately no ``artifact`` field: the old job's partial projection
        # must not become a second source of truth while graph artifacts are
        # being committed.
        self.progress_callback(
            {
                "module_id": task_id,
                "title": spec.task.title,
                "status": status,
                "message": message,
            }
        )

    def _cancelled(self) -> bool:
        try:
            return bool(self.cancel_check and self.cancel_check())
        except Exception:
            # A cancellation observer must never make a successful model
            # result look like a provider failure.  The enclosing job still
            # performs its terminal guard before materialization.
            return False

    def _ensure_active(self, task_id: str, *, run_id: str | None = None) -> None:
        if not self._cancelled():
            return
        candidate_run_id = run_id or self._active_run_id
        if candidate_run_id:
            try:
                self.service.conflict_run(
                    candidate_run_id,
                    message="world-build job was superseded before commit",
                )
            except BuildRunConflict:
                pass
        raise WorldBuildGraphCancelled(
            task_id,
            (
                BuildDiagnostic(
                    "build_run_conflict",
                    f"tasks.{task_id}",
                    "world-build job was superseded before this task could commit",
                ),
            ),
            message="world-build job was superseded",
        )

    # ------------------------------------------------------------------
    # Root import and existing-project bootstrap
    # ------------------------------------------------------------------
    def _materialized_mode_matches_current_graph(self) -> bool:
        marker = self.store.build_graph_materialization()
        if not isinstance(marker, Mapping):
            return False
        if (
            marker.get("graph_id") != self.graph.definition.graph_id
            or marker.get("power_progression_mode") != self.power_progression_mode
        ):
            return False
        state = self.service.inspect_graph()
        revisions = {
            task_id: int(task_state.current_artifact_revision)
            for task_id, task_state in state.tasks.items()
            if task_state.status == "completed" and task_state.current_artifact_revision is not None
        }
        return dict(marker.get("artifact_revisions") or {}) == revisions

    def _ensure_world_input(self) -> None:
        task_id = "world_input"
        self._ensure_active(task_id)
        current = self.service.inspect_artifact(task_id)
        previous = current.payload if current is not None and isinstance(current.payload, Mapping) else None
        payload = canonical_world_input(self.project, store=self.store, previous=previous)
        if current is not None and current.payload == payload:
            return
        explicit_mode = self.project.world_blueprint.get("power_progression_mode")
        already_materialized_mode = (
            explicit_mode == self.power_progression_mode
            and self._materialized_mode_matches_current_graph()
        )
        if (
            current is not None
            and "power_progression_mode" not in current.payload
            and (explicit_mode not in {"custom", "traditional_class"} or already_materialized_mode)
            and {
                key: value
                for key, value in current.payload.items()
                if key != "power_progression_mode"
            }
            == {
                key: value
                for key, value in payload.items()
                if key != "power_progression_mode"
            }
        ):
            # Older completed graphs predate the locked mode metadata.  The
            # mode has already been selected deterministically for this runner
            # from the project and prior artifacts; backfilling the root
            # artifact as a new revision would stale every downstream task.
            return
        expected = current.revision if current is not None else None
        result = self.service.commit_candidate(
            task_id,
            payload,
            expected_revision=expected,
            source="imported",
            requested_writes=self.graph.spec(task_id).task.owns,
        )
        if result.artifact is None:
            raise WorldBuildGraphFailure(task_id, result.validation.diagnostics)
        self._progress(task_id, "done", "已记录世界构建输入")

    def _bootstrap_existing_values(self) -> None:
        """Import valid existing domain values without calling a model."""

        for task_id in self.graph.definition.ordered_task_ids:
            if task_id in {"world_input", "power_system_final"}:
                continue
            state = self.service.inspect_task(task_id)
            if state.current_artifact_revision is not None:
                continue
            if state.status != "ready":
                continue
            payload = task_payload_from_project(self.project, task_id)
            if not payload:
                continue
            spec = self.graph.spec(task_id)
            # A partial/invalid author value is intentionally not deleted.  A
            # failed import leaves the task runnable so the model can produce
            # exactly this section; the invalid value never becomes an
            # official artifact.
            result = self.service.commit_candidate(
                task_id,
                payload,
                expected_revision=None,
                source="imported",
                requested_writes=spec.task.owns,
            )
            if result.artifact is not None:
                self._progress(task_id, "done", f"已复用现有设定：{spec.task.title}")

    def _preserve_existing_non_power_values(
        self,
        task_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Keep existing non-power fields authoritative during completion."""

        return preserve_existing_non_power_values(self.project, task_id, payload)

    # ------------------------------------------------------------------
    # Model and deterministic tasks
    # ------------------------------------------------------------------
    def _prompt_log_start(self, request: ModelRequest) -> tuple[PromptCallLog | None, str | None]:
        recorder: PromptCallLog | None = None
        try:
            candidate = self.store.prompt_call_log()
            if isinstance(candidate, PromptCallLog):
                recorder = candidate
        except Exception:
            recorder = None
        if recorder is None:
            return None, None
        try:
            settings = resolve_stage_runtime("planner")
            provider = str(getattr(settings, "provider_id", "") or "")
            protocol = str(getattr(settings, "protocol", "") or "")
            model = str(getattr(settings, "model", "") or "")
            temperature = getattr(settings, "temperature", None)
        except Exception:
            provider = protocol = model = ""
            temperature = None
        try:
            call_id = recorder.start(
                chapter_number=0,
                stage="planner",
                agent=request.operation,
                user_prompt=request.prompt,
                system_prompt=request.system_prompt,
                provider=provider,
                protocol=protocol,
                model=model,
                temperature=temperature,
                requested_max_tokens=request.max_tokens,
                json_mode=request.json_mode,
            )
        except Exception:
            return recorder, None
        return recorder, call_id

    @staticmethod
    def _prompt_log_finish(
        recorder: PromptCallLog | None,
        call_id: str | None,
        response: Any,
    ) -> None:
        if recorder is None or not call_id:
            return
        try:
            recorder.finish(
                call_id,
                status="success" if getattr(response, "ok", False) else "error",
                provider=str(getattr(response, "provider", "") or ""),
                model=str(getattr(response, "resolved_model", "") or getattr(response, "model", "") or ""),
                resolved_model=str(getattr(response, "resolved_model", "") or ""),
                output=str(getattr(response, "text", "") or "") if getattr(response, "ok", False) else "",
                error="model_call_failed" if not getattr(response, "ok", False) else "",
                temperature_omitted=bool(getattr(response, "temperature_omitted", False)),
                raw=getattr(response, "raw", None),
                usage=getattr(response, "usage", None),
            )
        except Exception:
            pass

    def _call_model(self, task_id: str, prompt: str) -> tuple[Any, str | None]:
        spec = self.graph.spec(task_id)
        request = ModelRequest(
            prompt=prompt,
            system_prompt="You are a senior Chinese webnovel worldbuilding editor. Return JSON only.",
            provider="",
            model="",
            operation=f"world_build_{task_id}",
            max_tokens=spec.max_tokens,
            json_mode=True,
            metadata={
                "reasoning_effort": "low",
                "enable_thinking": False,
                "world_build_task": task_id,
                "stream": False,
            },
        )
        recorder, call_id = self._prompt_log_start(request)
        try:
            response = self.gateway.complete_stage("planner", request)
        except Exception:
            class FailedResponse:
                ok = False
                error = "model_call_failed"
                text = ""
                provider = ""
                model = ""
                resolved_model = ""
                temperature_omitted = False

            response = FailedResponse()
        self._prompt_log_finish(recorder, call_id, response)
        return response, call_id

    @staticmethod
    def _power_error_diagnostics(error: PowerSystemValidationError) -> tuple[BuildDiagnostic, ...]:
        diagnostics: list[BuildDiagnostic] = []
        for section in error.missing_sections:
            diagnostics.append(
                BuildDiagnostic(
                    f"power.final.missing_{section}",
                    section,
                    f"final power spec is missing {section}",
                )
            )
        for violation in error.violations:
            diagnostics.append(
                BuildDiagnostic(
                    f"power.final.{violation}",
                    violation,
                    f"final power spec violates {violation}",
                )
            )
        return tuple(diagnostics) or (
            BuildDiagnostic(
                "power.final.invalid",
                "power_system_spec",
                "final power spec failed deterministic validation",
            ),
        )

    def _power_repair_budget_path(self):
        return self.store.webnovel_dir / POWER_REPAIR_BUDGET_FILENAME

    def _power_input_revision(self) -> int | None:
        return self.service.inspect_task("world_input").current_artifact_revision

    def _read_power_repair_budget(self) -> dict[str, Any]:
        raw = self.store.snapshot_store.read_json(self._power_repair_budget_path(), {})
        return dict(raw) if isinstance(raw, Mapping) else {}

    def _reset_power_repair_budget(self) -> None:
        payload = {
            "schema_version": "world-build-power-repair/v1",
            "definition_fingerprint": self.graph.definition.definition_fingerprint,
            "world_input_revision": self._power_input_revision(),
            "attempted_owners": [],
            "failed_owners": [],
        }
        self.store.snapshot_store.replace_json_transaction({self._power_repair_budget_path(): payload})

    def _power_repair_budget_matches(self, budget: Mapping[str, Any]) -> bool:
        return (
            budget.get("definition_fingerprint")
            == self.graph.definition.definition_fingerprint
            and budget.get("world_input_revision") == self._power_input_revision()
        )

    def _power_repair_budget_exhausted(self, task_id: str) -> bool:
        budget = self._read_power_repair_budget()
        return self._power_repair_budget_matches(budget) and task_id in set(budget.get("failed_owners") or [])

    def _mark_power_repair_failed(self, task_id: str) -> None:
        budget = self._read_power_repair_budget()
        if not self._power_repair_budget_matches(budget):
            return
        failed = set(budget.get("failed_owners") or [])
        failed.add(task_id)
        payload = {
            "schema_version": "world-build-power-repair/v1",
            "definition_fingerprint": self.graph.definition.definition_fingerprint,
            "world_input_revision": self._power_input_revision(),
            "attempted_owners": sorted(set(budget.get("attempted_owners") or [])),
            "failed_owners": sorted(failed),
        }
        self.store.snapshot_store.replace_json_transaction({self._power_repair_budget_path(): payload})

    def _route_power_final_diagnostics(
        self,
        diagnostics: Sequence[BuildDiagnostic],
    ) -> bool:
        owners: dict[str, list[BuildDiagnostic]] = {}
        for diagnostic in diagnostics:
            owner = power_final_owner_task(diagnostic)
            if owner is not None:
                owners.setdefault(owner, []).append(diagnostic)
        if not owners:
            return False

        input_revision = self._power_input_revision()
        budget = self._read_power_repair_budget()
        same_generation = self._power_repair_budget_matches(budget)
        attempted = set(budget.get("attempted_owners") or []) if same_generation else set()
        pending = sorted(owner for owner in owners if owner not in attempted)
        if not pending:
            # A residual failure after the owner has already had its one
            # focused repair is a clean, persistent failure, not a hidden
            # deterministic retry loop.
            return False

        updated_attempted = sorted(attempted.union(pending))
        self.store.snapshot_store.replace_json_transaction(
            {
                self._power_repair_budget_path(): {
                    "schema_version": "world-build-power-repair/v1",
                    "definition_fingerprint": self.graph.definition.definition_fingerprint,
                    "world_input_revision": input_revision,
                    "attempted_owners": updated_attempted,
                    "failed_owners": sorted(set(budget.get("failed_owners") or [])) if same_generation else [],
                }
            }
        )
        for owner in pending:
            self.service.invalidate_task(owner, owners[owner])
        return True

    def _power_candidate_from_dependencies(self) -> dict[str, Any]:
        return power_candidate_from_dependencies(self.project, self.service, self.power_progression_mode)

    @staticmethod
    def _merge_repair_patch(
        base_candidate: Mapping[str, Any] | None,
        repair_patch: Mapping[str, Any],
        repair_fields: Sequence[str] | None,
    ) -> tuple[dict[str, Any] | None, tuple[BuildDiagnostic, ...]]:
        """Shared pure merge contract also used by Workbench repair."""

        return merge_repair_patch(base_candidate, repair_patch, repair_fields)

    def _run_deterministic(self, task_id: str) -> None:
        self._ensure_active(task_id)
        run = self.service.start_run(task_id)
        self._active_run_id = run.run_id
        self._progress(task_id, "running", f"正在组装：{self.graph.spec(task_id).task.title}")
        try:
            if task_id != "power_system_final":
                raise WorldBuildGraphFailure(
                    task_id,
                    (BuildDiagnostic("world.deterministic_task_unknown", task_id, "unknown deterministic task"),),
                )
            try:
                candidate = self._power_candidate_from_dependencies()
            except PowerSystemValidationError as exc:
                diagnostics = self._power_error_diagnostics(exc)
                self.service.fail_run(run.run_id, diagnostics)
                if self._route_power_final_diagnostics(diagnostics):
                    return
                raise WorldBuildGraphFailure(task_id, diagnostics) from exc
            self._ensure_active(task_id, run_id=run.run_id)
            result = self.service.commit_run(
                run.run_id,
                candidate,
                requested_writes=self.graph.spec(task_id).task.owns,
                source="deterministic",
            )
            if result.artifact is None:
                raise WorldBuildGraphFailure(task_id, result.validation.diagnostics)
            self._progress(task_id, "done", f"已完成：{self.graph.spec(task_id).task.title}")
        except BuildRunConflict as exc:
            raise WorldBuildGraphCancelled(
                task_id,
                (BuildDiagnostic("build_run_conflict", f"tasks.{task_id}", "deterministic run was superseded"),),
            ) from exc
        finally:
            self._active_run_id = None

    def _run_model(self, task_id: str) -> None:
        spec = self.graph.spec(task_id)
        contract = build_input_contract(self.project, self.graph, self.service, task_id)
        task_state = self.service.inspect_task(task_id)
        current_artifact = self.service.inspect_artifact(task_id)
        final_diagnostics = tuple(
            diagnostic
            for diagnostic in task_state.diagnostics
            if diagnostic.code.startswith("power.final.")
        )
        final_repair_candidate = (
            current_artifact.payload
            if final_diagnostics
            and current_artifact is not None
            and isinstance(current_artifact.payload, Mapping)
            else None
        )
        run = self.service.start_run(
            task_id,
            input_fingerprint=input_fingerprint(contract),
            read_projection=run_read_projection(self.graph, task_id, contract),
        )
        self._active_run_id = run.run_id
        self._progress(task_id, "running", f"正在构建：{spec.task.title}")
        try:
            # A residual full-validator diagnostic is already the one focused
            # repair allowance for this owner.  Do not spend a normal
            # regeneration call before showing the model the exact final
            # diagnostic and the current committed section.
            final_repair = final_repair_candidate is not None
            final_repair_fields = (
                repair_fields_for_diagnostics(spec, final_diagnostics)
                if final_repair and task_id != "power_system_paths"
                else None
            )
            final_path_scope = (
                power_path_repair_scope(
                    final_repair_candidate,
                    final_diagnostics,
                    self.project,
                    raw_spec=raw_power_spec_from_artifacts(self.service),
                    progression_mode=self.power_progression_mode,
                )
                if final_repair and task_id == "power_system_paths" and isinstance(final_repair_candidate, Mapping)
                else None
            )
            if (
                final_repair
                and task_id == "power_system_paths"
                and final_path_scope is not None
                and not final_path_scope.has_mutations
            ):
                unresolved = _unresolved_path_repair_scope()
                self.service.fail_run(run.run_id, unresolved)
                self._mark_power_repair_failed(task_id)
                raise WorldBuildGraphFailure(
                    task_id,
                    unresolved,
                    message="power path repair scope could not be resolved",
                )
            if final_repair and task_id == "power_system_paths" and final_path_scope is not None:
                prompt = build_power_path_repair_prompt(
                    self.graph,
                    task_id,
                    contract,
                    repair_candidate=final_repair_candidate,
                    diagnostics=final_diagnostics,
                    scope=final_path_scope,
                )
            else:
                prompt = build_task_prompt(
                    self.graph,
                    task_id,
                    contract,
                    repair_candidate=final_repair_candidate if final_repair else None,
                    diagnostics=final_diagnostics if final_repair else (),
                    repair_fields=final_repair_fields,
                )
            self._ensure_active(task_id, run_id=run.run_id)
            response, call_id = self._call_model(task_id, prompt)
            self._ensure_active(task_id, run_id=run.run_id)
            if not getattr(response, "ok", False):
                diagnostics = (
                    BuildDiagnostic(
                        "model.repair_request_failed" if final_repair else "model.request_failed",
                        f"tasks.{task_id}",
                        "focused repair request failed" if final_repair else "model request failed",
                    ),
                )
                self.service.fail_run(run.run_id, diagnostics)
                if final_repair:
                    self._mark_power_repair_failed(task_id)
                raise WorldBuildGraphFailure(task_id, diagnostics, message="world model request failed")
            if final_repair:
                repaired: dict[str, Any] | None = None
                repair_diagnostics: tuple[BuildDiagnostic, ...] = ()
                if task_id == "power_system_paths" and final_path_scope is not None:
                    patch, repair_parse_diagnostics = parse_power_path_repair_payload(
                        getattr(response, "text", "")
                    )
                    if patch is None:
                        repair_diagnostics = repair_parse_diagnostics
                    else:
                        repaired, repair_diagnostics = merge_power_path_repair(
                            final_repair_candidate,
                            patch,
                            final_path_scope,
                        )
                else:
                    candidate, parse_diagnostics = parse_task_payload(
                        getattr(response, "text", ""),
                        spec.output_fields,
                    )
                    if candidate is None:
                        repair_diagnostics = parse_diagnostics
                    else:
                        repaired, merge_diagnostics = self._merge_repair_patch(
                            final_repair_candidate,
                            candidate,
                            final_repair_fields,
                        )
                        if merge_diagnostics:
                            repair_diagnostics = merge_diagnostics
                if repaired is not None and not repair_diagnostics:
                    repaired = self._preserve_existing_non_power_values(task_id, repaired)
                    repair_diagnostics = self.service.validate(
                        task_id,
                        repaired,
                        requested_writes=spec.task.owns,
                    ).diagnostics
                if repaired is not None and not repair_diagnostics:
                    self._ensure_active(task_id, run_id=run.run_id)
                    result = self.service.commit_run(
                        run.run_id,
                        repaired,
                        requested_writes=spec.task.owns,
                        source="ai_repair",
                        provider=str(getattr(response, "provider", "") or "") or None,
                        model=str(getattr(response, "resolved_model", "") or getattr(response, "model", "") or "") or None,
                        prompt_call_id=call_id,
                    )
                    if result.artifact is None:
                        raise WorldBuildGraphFailure(task_id, result.validation.diagnostics)
                    self._progress(task_id, "done", f"已修复并完成：{spec.task.title}")
                    return
                self.service.fail_run(run.run_id, repair_diagnostics)
                if final_repair:
                    self._mark_power_repair_failed(task_id)
                raise WorldBuildGraphFailure(task_id, repair_diagnostics)

            candidate, parse_diagnostics = parse_task_payload(
                getattr(response, "text", ""),
                spec.output_fields,
            )
            if candidate is None:
                diagnostics = parse_diagnostics
            else:
                diagnostics = self.service.validate(
                    task_id,
                    self._preserve_existing_non_power_values(task_id, candidate),
                    requested_writes=spec.task.owns,
                ).diagnostics
            if candidate is not None and not diagnostics:
                self._ensure_active(task_id, run_id=run.run_id)
                result = self.service.commit_run(
                    run.run_id,
                    self._preserve_existing_non_power_values(task_id, candidate),
                    requested_writes=spec.task.owns,
                    source="llm",
                    provider=str(getattr(response, "provider", "") or "") or None,
                    model=str(getattr(response, "resolved_model", "") or getattr(response, "model", "") or "") or None,
                    prompt_call_id=call_id,
                )
                if result.artifact is None:
                    raise WorldBuildGraphFailure(task_id, result.validation.diagnostics)
                self._progress(task_id, "done", f"已完成：{spec.task.title}")
                return

            # End the first run with structured validation diagnostics before
            # beginning the one and only focused repair run.
            self.service.fail_run(run.run_id, diagnostics)
            path_repair_scope = (
                power_path_repair_scope(
                    candidate,
                    diagnostics,
                    self.project,
                    raw_spec=raw_power_spec_from_artifacts(self.service),
                    progression_mode=self.power_progression_mode,
                )
                if task_id == "power_system_paths" and isinstance(candidate, Mapping)
                else None
            )
            repair_run = self.service.start_run(
                task_id,
                input_fingerprint=input_fingerprint(contract),
                read_projection=run_read_projection(self.graph, task_id, contract),
            )
            self._active_run_id = repair_run.run_id
            if path_repair_scope is not None and not path_repair_scope.has_mutations:
                unresolved = _unresolved_path_repair_scope()
                self.service.fail_run(repair_run.run_id, unresolved)
                raise WorldBuildGraphFailure(
                    task_id,
                    unresolved,
                    message="power path repair scope could not be resolved",
                )
            if path_repair_scope is not None:
                repair_prompt = build_power_path_repair_prompt(
                    self.graph,
                    task_id,
                    contract,
                    repair_candidate=candidate,
                    diagnostics=diagnostics,
                    scope=path_repair_scope,
                )
            else:
                repair_prompt = build_task_prompt(
                    self.graph,
                    task_id,
                    contract,
                    repair_candidate=candidate,
                    diagnostics=diagnostics,
                    repair_fields=repair_fields_for_diagnostics(spec, diagnostics),
                )
            self._ensure_active(task_id, run_id=repair_run.run_id)
            repair_response, repair_call_id = self._call_model(task_id, repair_prompt)
            self._ensure_active(task_id, run_id=repair_run.run_id)
            repaired: dict[str, Any] | None = None
            repair_diagnostics: tuple[BuildDiagnostic, ...] = ()
            if not getattr(repair_response, "ok", False):
                repair_diagnostics = (
                    BuildDiagnostic(
                        "model.repair_request_failed",
                        f"tasks.{task_id}",
                        "focused repair request failed",
                    ),
                )
            else:
                if path_repair_scope is not None:
                    patch, repair_parse_diagnostics = parse_power_path_repair_payload(
                        getattr(repair_response, "text", "")
                    )
                    if patch is None:
                        repair_diagnostics = repair_parse_diagnostics
                    else:
                        repaired, repair_diagnostics = merge_power_path_repair(
                            candidate,
                            patch,
                            path_repair_scope,
                        )
                else:
                    repaired, repair_parse_diagnostics = parse_task_payload(
                        getattr(repair_response, "text", ""),
                        spec.output_fields,
                    )
                    if repaired is None:
                        repair_diagnostics = repair_parse_diagnostics
                    else:
                        repair_fields = repair_fields_for_diagnostics(spec, diagnostics)
                        repaired, merge_diagnostics = self._merge_repair_patch(
                            candidate,
                            repaired,
                            repair_fields,
                        )
                        if merge_diagnostics:
                            repair_diagnostics = merge_diagnostics
            if repaired is not None and not repair_diagnostics:
                repaired = self._preserve_existing_non_power_values(task_id, repaired)
                repair_diagnostics = self.service.validate(
                    task_id,
                    repaired,
                    requested_writes=spec.task.owns,
                ).diagnostics
            if repaired is not None and not repair_diagnostics:
                self._ensure_active(task_id, run_id=repair_run.run_id)
                result = self.service.commit_run(
                    repair_run.run_id,
                    repaired,
                    requested_writes=spec.task.owns,
                    source="ai_repair",
                    provider=str(getattr(repair_response, "provider", "") or "") or None,
                    model=str(getattr(repair_response, "resolved_model", "") or getattr(repair_response, "model", "") or "") or None,
                    prompt_call_id=repair_call_id,
                )
                if result.artifact is None:
                    raise WorldBuildGraphFailure(task_id, result.validation.diagnostics)
                self._progress(task_id, "done", f"已修复并完成：{spec.task.title}")
                return
            self.service.fail_run(repair_run.run_id, repair_diagnostics)
            raise WorldBuildGraphFailure(task_id, repair_diagnostics)
        except BuildRunConflict as exc:
            raise WorldBuildGraphCancelled(
                task_id,
                (BuildDiagnostic("build_run_conflict", f"tasks.{task_id}", "model run was superseded"),),
            ) from exc
        finally:
            self._active_run_id = None

    def run(self) -> NovelProject:
        """Resume the graph until ready, then return an unpersisted project candidate."""

        self._ensure_active("world_input")
        self._ensure_world_input()
        try:
            reconciled = reconcile_project_to_graph(
                self.project,
                self.graph,
                self.service,
                store=self.store,
            )
            if reconciled:
                self._reset_power_repair_budget()
        except ValueError as exc:
            # A project with an invalid author edit must not remain labelled
            # environment_ready.  Revert only the readiness marker; the
            # author's invalid content remains untouched for review/repair.
            try:
                self.store.update_project({"pipeline_stage": "imported"})
            except Exception:
                pass
            raise WorldBuildGraphFailure(
                "project_reconciliation",
                (
                    BuildDiagnostic(
                        "world.external_edit_invalid",
                        "world_blueprint",
                        "an external project edit failed the graph validator",
                    ),
                ),
            ) from exc

        while True:
            self._ensure_active("world_input")
            self._bootstrap_existing_values()
            state = self.service.inspect_graph()
            readiness = self.service.build_readiness()
            if readiness.ready:
                self._ensure_active("materialization")
                return materialize_project(self.project, self.graph, self.service)

            runnable = [
                task_id
                for task_id in self.graph.definition.ordered_task_ids
                if state.tasks[task_id].status in {"ready", "stale", "validation_failed"}
            ]
            if not runnable:
                blocked = tuple(readiness.blocked_by or readiness.failed_tasks or readiness.review_required_tasks)
                raise WorldBuildGraphFailure(
                    "readiness",
                    (
                        BuildDiagnostic(
                            "world.build_not_ready",
                            "build_graph",
                            "world Build Graph is not ready",
                        ),
                    ),
                    message=f"world Build Graph is not ready: {','.join(blocked)}",
                )
            task_id = runnable[0]
            if self._power_repair_budget_exhausted(task_id):
                raise WorldBuildGraphFailure(
                    task_id,
                    (
                        BuildDiagnostic(
                            "power.final_repair_budget_exhausted",
                            f"tasks.{task_id}",
                            "the focused power-final repair allowance is exhausted for this graph generation",
                        ),
                    ),
                )
            spec = self.graph.spec(task_id)
            if spec.kind == "deterministic":
                self._run_deterministic(task_id)
            else:
                self._run_model(task_id)


__all__ = [
    "power_candidate_from_dependencies",
    "WorldBuildGraphCancelled",
    "WorldBuildGraphFailure",
    "WorldBuildGraphRunner",
]
