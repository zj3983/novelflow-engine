"""Product screens backed by the existing creation handlers and authority checks.

Action handles are keyed digests, not encoded engineering payloads. They are
recomputed from current authority for each request; there is no action cache or
second job runner. The existing handler is the final admission/commit boundary.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from apps.api.routes import file_projects as workbench
from apps.api.routes.file_project_candidates import _candidate_project_ids
from packages.story_core import product_presentation as product
from packages.story_core.build_graph.contracts import BuildGraphError
from packages.story_core.opening_build import execution, runtime
from packages.story_core.persistence.project_locking import project_update_lock

_ACTION_KEY = secrets.token_bytes(32)


def _key(*values):
    data = json.dumps(values, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hmac.new(_ACTION_KEY, data, hashlib.sha256).hexdigest()


def _handler(http_request, name, **kwargs):
    for route in http_request.app.routes:
        if getattr(route, "name", None) == name:
            if route.dependant.dependencies or http_request.app.router.dependencies:
                raise HTTPException(503, "product_adapter_dependencies")
            return route.endpoint(**kwargs)
    raise HTTPException(503, "product_adapter_unavailable")


class ProductRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def safe(request):
            try:
                return await original(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"detail": {
                    "message": "填写的内容不完整，请检查后再试。", "impact": "当前内容尚未修改。"}})
            except (HTTPException, BuildGraphError, ValueError, FileNotFoundError) as exc:
                raw = exc.detail if isinstance(exc, HTTPException) else getattr(exc, "code", str(exc))
                issue = product.problem(raw)
                code = exc.status_code if isinstance(exc, HTTPException) else 409
                return JSONResponse(status_code=code, content={"detail": {
                    "message": issue["message"], "impact": issue["suggestion"]}})
        return safe


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    token: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]+$")
    values: dict[str, str] = Field(default_factory=dict)


class Screen:
    def __init__(self, request, project_id):
        self.request, self.project_id = request, project_id
        self.store = workbench._store_for(project_id)
        self.actions = {}
        self.origin = f"/projects/{quote(project_id, safe='')}"

    def call(self, name, **kwargs):
        return _handler(self.request, name, project_id=self.project_id, **kwargs)

    def action(self, name, label, authority, callback, *, enabled=True, reason=None):
        digest = _key(self.project_id, name, authority)
        token = self.mode + digest[1:]
        if enabled:
            self.actions[token] = callback
        result = {"token": token, "label": label, "enabled": enabled}
        if reason:
            result["reason"] = reason
        return result

    def link(self, label, suffix):
        return {"token": "", "label": label, "enabled": True, "href": self.origin + suffix}

    def prepare_build(self):
        self.build_job = self.call("get_current_file_project_build_orchestration") or {}

    def build(self, selection=None, *, all_actions=False, action_token=None):
        self.mode = "b"
        graph = self.call("get_file_project_build_graph")
        tasks = graph.get("tasks") or []
        job = self.build_job
        running = job.get("status") in {"pending", "queued", "running"} or any(t["status"] == "running" for t in tasks)
        revision = graph.get("graph_revision")
        completed = sum(t["status"] == "completed" for t in tasks)
        attention = next((t for t in tasks if t["status"] in {"failed", "validation_failed", "review_required", "stale"}), None)
        state = "running" if running else attention["status"] if attention else "completed" if tasks and completed == len(tasks) else "pending"
        result = {"title": "准备故事", "subtitle": "完善故事设定和章节规划，然后开始写作。",
                  "status": product.status(state), "progress": {"completed": completed, "total": len(tasks),
                  "label": f"已完成 {completed} / {len(tasks)} 部分"}, "parts": [], "actions": [], "notices": []}
        if running:
            result["refresh_after_ms"] = 1500
        if job.get("status") in {"failed", "conflicted", "interrupted"} and not running:
            issue = product.problem(job.get("error_code"))
            result["status"] = product.status("failed", issue["message"])
            result["notices"].append(issue["suggestion"])

        def opening_action(name, label, endpoint):
            return self.action(name, label, revision, lambda values: self.call(endpoint,
                request=workbench.BuildWorkbenchOpeningRequest(expected_graph_revision=revision)), enabled=not running)

        if not graph.get("opening_graph"):
            result["actions"].append(opening_action("activate", "开始准备故事", "activate_file_project_opening_graph"))
        else:
            config = runtime.settings(self.store)
            if config.get("sync_pending") or (not config.get("execution") and config.get("source_revision") != runtime.source_revision(self.store)):
                result["actions"].append(opening_action("sync", "更新创作想法", "sync_file_project_opening_input"))
            if graph.get("opening_next_volume_available"):
                result["actions"].append(opening_action("next-volume", "规划下一卷", "extend_file_project_next_volume"))
                result["status"] = product.status("ready", "这一卷已完成，可以规划下一卷。")
            elif graph.get("opening_planning_pending"):
                result["notices"].append("正在准备后续章节。完成规划前，暂时不能生成新的正文。")
            elif tasks and completed == len(tasks) and not config.get("execution"):
                plan = runtime.canonical_plan(self.store).outline
                first = next((arc for arc in plan.arcs if arc.start_chapter == 1), None)
                if first and first.end_chapter > config.get("chapter_count", 3):
                    result["actions"].append(opening_action("first-volume", "完善本卷规划", "extend_file_project_opening_volume"))

        if graph.get("initialized") and not (graph.get("opening_execution_started") and not graph.get("opening_planning_pending")):
            for mode, label in (("continue", "生成规划"), ("rebuild_stale", "更新受影响的内容"), ("next", "继续下一部分")):
                if mode == "rebuild_stale" and not any(t["status"] == "stale" for t in tasks):
                    continue
                result["actions"].append(self.action("build-" + mode, label, revision,
                    lambda values, mode=mode: self.call("start_file_project_build_orchestration",
                        request=workbench.BuildWorkbenchOrchestrationRequest(mode=mode)), enabled=not running))
        if tasks and completed == len(tasks) and not running:
            result["actions"].append(self.link("开始写作", "/write"))
        if action_token in self.actions:
            return result
        selected_id = None
        for task in tasks:
            key = _key(self.project_id, "part", task["task_id"])
            result["parts"].append({"selection": key, "title": product.part_title(task["task_id"], task["title"]),
                                    "status": product.status(task["status"])})
            if key == selection:
                selected_id = task["task_id"]
        if selected_id is None and tasks:
            selected_id = (attention or tasks[0])["task_id"]
        for task in tasks:
            if task["task_id"] != selected_id and not all_actions:
                continue
            if action_token:
                authority = [revision, task.get("artifact_revision")]
                possible = {_key(self.project_id, f"{task['task_id']}-{operation}", authority) for operation in ("repair", "rerun", "save")}
                if action_token not in {self.mode + digest[1:] for digest in possible}:
                    continue
            detail = self.call("get_file_project_build_graph_task", task_id=task["task_id"])
            artifact = detail.get("artifact") or {}
            task_id = task["task_id"]
            editable_payload = product.editable_payload(artifact.get("payload") or {}, detail.get("diagnostics"))
            fields, paths = product.editable_fields(editable_payload, lambda path: _key(task_id, path))
            item = {"selection": _key(self.project_id, "part", task_id),
                    "title": product.part_title(task_id, task["title"]),
                    "description": product.status(task["status"])["message"],
                    "paragraphs": [f'{field["label"]}：{field["value"]}' for field in fields],
                    "issues": product.issues(detail.get("diagnostics")), "actions": []}
            editable = detail.get("editable") and task["status"] != "review_required"
            if editable:
                authority = [revision, artifact.get("revision")]
                for operation, label, endpoint, request_type in (
                    ("repair", "让 AI 修复", "repair_file_project_build_graph_task", workbench.BuildWorkbenchRepairRequest),
                    ("rerun", "重新创作这一部分", "rerun_file_project_build_graph_task", workbench.BuildWorkbenchRerunRequest),
                ):
                    item["actions"].append(self.action(f"{task_id}-{operation}", label, authority,
                        lambda values, task_id=task_id, endpoint=endpoint, request_type=request_type, rev=artifact["revision"]:
                            self.call(endpoint, task_id=task_id, request=request_type(expected_revision=rev)), enabled=not running))

                def save(values, task_id=task_id, payload=editable_payload, paths=paths, rev=artifact["revision"]):
                    return self.call("edit_file_project_build_graph_task", task_id=task_id,
                        request=workbench.BuildWorkbenchArtifactCommitRequest(expected_revision=rev,
                            payload=product.apply_fields(payload, paths, values)))

                item["form"] = {"title": "我来修改", "description": "修改后保存；系统会检查内容是否完整。",
                                "fields": fields, "actions": [self.action(f"{task_id}-save", "保存修改", authority, save, enabled=not running)]}
            if task_id == selected_id:
                result["selected"] = item
        return result

    def prepare_write(self):
        # Existing interrupted-job recovery owns its job lock. Call it before
        # taking the project lock, and do not resume continuous generation here.
        try:
            self.generation_job = self.call("get_current_file_generation_job") or {}
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            self.generation_job = {}

    def write(self, chapter=None, *, all_actions=False):
        self.mode = "a"
        store = self.store
        state = store.state()
        confirmed = int(state.get("current_chapter") or 0)
        numbers = store.chapter_numbers()
        accepted = _candidate_project_ids(store, self.project_id)
        candidates = [c for c in store.candidate_store.list() if c.project_id in accepted and c.status == "pending"]
        target = chapter or (max(candidates, key=lambda c: c.chapter_number).chapter_number if candidates else confirmed)
        candidate = next((c for c in candidates if c.chapter_number == target), None)
        job = self.generation_job
        continuous = workbench._continuous_job_store(store).load()
        continuous = continuous.to_dict() if hasattr(continuous, "to_dict") else continuous or {}
        running = job.get("status") in {"queued", "running"} or continuous.get("status") in {"queued", "running", "stopping"}
        result = {"title": store.project().get("title") or "正文创作", "subtitle": "创作、修改、确认，再继续下一章。",
                  "status": product.status("running" if running else "ready"), "chapters": [], "actions": [], "forms": [], "notices": [],
                  "steps": [{"label": label, "current": index == (1 if candidate else 3 if confirmed else 0)}
                            for index, label in enumerate(("生成候选", "阅读与审查", "人工确认", "继续写作"))]}
        if running:
            result["refresh_after_ms"] = 1500
        for number in numbers:
            # Directory metadata does not require loading every chapter body or
            # writing the existing optional chapter-index cache during a GET.
            content = store.snapshot_store.read_json(store.story_system_dir / "chapters" / f"{number:04d}.json", {})
            result["chapters"].append({"number": number, "title": content.get("chapter_title") or f"第 {number} 章",
                                       "summary": str(content.get("summary") or "")})
            if number == target:
                content = store.chapter(number)
                result["chapter"] = {"number": number, "title": content.get("chapter_title") or f"第 {number} 章",
                                     "body": content.get("body") or "", "summary": str(content.get("summary") or "")}
        if job.get("status") in {"failed", "conflicted", "interrupted"} and not running:
            issue = product.problem(job.get("error") or job.get("error_code"))
            result["status"] = product.status("failed", issue["message"])
            result["notices"].append(issue["suggestion"])

        opening = runtime.enabled(store)
        authority = execution.source_fingerprint(store)
        ready = True
        try:
            if opening:
                execution.capture(store)
            else:
                store.require_volume_detail_for_prose(confirmed + 1)
                if store.rolling_fill_status(confirmed + 1).get("status") not in {"present", "legacy"}:
                    raise ValueError("outline_required")
        except ValueError as exc:
            ready = False
            result["status"] = product.status("blocked", product.problem(exc)["message"])
            result["actions"].append(self.link("完善章节规划", "/build" if opening else "/outline?tab=chapters"))
        if ready and not candidates:
            result["actions"].append(self.action("generate", "生成第一章" if confirmed == 0 else "生成下一章", authority,
                lambda values: self._generate(confirmed + 1), enabled=not running))
        for current in candidates:
            if current is not candidate and not all_actions:
                continue
            review, findings, blocked, warning = product.candidate_review(current, store=store)
            if opening:
                try:
                    execution.verify(store, current.submission_payload.get("opening_authority"))
                except ValueError as exc:
                    blocked = True
                    issue = product.problem(exc)
                    review = product.status("blocked", issue["message"])
                    findings = [issue, *findings]
            ref = [authority, current.to_dict()]
            confirm = self.action("confirm-" + current.candidate_id, "仍然采用" if warning else "确认提交", ref,
                lambda values, c=current, warning=warning: self._confirm(c, warning),
                enabled=not running and not blocked, reason="请先处理正文中的冲突。" if blocked else None)
            discard = self.action("discard-" + current.candidate_id, "丢弃候选稿", ref,
                lambda values, c=current: self.call("discard_file_project_candidate", candidate_id=c.candidate_id), enabled=not running)
            from packages.story_core.candidate_editing import candidate_authority, save_edit
            expected = candidate_authority(current)
            editable = current.operation == "generate" and current.chapter_number == confirmed + 1
            body_key = _key("candidate-body", current.candidate_id)
            guidance_key = _key("candidate-guidance", current.candidate_id)
            save = self.action("edit-" + current.candidate_id, "保存改稿", ref,
                lambda values, c=current, expected=expected, body_key=body_key: save_edit(
                    store, c.candidate_id, body=values.get(body_key, ""),
                    expected=expected, expected_source=authority), enabled=editable and not running)
            recheck = self.action("recheck-" + current.candidate_id, "重新检查", ref,
                lambda values, c=current, expected=expected: workbench.start_candidate_review_job(
                    self.project_id, c.candidate_id, expected=expected), enabled=editable and not running)
            revise = self.action("revise-" + current.candidate_id, "让 AI 修改并检查", ref,
                lambda values, c=current, expected=expected, key=guidance_key: workbench.start_candidate_review_job(
                    self.project_id, c.candidate_id, expected=expected, guidance=values.get(key, "")),
                enabled=editable and not running)
            if current is candidate:
                result["candidate"] = {"number": current.chapter_number, "title": current.chapter_title or f"第 {current.chapter_number} 章候选稿",
                                       "body": current.body, "review": review, "issues": findings, "actions": [recheck, confirm, discard]}
                if editable:
                    result["candidate"]["form"] = {"title": "我来改写", "description": "保存会保留旧稿。改稿后请重新检查，再确认正文。",
                        "fields": [{"key": body_key, "label": "候选正文", "value": current.body, "type": "textarea"}], "actions": [save]}
                    result["forms"].append({"title": "让 AI 修改", "description": "按已保存的候选修改。请先保存手工改稿。",
                        "fields": [{"key": guidance_key, "label": "修改要求", "value": "", "type": "textarea"}], "actions": [revise]})
                result["status"] = review
        if candidates and not candidate:
            result["actions"].append(self.link("查看待确认的候选", f"/write?chapter={candidates[0].chapter_number}"))
        if not opening:
            for number in numbers if all_actions else [target] if target in numbers else []:
                guidance_key = _key("guidance", number)
                ops = []
                for operation, label in ((None, "重新生成本章"), ("expand", "扩写本章"), ("polish", "润色本章")):
                    ops.append(self.action(f"rewrite-{number}-{operation}", label, authority,
                        lambda values, number=number, operation=operation, guidance_key=guidance_key: workbench.start_file_generation_job(self.project_id,
                            workbench.FileProjectGenerationJobRequest(chapter_number=number, operation=operation,
                                                                     guidance=values.get(guidance_key) or None)), enabled=not running))
                if number == target:
                    result["forms"].append({"title": "修改本章", "fields": [{"key": guidance_key, "label": "修改要求", "value": "", "type": "textarea"}], "actions": ops})
            count_key = _key("count")
            if continuous.get("status") in {"queued", "running", "stopping"}:
                result["actions"].append(self.action("stop", "停止连续创作", continuous.get("job_id"),
                    lambda values: self.call("stop_continuous_generation_job", job_id=continuous["job_id"])))
            elif not candidates and ready:
                def start(values):
                    count = int(values.get(count_key) or "2")
                    return workbench.start_continuous_generation_job(self.project_id, workbench.FileProjectContinuousGenerationRequest(count=count))
                result["forms"].append({"title": "连续创作", "description": "可选择 2、5、10 或 20 章。",
                    "fields": [{"key": count_key, "label": "创作章数", "type": "number", "value": "2"}],
                    "actions": [self.action("continuous", "开始连续创作", authority, start, enabled=not running)]})
        return result

    def _confirm(self, candidate, warning):
        self.call("confirm_file_project_candidate", candidate_id=candidate.candidate_id, force=warning)
        return {"redirect": self.origin + f"/write?chapter={candidate.chapter_number}"}

    def _generate(self, chapter):
        workbench.start_file_generation_job(self.project_id, workbench.FileProjectGenerationJobRequest(candidate_only=True))
        return {"redirect": self.origin + f"/write?chapter={chapter}"}


def init_creation_product_routes():
    router = APIRouter(prefix="/file-projects/{project_id}/product", route_class=ProductRoute)

    @router.get("/build")
    def get_build_product(project_id: str, request: Request, selection: str | None = None):
        screen = Screen(request, project_id)
        screen.prepare_build()
        with project_update_lock(screen.store.root):
            return screen.build(selection)

    @router.get("/write")
    def get_write_product(project_id: str, request: Request, chapter: int | None = None):
        screen = Screen(request, project_id)
        screen.prepare_write()
        with project_update_lock(screen.store.root):
            return screen.write(chapter)

    @router.post("/actions")
    def perform_product_action(project_id: str, request: Request, body: ActionRequest):
        screen = Screen(request, project_id)
        # Only compute/check the action under this short lock. Original handlers
        # retain their admission and commit checks; model work is outside it.
        if body.token.startswith("b"):
            screen.prepare_build()
        else:
            screen.prepare_write()
        with project_update_lock(screen.store.root):
            if body.token.startswith("b"):
                screen.build(all_actions=True, action_token=body.token)
            else:
                screen.write(all_actions=True)
            callback = screen.actions.get(body.token)
        if callback is None:
            raise HTTPException(409, "revision_conflict")
        result = callback(body.values)
        # Never forward engineering handler responses to the browser.
        response = {"message": "操作已完成，请查看最新内容。"}
        if isinstance(result, dict) and result.get("redirect"):
            response["redirect"] = result["redirect"]
        return response

    return router
