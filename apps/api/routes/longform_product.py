"""The four-page author workspace, backed by existing services and admission gates."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.api.routes import file_projects as workbench
from apps.api.routes.creation_product import ProductRoute, Screen, _handler, _key
from apps.api.routes.file_project_candidates import _candidate_project_ids
from packages.story_core import longform_lifecycle as lifecycle
from packages.story_core import product_presentation as product
from packages.story_core.candidate_editing import assert_review_current, candidate_authority, save_edit
from packages.story_core.file_project_creation import FileProjectCreateSpec
from packages.story_core.longform_presentation import genre_id, opening_content, project_content, text
from packages.story_core.models import NovelProject
from packages.story_core.opening_build import execution, runtime
from packages.story_core.persistence.project_locking import project_update_lock


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    bookId: str | None = None
    token: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]+$")
    command: dict[str, Any]


class PlanningScreen(Screen):
    """Retain this request's already-read details for the four-page projection."""
    def __init__(self, request, project_id):
        super().__init__(request, project_id)
        self.graph = {}
        self.details = {}

    def call(self, name, **kwargs):
        if name == "get_file_project_build_graph_task" and kwargs["task_id"] in self.details:
            return self.details[kwargs["task_id"]]
        value = super().call(name, **kwargs)
        if name == "get_file_project_build_graph":
            self.graph = value
            # The caller holds the project lock for this entire projection. Reuse
            # its validated graph snapshot instead of reconstructing and checking
            # the complete graph once per chapter just to read its text.
            self.details = {}
            if value.get("initialized"):
                definition = runtime.graph_for(self.store, NovelProject.model_validate(self.store.project()))
                build_store = self.store.build_graph_store()
                for task in value["tasks"]:
                    revision = task.get("artifact_revision")
                    artifact = build_store.read_artifact(task["task_id"], revision) if revision is not None else None
                    if revision is not None and artifact is None:
                        raise HTTPException(409, "build_graph_artifact_missing")
                    self.details[task["task_id"]] = {
                        **task,
                        "artifact": artifact.to_dict() if artifact else None,
                        "editable": definition.spec(task["task_id"]).kind == "model"
                            and artifact is not None and not value.get("opening_execution_started"),
                    }
        elif name == "get_file_project_build_graph_task":
            self.details[kwargs["task_id"]] = value
        return value


class AuthorScreen(Screen):
    def __init__(self, request, project_id):
        super().__init__(request, project_id)
        self.mode = "c"
        self.commands = {}

    def command(self, name, label, authority, callback, *, enabled=True, reason=None):
        action = self.action(name, label, authority, callback, enabled=enabled, reason=reason)
        action["command"] = name
        self.commands[name] = action
        return action

    def start_next(self, reservation=None, *, expected_plan=None):
        lifecycle.require_accepted_plan(self.store)
        return workbench.start_file_generation_job(self.project_id,
            workbench.FileProjectGenerationJobRequest(candidate_only=True, require_accepted_plan=True), reserved_job_id=reservation, expected_plan=expected_plan)

    def prepare(self):
        self.generation_job = workbench.read_file_generation_job_state(self.store) or {}
        self.build_screen = PlanningScreen(self.request, self.project_id)
        self.build_screen.prepare_build()
        # Read job ownership before taking the project lock. A failed next
        # chapter must stay recoverable even when the receipt still says queued.
        self.continuation_jobs = {}
        current_chapter = int(self.store.state().get("current_chapter") or 0)
        accepted_ids = _candidate_project_ids(self.store, self.project_id)
        for candidate in self.store.candidate_store.list():
            if candidate.status == "confirmed" and candidate.chapter_number == current_chapter and candidate.project_id in accepted_ids:
                intent = lifecycle.continuation_state(self.store, candidate.candidate_id)
                if intent and intent.get("job_id"):
                    self.continuation_jobs[intent["job_id"]] = workbench.read_file_generation_job_state(self.store, intent["job_id"])

    def view(self, chapter=None):
        store = self.store
        info, state = store.project(), store.state()
        confirmed = int(state.get("current_chapter") or 0)
        source = execution.source_fingerprint(store)
        accepted_ids = _candidate_project_ids(store, self.project_id)
        pending = [c for c in store.candidate_store.list() if c.project_id in accepted_ids and c.status == "pending"]
        candidate = max(pending, key=lambda c: c.chapter_number) if pending else None
        selected = chapter if chapter is not None else candidate.chapter_number if candidate else confirmed
        job = self.generation_job
        busy = job.get("status") in {"queued", "running"}
        continuous = workbench._continuous_job_store(store).load()
        if continuous:
            data = continuous.to_dict() if hasattr(continuous, "to_dict") else continuous
            busy = busy or data.get("status") in {"queued", "running", "stopping"}
        plan = lifecycle.plan_state(store)
        setup = opening_content(store)
        selected_direction = next((d for d in setup.get("directions", []) if d.get("id") == setup.get("selected_id")), {})
        content = project_content(store)
        authority = [source, info, plan["fingerprint"], job.get("job_id"), job.get("status")]
        result = {"id": self.project_id, "title": text(info.get("title")) or "未命名作品",
                  "genre": genre_id(info, state), "idea": text((setup.get("brief") or {}).get("idea")),
                  "targetWords": info.get("target_words"), "chapterWords": info.get("target_chapter_words"),
                  "requirements": "\n".join(info.get("author_constraints") or []),
                  "direction": text(selected_direction.get("title")), "planAdopted": plan["accepted"],
                  "directions": [{"id": _key("direction", self.project_id, d.get("id")), "text": text(d.get("title")), "label": text(d.get("logline")) or text(d.get("hook"))} for d in setup.get("directions", [])],
                  "chapters": [], "notice": "正在处理，请稍候。" if busy else "", "busy": busy,
                  "canRetry": job.get("status") in {"failed", "interrupted", "conflicted"},
                  "nextVolume": False, "archived": False, **content}
        result["future"] = lifecycle.author_future_intent(store)
        if not result["direction"] and (confirmed or content["plan"]):
            result["direction"] = content["plan"] or "沿用已有故事规划"
        for number in store.chapter_numbers():
            data = store.snapshot_store.read_json(store.story_system_dir / "chapters" / f"{number:04d}.json", {})
            body = store.chapter(number).get("body", "") if number == selected else ""
            result["chapters"].append({"number": number, "title": data.get("chapter_title") or f"第 {number} 章", "body": body})
        if result["canRetry"]:
            result["notice"] = product.problem(job.get("error") or job.get("error_code"))["message"]

        def directions(values):
            return workbench.start_opening_direction_job(self.project_id, expected_source=source, guidance=text(values.get("text")))

        def choose(values):
            direction = next((d for d in setup.get("directions", []) if _key("direction", self.project_id, d.get("id")) == values.get("id")), None)
            if direction is None:
                raise ValueError("direction_not_found")
            with project_update_lock(store.root):
                if execution.source_fingerprint(store) != source or opening_content(store) != setup:
                    raise ValueError("candidate_source_changed")
                return self.call("select_opening_direction", direction_id=direction["id"])

        self.command("prepare-directions", "准备故事方向", authority, directions,
            enabled=not busy and confirmed == 0 and not setup.get("selected_id"))
        self.command("direction", "选择这个方向", [authority, setup], choose, enabled=not busy and confirmed == 0 and bool(setup.get("directions")))
        self.command("adopt", "采纳当前规划", authority,
            lambda values: lifecycle.accept_plan(store, plan["fingerprint"]), enabled=not busy and plan["ready"])
        self.command("generate", "生成候选" if confirmed == 0 else "继续写作", authority,
            lambda values: self.start_next(expected_plan=plan["fingerprint"]), enabled=not busy and not pending and plan["accepted"] and plan["ready"],
            reason=None if plan["accepted"] else "请先完成并采纳当前规划。")
        self.command("requirements", "保存作者要求", authority,
            lambda values: lifecycle.save_author_requirements(store, requirements=text(values.get("text")).splitlines(), expected_source=source), enabled=not busy)

        def save_plan(values, key):
            outline = deepcopy(store.snapshot_store.read_json(store.webnovel_dir / "outline.json", {}))
            outline.setdefault("overall", {})[key] = text(values.get("text"))
            return lifecycle.save_future_plan(store, payload=outline, expected_source=source)

        edit_reason = "请在下方相应规划部分修改；已被正文采用的内容不能覆盖。" if runtime.enabled(store) else None
        self.command("future", "保存后续创作想法", authority,
            lambda values: lifecycle.save_future_intent(store, text(values.get("text")), expected_source=source), enabled=not busy)
        self.command("plan", "保存全书方向", authority, lambda values: save_plan(values, "story"),
            enabled=not busy and not runtime.enabled(store), reason=edit_reason)
        self.command("archive", "归档作品", authority, lambda values: self.call("archive_file_project"), enabled=not busy)

        if not pending:
            last = next((c for c in store.candidate_store.list() if c.project_id in accepted_ids
                         and c.status == "confirmed" and c.chapter_number == confirmed), None)
            intent = lifecycle.continuation_state(store, last.candidate_id) if last else None
            next_job = self.continuation_jobs.get(intent.get("job_id")) if intent else None
            interrupted = intent and (intent.get("state") in {"failed", "launching"}
                or (next_job or {}).get("status") in {"failed", "interrupted", "conflicted"}
                or intent.get("state") in {"queued", "running"} and not next_job)
            if interrupted:
                result["notice"] = "本章已保存，下一章尚未开始。完成规划后可以继续。"
                self.command("retry-next", "继续准备下一章", [authority, intent],
                    lambda values: lifecycle.confirm_and_continue(store, last.candidate_id, expected_candidate=None,
                        accept_quality_warnings=False, start_next=self.start_next, retry=True,
                        read_job=lambda job_id: workbench.read_file_generation_job_state(store, job_id)),
                    enabled=not busy and plan["accepted"] and plan["ready"])

        if candidate:
            review, issues, blocked, warning = product.candidate_review(candidate, store=store)
            if runtime.enabled(store):
                try:
                    execution.verify(store, candidate.submission_payload.get("opening_authority"))
                except ValueError as exc:
                    blocked = True
                    issues = [product.problem(exc), *issues]
            expected = candidate_authority(candidate)
            ref = [authority, expected]
            editable = candidate.operation == "generate" and candidate.chapter_number == confirmed + 1
            needs_check = bool(candidate.review_binding) and candidate.review_binding.get("state") != "checked"
            try:
                assert_review_current(store, candidate)
            except ValueError:
                needs_check = True
            result["candidate"] = {"key": _key("candidate", candidate.candidate_id), "number": candidate.chapter_number,
                "title": candidate.chapter_title, "body": candidate.body, "label": review["message"],
                "needsCheck": needs_check, "checking": busy and job.get("operation") in {"candidate_review", "candidate_revise"},
                "canConfirm": not busy and not blocked and not warning, "canAcceptSuggestion": not busy and not blocked and warning,
                "concerns": issues, "concern": issues[0] if issues else None, "pastDrafts": []}
            for entry in candidate.revision_history[-20:]:
                old_id = entry.get("candidate_id") if isinstance(entry, dict) else entry
                if not isinstance(old_id, str) or not re.fullmatch(r"cd-[a-f0-9]+", old_id):
                    continue
                old = store.candidate_store.get(old_id)
                if old and old.project_id in accepted_ids:
                    result["candidate"]["pastDrafts"].append({"body": old.body, "label": "先前保存的稿件"})
            self.command("save-draft", "保存改稿", ref,
                lambda values: save_edit(store, candidate.candidate_id, body=text(values.get("text")), expected=expected, expected_source=source), enabled=editable and not busy)
            self.command("review", "重新检查", ref,
                lambda values: workbench.start_candidate_review_job(self.project_id, candidate.candidate_id, expected=expected), enabled=editable and not busy)
            self.command("ai-edit", "让 AI 修改", ref,
                lambda values: workbench.start_candidate_review_job(self.project_id, candidate.candidate_id, expected=expected, guidance=text(values.get("instruction"))), enabled=editable and not busy)
            self.command("discard", "放弃当前候选", ref,
                lambda values: self.call("discard_file_project_candidate", candidate_id=candidate.candidate_id), enabled=not busy)
            def confirm(values, allow_warning=False):
                workbench._assert_candidate_mutation_allowed(store)
                if values.get("continue") is True:
                    return lifecycle.confirm_and_continue(store, candidate.candidate_id, expected_candidate=expected,
                        accept_quality_warnings=allow_warning, start_next=self.start_next,
                        read_job=lambda job_id: workbench.read_file_generation_job_state(store, job_id))
                with project_update_lock(store.root):
                    current = store.candidate_store.get(candidate.candidate_id)
                    if current is None or candidate_authority(current) != expected:
                        raise ValueError("candidate_revision_conflict")
                    lifecycle.require_accepted_plan(store)
                    # Final body/check/source admission and the confirmation
                    # transaction share the lock. There is no model call here.
                    return store.confirm_candidate(candidate.candidate_id, accept_quality_warnings=allow_warning)
            self.command("confirm", "确认本章", ref, confirm, enabled=not busy and not blocked and not warning)
            self.command("accept-suggestion", "保留原文并确认本章（接受提醒）", ref,
                lambda values: confirm(values, True), enabled=not busy and not blocked and warning)

        # Reuse each existing build callback, including its commit-time protections.
        build = self.build_screen
        with project_update_lock(store.root):
            planning = build.build(all_actions=True)
        if planning.get("refresh_after_ms"):
            result["busy"] = True
            result["notice"] = "正在准备故事规划。"
        known = {"开始准备故事": "prepare-plan", "更新创作想法": "sync-plan", "生成规划": "prepare-plan",
                 "更新受影响的内容": "refresh-plan", "继续下一部分": "continue-plan", "规划下一卷": "next-volume", "完善本卷规划": "complete-volume"}
        for action in planning.get("actions", []):
            name = known.get(action["label"])
            if name and action.get("token") in build.actions:
                self.command(name, action["label"], [authority, action["token"]], build.actions[action["token"]], enabled=action["enabled"] and not busy)
                if name == "next-volume":
                    result["nextVolume"] = action["enabled"]
        # The editing fields already contain author labels and opaque paths.
        result["planningParts"] = []
        for task in build.graph.get("tasks", []):
            task_id = task["task_id"]
            detail = build.details.get(task_id)
            if detail is None:
                continue
            artifact = detail.get("artifact") or {}
            editable = product.editable_payload(artifact.get("payload") or {}, detail.get("diagnostics"))
            fields, _ = product.editable_fields(editable, lambda path: _key(task_id, path))
            ref = [build.graph.get("graph_revision"), artifact.get("revision")]
            display = {"key": _key("planning-part", self.project_id, task_id), "title": product.part_title(task_id, task["title"]),
                       "description": product.status(task["status"])["message"],
                       "paragraphs": [f'{f["label"]}：{f["value"]}' for f in fields],
                       "issues": product.issues(detail.get("diagnostics")), "actions": []}
            for operation, label in (("repair", "让 AI 修复"), ("rerun", "重新创作这一部分"), ("save", "保存修改")):
                digest = _key(self.project_id, f"{task_id}-{operation}", ref)
                original = "b" + digest[1:]
                if original not in build.actions:
                    continue
                action = {"token": original, "label": label, "enabled": not busy}
                if operation == "save":
                    display["form"] = {"title": "我来修改", "description": "保存后检查规划是否完整。", "fields": fields, "actions": [action]}
                else:
                    display["actions"].append(action)
            for action in display.get("actions", []):
                callback = build.actions.get(action["token"])
                if callback:
                    self.command("planning-action:" + action["token"], action["label"], [authority, action["token"]], callback, enabled=action["enabled"] and not busy)
                    action.update(self.commands["planning-action:" + action["token"]])
            form = display.get("form")
            if form:
                for action in form.get("actions", []):
                    original = action["token"]
                    callback = build.actions.get(original)
                    if callback:
                        mapped = self.command("planning-action:" + original, action["label"], [authority, original],
                            lambda values, callback=callback: callback(values.get("values", {})), enabled=action["enabled"] and not busy)
                        action.update(mapped)
            result["planningParts"].append(display)
        if result["busy"]:
            for action in self.commands.values():
                action["enabled"] = False
                action["reason"] = "请等待当前创作完成。"
            for part in result["planningParts"]:
                for action in [*part.get("actions", []), *(part.get("form") or {}).get("actions", [])]:
                    action["enabled"] = False
        result["actions"] = self.commands
        return result


def _workspace(request, book_id=None, chapter=None):
    books = []
    selected = None
    genres = _handler(request, "list_registered_novel_types")
    genre_names = {g["id"]: g["name"] for g in genres}
    for store in workbench._stores(lifecycle="active"):
        project_id = workbench._public_project_id(store)
        screen = AuthorScreen(request, project_id)
        screen.prepare()
        with project_update_lock(store.root):
            book = screen.view(chapter if project_id == book_id else None)
        book["genre"] = genre_names.get(book["genre"], "未设置")
        books.append(book)
        if project_id == book_id or selected is None and book_id is None:
            selected = screen
    for store in workbench._stores(lifecycle="archived"):
        info = store.project()
        project_id = workbench._public_project_id(store)
        token = _key("restore", project_id, info)
        books.append({"id": project_id, "title": text(info.get("title")), "genre": genre_names.get(genre_id(info), "未设置"),
                      "idea": "", "requirements": "", "future": "", "plan": "", "planAdopted": False,
                      "planningVolume": 1, "chapters": [], "archived": True, "notice": "作品已归档。", "busy": False,
                      "canRetry": False, "nextVolume": False, "actions": {"archive": {"token": token, "label": "恢复作品", "enabled": True}}})
    return {"books": books, "bookId": book_id or (selected.project_id if selected else ""), "page": "books", "selectedChapter": chapter,
            "showNew": False, "storyTab": "人物", "person": "", "storageWarning": "",
            "genres": [{"value": g["id"], "label": g["name"]} for g in genres],
            "actions": {"create": {"token": _key("create-author-book"), "label": "开始创作", "enabled": True}},
            "links": {"settings": "/config", "import": "/projects?import=1"}}, selected


def init_longform_product_routes():
    router = APIRouter(route_class=ProductRoute)

    @router.get("/author-workspace")
    def author_workspace(request: Request, book_id: str | None = None, chapter: int | None = None):
        return _workspace(request, book_id, chapter)[0]

    @router.post("/author-workspace/commands")
    def author_command(request: Request, body: CommandRequest):
        command = body.command
        name = command.get("type")
        if name == "create":
            if body.token != _key("create-author-book"):
                raise HTTPException(409, "product_action_revision_expired")
            result = _handler(request, "create_new_file_project", payload=FileProjectCreateSpec(
                mode="inspiration", title=text(command.get("title")), novel_type_id=text(command.get("genre")), idea=text(command.get("idea")),
                target_words=command.get("targetWords", 900000), target_chapter_words=command.get("chapterWords", 3000),
                author_constraints=text(command.get("requirements")).splitlines()))
            return {"bookId": result["project_id"], "message": "作品已创建，请准备故事方向。"}
        if not body.bookId:
            raise HTTPException(422, "project_not_found")
        if name == "archive" and command.get("archived") is False:
            store = workbench._store_for(body.bookId)
            if store.project().get("project_lifecycle") != "archived":
                raise HTTPException(409, "product_action_revision_expired")
            if body.token != _key("restore", body.bookId, store.project()):
                raise HTTPException(409, "product_action_revision_expired")
            _handler(request, "restore_file_project", project_id=body.bookId)
            return {"bookId": body.bookId, "message": "作品已恢复。"}
        screen = AuthorScreen(request, body.bookId)
        screen.prepare()
        with project_update_lock(screen.store.root):
            screen.view()
            action = screen.commands.get(name)
            if not action or not action["enabled"] or action["token"] != body.token:
                raise HTTPException(409, "product_action_revision_expired")
            callback = screen.actions[body.token]
        result = callback(command)
        message = "已保存。"
        if isinstance(result, dict) and isinstance(result.get("next"), dict):
            message = result["next"].get("message") or message
        return {"bookId": body.bookId, "message": message}

    return router
