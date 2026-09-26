"""Automation API. Mutation adapters reuse registered workbench operations."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from apps.api.routes import file_projects as workbench
from apps.api.routes.file_project_candidates import _candidate_project_ids
from packages.story_core import build_public as projection
from packages.story_core.build_graph.contracts import BuildGraphError
from packages.story_core.models import NovelProject
from packages.story_core.opening_build import runtime
from packages.story_core.persistence.project_locking import project_update_lock


class PublicRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def safe(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"detail": {"code": "invalid_request"}})
            except HTTPException as exc:
                detail = exc.detail
                code = detail.get("code") if isinstance(detail, dict) else detail
                if isinstance(detail, dict) and detail.get("passed") is False:
                    code = "validation_failed"
                safe_detail = {"code": projection.safe_code(code)}
                if isinstance(detail, dict):
                    safe_detail["diagnostics"] = [{"code": projection.safe_code(d.get("code")), "severity": "warning" if d.get("severity") == "warning" else "blocking"} for d in detail.get("diagnostics", []) if isinstance(d, dict)]
                    details = detail.get("details", {})
                    safe_detail["revisions"] = {key: details[key] for key in (
                        "expected_revision", "current_revision", "expected_graph_revision", "current_graph_revision"
                    ) if key in details and (details[key] is None or type(details[key]) is int)}
                return JSONResponse(status_code=exc.status_code, content={"detail": safe_detail})
            except BuildGraphError as exc:
                return JSONResponse(status_code=409, content={"detail": {"code": projection.safe_code(exc.code)}})
        return safe


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_graph_revision: int = Field(ge=0)


class NextRequest(RevisionRequest):
    task_id: str = Field(min_length=1, max_length=128)


class ArtifactRequest(RevisionRequest):
    expected_revision: int = Field(ge=1)
    payload: dict[str, Any]


def _context(project_id):
    store = workbench._store_for(project_id)
    graph = runtime.graph_for(store, NovelProject.model_validate(store.project()))
    build_store = store.build_graph_store()
    state = build_store.read_state()
    projection.assert_matching(graph.definition, state)
    return store, graph, build_store, state


def _delegate(http_request, name, **kwargs):
    # Resolve the registered route so this is the very same operation as Web.
    for route in http_request.app.routes:
        if getattr(route, "name", None) == name:
            # Fail closed if a future route adds authorization dependencies.
            if route.dependant.dependencies or http_request.app.router.dependencies:
                raise HTTPException(503, "public_adapter_dependency_update_required")
            return route.endpoint(**kwargs)
    raise HTTPException(503, "public_adapter_unavailable")


def _snapshot(project_id):
    store = workbench._store_for(project_id)
    with workbench._world_build_jobs_lock, project_update_lock(store.root):
        store, graph, build_store, state = _context(project_id)
        result = projection.graph_projection(graph.definition, state, build_store)
        blockers = result["readiness"]["blockers"]
        if state is None:
            blockers.append({"code": "build_graph_not_initialized"})
        busy = workbench._has_active_world_build_job(workbench._strip_file_prefix(project_id)) or workbench._has_active_build_orchestration_job(workbench._strip_file_prefix(project_id))
        busy = busy or bool(state and any(task.active_run_id or task.status == "running" for task in state.tasks.values()))
        if busy:
            blockers.append({"code": "build_job_in_progress"})
        source_blocked = False
        try:
            runtime.assert_planning_sources_current(store)
        except ValueError as exc:
            source_blocked = True
            blockers.append({"code": projection.safe_code(str(exc))})
        config = runtime.settings(store) if runtime.enabled(store) else {}
        from packages.story_core.world_build.materialize import materialized_domain_conflicts
        if not config.get("pending_extension") and materialized_domain_conflicts(NovelProject.model_validate(store.project()), graph, store.build_graph_materialization()):
            source_blocked = True
            blockers.append({"code": "project_source_changed"})
        pending = config.get("pending_extension") or {}
        future = {f"chapter_outline_{number}" for number in range(pending.get("start_chapter", 1), pending.get("end_chapter", 0) + 1)}
        actions = []
        prefix = f"/file-projects/{project_id}/public-build"
        for task in result["tasks"]:
            task_id = task["task_id"]
            writable = not config.get("execution") or task_id in future
            dependencies_ready = state is not None and all(state.tasks[d].status == "completed" for d in task["dependencies"])
            if not busy and not source_blocked and writable and dependencies_ready and task["artifact_revision"] and task["status"] not in {"running", "review_required"} and graph.spec(task_id).kind == "model":
                actions.append({"action": "edit_artifact", "task_id": task_id, "method": "PATCH",
                                "href": f"{prefix}/tasks/{task_id}/artifact",
                                "preconditions": {"expected_graph_revision": state.graph_revision,
                                                  "expected_revision": task["artifact_revision"],
                                                  "dependency_revisions": {d: state.tasks[d].current_artifact_revision for d in task["dependencies"]}},
                                "requires_human_confirmation": False})
        next_task = workbench._next_build_orchestration_task(graph, state, "next") if state else None
        if next_task and not busy and not source_blocked and (not config.get("execution") or graph.spec(next_task).kind != "model" or next_task in future):
            actions.append({"action": "run_next", "task_id": next_task, "method": "POST",
                            "href": f"{prefix}/next", "preconditions": {"expected_graph_revision": state.graph_revision, "task_id": next_task},
                            "requires_human_confirmation": False})
        candidates = []
        accepted = _candidate_project_ids(store, project_id)
        for candidate in store.candidate_store.list():
            if candidate.project_id in accepted and candidate.status == "pending":
                candidates.append({"kind": "candidate_confirmation", "candidate_id": candidate.candidate_id,
                                   "chapter_number": candidate.chapter_number,
                                   "context_snapshot_id": candidate.context_snapshot_id,
                                   "requires_human_confirmation": True})
        result["readiness"]["human_confirmation"].extend(candidates)
        result["readiness"]["ready"] = result["readiness"]["ready"] and not busy and not source_blocked
        result["readiness"]["can_continue"] = bool(actions)
        result["next_actions"] = actions
        active_id = workbench._active_build_orchestration_jobs.get(workbench._strip_file_prefix(project_id))
        job = workbench._build_orchestration_jobs.get(active_id or "") or workbench._load_build_orchestration_job(store)
        result["job"] = ({key: job.get(key) for key in ("job_id", "status", "current_task_id", "next_task_id", "graph_revision")} if job else None)
        return result


def _check_revision(state, expected):
    if state is None:
        raise HTTPException(409, "build_graph_not_initialized")
    if state.graph_revision != expected:
        raise HTTPException(409, {"code": "build_revision_conflict", "details": {
            "expected_graph_revision": expected, "current_graph_revision": state.graph_revision}})


def init_build_public_routes() -> APIRouter:
    router = APIRouter(prefix="/file-projects/{project_id}/public-build", route_class=PublicRoute)

    @router.get("")
    def get_public_build(project_id: str):
        return _snapshot(project_id)

    @router.get("/readiness")
    def get_readiness(project_id: str):
        result = _snapshot(project_id)
        return {key: result[key] for key in ("schema_version", "graph_revision", "readiness")}

    @router.get("/next-actions")
    def get_next_actions(project_id: str):
        result = _snapshot(project_id)
        return {key: result[key] for key in ("schema_version", "graph_revision", "next_actions")}

    @router.get("/tasks/{task_id}")
    def get_task(project_id: str, task_id: str):
        result = _snapshot(project_id)
        task = next((task for task in result["tasks"] if task["task_id"] == task_id), None)
        if task is None:
            raise HTTPException(404, "build_task_not_found")
        return {"schema_version": projection.SCHEMA, "graph_revision": result["graph_revision"], "task": task}

    @router.get("/tasks/{task_id}/artifacts/{revision}")
    def get_artifact(project_id: str, task_id: str, revision: int):
        store = workbench._store_for(project_id)
        with project_update_lock(store.root):
            _, graph, build_store, state = _context(project_id)
            if task_id not in graph.definition.tasks_by_id or revision < 1:
                raise HTTPException(404, "build_artifact_not_found")
            if state is None:
                raise HTTPException(409, "build_graph_not_initialized")
            artifact = build_store.read_artifact(task_id, revision)
            if artifact is None:
                raise HTTPException(404, "build_artifact_not_found")
            return {"schema_version": projection.SCHEMA, "graph_revision": state.graph_revision,
                    "artifact": projection.artifact_projection(artifact)}

    @router.get("/capabilities")
    def get_capabilities(project_id: str):
        from packages.story_core.runtime_config import resolve_stage_runtime
        from packages.story_core.model_gateway.capabilities import resolve_model_profile
        store = workbench._store_for(project_id)
        with project_update_lock(store.root):
            _, graph, _, _ = _context(project_id)
        stages = sorted({"writer", *{task.model_stage for task in graph.definition.tasks if task.model_stage}})
        bindings = []
        for stage in stages:
            settings = resolve_stage_runtime(stage)
            profile = resolve_model_profile(settings.provider_id, settings.base_url, settings.model,
                                            settings.protocol, user_declared=settings.user_declared_capabilities)
            bindings.append({"stage": stage, "binding_source": "runtime_stage_configuration",
                             **projection.capability_projection(profile)})
        return {"schema_version": projection.SCHEMA, "bindings": bindings}

    @router.patch("/tasks/{task_id}/artifact")
    def edit_artifact(project_id: str, task_id: str, body: ArtifactRequest, request: Request):
        store = workbench._store_for(project_id)
        with workbench._world_build_jobs_lock, project_update_lock(store.root):
            _, _, _, state = _context(project_id)
            _check_revision(state, body.expected_graph_revision)
            if task_id in state.tasks and state.tasks[task_id].status == "review_required":
                raise HTTPException(403, "human_review_required")
            if workbench._has_active_build_orchestration_job(workbench._strip_file_prefix(project_id)):
                raise HTTPException(409, "build_orchestration_in_progress")
            _delegate(request, "edit_file_project_build_graph_task", project_id=project_id, task_id=task_id,
                      request=workbench.BuildWorkbenchArtifactCommitRequest(expected_revision=body.expected_revision, payload=body.payload))
            return _snapshot(project_id)

    @router.post("/next")
    def run_next(project_id: str, body: NextRequest, request: Request):
        store = workbench._store_for(project_id)
        with workbench._world_build_jobs_lock, project_update_lock(store.root):
            _, _, _, state = _context(project_id)
            _check_revision(state, body.expected_graph_revision)
            if not any(action["action"] == "run_next" and action["task_id"] == body.task_id for action in _snapshot(project_id)["next_actions"]):
                raise HTTPException(409, "build_no_allowed_action")
            job = _delegate(request, "start_file_project_build_orchestration", project_id=project_id,
                            request=workbench.BuildWorkbenchOrchestrationRequest(mode="next"))
            return {"schema_version": projection.SCHEMA, "job_id": job["job_id"], "status": job["status"],
                    "graph_revision": state.graph_revision,
                    "status_href": f"/file-projects/{project_id}/public-build"}

    return router

