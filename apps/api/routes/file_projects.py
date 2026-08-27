from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import re
import shutil
from pathlib import Path
from threading import Lock
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Path as ApiPath, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.story_core.book_dissection import diagnose_project_chapter, dissect_reference_text
from packages.story_core.file_project_creation import FileProjectCreateSpec, create_file_project
from packages.story_core.generation_progress import generation_progress
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.cover_image_provider import CoverImageError, OpenAICoverImageProvider
from packages.story_core.cover_renderer import CoverRenderError, normalize_cover_title, render_cover
from packages.story_core.skill_packs import resolve_enabled_skill_ids, resolve_enabled_skill_module_ids
from packages.story_core.models import (
    AgentRuntimeState,
    AgentSettings,
    ForeshadowingState,
    ForeshadowingStatus,
    NovelProject,
)
from packages.story_core.model_gateway import RuntimeModelGateway
from packages.story_core.opening_directions import LLMOpeningDirectionGenerator
from packages.story_core.outline_planning_generation import LLMOutlinePlanningGenerator
from packages.story_core.simplified_review import build_simplified_review, user_facing_generation_error
from packages.story_core.publishing_assets import (
    CoverPromptGenerator,
    FanqieSynopsis,
    SynopsisGenerator,
    build_publishing_context,
)
from packages.story_core.runtime_config import (
    ImageRuntimeConfigurationError,
    resolve_image_runtime,
    resolve_stage_runtime,
)
from packages.story_core.world_enrichment import WorldEnrichmentError, enrich_project_world
from packages.story_core.workflow_steps import merge_workflow_step, normalize_workflow_artifact, normalize_workflow_step
from apps.api.services.file_project_lifecycle import (
    FileProjectLifecycleError,
    activate_project,
    archive_project,
    delete_trashed_project,
    restore_project,
    trash_project,
)
from apps.api.services.continuous_generation import (
    ACTIVE_STATUSES as CONTINUOUS_ACTIVE_STATUSES,
    SAFE_RECOVERY_PHASES,
    ContinuousGenerationJobStore,
    ContinuousGenerationRunner,
)
from apps.api.routes.file_project_candidates import register_file_project_candidate_routes
from apps.api.routes.file_project_outline import register_file_project_outline_routes


router = APIRouter()
opening_direction_generator = LLMOpeningDirectionGenerator()
outline_planning_generator = LLMOutlinePlanningGenerator()
synopsis_generator = SynopsisGenerator()
cover_prompt_generator = CoverPromptGenerator()
# Kept as an explicit alias/seam for route tests and compatible image providers.
OpenAICompatibleCoverImageProvider = OpenAICoverImageProvider
cover_image_provider = OpenAICompatibleCoverImageProvider()
shuangwen_model_gateway = RuntimeModelGateway()
FILE_ID_PREFIX = "file:"
FILE_GENERATION_JOB_STALE_SECONDS = 15 * 60
FILE_GENERATION_JOB_STEP_LIMIT = 200
_file_generation_executor = ThreadPoolExecutor(max_workers=1)
_file_generation_jobs: dict[str, dict[str, object]] = {}
_active_file_generation_jobs: dict[str, str] = {}
_file_generation_jobs_lock = Lock()
_world_build_executor = ThreadPoolExecutor(max_workers=1)
_world_build_jobs: dict[str, dict[str, object]] = {}
_active_world_build_jobs: dict[str, str] = {}
_world_build_jobs_lock = Lock()
_continuous_generation_executor = ThreadPoolExecutor(max_workers=1)
_active_continuous_generation_jobs: dict[str, str] = {}
# Plan rule: "Add a dedicated single-worker executor" for the
# continuation bootstrap. Body generation and bootstrap share
# a single worker to keep the disk state coherent.
_continuation_bootstrap_executor = ThreadPoolExecutor(max_workers=1)
_continuation_bootstrap_checkpoints: dict[str, dict[str, object]] = {}
_continuation_bootstrap_lock = Lock()


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
    operation: Literal["polish", "expand"] | None = None
    variant: str | None = None
    guidance: str | None = None
    chapter_direction_id: str | None = None


class FileProjectContinuousGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    count: Literal[2, 5, 10, 20] = 5


class FileProjectUpdateRequest(BaseModel):
    title: str | None = None
    game_title: str | None = None
    seed_outline: str | None = None
    world_summary: str | None = None
    current_focus: str | None = None
    author_constraints: list[str] | None = None
    world_blueprint: dict[str, Any] | None = None
    character_profiles: list[dict[str, Any]] | None = None
    relationship_graph: list[dict[str, Any]] | None = None
    enabled_skill_ids: list[str] | None = None
    enabled_skill_module_ids: list[str] | None = None
    status: str | None = None
    pipeline_stage: str | None = None


class BookDissectionReferenceRequest(BaseModel):
    text: str
    genre: str = ""
    focus: str = ""


class BookDissectionChapterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_number: int | None = None
    body: str | None = Field(default=None, max_length=200_000)


class PromptTemplateUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)


class PublishingGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    guidance: str = Field(default="", max_length=1000)

    @field_validator("guidance", mode="before")
    @classmethod
    def trim_guidance(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class SynopsisUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tags: list[Annotated[str, Field(strict=True, min_length=1, max_length=32)]] = Field(min_length=4, max_length=8)
    body: str = Field(min_length=1, max_length=2000)

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Any) -> Any:
        if not isinstance(value, list) or any(not isinstance(tag, str) for tag in value):
            raise ValueError("tags_must_be_list_of_strings")
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in value:
            clean = tag.strip()
            if not clean or clean in seen:
                continue
            normalized.append(clean)
            seen.add(clean)
        if not 4 <= len(normalized) <= 8:
            raise ValueError("tags_must_contain_4_to_8_unique_values")
        return normalized

    @field_validator("body", mode="before")
    @classmethod
    def trim_body(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class CoverPromptUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    prompt: str = Field(min_length=1, max_length=2000)

    @field_validator("prompt", mode="before")
    @classmethod
    def trim_prompt(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class ForeshadowingLedgerItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    text: str
    first_chapter: int = Field(ge=0)
    last_touched_chapter: int | None = Field(default=None, ge=0)
    status: ForeshadowingStatus = "open"
    payoff_plan: str = ""
    resolved_chapter: int | None = Field(default=None, ge=0)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("foreshadowing_text_required")
        return normalized

    @model_validator(mode="after")
    def validate_resolution(self) -> "ForeshadowingLedgerItemRequest":
        last_touched_chapter = (
            self.last_touched_chapter
            if self.last_touched_chapter is not None
            else self.first_chapter
        )
        if last_touched_chapter < self.first_chapter:
            raise ValueError("last_touched_chapter_before_first_chapter")
        if (
            self.resolved_chapter is not None
            and self.resolved_chapter < last_touched_chapter
        ):
            raise ValueError("resolved_chapter_before_last_touched_chapter")
        if self.status == "resolved":
            if self.resolved_chapter is None:
                raise ValueError("resolved_chapter_required")
        elif self.status in {"open", "reinforced"} and self.resolved_chapter is not None:
            raise ValueError("unresolved_status_has_resolved_chapter")
        return self

    def to_domain(self) -> ForeshadowingState:
        payload = self.model_dump()
        if payload["last_touched_chapter"] is None:
            payload["last_touched_chapter"] = self.first_chapter
        return ForeshadowingState.model_validate(payload)


class ForeshadowingLedgerUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ForeshadowingLedgerItemRequest]
    base_version: str | None = None


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


def _file_generation_job_log_dir(store: FileProjectStore) -> Path:
    return store.story_system_dir / "generation-jobs"


def _world_build_job_log_dir(store: FileProjectStore) -> Path:
    return store.story_system_dir / "world-build-jobs"


def _persist_world_build_job(job: dict[str, object]) -> None:
    project_root = str(job.get("_project_root", "")).strip()
    job_id = str(job.get("job_id", "")).strip()
    if not project_root or not job_id:
        return
    log_dir = Path(project_root) / ".story-system" / "world-build-jobs"
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in job.items() if not str(key).startswith("_")}
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    for target in (log_dir / f"{job_id}.json", log_dir / "latest.json"):
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(target)


def _load_world_build_job(store: FileProjectStore, job_id: str | None = None) -> dict[str, object] | None:
    filename = f"{job_id}.json" if job_id else "latest.json"
    path = _world_build_job_log_dir(store) / filename
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not str(payload.get("job_id", "")).strip():
        return None
    payload["_project_root"] = str(store.root)
    return _reconcile_world_build_job(store, payload)


def _project_world_revision(store: FileProjectStore) -> str:
    """Hash the project's world-bearing state for change detection.

    The store has no built-in monotonic revision, so derive one from the
    fields the world-build job is allowed to overwrite.  An author who
    manually edits the project between job start and final persistence
    gets a different hash and the job is marked conflicted.
    """

    project = store.project() if hasattr(store, "project") else {}
    if not isinstance(project, dict):
        return ""
    payload = {
        "project_id": str(project.get("project_id", "")).strip(),
        "title": str(project.get("title", "")).strip(),
        "world_summary": str(project.get("world_summary", "")).strip(),
        "current_focus": str(project.get("current_focus", "")).strip(),
        "world_blueprint": project.get("world_blueprint") or {},
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return sha256(serialized.encode("utf-8")).hexdigest()


_WORLD_BUILD_ERROR_USER_MESSAGES: dict[str, str] = {
    "world_build_provider_error": "模型服务暂不可用，请稍后重试。",
    "world_build_validation_error": "本次结果未能通过校验，请重试。",
    "world_build_module_incomplete": "模型返回的设定不完整，请重试。",
    "world_build_unknown": "世界观补全失败，请稍后重试。",
}


def _world_build_error_code(exc: BaseException) -> str:
    message = str(exc or "")
    lowered = message.lower()
    if "world_build_module_incomplete" in message:
        return "world_build_module_incomplete"
    if "world_build_module_validation_failed" in message:
        return "world_build_validation_error"
    if any(
        marker in lowered
        for marker in (
            "http",
            "https://",
            "://",
            "api key",
            "api_key",
            "unauthorized",
            "timeout",
            "rate limit",
            "rate_limit",
        )
    ):
        return "world_build_provider_error"
    return "world_build_unknown"


def _world_build_user_message(code: str) -> str:
    return _WORLD_BUILD_ERROR_USER_MESSAGES.get(
        code, _WORLD_BUILD_ERROR_USER_MESSAGES["world_build_unknown"]
    )


def _sanitize_world_build_error_detail(exc: BaseException) -> str:
    """Return the user-facing message only — never the raw code.

    The machine-readable code lives in its own ``error_code`` field on the
    job record so the browser can render plain Chinese without leaking the
    internal ``world_build_*`` taxonomy.
    """
    code = _world_build_error_code(exc)
    return _world_build_user_message(code)


def _reconcile_world_build_job(
    store: FileProjectStore, job: dict[str, object] | None
) -> dict[str, object] | None:
    """Mark a persisted job that is still queued/running after a restart.

    The in-memory executor and active-job map are process-local.  If the
    server restarts, a job that was running becomes a stuck record on disk.
    This helper turns it into ``interrupted`` so the UI can ask the author
    to retry instead of showing infinite progress.
    """

    if job is None:
        return None
    if str(job.get("status")) not in {"queued", "running"}:
        return job
    recovered = {
        **job,
        "status": "interrupted",
        "progress": "服务已重启，请重新开始补全",
        "active_module_status": "interrupted",
        "updated_at": _now_iso(),
    }
    project_root = str(recovered.get("_project_root") or store.root)
    with _world_build_jobs_lock:
        _active_world_build_jobs.pop(_strip_file_prefix(str(recovered.get("project_id", ""))), None)
        _world_build_jobs.pop(str(recovered.get("job_id", "")).strip(), None)
    _persist_world_build_job({**recovered, "_project_root": project_root})
    return recovered


def _has_active_world_build_job(project_id: str) -> bool:
    normalized = _strip_file_prefix(project_id)
    with _world_build_jobs_lock:
        job_id = _active_world_build_jobs.get(normalized)
        if not job_id:
            return False
        job = _world_build_jobs.get(job_id)
        if job is None:
            _active_world_build_jobs.pop(normalized, None)
            return False
        return str(job.get("status")) in {"queued", "running"}


def _check_world_build_conflict(
    store: FileProjectStore, job_id: str
) -> bool:
    """Mark the job conflicted when the project's world data has changed.

    The author may hand-edit ``world_blueprint`` between job start and
    final persistence.  When that happens the job must not silently
    overwrite the author's edits; the completed artifacts are preserved
    in the job record but ``world_blueprint`` is left untouched.
    """

    with _world_build_jobs_lock:
        job = _world_build_jobs.get(job_id)
    if job is None:
        return False
    stored_revision = str(job.get("project_revision") or "")
    if not stored_revision:
        return False
    current_revision = _project_world_revision(store)
    if stored_revision == current_revision:
        return False
    _update_world_build_job(
        job_id,
        status="conflicted",
        progress="世界观已被手动修改，请重新开始补全",
        active_module_status="conflicted",
        error_code="world_build_conflict",
        error="世界观已被手动修改，请重新开始补全。",
        project_revision=current_revision,
    )
    return True


def _world_build_job_response(job: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in job.items()
        if not str(key).startswith("_")
    }


def _update_world_build_job(job_id: str, **updates: object) -> None:
    with _world_build_jobs_lock:
        job = _world_build_jobs.get(job_id)
        if job is None:
            return
        job.update(updates)
        job["updated_at"] = _now_iso()
        _persist_world_build_job(job)


def _persist_partial_world_build_artifact(
    store: FileProjectStore,
    artifact: object,
    *,
    job_id: str | None = None,
) -> bool:
    if not isinstance(artifact, dict):
        return True
    module_id = str(artifact.get("module_id", "")).strip()
    if not module_id:
        return True
    if job_id and _check_world_build_conflict(store, job_id):
        return False
    current = store.project()
    blueprint = current.get("world_blueprint") if isinstance(current.get("world_blueprint"), dict) else {}
    artifacts = blueprint.get("world_build_artifacts") if isinstance(blueprint.get("world_build_artifacts"), list) else []
    next_artifacts = [
        item for item in artifacts
        if not isinstance(item, dict) or str(item.get("module_id", "")).strip() != module_id
    ]
    next_artifacts.append(artifact)
    next_blueprint = {**blueprint, "world_build_artifacts": next_artifacts}
    store.update_project({"world_blueprint": next_blueprint}, replace_world_blueprint=True)
    return True


def _run_world_build_job(job_id: str, project_id: str) -> None:
    store = _store_for(project_id)

    def report_progress(event: dict[str, object]) -> None:
        message = str(event.get("message", "正在构建世界观")).strip()
        module_id = str(event.get("module_id", "")).strip()
        module_status = str(event.get("status", "running")).strip()
        artifact = event.get("artifact")
        _update_world_build_job(
            job_id,
            status="running",
            progress=message,
            active_module_id=module_id,
            active_module_title=str(event.get("title", "")).strip(),
            active_module_status=module_status,
        )
        if artifact is not None:
            _persist_partial_world_build_artifact(store, artifact, job_id=job_id)

    try:
        if _check_world_build_conflict(store, job_id):
            return
        project_payload = {
            **store.project(),
            "project_id": _public_project_id(store),
            "source_path": str(store.root),
            "active_story_id": _story_id_for(store),
            "story_core_context": store.story_core_context("world"),
        }
        enriched = enrich_project_world(
            NovelProject.model_validate(project_payload),
            progress_callback=report_progress,
        )
        if _check_world_build_conflict(store, job_id):
            return
        enriched_payload = enriched.model_dump(mode="json")
        store.update_project(
            {
                key: value
                for key, value in enriched_payload.items()
                if key in {
                    "title", "world_summary", "current_focus", "author_constraints",
                    "world_blueprint", "character_profiles", "relationship_graph",
                    "enabled_skill_ids", "enabled_skill_module_ids", "status",
                }
            }
            | {"pipeline_stage": "environment_ready"},
            replace_world_blueprint=True,
        )
    except Exception as exc:  # pragma: no cover - background safety net
        code = _world_build_error_code(exc)
        _update_world_build_job(
            job_id,
            status="failed",
            progress=_world_build_user_message(code),
            error_code=code,
            error=_sanitize_world_build_error_detail(exc),
        )
    else:
        _update_world_build_job(
            job_id,
            status="completed",
            progress="世界观构建完成",
            error="",
            active_module_id="",
            active_module_title="",
            active_module_status="done",
        )
    finally:
        with _world_build_jobs_lock:
            _active_world_build_jobs.pop(_strip_file_prefix(project_id), None)


def _start_world_build_job(project_id: str) -> dict[str, object]:
    store = _store_for(project_id)
    normalized_project_id = _strip_file_prefix(project_id)
    with _world_build_jobs_lock:
        active_job_id = _active_world_build_jobs.get(normalized_project_id)
        if active_job_id:
            active = _world_build_jobs.get(active_job_id)
            if active is not None and str(active.get("status")) in {"queued", "running"}:
                return _world_build_job_response(active)
        now = _now_iso()
        job_id = f"wbg-{uuid4().hex}"
        job: dict[str, object] = {
            "schema_version": "world-build-job/v1",
            "job_id": job_id,
            "project_id": _public_project_id(store),
            "status": "queued",
            "progress": "等待构建核心规则",
            "active_module_id": "core_rules",
            "active_module_title": "核心规则",
            "active_module_status": "queued",
            "error": "",
            "created_at": now,
            "updated_at": now,
            "project_revision": _project_world_revision(store),
            "_project_root": str(store.root),
        }
        _world_build_jobs[job_id] = job
        _active_world_build_jobs[normalized_project_id] = job_id
        _persist_world_build_job(job)
    _world_build_executor.submit(_run_world_build_job, job_id, project_id)
    return _world_build_job_response(job)


def _persist_file_generation_job(job: dict[str, object]) -> None:
    project_root = str(job.get("_project_root", "")).strip()
    job_id = str(job.get("job_id", "")).strip()
    if not project_root or not job_id:
        return
    log_dir = Path(project_root) / ".story-system" / "generation-jobs"
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in job.items() if not str(key).startswith("_")}
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    for target in (log_dir / f"{job_id}.json", log_dir / "latest.json"):
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        temporary.write_text(serialized, encoding="utf-8")
        temporary.replace(target)


def _load_file_generation_job(store: FileProjectStore, job_id: str | None = None) -> dict[str, object] | None:
    filename = f"{job_id}.json" if job_id else "latest.json"
    path = _file_generation_job_log_dir(store) / filename
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not str(payload.get("job_id", "")).strip():
        return None
    payload["_project_root"] = str(store.root)
    return payload


def _list_file_generation_jobs(store: FileProjectStore, *, limit: int = 30) -> list[dict[str, object]]:
    jobs: list[dict[str, object]] = []
    log_dir = _file_generation_job_log_dir(store)
    try:
        paths = list(log_dir.glob("fgj-*.json"))
    except OSError:
        return jobs
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not str(payload.get("job_id", "")).strip():
            continue
        jobs.append(payload)
    jobs.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
    return jobs[: max(1, min(limit, 100))]


def _sanitize_file_generation_step_item(value: object) -> dict[str, object]:
    return normalize_workflow_step(value)


def _normalize_file_generation_step_artifact(value: object) -> dict[str, object] | list[object] | str | int | float | bool | None:
    return normalize_workflow_artifact(value)


def _infer_file_generation_source(message: str, stage: str | None = None) -> str:
    lowered = message.lower()
    if stage == "review":
        return "reviewer"
    if any(keyword in lowered for keyword in ["model", "llm", "timeout", "request", "response"]):
        return "llm"
    if any(keyword in message for keyword in ["璁板繂", "鍥炲啓", "璐︽湰", "鍐欏洖"]):
        return "memory"
    if any(keyword in message for keyword in ["瀹＄", "鏀圭", "璐ㄩ噺", "鍘嬬缉", "鎻愬彇"]):
        return "reviewer"
    if any(keyword in message for keyword in ["鍐欎綔", "姝ｆ枃", "鍒嗘", "鎵╁啓", "绔犺妭"]):
        return "writer"
    return "orchestrator"


def _infer_file_generation_stage(message: str) -> str:
    lowered = message.lower()
    if "review" in lowered or "瀹＄" in message:
        return "review"
    if "planning" in lowered or "plan" in lowered or "璁″垝" in message:
        return "director"
    if "memory" in lowered or "璁板繂" in message:
        return "memory"
    if any(keyword in message for keyword in ["姝ｆ枃", "鍐欎綔", "绔犺妭", "妯″瀷", "璐ㄩ噺"]):
        return "writer"
    return "orchestrator"


def _user_facing_generation_error(exc: Exception) -> str:
    return user_facing_generation_error(exc)


def _append_file_generation_job_step(
    job: dict[str, object],
    message: str,
    *,
    status: str = "running",
    stage: str | None = None,
    source: str | None = None,
    artifact: object = None,
) -> None:
    cleaned = str(message or "").strip()
    if not cleaned:
        return
    steps = job.get("steps")
    if not isinstance(steps, list):
        steps = []
        job["steps"] = steps
    normalized_status = "running" if status not in {"running", "done", "error", "queued"} else status
    normalized = {"message": cleaned, "status": normalized_status, "stage": stage, "source": source}
    if artifact is not None:
        normalized["artifact"] = artifact
    merge_workflow_step(steps, normalized)
    if len(steps) > FILE_GENERATION_JOB_STEP_LIMIT:
        steps.pop(0)
    _persist_file_generation_job(job)


def _normalise_file_generation_job_steps(job: dict[str, object]) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    for value in job.get("steps", []):
        clean = _sanitize_file_generation_step_item(value)
        if not clean:
            continue
        raw_artifact = value.get("artifact") if isinstance(value, dict) else None
        if raw_artifact is not None:
            normalized_artifact = _normalize_file_generation_step_artifact(raw_artifact)
            if normalized_artifact is not None:
                clean["artifact"] = normalized_artifact
        steps.append(clean)
    if len(steps) != (len(job.get("steps", []) if isinstance(job.get("steps"), list) else [])):
        job["steps"] = steps
    return steps


def _is_hidden_file_project_dir(path: Path) -> bool:
    name = path.name
    return (
        name.startswith((".", "_"))
        or ".backup-" in name
        or ".before-" in name
        or name.endswith(".bak")
        or name.endswith(".backup")
    )


def _stores(*, lifecycle: Literal["active", "archived", "trashed"] | None = None) -> list[FileProjectStore]:
    root = _export_root() / ".trash" if lifecycle == "trashed" else _export_root()
    if not root.exists():
        return []
    stores: list[FileProjectStore] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or _is_hidden_file_project_dir(child):
            continue
        store = FileProjectStore(child)
        if store.exists():
            project_lifecycle = str(store.project().get("project_lifecycle") or "active")
            if lifecycle is None or project_lifecycle == lifecycle:
                stores.append(store)
    return stores


def _store_for(project_id: str) -> FileProjectStore:
    wanted = _strip_file_prefix(project_id)
    if not wanted:
        raise HTTPException(status_code=404, detail="file_project_not_found")

    root = _export_root()
    if root.is_dir():
        direct_root = root / wanted
        if direct_root.exists() and direct_root.is_dir():
            direct_store = FileProjectStore(direct_root)
            if direct_store.exists():
                return direct_store

    for store in _stores():
        if store.root.name == wanted or _strip_file_prefix(_story_id_for(store)) == wanted:
            return store
        project = store.project()
        project_id = str(project.get("project_id") or "")
        if project_id == wanted:
            return store
    raise HTTPException(status_code=404, detail="file_project_not_found")


def _trashed_store_for(project_id: str) -> FileProjectStore:
    wanted = _strip_file_prefix(project_id)
    for store in _stores(lifecycle="trashed"):
        if store.root.name == wanted or _strip_file_prefix(_story_id_for(store)) == wanted:
            return store
        if str(store.project().get("project_id") or "") == wanted:
            return store
    raise HTTPException(status_code=404, detail="file_project_not_found")


def _assert_file_project_lifecycle_mutation_allowed(store: FileProjectStore) -> None:
    story_id = _story_id_for(store)
    project_id = _strip_file_prefix(_public_project_id(store))
    with _file_generation_jobs_lock:
        if _continuous_generation_active_locked(store):
            raise HTTPException(status_code=409, detail="project_generation_in_progress")
        for key in (story_id, project_id, f"file:{project_id}"):
            job_id = _active_file_generation_jobs.get(key)
            job = _file_generation_jobs.get(job_id or "")
            if job and job.get("status") in {"queued", "running"}:
                raise HTTPException(status_code=409, detail="project_generation_in_progress")


def _assert_candidate_mutation_allowed(store: FileProjectStore) -> None:
    with _file_generation_jobs_lock:
        if _continuous_generation_active_locked(store):
            raise HTTPException(status_code=409, detail="project_generation_in_progress")


def _file_project_lifecycle_payload(store: FileProjectStore) -> dict[str, Any]:
    project = store.project()
    return {
        **_project_payload(store),
        "project_lifecycle": str(project.get("project_lifecycle") or "active"),
        "archived_at": str(project.get("archived_at") or ""),
        "trashed_at": str(project.get("trashed_at") or ""),
    }


def _raise_file_project_error(exc: ValueError) -> None:
    detail = str(exc)
    if detail.startswith(
        (
            "chapter_frozen:",
            "next_volume_required:",
            "volume_detail_required:",
            "volume_detail_incomplete:",
        )
    ):
        raise HTTPException(status_code=409, detail=detail) from exc
    raise HTTPException(status_code=400, detail=detail) from exc


def _raise_file_project_lifecycle_error(exc: FileProjectLifecycleError) -> None:
    detail = str(exc)
    status_code = 422 if detail == "project_title_confirmation_mismatch" else 409
    raise HTTPException(status_code=status_code, detail=detail) from exc


def _story_id_for(store: FileProjectStore) -> str:
    project = store.project()
    project_id = str(project.get("project_id") or "").strip()
    if project_id:
        return _file_id(project_id)
    return _file_id(store.root.name)


def _file_generation_job_response(job: dict[str, object]) -> dict[str, object]:
    return {
        "job_id": str(job.get("job_id", "")),
        "story_id": str(job.get("story_id", "")),
        "status": str(job.get("status", "")),
        "progress": str(job.get("progress", "")),
        "chapter_number": job.get("chapter_number") if isinstance(job.get("chapter_number"), int) else None,
        "error": str(job.get("error", "")),
        "steps": _normalise_file_generation_job_steps(job),
        "created_at": str(job.get("created_at", "")),
        "updated_at": str(job.get("updated_at", "")),
    }


def _continuous_generation_job_response(job: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "continuous-generation-job/v1",
        "job_id": str(job.get("job_id", "")),
        "project_id": str(job.get("project_id", "")),
        "story_id": str(job.get("story_id", "")),
        "status": str(job.get("status", "")),
        "phase": str(job.get("phase", "")),
        "requested_count": int(job.get("requested_count") or 0),
        "completed_count": int(job.get("completed_count") or 0),
        "start_chapter": int(job.get("start_chapter") or 0),
        "current_chapter": int(job.get("current_chapter") or 0),
        "completed_chapters": list(job.get("completed_chapters") or []),
        "review_warnings": list(job.get("review_warnings") or []),
        "candidate_id": str(job.get("candidate_id", "")),
        "stop_requested": bool(job.get("stop_requested")),
        "progress": str(job.get("progress", "")),
        "stop_reason": str(job.get("stop_reason", "")),
        "error": str(job.get("error", "")),
        "created_at": str(job.get("created_at", "")),
        "updated_at": str(job.get("updated_at", "")),
    }


def _active_job_for_story(
    active_jobs: dict[str, str],
    story_id: str,
) -> str | None:
    plain_id = _strip_file_prefix(story_id)
    return active_jobs.get(story_id) or active_jobs.get(plain_id) or active_jobs.get(
        _file_id(plain_id)
    )


def _continuous_job_store(store: FileProjectStore) -> ContinuousGenerationJobStore:
    return ContinuousGenerationJobStore(store.root)


def _run_continuous_generation_job(job_id: str, project_id: str) -> None:
    store = _store_for(project_id)
    story_id = _story_id_for(store)
    try:
        ContinuousGenerationRunner().run(
            job_id,
            project_store=store,
            job_store=_continuous_job_store(store),
        )
    finally:
        with _file_generation_jobs_lock:
            if _active_job_for_story(
                _active_continuous_generation_jobs, story_id
            ) == job_id:
                for key in {
                    story_id,
                    _strip_file_prefix(story_id),
                    _file_id(_strip_file_prefix(story_id)),
                }:
                    if _active_continuous_generation_jobs.get(key) == job_id:
                        _active_continuous_generation_jobs.pop(key, None)


def _register_continuous_job(story_id: str, job_id: str) -> None:
    _active_continuous_generation_jobs[story_id] = job_id


def _normal_generation_active_locked(store: FileProjectStore) -> bool:
    story_id = _story_id_for(store)
    active_job_id = _active_job_for_story(_active_file_generation_jobs, story_id)
    if not active_job_id:
        return False
    active_job = _file_generation_jobs.get(active_job_id)
    if active_job is None:
        active_job = _load_file_generation_job(store, active_job_id)
        if active_job is not None:
            _file_generation_jobs[active_job_id] = active_job
    if active_job is None:
        return False
    if isinstance(active_job.get("starting_chapter"), int):
        _reconcile_file_generation_job_locked(active_job, store=store)
    return str(active_job.get("status")) in {"queued", "running"}


def _continuous_generation_active_locked(store: FileProjectStore) -> bool:
    story_id = _story_id_for(store)
    jobs = _continuous_job_store(store)
    job_id = _active_job_for_story(_active_continuous_generation_jobs, story_id)
    job = jobs.load(job_id) if job_id else jobs.load()
    if job is None:
        return False
    if not job_id:
        job = jobs.reconcile(
            job,
            official_chapter=int(store.summary().get("current_chapter") or 0),
        )
    if str(job.get("status")) in CONTINUOUS_ACTIVE_STATUSES:
        _register_continuous_job(story_id, str(job.get("job_id") or ""))
        return True
    return False


def _update_file_generation_job(job_id: str, **updates: object) -> None:
    with _file_generation_jobs_lock:
        job = _file_generation_jobs.get(job_id)
        if job is None:
            return
        job.update(updates)
        job["updated_at"] = _now_iso()
        _persist_file_generation_job(job)


def _parse_iso_datetime(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _reconcile_file_generation_job_locked(
    job: dict[str, object], *, store: FileProjectStore | None = None
) -> None:
    story_id = str(job.get("story_id", ""))
    if job.get("status") not in {"queued", "running"}:
        return
    if store is not None:
        starting_chapter = int(job.get("starting_chapter") or 0)
        current_chapter = int(store.summary().get("current_chapter") or 0)
        if current_chapter > starting_chapter:
            _append_file_generation_job_step(
                job,
                "生成完成",
                status="done",
                stage="orchestrator",
                source="file-project-route",
                artifact={"reason": "chapter_advanced"},
            )
            job.update(
                {
                    "status": "completed",
                    "progress": "生成完成",
                    "chapter_number": current_chapter,
                    "error": "",
                    "updated_at": _now_iso(),
                }
            )
            _persist_file_generation_job(job)
            story_id = str(job.get("story_id", ""))
            if _active_file_generation_jobs.get(story_id) == job.get("job_id"):
                _active_file_generation_jobs.pop(story_id, None)
            return

    updated_at = _parse_iso_datetime(job.get("updated_at"))
    if updated_at is None:
        return
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - updated_at).total_seconds() > FILE_GENERATION_JOB_STALE_SECONDS:
        _append_file_generation_job_step(
            job,
            "生成超时",
            status="error",
            stage="orchestrator",
            source="file-project-route",
            artifact={"reason": "stale_timeout"},
        )
        job.update(
            {
                "status": "failed",
                "progress": "生成超时",
                "error": "生成超时，请稍后重试。",
                "updated_at": _now_iso(),
            }
        )
        _persist_file_generation_job(job)
        if _active_file_generation_jobs.get(story_id) == job.get("job_id"):
            _active_file_generation_jobs.pop(story_id, None)


def _run_file_generation_job(
    job_id: str,
    project_id: str,
    *,
    chapter_number: int | None = None,
    operation: Literal["polish", "expand"] | None = None,
    variant: str | None = None,
    guidance: str | None = None,
    chapter_direction_id: str | None = None,
) -> None:
    def report_progress(message: str | dict[str, object]) -> None:
        if isinstance(message, dict):
            payload = dict(message)
        else:
            payload = {"message": message}
        display_message = str(payload.get("message", "")).strip()
        if not display_message:
            return
        status = str(payload.get("status", "running")).strip().lower()
        normalized_status = status if status in {"running", "done", "error", "queued"} else "running"
        stage = payload.get("stage")
        if not isinstance(stage, str) or not stage.strip():
            stage = _infer_file_generation_stage(display_message)
        source = payload.get("source")
        if not isinstance(source, str) or not source.strip():
            source = _infer_file_generation_source(display_message, stage)
        artifact = payload.get("artifact")
        _update_file_generation_job(job_id, status=normalized_status, progress=display_message)
        with _file_generation_jobs_lock:
            job = _file_generation_jobs.get(job_id)
        if job is not None:
            _append_file_generation_job_step(
                job,
                display_message,
                status=normalized_status,
                stage=stage,
                source=source,
                artifact=artifact,
            )

    story_id = _file_id(_strip_file_prefix(project_id))
    report_progress(
        {
            "message": "生产任务启动中",
            "status": "running",
            "stage": "orchestrator",
            "source": "file-project-route",
            "artifact": {
                "reason": "execution_started",
                "used_modules": [
                    "story_store",
                    "director",
                    "writer",
                    "memory",
                    "runtime_manager",
                ],
                "inputs": {
                    "project_id": project_id,
                    "chapter_number": chapter_number,
                    "operation": operation or ("regenerate" if chapter_number else "generate"),
                    "variant": variant or "",
                    "guidance": guidance or "",
                    "chapter_direction_id": chapter_direction_id or "",
                },
            },
        }
    )
    try:
        store = _store_for(project_id)
        with generation_progress(report_progress):
            if operation == "polish":
                if not isinstance(chapter_number, int) or chapter_number < 1:
                    raise ValueError("chapter_number_required_for_polish")
                generated = store.polish_chapter(chapter_number)
            elif operation == "expand":
                if not isinstance(chapter_number, int) or chapter_number < 1:
                    raise ValueError("chapter_number_required_for_expansion")
                generated = store.expand_chapter(chapter_number)
            else:
                generated = (
                    store.regenerate_chapter(chapter_number, variant=variant, guidance=guidance, persist=False)
                    if isinstance(chapter_number, int) and chapter_number > 0
                    else store.generate_next_chapter(
                    chapter_direction_id=chapter_direction_id,
                    persist=True,
                    accept_quality_warnings=True,
                )
                )
    except Exception as exc:  # pragma: no cover - background safety net
        friendly_error = _user_facing_generation_error(exc)
        _update_file_generation_job(job_id, status="failed", progress="生成失败", error=friendly_error)
        with _file_generation_jobs_lock:
            job = _file_generation_jobs.get(job_id)
            if job is not None:
                _append_file_generation_job_step(
                    job,
                    f"生产失败：{friendly_error}",
                    status="error",
                    source="file-project-route",
                    artifact={
                        "reason": "generation_exception",
                        "used_modules": ["story_store", "director", "writer", "memory"],
                        "inputs": {
                            "chapter_number": chapter_number,
                            "variant": variant or "",
                            "guidance": guidance or "",
                            "chapter_direction_id": chapter_direction_id or "",
                        },
                        "outputs": {"error": str(exc)},
                    },
                )
    else:
        chapter_number = generated.get("chapter_number") if isinstance(generated, dict) else None
        _update_file_generation_job(
            job_id,
            status="completed",
            progress="生成完成",
            chapter_number=chapter_number if isinstance(chapter_number, int) else None,
            error="",
        )
        with _file_generation_jobs_lock:
            job = _file_generation_jobs.get(job_id)
            if job is not None:
                _append_file_generation_job_step(
                    job,
                    "生产完成",
                    status="done",
                    source="file-project-route",
                    artifact={
                        "reason": "execution_complete",
                        "used_modules": ["story_store", "director", "writer", "memory", "review"],
                        "outputs": {
                            "generated_chapter": chapter_number,
                            "status": "completed",
                        },
                    },
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
        if title and len(title) <= 40:
            return title

    for fact in state.get("world_facts") or []:
        text = str(fact or "")
        match = re.search(r"世界.*?[:：]([^，。；!?！？;:.]*)", text)
        if match:
            return match.group(1).strip()
        match = re.search(r"世界观[:：](.{1,40})", text)
        if match:
            return match.group(1).strip()

    title = str(project.get("title") or summary.get("title") or "").strip()
    if title and len(title) <= 24:
        return title
    return fallback


def _project_payload(store: FileProjectStore) -> dict[str, Any]:
    project = store.project()
    state = store.persisted_state()
    enabled_skill_module_ids = resolve_enabled_skill_module_ids(project, state)
    summary = store.summary()
    current_chapter = int(summary.get("current_chapter") or 0)
    title = _display_title(project, state, summary, store.root.name)
    continuation = project.get("continuation") if isinstance(project.get("continuation"), dict) else {}
    raw_continuation_start = continuation.get("start_after_chapter")
    public_continuation = (
        {"start_after_chapter": raw_continuation_start}
        if isinstance(raw_continuation_start, int)
        and not isinstance(raw_continuation_start, bool)
        and raw_continuation_start >= 1
        else None
    )
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
        "enabled_skill_ids": resolve_enabled_skill_ids(project, state),
        "enabled_skill_module_ids": (
            list(enabled_skill_module_ids)
            if enabled_skill_module_ids is not None
            else []
        ),
        "skill_module_selection_mode": (
            "legacy_all" if enabled_skill_module_ids is None else "explicit"
        ),
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
        "publishing_assets": store.publishing_assets(),
        "continuation": public_continuation,
        "project_lifecycle": str(project.get("project_lifecycle") or "active"),
        "archived_at": str(project.get("archived_at") or ""),
        "trashed_at": str(project.get("trashed_at") or ""),
    }


def _publishing_context_for(store: FileProjectStore):
    opening_setup = store.opening_setup()
    opening_brief = opening_setup.get("brief") if isinstance(opening_setup, dict) else {}
    return build_publishing_context(
        project=store.project(),
        state=store.state(),
        opening_brief=opening_brief if isinstance(opening_brief, dict) else {},
        outline=store.project_outline(),
    )


def _public_synopsis(value: Any) -> dict[str, Any]:
    synopsis = dict(value) if isinstance(value, dict) else {}
    return {
        key: synopsis[key]
        for key in ("tags", "body", "format", "updated_at")
        if key in synopsis
    }


def _publishing_write_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=500, detail="publishing_asset_write_failed")


def _cover_error(exc: Exception) -> HTTPException:
    detail = str(exc)
    if detail == "cover_font_unavailable":
        return HTTPException(status_code=503, detail=detail)
    if detail in {"image_provider_unauthorized", "image_generation_timeout", "unsupported_image_response", "invalid_image_payload", "image_model_unsupported"}:
        return HTTPException(status_code=502, detail=detail)
    return HTTPException(status_code=502, detail="cover_generation_failed")


def _cover_title(store: FileProjectStore) -> str:
    title = str(store.project().get("title") or "").strip()
    if title:
        try:
            return normalize_cover_title(title)
        except CoverRenderError as exc:
            raise ValueError(str(exc)) from exc
    try:
        return normalize_cover_title(_display_title(store.project(), store.state(), store.summary(), store.root.name))
    except CoverRenderError as exc:
        raise ValueError(str(exc)) from exc


def _if_none_match_matches(value: str, etag: str) -> bool:
    """Use RFC weak comparison for GET without accepting malformed substrings."""
    stripped = value.strip()
    if stripped == "*":
        return True
    for raw_tag in value.split(","):
        tag = raw_tag.strip()
        if tag.startswith("W/"):
            tag = tag[2:]
        if len(tag) >= 2 and tag.startswith('"') and tag.endswith('"') and tag == etag:
            return True
    return False


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
        "world_snapshot": state.get("world_snapshot") or {},
        "continuity_facts": state.get("continuity_facts") or [],
        "characters": state.get("characters") or [],
        "history": history,
        "parent_story_id": None,
        "branched_from_chapter": None,
        "storage_source": "file",
    }


def _story_overview_payload(store: FileProjectStore) -> dict[str, Any]:
    overview = store.story_overview_data()
    state = overview["state"]
    project = overview["project"]
    chapters = overview["chapters"]
    current_chapter = int(
        state.get("current_chapter")
        or (chapters[-1].get("chapter_number") if chapters else 0)
        or 0
    )
    return {
        "story_id": _story_id_for(store),
        "outline": str(state.get("outline") or project.get("seed_outline") or ""),
        "genre": str(state.get("genre") or ""),
        "style": str(state.get("style") or ""),
        "current_chapter": current_chapter,
        "agent_settings": state.get("agent_settings") or AgentSettings().model_dump(),
        "agent_runtime": state.get("agent_runtime") or AgentRuntimeState().model_dump(),
        "author_constraints": state.get("author_constraints") or [],
        "writing_lessons": state.get("writing_lessons") or [],
        "world_facts": state.get("world_facts") or [],
        "world_snapshot": state.get("world_snapshot") or {},
        "continuity_facts": state.get("continuity_facts") or [],
        "characters": state.get("characters") or [],
        "chapter_count": len(chapters),
        "total_body_chars": sum(int(chapter.get("body_chars") or 0) for chapter in chapters),
        "chapters": chapters,
        "parent_story_id": None,
        "branched_from_chapter": None,
        "storage_source": "file",
    }


def _file_story_store(story_id: str) -> FileProjectStore:
    wanted = _strip_file_prefix(story_id)
    try:
        store = _store_for(story_id)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="file_story_not_found") from exc
        raise
    if not wanted or _strip_file_prefix(_story_id_for(store)) != wanted:
        raise HTTPException(status_code=404, detail="file_story_not_found")
    return store


def _file_chapter_payload(store: FileProjectStore, chapter_number: int) -> dict[str, Any]:
    try:
        chapter = dict(store.chapter(chapter_number))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"chapter_not_found:{chapter_number}",
        ) from exc
    quality = dict(chapter.get("quality_report") or {})
    quality["simplified_review"] = build_simplified_review(quality)
    chapter["quality_report"] = quality
    chapter.pop("updated_story", None)
    return chapter


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
        "project_lifecycle": project["project_lifecycle"],
        "archived_at": project["archived_at"],
        "trashed_at": project["trashed_at"],
    }


def start_file_generation_job(
    project_id: str,
    payload: FileProjectGenerationJobRequest | None = None,
    *,
    reserved_job_id: str | None = None,
) -> dict[str, object]:
    """Queue generation through the shared file-project job runner."""
    store = _store_for(project_id)
    story_id = _story_id_for(store)
    with _file_generation_jobs_lock:
        if _continuous_generation_active_locked(store):
            raise HTTPException(status_code=409, detail="project_generation_in_progress")
    operation = payload.operation if payload else None
    target_chapter = (
        payload.chapter_number
        if payload and isinstance(payload.chapter_number, int)
        else None
    )
    if operation in {"polish", "expand"} and not (
        isinstance(target_chapter, int) and target_chapter > 0
    ):
        raise HTTPException(
            status_code=422,
            detail="chapter_number_required_for_polish",
        )
    current_chapter = int(store.summary().get("current_chapter") or 0)
    targets_existing_chapter = (
        isinstance(target_chapter, int)
        and target_chapter > 0
        and target_chapter <= current_chapter
    )
    job_operation = (
        "polish"
        if operation in {"polish", "expand"}
        else "regenerate"
        if targets_existing_chapter
        else "generate"
    )
    execution_chapter_number = (
        target_chapter if job_operation in {"polish", "regenerate"} else None
    )
    requires_new_chapter_outline = (
        operation not in {"polish", "expand"} and not targets_existing_chapter
    )
    if target_chapter is None and requires_new_chapter_outline:
        next_chapter = current_chapter + 1
        try:
            store.require_volume_detail_for_prose(next_chapter)
        except ValueError as exc:
            _raise_file_project_error(exc)
    elif (
        requires_new_chapter_outline
        and isinstance(target_chapter, int)
        and target_chapter > 0
    ):
        try:
            store.require_volume_detail_for_prose(target_chapter)
        except ValueError as exc:
            _raise_file_project_error(exc)
    variant = payload.variant if payload else None
    guidance = payload.guidance if payload else None
    chapter_direction_id = payload.chapter_direction_id if payload else None
    submit_loaded_job = False
    with _file_generation_jobs_lock:
        if reserved_job_id:
            reserved = _file_generation_jobs.get(reserved_job_id)
            if reserved is not None:
                return _file_generation_job_response(reserved)
            loaded = _load_file_generation_job(store, reserved_job_id)
            if loaded is not None:
                _file_generation_jobs[reserved_job_id] = loaded
                if loaded.get("status") in {"queued", "running"}:
                    _active_file_generation_jobs[story_id] = reserved_job_id
                    submit_loaded_job = True
                response = _file_generation_job_response(loaded)
                job_id = reserved_job_id
                job_kwargs = {
                    "chapter_number": (
                        loaded.get("target_chapter")
                        if loaded.get("operation") in {"polish", "expand", "regenerate"}
                        else None
                    ),
                    "variant": loaded.get("variant") or None,
                    "guidance": loaded.get("guidance") or None,
                }
                if loaded.get("operation") in {"polish", "expand"}:
                    job_kwargs["operation"] = "polish"
                loaded_direction = loaded.get("chapter_direction_id")
                if loaded_direction:
                    job_kwargs["chapter_direction_id"] = loaded_direction
                if not submit_loaded_job:
                    return response
            else:
                job_kwargs = {}
        active_job_id = _active_file_generation_jobs.get(story_id)
        if not submit_loaded_job and active_job_id:
            active_job = _file_generation_jobs.get(active_job_id)
            if active_job:
                _reconcile_file_generation_job_locked(active_job, store=store)
            if active_job and active_job.get("status") in {"queued", "running"}:
                return _file_generation_job_response(active_job)

        if submit_loaded_job:
            pass
        else:
            now = _now_iso()
            job_id = reserved_job_id or f"fgj-{uuid4().hex[:12]}"
            job: dict[str, object] = {
                "job_id": job_id,
                "story_id": story_id,
                "project_id": _public_project_id(store),
                "status": "queued",
                "progress": "生成已排队",
                "steps": [
                    {
                        "message": "生成已排队",
                        "status": "queued",
                        "stage": "orchestrator",
                        "source": "file-project-route",
                        "artifact": {
                            "reason": "job_context",
                            "used_modules": [
                                "story_store",
                                "director",
                                "writer",
                                "memory",
                                "outline",
                                "character_agent",
                            ],
                            "inputs": {
                                "project_id": _public_project_id(store),
                                "target_chapter": target_chapter,
                                "operation": job_operation,
                                "variant": variant or "",
                                "guidance": guidance or "",
                                "chapter_direction_id": chapter_direction_id or "",
                                "starting_chapter": int(
                                    store.summary().get("current_chapter") or 0
                                ),
                            },
                            "outputs": {
                                "will_run_generate_next": job_operation == "generate",
                                "will_regen": job_operation == "regenerate",
                                "will_polish": job_operation == "polish",
                            },
                        },
                        "at": now,
                    }
                ],
                "chapter_number": None,
                "target_chapter": target_chapter,
                "operation": job_operation,
                "variant": variant or "",
                "guidance": guidance or "",
                "chapter_direction_id": chapter_direction_id or "",
                "starting_chapter": int(store.summary().get("current_chapter") or 0),
                "error": "",
                "created_at": now,
                "updated_at": now,
                "_project_root": str(store.root),
            }
            _file_generation_jobs[job_id] = job
            _active_file_generation_jobs[story_id] = job_id
            _persist_file_generation_job(job)
            response = _file_generation_job_response(job)

    if not submit_loaded_job:
        job_kwargs = {
            "chapter_number": execution_chapter_number,
            "variant": variant,
            "guidance": guidance,
        }
        if operation in {"polish", "expand"}:
            job_kwargs["operation"] = "polish"
        if chapter_direction_id:
            job_kwargs["chapter_direction_id"] = chapter_direction_id
    _file_generation_executor.submit(
        _run_file_generation_job, job_id, project_id, **job_kwargs
    )
    return response


def start_continuous_generation_job(
    project_id: str,
    payload: FileProjectContinuousGenerationRequest,
) -> dict[str, object]:
    store = _store_for(project_id)
    story_id = _story_id_for(store)
    with _file_generation_jobs_lock:
        if _normal_generation_active_locked(store) or _continuous_generation_active_locked(
            store
        ):
            raise HTTPException(status_code=409, detail="project_generation_in_progress")
        current_chapter = int(store.summary().get("current_chapter") or 0)
        job = _continuous_job_store(store).create(
            project_id=_public_project_id(store),
            story_id=story_id,
            count=payload.count,
            start_chapter=current_chapter + 1,
        )
        job_id = str(job["job_id"])
        _register_continuous_job(story_id, job_id)
    _continuous_generation_executor.submit(
        _run_continuous_generation_job,
        job_id,
        project_id,
    )
    return _continuous_generation_job_response(job)


def _load_continuous_generation_job_for_route(
    project_id: str,
    *,
    job_id: str | None = None,
    resume_safe: bool = False,
) -> dict[str, object]:
    store = _store_for(project_id)
    jobs = _continuous_job_store(store)
    job = jobs.load(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="continuous_generation_job_not_found",
        )
    if _strip_file_prefix(str(job.get("project_id") or "")) != _strip_file_prefix(
        _public_project_id(store)
    ):
        raise HTTPException(
            status_code=404,
            detail="continuous_generation_job_not_found",
        )
    story_id = _story_id_for(store)
    with _file_generation_jobs_lock:
        registered_job_id = _active_job_for_story(
            _active_continuous_generation_jobs,
            story_id,
        )
    if registered_job_id != str(job.get("job_id") or ""):
        job = jobs.reconcile(
            job,
            official_chapter=int(store.summary().get("current_chapter") or 0),
        )
    should_submit = False
    if resume_safe and str(job.get("status")) in CONTINUOUS_ACTIVE_STATUSES:
        phase = str(job.get("phase") or "")
        if phase in SAFE_RECOVERY_PHASES:
            with _file_generation_jobs_lock:
                active_id = _active_job_for_story(
                    _active_continuous_generation_jobs, story_id
                )
                if not active_id:
                    _register_continuous_job(story_id, str(job["job_id"]))
                    should_submit = True
    if should_submit:
        _continuous_generation_executor.submit(
            _run_continuous_generation_job,
            str(job["job_id"]),
            project_id,
        )
    return job


# ---------------------------------------------------------------------------
# Continuation bootstrap
# ---------------------------------------------------------------------------


def _read_continuation_bootstrap_checkpoint(
    project_root: Path,
) -> dict[str, Any]:
    """Read the bootstrap checkpoint from disk.

    Plan rule: "Progress and artifacts survive reload." The
    endpoint must read the file every time so a route reload
    sees the same status the worker wrote. An in-memory cache
    is only an opportunistic accelerator and must not be the
    source of truth.
    """

    from packages.story_core.continuation_outline_bootstrap import (
        ContinuationOutlineBootstrapper,
    )

    return ContinuationOutlineBootstrapper(
        project_root=project_root,
        planning_generator=object(),
        rolling_generator=object(),
    ).read_checkpoint()


def _run_continuation_bootstrap_job(
    project_id: str,
    project_root: Path,
) -> None:
    """Background entry point: run the bootstrapper and update
    the cached status snapshot.
    """

    from packages.story_core.continuation_outline_bootstrap import (
        ContinuationOutlineBootstrapper,
        LLMRollingWindowGenerator,
        validate_continuation_bootstrap,
    )
    from packages.story_core.outline_planning_generation import (
        LLMOutlinePlanningGenerator,
    )

    try:
        planning = LLMOutlinePlanningGenerator()
        rolling = LLMRollingWindowGenerator()
        bootstrapper = ContinuationOutlineBootstrapper(
            project_root=project_root,
            planning_generator=planning,
            rolling_generator=rolling,
        )
        bootstrapper.run()
    except Exception:
        # Persist a failed status so the API surfaces a
        # stable error to the operator.
        with _continuation_bootstrap_lock:
            _continuation_bootstrap_checkpoints[project_id] = (
                _read_continuation_bootstrap_checkpoint(project_root)
            )
        return

    with _continuation_bootstrap_lock:
        _continuation_bootstrap_checkpoints[project_id] = (
            _read_continuation_bootstrap_checkpoint(project_root)
        )
    # Touch the validator so the result is part of the public
    # status surface.
    validate_continuation_bootstrap(project_root)


def enqueue_continuation_bootstrap(
    project_id: str,
    project_root: Path,
) -> dict[str, Any]:
    """Persist initial progress and submit one bootstrap worker."""

    from packages.story_core.continuation_outline_bootstrap import (
        ContinuationOutlineBootstrapper,
    )

    stripped = _strip_file_prefix(project_id)
    current = _read_continuation_bootstrap_checkpoint(project_root)
    bootstrapper = ContinuationOutlineBootstrapper(
        project_root=project_root,
        planning_generator=object(),
        rolling_generator=object(),
    )
    if (
        current.get("status") == "ready"
        and not bootstrapper.outline_foundation_needs_refresh()
    ):
        current = bootstrapper.refresh_ready_checkpoint(current)
        return {"status": "ready", "checkpoint": current}

    with _continuation_bootstrap_lock:
        cached = _continuation_bootstrap_checkpoints.get(stripped)
        if isinstance(cached, dict) and cached.get("status") in {"queued", "running"}:
            return {"status": "queued", "checkpoint": cached}

    checkpoint = bootstrapper.prepare()
    _continuation_bootstrap_executor.submit(
        _run_continuation_bootstrap_job,
        stripped,
        project_root,
    )
    with _continuation_bootstrap_lock:
        _continuation_bootstrap_checkpoints[stripped] = checkpoint
    return {"status": "queued", "checkpoint": checkpoint}


def init_file_project_routes() -> APIRouter:
    register_file_project_outline_routes(
        router,
        store_for=_store_for,
        planning_generator=lambda: outline_planning_generator,
    )
    register_file_project_candidate_routes(
        router,
        store_for=_store_for,
        assert_mutation_allowed=_assert_candidate_mutation_allowed,
        project_payload=_project_payload,
        story_payload=_story_payload,
    )

    @router.post("/book-dissection/reference")
    def dissect_book_reference(payload: BookDissectionReferenceRequest) -> dict[str, Any]:
        try:
            return dissect_reference_text(payload.text, genre=payload.genre, focus=payload.focus)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/file-projects")
    def list_file_projects(
        lifecycle: Literal["active", "archived", "trashed"] = "active",
    ) -> list[dict[str, Any]]:
        return [_summary_payload(store) for store in _stores(lifecycle=lifecycle)]

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

    @router.post("/file-projects/{project_id}/publishing/synopsis")
    def generate_file_project_synopsis(
        project_id: str,
        payload: PublishingGenerationRequest,
    ) -> dict[str, Any]:
        store = _store_for(project_id)
        existing = store.publishing_assets()
        synopsis_snapshot = existing.get("synopsis") if isinstance(existing.get("synopsis"), dict) else None
        try:
            generated = FanqieSynopsis.model_validate(
                synopsis_generator.generate(
                    _publishing_context_for(store),
                    resolve_stage_runtime("planner"),
                    guidance=payload.guidance,
                )
            )
            saved = store.save_synopsis(
                {
                    **generated.model_dump(mode="json"),
                    "format": "fanqie",
                    "updated_at": _now_iso(),
                },
                expected_synopsis=synopsis_snapshot,
            )
        except ValueError as exc:
            if str(exc) == "publishing_asset_stale_synopsis":
                raise HTTPException(status_code=409, detail="publishing_asset_stale_synopsis") from exc
            if str(exc) == "publishing_asset_write_failed":
                raise _publishing_write_error(exc) from exc
            if str(exc) == "synopsis_generation_invalid":
                raise HTTPException(status_code=502, detail="synopsis_generation_invalid") from exc
            raise HTTPException(status_code=502, detail="synopsis_generation_failed") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="synopsis_generation_failed") from exc
        return {"synopsis": _public_synopsis(saved.get("synopsis"))}

    @router.put("/file-projects/{project_id}/publishing/synopsis")
    def update_file_project_synopsis(
        project_id: str,
        payload: SynopsisUpdateRequest,
    ) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            saved = store.save_synopsis(
                {
                    "tags": payload.tags,
                    "body": payload.body,
                    "format": "fanqie",
                    "updated_at": _now_iso(),
                }
            )
        except ValueError as exc:
            raise _publishing_write_error(exc) from exc
        return {"synopsis": _public_synopsis(saved.get("synopsis"))}

    @router.post("/file-projects/{project_id}/publishing/cover")
    def generate_file_project_cover(
        project_id: str,
        payload: PublishingGenerationRequest,
    ) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            cover_title = _cover_title(store)
            existing = store.publishing_assets()
            cover_snapshot = str((existing.get("cover") or {}).get("prompt") or "")
            synopsis = existing.get("synopsis") if isinstance(existing.get("synopsis"), dict) else {}
            prompt = cover_prompt_generator.generate(
                _publishing_context_for(store),
                resolve_stage_runtime("planner"),
                visual_hook=str(synopsis.get("visual_hook") or ""),
                guidance=payload.guidance,
            )
            prompt_state = store.save_cover_prompt(prompt, expected_prompt=cover_snapshot)
        except ValueError as exc:
            if str(exc) == "publishing_asset_stale_cover":
                raise HTTPException(status_code=409, detail="publishing_asset_stale_cover") from exc
            if str(exc) == "publishing_asset_write_failed":
                raise _publishing_write_error(exc) from exc
            if str(exc) in {"cover_title_invalid", "cover_title_required", "cover_title_too_long"}:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            raise HTTPException(status_code=502, detail="cover_prompt_generation_failed") from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail="cover_prompt_generation_failed") from exc

        try:
            image_runtime = resolve_image_runtime()
        except ImageRuntimeConfigurationError:
            return {
                "status": "prompt_ready",
                "reason": "image_provider_not_configured",
                "cover": prompt_state.get("cover"),
            }

        try:
            base_image = cover_image_provider.generate(prompt, image_runtime)
            rendered_image = render_cover(base_image, cover_title)
        except Exception as exc:
            if str(exc) == "cover_font_unavailable":
                try:
                    store.save_cover_base(prompt=prompt, base_image=base_image, model=image_runtime.model, expected_prompt=prompt, expected_title=cover_title)
                except (UnboundLocalError, ValueError) as write_exc:
                    if isinstance(write_exc, ValueError):
                        if str(write_exc) == "publishing_asset_stale_cover":
                            raise HTTPException(status_code=409, detail="publishing_asset_stale_cover") from write_exc
                        raise _publishing_write_error(write_exc) from write_exc
                raise _cover_error(exc) from exc
            mapped = _cover_error(exc)
            raise HTTPException(
                status_code=mapped.status_code,
                detail={
                    "code": str(mapped.detail),
                    "phase": "image",
                    "prompt_saved": True,
                    "cover": prompt_state.get("cover"),
                },
            ) from exc
        try:
            saved = store.save_cover(
                prompt=prompt,
                base_image=base_image,
                rendered_image=rendered_image,
                model=image_runtime.model,
                expected_prompt=prompt,
                expected_title=cover_title,
                rendered_title=cover_title,
            )
        except ValueError as exc:
            if str(exc) == "publishing_asset_stale_cover":
                raise HTTPException(status_code=409, detail="publishing_asset_stale_cover") from exc
            raise _publishing_write_error(exc) from exc
        return {"status": "ready", "cover": saved.get("cover")}

    @router.put("/file-projects/{project_id}/publishing/cover-prompt")
    def update_file_project_cover_prompt(
        project_id: str,
        payload: CoverPromptUpdateRequest,
    ) -> dict[str, Any]:
        try:
            saved = _store_for(project_id).save_cover_prompt(payload.prompt)
        except ValueError as exc:
            raise _publishing_write_error(exc) from exc
        return {"cover": saved.get("cover")}

    @router.post("/file-projects/{project_id}/publishing/cover/render-image")
    def render_file_project_cover_image(project_id: str) -> dict[str, Any]:
        """Render from the saved human-approved prompt without invoking the text model."""
        store = _store_for(project_id)
        existing = store.publishing_assets()
        cover = existing.get("cover") if isinstance(existing.get("cover"), dict) else {}
        prompt = str(cover.get("prompt") or "").strip()
        if not prompt:
            raise HTTPException(status_code=404, detail="cover_prompt_not_found")
        try:
            cover_title = _cover_title(store)
        except ValueError as exc:
            if str(exc) in {"cover_title_invalid", "cover_title_required", "cover_title_too_long"}:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            raise HTTPException(status_code=500, detail="publishing_asset_read_failed") from exc
        try:
            image_runtime = resolve_image_runtime()
        except ImageRuntimeConfigurationError:
            return {
                "status": "prompt_ready",
                "reason": "image_provider_not_configured",
                "cover": cover,
            }
        try:
            base_image = cover_image_provider.generate(prompt, image_runtime)
            rendered_image = render_cover(base_image, cover_title)
        except Exception as exc:
            if str(exc) == "cover_font_unavailable":
                try:
                    store.save_cover_base(prompt=prompt, base_image=base_image, model=image_runtime.model, expected_prompt=prompt, expected_title=cover_title)
                except (UnboundLocalError, ValueError) as write_exc:
                    if isinstance(write_exc, ValueError):
                        if str(write_exc) == "publishing_asset_stale_cover":
                            raise HTTPException(status_code=409, detail="publishing_asset_stale_cover") from write_exc
                        raise _publishing_write_error(write_exc) from write_exc
                raise _cover_error(exc) from exc
            raise _cover_error(exc) from exc
        try:
            saved = store.save_cover(
                prompt=prompt,
                base_image=base_image,
                rendered_image=rendered_image,
                model=image_runtime.model,
                expected_prompt=prompt,
                expected_title=cover_title,
                rendered_title=cover_title,
            )
        except ValueError as exc:
            if str(exc) == "publishing_asset_stale_cover":
                raise HTTPException(status_code=409, detail="publishing_asset_stale_cover") from exc
            raise _publishing_write_error(exc) from exc
        return {"status": "ready", "cover": saved.get("cover")}

    @router.post("/file-projects/{project_id}/publishing/cover/render-title")
    def render_file_project_cover_title(project_id: str) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            cover_title = _cover_title(store)
            base_snapshot = store.read_cover_base()
        except ValueError as exc:
            if str(exc) in {"cover_title_invalid", "cover_title_required", "cover_title_too_long"}:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            raise HTTPException(status_code=500, detail="publishing_asset_read_failed") from exc
        if base_snapshot is None:
            raise HTTPException(status_code=404, detail="cover_base_not_found")
        base_image, base_version = base_snapshot
        try:
            rendered = render_cover(base_image, cover_title)
        except Exception as exc:
            raise _cover_error(exc) from exc
        try:
            saved = store.save_rendered_cover(rendered, expected_base_version=base_version, expected_title=cover_title, rendered_title=cover_title)
        except ValueError as exc:
            if str(exc) == "publishing_asset_stale_base":
                raise HTTPException(status_code=409, detail="publishing_asset_stale_base") from exc
            if str(exc) == "publishing_asset_stale_cover":
                raise HTTPException(status_code=409, detail="publishing_asset_stale_cover") from exc
            raise _publishing_write_error(exc) from exc
        return {"status": "ready", "cover": saved.get("cover")}

    @router.get("/file-projects/{project_id}/publishing/cover.png")
    def get_file_project_cover(project_id: str, request: Request, download: int = 0) -> Response:
        store = _store_for(project_id)
        cover = store.publishing_assets().get("cover") or {}
        if not isinstance(cover, dict) or cover.get("rendered_path") != "assets/cover.png":
            raise HTTPException(status_code=404, detail="cover_not_found")
        try:
            image = store.read_rendered_cover()
        except ValueError as exc:
            raise HTTPException(status_code=500, detail="publishing_asset_read_failed") from exc
        if image is None:
            raise HTTPException(status_code=404, detail="cover_not_found")
        etag = f'"{sha256(image).hexdigest()}"'
        if _if_none_match_matches(request.headers.get("if-none-match", ""), etag):
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "private, max-age=0, must-revalidate"})
        filename = re.sub(r"[^A-Za-z0-9._-]+", "-", _display_title(store.project(), store.state(), store.summary(), "cover"))
        headers = {"ETag": etag, "Cache-Control": "private, max-age=0, must-revalidate"}
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{filename or "cover"}.png"'
        else:
            headers["Content-Disposition"] = "inline"
        return Response(content=image, media_type="image/png", headers=headers)


    @router.post("/file-projects/{project_id}/archive")
    def archive_file_project(project_id: str) -> dict[str, Any]:
        store = _store_for(project_id)
        _assert_file_project_lifecycle_mutation_allowed(store)
        return _file_project_lifecycle_payload(archive_project(store))

    @router.post("/file-projects/{project_id}/trash")
    def trash_file_project(project_id: str) -> dict[str, Any]:
        store = _store_for(project_id)
        _assert_file_project_lifecycle_mutation_allowed(store)
        try:
            moved_store = trash_project(store, export_root=_export_root(), move=shutil.move)
        except FileProjectLifecycleError as exc:
            _raise_file_project_lifecycle_error(exc)
        return _file_project_lifecycle_payload(moved_store)

    @router.post("/file-projects/{project_id}/restore")
    def restore_file_project(project_id: str) -> dict[str, Any]:
        try:
            active_store = _store_for(project_id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            active_store = None
        if active_store is not None:
            _assert_file_project_lifecycle_mutation_allowed(active_store)
            return _file_project_lifecycle_payload(activate_project(active_store))

        store = _trashed_store_for(project_id)
        _assert_file_project_lifecycle_mutation_allowed(store)
        try:
            restored_store = restore_project(store, export_root=_export_root(), move=shutil.move)
        except FileProjectLifecycleError as exc:
            _raise_file_project_lifecycle_error(exc)
        return _file_project_lifecycle_payload(restored_store)

    @router.delete("/file-projects/{project_id}")
    def delete_file_project(project_id: str, confirm_title: str) -> dict[str, Any]:
        store = _trashed_store_for(project_id)
        _assert_file_project_lifecycle_mutation_allowed(store)
        story_id = _story_id_for(store)
        try:
            delete_trashed_project(
                store,
                export_root=_export_root(),
                confirmation_title=confirm_title,
                actual_title=_display_title(store.project(), store.state(), store.summary(), store.root.name),
                remove_tree=shutil.rmtree,
            )
        except FileProjectLifecycleError as exc:
            _raise_file_project_lifecycle_error(exc)
        return {"deleted": True, "project_id": project_id, "deleted_story_ids": [story_id]}

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

    @router.get("/file-projects/{project_id}/story-core")
    def get_file_project_story_core(project_id: str) -> dict[str, Any]:
        try:
            return _store_for(project_id).story_core()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.put("/file-projects/{project_id}/story-core")
    def update_file_project_story_core(
        project_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return _store_for(project_id).update_story_core(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/file-projects/{project_id}/continuation-bootstrap")
    def start_continuation_bootstrap(
        project_id: str, response: Response
    ) -> dict[str, Any]:
        """Enqueue the continuation bootstrap for a file project.

        Plan rule: the bootstrap runs in a dedicated single-worker
        executor; the route returns 202 immediately so a refresh
        does not block on the model. A duplicate call short-
        circuits when the persisted checkpoint is already
        ``ready`` and returns 200 so the operator can tell
        the difference between ``enqueued`` and ``no-op``.
        """

        store = _store_for(project_id)
        result = enqueue_continuation_bootstrap(project_id, store.root)
        if result["status"] == "ready":
            response.status_code = status.HTTP_200_OK
            return result
        response.status_code = status.HTTP_202_ACCEPTED
        return result

    @router.get("/file-projects/{project_id}/continuation-bootstrap")
    def get_continuation_bootstrap(project_id: str) -> dict[str, Any]:
        """Return the persisted bootstrap status.

        Plan rule: the status comes from disk, not from
        transient route memory, so a page reload never loses
        progress.
        """

        store = _store_for(project_id)
        return _read_continuation_bootstrap_checkpoint(store.root)

    @router.post("/file-projects/{project_id}/enrich-world")
    def enrich_file_project_world(project_id: str) -> dict[str, Any]:
        # Plan rule: the legacy synchronous path and the new world-build
        # job path are mutually exclusive — both call the same model
        # graph and would race for the same world_blueprint if a user
        # double-clicked.  Reject the synchronous path while a job is
        # active; the caller can poll the job instead.
        if _has_active_world_build_job(project_id):
            raise HTTPException(status_code=409, detail="world_build_in_progress")
        store = _store_for(project_id)
        project_payload = {
            **store.project(),
            "project_id": _public_project_id(store),
            "source_path": str(store.root),
            "active_story_id": _story_id_for(store),
            "story_core_context": store.story_core_context("world"),
        }
        try:
            enriched = enrich_project_world(NovelProject.model_validate(project_payload))
        except WorldEnrichmentError as exc:
            detail = str(exc) or "world_enrichment_failed"
            status_code = 400 if detail == "missing_api_key" else 502
            raise HTTPException(status_code=status_code, detail=detail) from exc
        except Exception as exc:
            code = _world_build_error_code(exc)
            raise HTTPException(
                status_code=502,
                detail=_world_build_user_message(code),
            ) from exc
        enriched_payload = enriched.model_dump(mode="json")
        store.update_project(
            {
                key: value
                for key, value in enriched_payload.items()
                if key
                in {
                    "title",
                    "world_summary",
                    "current_focus",
                    "author_constraints",
                    "world_blueprint",
                    "character_profiles",
                    "relationship_graph",
                    "enabled_skill_ids",
                    "enabled_skill_module_ids",
                    "status",
                }
            }
            | {"pipeline_stage": "environment_ready"},
            replace_world_blueprint=True,
        )
        return _project_payload(store)

    @router.post("/file-projects/{project_id}/world-build-jobs")
    def start_file_project_world_build_job(project_id: str) -> dict[str, object]:
        # Plan rule: starting a job while the legacy endpoint is mid-run
        # would also race.  Reuse the same cross-check helper so both
        # directions share one conflict guard.
        if _has_active_world_build_job(project_id):
            raise HTTPException(status_code=409, detail="world_build_in_progress")
        return _start_world_build_job(project_id)

    @router.get("/file-projects/{project_id}/world-build-jobs/current")
    def get_current_file_project_world_build_job(project_id: str) -> dict[str, object]:
        normalized_project_id = _strip_file_prefix(project_id)
        with _world_build_jobs_lock:
            job_id = _active_world_build_jobs.get(normalized_project_id)
            job = _world_build_jobs.get(job_id) if job_id else None
            if job is None:
                job = _load_world_build_job(_store_for(project_id))
            if job is None:
                raise HTTPException(status_code=404, detail="world_build_job_not_found")
            return _world_build_job_response(job)

    @router.get("/file-projects/{project_id}/world-build-jobs/{job_id}")
    def get_file_project_world_build_job(project_id: str, job_id: str) -> dict[str, object]:
        with _world_build_jobs_lock:
            job = _world_build_jobs.get(job_id)
            if job is None:
                job = _load_world_build_job(_store_for(project_id), job_id)
            if job is None or _strip_file_prefix(str(job.get("project_id", ""))) != _strip_file_prefix(project_id):
                raise HTTPException(status_code=404, detail="world_build_job_not_found")
            return _world_build_job_response(job)

    @router.get("/file-projects/{project_id}/foreshadowing")
    def get_file_project_foreshadowing(project_id: str) -> dict[str, Any]:
        store = _store_for(project_id)
        items = store.foreshadowing_ledger()
        return {
            "items": [item.model_dump() for item in items],
            "version": store.foreshadowing_version(items),
        }

    @router.put("/file-projects/{project_id}/foreshadowing")
    def update_file_project_foreshadowing(
        project_id: str,
        payload: ForeshadowingLedgerUpdateRequest,
    ) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            items = store.update_foreshadowing_ledger(
                [item.to_domain() for item in payload.items],
                expected_version=payload.base_version,
            )
        except ValueError as exc:
            if str(exc) == "foreshadowing_version_conflict":
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise
        return {
            "items": [item.model_dump() for item in items],
            "version": store.foreshadowing_version(items),
        }

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
        try:
            store.update_project(payload.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _project_payload(store)

    @router.get("/file-projects/{project_id}/writing-packet")
    def get_file_project_writing_packet(project_id: str, chapter_number: int | None = None) -> dict[str, Any]:
        store = _store_for(project_id)
        return store.writing_packet(chapter_number)

    @router.post(
        "/file-projects/{project_id}/chapters/{chapter_number}/skill-reviews/commercial-shuangwen"
    )
    def run_file_project_shuangwen_review(
        project_id: str,
        chapter_number: int,
    ) -> dict[str, Any]:
        from packages.story_core.shuangwen_review import (
            ShuangwenReviewError,
            ShuangwenReviewPreconditionError,
        )

        store = _store_for(project_id)
        try:
            return store.run_shuangwen_review(
                chapter_number,
                model_gateway=shuangwen_model_gateway,
            )
        except FileNotFoundError as exc:
            if str(exc).startswith("chapter_not_found:"):
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ShuangwenReviewPreconditionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            detail = str(exc)
            if detail == "commercial_shuangwen_skill_missing":
                raise HTTPException(status_code=404, detail=detail) from exc
            if detail.startswith("chapter_not_confirmed:") or detail in {
                "commercial_shuangwen_skill_disabled",
                "commercial_shuangwen_reviewer_disabled",
                "shuangwen_review_chapter_changed",
                "shuangwen_review_body_changed",
                "shuangwen_review_candidate_changed",
            }:
                raise HTTPException(status_code=409, detail=detail) from exc
            raise HTTPException(status_code=422, detail=detail) from exc
        except ShuangwenReviewError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post("/file-projects/{project_id}/outline/rolling-fill")
    def trigger_file_project_rolling_fill(
        project_id: str,
        target_chapter: int = 1,
    ) -> dict[str, Any]:
        """Compatibility check for callers of the removed auto-fill route.

        Missing chapter outlines are generated from the outline workspace,
        never as a side effect of a body-generation request.
        """
        if target_chapter is None or int(target_chapter) < 1:
            raise HTTPException(
                status_code=422,
                detail="rolling_fill_invalid_target_chapter",
            )
        store = _store_for(project_id)
        status = store.rolling_fill_status(int(target_chapter))
        if status.get("status") not in {"present", "legacy"}:
            raise HTTPException(
                status_code=409,
                detail=f"chapter_outline_required:{int(target_chapter)}",
            )
        return {
            "schema_version": "file-project-rolling-fill-response/v1",
            "project_id": project_id,
            **status,
        }

    @router.get("/file-projects/{project_id}/outline/rolling-fill-status")
    def get_file_project_rolling_fill_status(
        project_id: str,
        target_chapter: int = 1,
    ) -> dict[str, Any]:
        """Read the rolling-fill status for ``target_chapter``.

        Pure read: no side effects, no generator call. Returns the same
        status object the writing packet exposes. The frontend uses this
        to poll after a failed fill so the retry button can be enabled
        without re-fetching the full writing packet.
        """
        if target_chapter is None or int(target_chapter) < 1:
            raise HTTPException(
                status_code=422,
                detail="rolling_fill_invalid_target_chapter",
            )
        store = _store_for(project_id)
        status = store.rolling_fill_status(int(target_chapter))
        return {
            "schema_version": "file-project-rolling-fill-status/v1",
            "project_id": project_id,
            **status,
        }

    @router.get("/file-projects/{project_id}/outline/rolling")
    def get_file_project_rolling_outline(project_id: str) -> dict[str, Any]:
        """Return the independent, upcoming chapter-outline window."""

        from packages.story_core.outline_rolling_store import RollingOutlineStore

        store = _store_for(project_id)
        return RollingOutlineStore(store.root).read_rolling_outline() or {
            "schema_version": "rolling-outline/v1",
            "chapters": [],
        }

    @router.put("/file-projects/{project_id}/outline/rolling-chapter/{chapter_number}")
    def update_file_project_rolling_chapter(
        project_id: str,
        chapter_number: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Edit a rolling chapter and mark it as ``source="manual"``.

        The endpoint is the operator's (or the outline editor UI's) way
        to lock a chapter: after this call, ``RollingOutlineStore`` and
        ``RollingOutlinePlanner`` both skip the chapter, so subsequent
        rolling fills never overwrite the operator's edits (per plan
        rule "已存在或人工修改的细纲不会被覆盖").

        Errors:

        * 404 — project not found.
        * 422 — invalid ``chapter_number`` or no rolling outline on
          disk.
        """
        if chapter_number is None or int(chapter_number) < 1:
            raise HTTPException(
                status_code=422,
                detail="rolling_chapter_invalid_number",
            )
        from packages.story_core.outline_rolling_store import (
            RollingOutlineStore,
            RollingOutlineStoreError,
        )
        try:
            store = _store_for(project_id)
        except HTTPException:
            raise
        try:
            updated = RollingOutlineStore(store.root).update_chapter(
                chapter_number=int(chapter_number),
                payload=dict(payload or {}),
            )
        except RollingOutlineStoreError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "schema_version": "file-project-rolling-chapter/v1",
            "project_id": project_id,
            "chapter": updated,
        }

    @router.get("/file-projects/{project_id}/prompt-preview")
    def get_file_project_prompt_preview(project_id: str, chapter_number: int | None = None) -> dict[str, Any]:
        store = _store_for(project_id)
        return store.prompt_preview(chapter_number)

    @router.get("/file-projects/{project_id}/prompt-context")
    def get_file_project_prompt_context(project_id: str, chapter_number: int | None = None) -> dict[str, Any]:
        store = _store_for(project_id)
        return store.prompt_context(chapter_number)

    @router.get("/file-projects/{project_id}/prompt-templates")
    def get_file_project_prompt_templates(project_id: str) -> dict[str, Any]:
        store = _store_for(project_id)
        return {
            "schema_version": "project-prompt-templates/v1",
            "project_id": project_id,
            "templates": store.prompt_templates(),
        }

    @router.put("/file-projects/{project_id}/prompt-templates/{template_key}")
    def update_file_project_prompt_template(
        project_id: str,
        template_key: str,
        payload: PromptTemplateUpdateRequest,
    ) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            return store.set_prompt_template_override(template_key, payload.content)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.delete("/file-projects/{project_id}/prompt-templates/{template_key}")
    def delete_file_project_prompt_template(project_id: str, template_key: str) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            return store.delete_prompt_template_override(template_key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/file-projects/{project_id}/prompt-calls")
    def list_file_project_prompt_calls(project_id: str, chapter_number: int | None = None) -> dict[str, Any]:
        store = _store_for(project_id)
        return {
            "schema_version": "prompt-call-list/v1",
            "project_id": project_id,
            "chapter_number": chapter_number,
            "calls": store.prompt_call_log().list(chapter_number=chapter_number),
        }

    @router.get("/file-projects/{project_id}/prompt-calls/{call_id}")
    def get_file_project_prompt_call(project_id: str, call_id: str) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            return store.prompt_call_log().get(call_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/file-projects/{project_id}/book-dissection/chapter")
    def dissect_file_project_chapter(project_id: str, payload: BookDissectionChapterRequest) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            chapter = dict(store.chapter(payload.chapter_number))
            body_snapshot_override = payload.body
            if body_snapshot_override is not None:
                chapter["body"] = body_snapshot_override
            return diagnose_project_chapter({"project": store.project(), "state": store.state()}, chapter)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/file-projects/{project_id}/generate-next")
    def generate_file_project_next(project_id: str, payload: FileProjectGenerateNextRequest | None = None) -> dict[str, Any]:
        store = _store_for(project_id)
        try:
            generated = store.generate_next_chapter(
                chapter_direction_id=payload.chapter_direction_id if payload else None
            )
        except ValueError as exc:
            _raise_file_project_error(exc)
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
    def start_file_generation_job_route(
        project_id: str,
        payload: FileProjectGenerationJobRequest | None = None,
    ) -> dict[str, object]:
        return start_file_generation_job(project_id, payload)

    @router.post("/file-projects/{project_id}/continuous-generation-jobs")
    def start_continuous_generation_job_route(
        project_id: str,
        payload: FileProjectContinuousGenerationRequest,
    ) -> dict[str, object]:
        return start_continuous_generation_job(project_id, payload)

    @router.get("/file-projects/{project_id}/continuous-generation-jobs/current")
    def get_current_continuous_generation_job(
        project_id: str,
    ) -> dict[str, object]:
        return _continuous_generation_job_response(
            _load_continuous_generation_job_for_route(
                project_id,
                resume_safe=True,
            )
        )

    @router.get(
        "/file-projects/{project_id}/continuous-generation-jobs/{job_id}"
    )
    def get_continuous_generation_job(
        project_id: str,
        job_id: str,
    ) -> dict[str, object]:
        return _continuous_generation_job_response(
            _load_continuous_generation_job_for_route(
                project_id,
                job_id=job_id,
                resume_safe=True,
            )
        )

    @router.post(
        "/file-projects/{project_id}/continuous-generation-jobs/{job_id}/stop"
    )
    def stop_continuous_generation_job(
        project_id: str,
        job_id: str,
    ) -> dict[str, object]:
        store = _store_for(project_id)
        existing = _load_continuous_generation_job_for_route(
            project_id,
            job_id=job_id,
        )
        try:
            stopped = _continuous_job_store(store).request_stop(
                str(existing["job_id"])
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail="continuous_generation_job_not_found",
            ) from exc
        return _continuous_generation_job_response(stopped)

    @router.get("/file-projects/{project_id}/generation-jobs")
    def list_file_generation_jobs(project_id: str, limit: int = 30) -> dict[str, object]:
        store = _store_for(project_id)
        items = []
        for job in _list_file_generation_jobs(store, limit=limit):
            items.append(
                {
                    "job_id": str(job.get("job_id", "")),
                    "story_id": str(job.get("story_id", "")),
                    "chapter_number": job.get("chapter_number") if isinstance(job.get("chapter_number"), int) else None,
                    "status": str(job.get("status", "")),
                    "progress": str(job.get("progress", "")),
                    "error": job.get("error"),
                    "created_at": str(job.get("created_at", "")),
                    "updated_at": str(job.get("updated_at", "")),
                }
            )
        return {"schema_version": "file-generation-job-history/v1", "items": items}

    @router.get("/file-projects/{project_id}/generation-jobs/current")
    def get_current_file_generation_job(project_id: str) -> dict[str, object]:
        requested_story_id = _strip_file_prefix(project_id)
        with _file_generation_jobs_lock:
            job: dict[str, object] | None = None
            active_job_id = _active_file_generation_jobs.get(requested_story_id) or _active_file_generation_jobs.get(
                _file_id(requested_story_id)
            )
            if active_job_id:
                job = _file_generation_jobs.get(active_job_id)
            if job is None:
                candidates = [
                    item
                    for item in _file_generation_jobs.values()
                    if _strip_file_prefix(str(item.get("story_id", ""))) == requested_story_id
                ]
                if candidates:
                    job = max(candidates, key=lambda item: str(item.get("updated_at", "")))
            if job is None:
                store = _store_for(project_id)
                job = _load_file_generation_job(store)
                if job is not None:
                    loaded_job_id = str(job.get("job_id", ""))
                    _file_generation_jobs[loaded_job_id] = job
                    if job.get("status") in {"queued", "running"}:
                        _active_file_generation_jobs[str(job.get("story_id", ""))] = loaded_job_id
            if job is None:
                raise HTTPException(status_code=404, detail="file_generation_job_not_found")
            _reconcile_file_generation_job_locked(job)
            return _file_generation_job_response(job)

    @router.get("/file-projects/{project_id}/generation-jobs/{job_id}")
    def get_file_generation_job(project_id: str, job_id: str) -> dict[str, object]:
        requested_story_id = _strip_file_prefix(project_id)
        with _file_generation_jobs_lock:
            job = _file_generation_jobs.get(job_id)
            if job is None:
                store = _store_for(project_id)
                job = _load_file_generation_job(store, job_id)
                if job is not None:
                    _file_generation_jobs[job_id] = job
            if job is None:
                raise HTTPException(status_code=404, detail="file_generation_job_not_found")
            if _strip_file_prefix(str(job.get("story_id", ""))) != requested_story_id:
                raise HTTPException(status_code=404, detail="file_generation_job_not_found")
            _reconcile_file_generation_job_locked(job)
            return _file_generation_job_response(job)

    @router.get("/file-projects/{project_id}/workflow-artifacts")
    def list_file_project_workflow_artifacts(
        project_id: str, job_id: str | None = None
    ) -> dict[str, object]:
        # Reject path-traversal payloads in the ``job_id`` query
        # parameter up front so the on-disk store never sees a
        # value that could escape ``.story-system/workflow/``.
        if job_id is not None:
            try:
                from packages.story_core.persistence.workflow_artifact_store import (
                    _validate_id,
                )

                _validate_id("job_id", job_id)
            except ValueError:
                raise HTTPException(
                    status_code=400, detail="workflow_artifact_invalid_job_id"
                )

        """List per-stage workflow artifacts the modular agent pipeline wrote.

        The new ``Director → Writer → FactExtractor`` pipeline
        stores one record per stage under
        ``.story-system/workflow/<job_id>/<stage_id>.json``.
        The workbench reads this list on page refresh to show
        the user what each agent saw and produced without
        re-running the model. The endpoint is intentionally
        read-only: a stage record is the agent's inspectable
        work product, not a control surface.
        """
        from packages.story_core.persistence.workflow_artifact_store import (
            WorkflowArtifactStore,
        )

        store = _store_for(project_id)
        workflow_store = WorkflowArtifactStore(store.root)
        if job_id is not None:
            job_dir = workflow_store.job_dir(job_id)
            job_ids = [job_id] if job_dir.is_dir() else []
        else:
            workflow_root = workflow_store.directory
            if not workflow_root.is_dir():
                job_ids = []
            else:
                job_ids = sorted(
                    path.name
                    for path in workflow_root.iterdir()
                    if path.is_dir()
                )
        items: list[dict[str, object]] = []
        for jid in job_ids:
            stages = workflow_store.list_stages(jid)
            items.append(
                {
                    "job_id": jid,
                    "stages": [
                        {
                            "stage_id": stage.stage_id,
                            "agent_id": stage.agent_id,
                            "status": stage.status,
                            "elapsed_ms": int(stage.elapsed_ms or 0),
                            "artifact_path": str(stage.artifact_path or ""),
                            "artifact_sha256": str(stage.artifact_sha256 or ""),
                            "reads": list(stage.reads or []),
                            "selected_entity_ids": list(
                                stage.selected_entity_ids or []
                            ),
                            "selected_module_ids": list(
                                stage.selected_module_ids or []
                            ),
                            "provider": str(stage.provider or ""),
                            "model": str(stage.model or ""),
                            "prompt_template_id": str(stage.prompt_template_id or ""),
                            "prompt_template_version": str(
                                stage.prompt_template_version or ""
                            ),
                            "output_summary": str(stage.output_summary or ""),
                            "error": str(stage.error or ""),
                            "started_at": str(stage.started_at or ""),
                            "finished_at": str(stage.finished_at or ""),
                        }
                        for stage in stages
                    ],
                }
            )
        return {
            "schema_version": "file-workflow-artifacts/v1",
            "project_id": project_id,
            "items": items,
        }

    @router.get(
        "/file-projects/{project_id}/workflow-artifacts/{job_id}/{stage_id}"
    )
    def get_file_project_workflow_artifact(
        project_id: str, job_id: str, stage_id: str
    ) -> dict[str, object]:
        # The URL path component already rejects ``..`` and ``/``,
        # but an explicit check protects against the rare case of
        # percent-encoded slashes or a misuse of the
        # ``workflow_artifact_invalid_*`` family of errors.
        try:
            from packages.story_core.persistence.workflow_artifact_store import (
                _validate_id,
            )

            _validate_id("job_id", job_id)
            _validate_id("stage_id", stage_id)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="workflow_artifact_invalid_id"
            )

        """Read a single per-stage workflow artifact record.

        The workbench calls this when the user expands a
        stage row in the audit panel. The record carries the
        exact reads, the selected entity / module ids, the
        provider / model metadata, and the output summary —
        everything the workbench needs to render the
        "本步产物" / "模型调用" / "调用模块" sections
        without re-running the model.
        """
        from packages.story_core.persistence.workflow_artifact_store import (
            WorkflowArtifactStore,
        )

        store = _store_for(project_id)
        workflow_store = WorkflowArtifactStore(store.root)
        record = workflow_store.read_stage(job_id, stage_id)
        if record is None:
            raise HTTPException(
                status_code=404, detail="workflow_artifact_not_found"
            )
        return {
            "schema_version": "file-workflow-artifact/v1",
            "project_id": project_id,
            "job_id": job_id,
            "stage_id": stage_id,
            "stage": {
                "stage_id": record.stage_id,
                "agent_id": record.agent_id,
                "status": record.status,
                "elapsed_ms": int(record.elapsed_ms or 0),
                "artifact_path": str(record.artifact_path or ""),
                "artifact_sha256": str(record.artifact_sha256 or ""),
                "reads": list(record.reads or []),
                "selected_entity_ids": list(record.selected_entity_ids or []),
                "selected_module_ids": list(record.selected_module_ids or []),
                "provider": str(record.provider or ""),
                "model": str(record.model or ""),
                "prompt_template_id": str(record.prompt_template_id or ""),
                "prompt_template_version": str(
                    record.prompt_template_version or ""
                ),
                "output_summary": str(record.output_summary or ""),
                "error": str(record.error or ""),
                "started_at": str(record.started_at or ""),
                "finished_at": str(record.finished_at or ""),
            },
        }

    @router.get("/file-stories/{story_id}")
    def get_file_story(story_id: str) -> dict[str, Any]:
        wanted = _strip_file_prefix(story_id)
        for store in _stores():
            if _strip_file_prefix(_story_id_for(store)) == wanted:
                return _story_payload(store)
        raise HTTPException(status_code=404, detail="file_story_not_found")

    @router.get("/file-stories/{story_id}/overview")
    def get_file_story_overview(story_id: str) -> dict[str, Any]:
        return _story_overview_payload(_file_story_store(story_id))

    @router.get("/file-stories/{story_id}/chapters/{chapter_number}")
    def get_file_story_chapter(
        story_id: str,
        chapter_number: int = ApiPath(ge=1),
    ) -> dict[str, Any]:
        return _file_chapter_payload(_file_story_store(story_id), chapter_number)

    return router
