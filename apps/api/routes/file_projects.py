from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
import re
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.story_core.book_dissection import diagnose_project_chapter, dissect_reference_text
from packages.story_core.file_project_creation import FileProjectCreateSpec, create_file_project
from packages.story_core.generation_progress import generation_progress
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import AgentRuntimeState, AgentSettings
from packages.story_core.opening_directions import LLMOpeningDirectionGenerator
from packages.story_core.simplified_review import build_simplified_review


router = APIRouter()
opening_direction_generator = LLMOpeningDirectionGenerator()
FILE_ID_PREFIX = "file:"
FILE_GENERATION_JOB_STALE_SECONDS = 15 * 60
_file_generation_executor = ThreadPoolExecutor(max_workers=1)
_file_generation_jobs: dict[str, dict[str, object]] = {}
_active_file_generation_jobs: dict[str, str] = {}
_file_generation_jobs_lock = Lock()


class FileProjectRegenerateRequest(BaseModel):
    chapter_number: int
    variant: str | None = None
    guidance: str | None = None


class FileProjectGenerateNextRequest(BaseModel):
    chapter_direction_id: str | None = None


class OpeningDirectionGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    guidance: str = Field(default="", max_length=1000)

    @field_validator("guidance", mode="before")
    @classmethod
    def trim_guidance(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class FileProjectGenerationJobRequest(BaseModel):
    chapter_number: int | None = None
    variant: str | None = None
    guidance: str | None = None
    chapter_direction_id: str | None = None


class FileProjectUpdateRequest(BaseModel):
    title: str | None = None
    seed_outline: str | None = None
    world_summary: str | None = None
    current_focus: str | None = None
    author_constraints: list[str] | None = None
    world_blueprint: dict[str, Any] | None = None
    character_profiles: list[dict[str, Any]] | None = None
    relationship_graph: list[dict[str, Any]] | None = None
    enabled_skill_ids: list[str] | None = None
    status: str | None = None
    pipeline_stage: str | None = None


class BookDissectionReferenceRequest(BaseModel):
    text: str
    genre: str = ""
    focus: str = ""


class BookDissectionChapterRequest(BaseModel):
    chapter_number: int | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _export_root() -> Path:
    configured = os.getenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR")
    if configured:
        return Path(configured).resolve()
    return (Path.cwd() / "data" / "exported-projects").resolve()


def _strip_file_prefix(value: str) -> str:
    return value[len(FILE_ID_PREFIX) :] if value.startswith(FILE_ID_PREFIX) else value


def _file_id(value: str) -> str:
    return value if value.startswith(FILE_ID_PREFIX) else f"{FILE_ID_PREFIX}{value}"


def _public_project_id(store: FileProjectStore) -> str:
    return _file_id(store.root.name)


def _is_hidden_file_project_dir(path: Path) -> bool:
    name = path.name
    return (
        name.startswith((".", "_"))
        or ".backup-" in name
        or ".before-" in name
        or name.endswith(".bak")
        or name.endswith(".backup")
    )


def _stores() -> list[FileProjectStore]:
    root = _export_root()
    if not root.exists():
        return []
    stores: list[FileProjectStore] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or _is_hidden_file_project_dir(child):
            continue
        store = FileProjectStore(child)
        if store.exists():
            stores.append(store)
    return stores


def _store_for(project_id: str) -> FileProjectStore:
    wanted = _strip_file_prefix(project_id)
    for store in _stores():
        project = store.project()
        candidates = {str(project.get("project_id") or ""), store.root.name}
        if wanted in candidates:
            return store
    raise HTTPException(status_code=404, detail="file_project_not_found")


def _raise_file_project_error(exc: ValueError) -> None:
    detail = str(exc)
    if detail.startswith("chapter_frozen:"):
        raise HTTPException(status_code=409, detail=detail) from exc
    raise HTTPException(status_code=400, detail=detail) from exc


def _story_id_for(store: FileProjectStore) -> str:
    return _file_id(store.root.name)


def _file_generation_job_response(job: dict[str, object]) -> dict[str, object]:
    return {
        "job_id": str(job.get("job_id", "")),
        "story_id": str(job.get("story_id", "")),
        "status": str(job.get("status", "")),
        "progress": str(job.get("progress", "")),
        "chapter_number": job.get("chapter_number") if isinstance(job.get("chapter_number"), int) else None,
        "error": str(job.get("error", "")),
        "created_at": str(job.get("created_at", "")),
        "updated_at": str(job.get("updated_at", "")),
    }


def _update_file_generation_job(job_id: str, **updates: object) -> None:
    with _file_generation_jobs_lock:
        job = _file_generation_jobs.get(job_id)
        if job is None:
            return
        job.update(updates)
        job["updated_at"] = _now_iso()


def _parse_iso_datetime(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _reconcile_file_generation_job_locked(job: dict[str, object]) -> None:
    if job.get("status") not in {"queued", "running"}:
        return
    story_id = str(job.get("story_id", ""))
    try:
        store = _store_for(story_id)
    except HTTPException:
        return
    starting_chapter = int(job.get("starting_chapter") or 0)
    current_chapter = int(store.summary().get("current_chapter") or 0)
    if current_chapter > starting_chapter:
        job.update(
            {
                "status": "completed",
                "progress": "generation completed",
                "chapter_number": current_chapter,
                "error": "",
                "updated_at": _now_iso(),
            }
        )
        if _active_file_generation_jobs.get(story_id) == job.get("job_id"):
            _active_file_generation_jobs.pop(story_id, None)
        return

    updated_at = _parse_iso_datetime(job.get("updated_at"))
    if updated_at is None:
        return
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - updated_at).total_seconds() > FILE_GENERATION_JOB_STALE_SECONDS:
        job.update(
            {
                "status": "failed",
                "progress": "generation timed out",
                "error": "file_generation_job_stale_timeout",
                "updated_at": _now_iso(),
            }
        )
        if _active_file_generation_jobs.get(story_id) == job.get("job_id"):
            _active_file_generation_jobs.pop(story_id, None)


def _run_file_generation_job(
    job_id: str,
    project_id: str,
    *,
    chapter_number: int | None = None,
    variant: str | None = None,
    guidance: str | None = None,
    chapter_direction_id: str | None = None,
) -> None:
    def report_progress(message: str) -> None:
        _update_file_generation_job(job_id, status="running", progress=message)

    story_id = _file_id(_strip_file_prefix(project_id))
    report_progress("generation started")
    try:
        store = _store_for(project_id)
        with generation_progress(report_progress):
            generated = (
                store.regenerate_chapter(chapter_number, variant=variant, guidance=guidance)
                if isinstance(chapter_number, int) and chapter_number > 0
                else store.generate_next_chapter(chapter_direction_id=chapter_direction_id)
            )
    except Exception as exc:  # pragma: no cover - background safety net
        _update_file_generation_job(job_id, status="failed", progress="generation failed", error=str(exc))
    else:
        chapter_number = generated.get("chapter_number") if isinstance(generated, dict) else None
        _update_file_generation_job(
            job_id,
            status="completed",
            progress="generation completed",
            chapter_number=chapter_number if isinstance(chapter_number, int) else None,
            error="",
        )
    finally:
        with _file_generation_jobs_lock:
            if _active_file_generation_jobs.get(story_id) == job_id:
                _active_file_generation_jobs.pop(story_id, None)


def _display_title(project: dict[str, Any], state: dict[str, Any], summary: dict[str, Any], fallback: str) -> str:
    title_candidates = [
        project.get("title"),
        project.get("novel_title"),
        project.get("book_title"),
        project.get("name"),
        summary.get("title"),
        summary.get("novel_title"),
        state.get("title"),
        state.get("novel_title"),
        state.get("book_title"),
    ]
    state_project = state.get("project")
    if isinstance(state_project, dict):
        title_candidates.extend(
            [
                state_project.get("title"),
                state_project.get("novel_title"),
                state_project.get("book_title"),
                state_project.get("name"),
            ]
        )
    for value in title_candidates:
        title = str(value or "").strip()
        if title and len(title) <= 40 and "，" not in title and "。" not in title:
            return title

    for fact in state.get("world_facts") or []:
        text = str(fact or "")
        match = re.search(r"世界摘要：?《([^》]+)》", text)
        if match:
            return match.group(1).strip()
        match = re.search(r"《([^》]+)》故事圣经", text)
        if match:
            return match.group(1).strip()

    title = str(project.get("title") or summary.get("title") or "").strip()
    if title and len(title) <= 24 and "，" not in title and "。" not in title:
        return title
    return fallback


def _project_payload(store: FileProjectStore) -> dict[str, Any]:
    project = store.project()
    state = store.state()
    summary = store.summary()
    current_chapter = int(summary.get("current_chapter") or 0)
    title = _display_title(project, state, summary, store.root.name)
    return {
        "project_id": _public_project_id(store),
        "title": title,
        "source_path": str(store.root),
        "seed_outline": str(project.get("seed_outline") or state.get("outline") or ""),
        "world_summary": str(project.get("world_summary") or state.get("outline") or ""),
        "current_focus": str(project.get("current_focus") or ""),
        "author_constraints": project.get("author_constraints") or state.get("author_constraints") or [],
        "world_blueprint": project.get("world_blueprint") or state.get("world_blueprint") or {},
        "character_profiles": project.get("character_profiles") or [],
        "relationship_graph": project.get("relationship_graph") or [],
        "enabled_skill_ids": project.get("enabled_skill_ids") or state.get("enabled_skill_ids") or [],
        "status": project.get("status") or "simulating",
        "pipeline_stage": project.get("pipeline_stage") or ("simulating" if current_chapter else "environment_ready"),
        "active_story_id": _story_id_for(store),
        "branches": [
            {
                "story_id": _story_id_for(store),
                "current_chapter": current_chapter,
                "parent_story_id": None,
                "branched_from_chapter": None,
            }
        ],
        "storage_source": "file",
    }


def _story_payload(store: FileProjectStore) -> dict[str, Any]:
    state = store.state()
    history = []
    for number in store.chapter_numbers():
        chapter = dict(store.chapter(number))
        quality = dict(chapter.get("quality_report") or {})
        quality["simplified_review"] = build_simplified_review(quality)
        chapter["quality_report"] = quality
        history.append(chapter)
    current_chapter = int(state.get("current_chapter") or (history[-1].get("chapter_number") if history else 0) or 0)
    return {
        "story_id": _story_id_for(store),
        "outline": str(state.get("outline") or store.project().get("seed_outline") or ""),
        "genre": str(state.get("genre") or ""),
        "style": str(state.get("style") or ""),
        "current_chapter": current_chapter,
        "agent_settings": state.get("agent_settings") or AgentSettings().model_dump(),
        "agent_runtime": state.get("agent_runtime") or AgentRuntimeState().model_dump(),
        "author_constraints": state.get("author_constraints") or [],
        "writing_lessons": state.get("writing_lessons") or [],
        "world_facts": state.get("world_facts") or [],
        "characters": state.get("characters") or [],
        "history": history,
        "parent_story_id": None,
        "branched_from_chapter": None,
        "storage_source": "file",
    }


def _summary_payload(store: FileProjectStore) -> dict[str, Any]:
    project = _project_payload(store)
    return {
        "project_id": project["project_id"],
        "title": project["title"],
        "status": project["status"],
        "pipeline_stage": project["pipeline_stage"],
        "active_story_id": project["active_story_id"],
        "current_chapter": store.summary().get("current_chapter") or 0,
        "source_path": project["source_path"],
        "storage_source": "file",
    }


def init_file_project_routes() -> APIRouter:
    @router.post("/book-dissection/reference")
    def dissect_book_reference(payload: BookDissectionReferenceRequest) -> dict[str, Any]:
        try:
            return dissect_reference_text(payload.text, genre=payload.genre, focus=payload.focus)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/file-projects")
    def list_file_projects() -> list[dict[str, Any]]:
        return [_summary_payload(store) for store in _stores()]

    @router.post("/file-projects", status_code=201)
    def create_new_file_project(payload: FileProjectCreateSpec) -> dict[str, Any]:
        try:
            created = create_file_project(_export_root(), payload)
        except (ValueError, FileExistsError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {**_project_payload(FileProjectStore(created.root)), "next_path": created.next_path}

    @router.get("/file-projects/{project_id}")
    def get_file_project(project_id: str) -> dict[str, Any]:
        return _project_payload(_store_for(project_id))

    @router.get("/file-projects/{project_id}/opening-directions")
    def get_opening_directions(project_id: str) -> dict[str, Any]:
        return _store_for(project_id).opening_setup()

    @router.post("/file-projects/{project_id}/opening-directions")
    def generate_opening_directions(
        project_id: str,
        payload: OpeningDirectionGenerationRequest | None = None,
    ) -> dict[str, Any]:
        try:
            guidance = payload.guidance if payload is not None else ""
            return _store_for(project_id).generate_opening_directions(
                opening_direction_generator,
                guidance=guidance,
            )
        except ValueError as exc:
            status_code = 502 if str(exc) == "opening_direction_generation_failed" else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    @router.post("/file-projects/{project_id}/opening-directions/{direction_id}/select")
    def select_opening_direction(project_id: str, direction_id: str) -> dict[str, Any]:
        try:
            return _store_for(project_id).select_opening_direction(direction_id)
        except KeyError as exc:
            detail = str(exc.args[0]) if exc.args else "direction_not_found"
            raise HTTPException(status_code=404, detail=detail) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/file-projects/{project_id}/outline")
    def get_file_project_outline(project_id: str) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            return store.project_outline()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.put("/file-projects/{project_id}/outline")
    def update_file_project_outline(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            return store.update_project_outline(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/file-projects/{project_id}/characters")
    def get_file_project_characters(project_id: str) -> list[dict[str, Any]]:
        store = _store_for(project_id)
        return [item for item in store.state().get("characters", []) if isinstance(item, dict)]

    @router.put("/file-projects/{project_id}/characters/{character_name}")
    def update_file_project_character(project_id: str, character_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            return store.update_character(character_name, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/file-projects/{project_id}/characters/{character_name}/complete-portrait")
    def complete_file_project_character_portrait(project_id: str, character_name: str) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            return store.complete_character_portrait(character_name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.put("/file-projects/{project_id}")
    def update_file_project(project_id: str, payload: FileProjectUpdateRequest) -> dict[str, Any]:
        store = _store_for(project_id)
        store.update_project(payload.model_dump(exclude_unset=True))
        return _project_payload(store)

    @router.get("/file-projects/{project_id}/writing-packet")
    def get_file_project_writing_packet(project_id: str, chapter_number: int | None = None) -> dict[str, Any]:
        store = _store_for(project_id)
        return store.writing_packet(chapter_number)

    @router.get("/file-projects/{project_id}/prompt-preview")
    def get_file_project_prompt_preview(project_id: str, chapter_number: int | None = None) -> dict[str, Any]:
        store = _store_for(project_id)
        return store.prompt_preview(chapter_number)

    @router.post("/file-projects/{project_id}/book-dissection/chapter")
    def dissect_file_project_chapter(project_id: str, payload: BookDissectionChapterRequest) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            chapter = store.chapter(payload.chapter_number)
            return diagnose_project_chapter({"project": store.project(), "state": store.state()}, chapter)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/file-projects/{project_id}/generate-next")
    def generate_file_project_next(project_id: str, payload: FileProjectGenerateNextRequest | None = None) -> dict[str, Any]:
        store = _store_for(project_id)
        generated = store.generate_next_chapter(chapter_direction_id=payload.chapter_direction_id if payload else None)
        return {
            "schema_version": "file-project-generate-next-response/v1",
            "project": _project_payload(store),
            "story": _story_payload(store),
            "generated": generated,
        }

    @router.post("/file-projects/{project_id}/regenerate-chapter")
    def regenerate_file_project_chapter(project_id: str, payload: FileProjectRegenerateRequest) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            generated = store.regenerate_chapter(payload.chapter_number, variant=payload.variant, guidance=payload.guidance)
        except ValueError as exc:
            _raise_file_project_error(exc)
        return {
            "schema_version": "file-project-regenerate-response/v1",
            "project": _project_payload(store),
            "story": _story_payload(store),
            "generated": generated,
        }

    @router.post("/file-projects/{project_id}/generation-jobs")
    def start_file_generation_job(project_id: str, payload: FileProjectGenerationJobRequest | None = None) -> dict[str, object]:
        store = _store_for(project_id)
        story_id = _story_id_for(store)
        target_chapter = payload.chapter_number if payload and isinstance(payload.chapter_number, int) else None
        variant = payload.variant if payload else None
        guidance = payload.guidance if payload else None
        chapter_direction_id = payload.chapter_direction_id if payload else None
        with _file_generation_jobs_lock:
            active_job_id = _active_file_generation_jobs.get(story_id)
            if active_job_id:
                active_job = _file_generation_jobs.get(active_job_id)
                if active_job:
                    _reconcile_file_generation_job_locked(active_job)
                if active_job and active_job.get("status") in {"queued", "running"}:
                    return _file_generation_job_response(active_job)

            now = _now_iso()
            job_id = f"fgj-{uuid4().hex[:12]}"
            job: dict[str, object] = {
                "job_id": job_id,
                "story_id": story_id,
                "project_id": _public_project_id(store),
                "status": "queued",
                "progress": "queued",
                "chapter_number": None,
                "target_chapter": target_chapter,
                "variant": variant or "",
                "guidance": guidance or "",
                "chapter_direction_id": chapter_direction_id or "",
                "starting_chapter": int(store.summary().get("current_chapter") or 0),
                "error": "",
                "created_at": now,
                "updated_at": now,
            }
            _file_generation_jobs[job_id] = job
            _active_file_generation_jobs[story_id] = job_id
            response = _file_generation_job_response(job)

        job_kwargs: dict[str, object] = {
            "chapter_number": target_chapter,
            "variant": variant,
            "guidance": guidance,
        }
        if chapter_direction_id:
            job_kwargs["chapter_direction_id"] = chapter_direction_id
        _file_generation_executor.submit(_run_file_generation_job, job_id, project_id, **job_kwargs)
        return response

    @router.get("/file-projects/{project_id}/generation-jobs/{job_id}")
    def get_file_generation_job(project_id: str, job_id: str) -> dict[str, object]:
        store = _store_for(project_id)
        story_id = _story_id_for(store)
        with _file_generation_jobs_lock:
            job = _file_generation_jobs.get(job_id)
            if job is None or job.get("story_id") != story_id:
                raise HTTPException(status_code=404, detail="file_generation_job_not_found")
            _reconcile_file_generation_job_locked(job)
            return _file_generation_job_response(job)

    @router.get("/file-stories/{story_id}")
    def get_file_story(story_id: str) -> dict[str, Any]:
        wanted = _strip_file_prefix(story_id)
        for store in _stores():
            if _strip_file_prefix(_story_id_for(store)) == wanted:
                return _story_payload(store)
        raise HTTPException(status_code=404, detail="file_story_not_found")

    return router
