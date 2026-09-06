from __future__ import annotations



from concurrent.futures import ThreadPoolExecutor

from datetime import datetime, timezone

from functools import wraps

import json

import re

from threading import Lock, RLock

from typing import Any, Literal

from uuid import uuid4



from fastapi import APIRouter, HTTPException, Response

from pydantic import BaseModel, ConfigDict, Field, field_validator



from apps.api.storage import (

    SQLiteStoryStore,

    SimulationFailedError,

    _project_world_facts,

    _sync_project_character_profiles,

    _sync_project_generation_context,

)

from packages.story_core.engine import ChapterBundle, StoryEngine

from packages.story_core.generation_progress import generation_progress

from packages.story_core.models import (

    AgentSettings,

    CharacterState,

    NewCharacterPolicy,

    NovelProject,

    NovelProjectSummary,

    StoryState,

)

from packages.story_core.novel_type_catalog import resolve_novel_type_id
from packages.story_core.book_style import normalize_book_style

from packages.story_core.orchestrator import _merge_writing_review_quality, _review_chapter_body

from packages.story_core.quality import validate_bundle

from packages.story_core.runtime_config import get_runtime_strategy_settings

from packages.story_core.skill_packs import (
    skill_pack_prompt_context,
    writer_skill_pack_prompt_context,
)
from packages.story_core.prompt_templates import (
    get_default_prompt_template,
    load_global_prompt_templates,
    save_global_prompt_template,
)

from packages.story_core.simplified_review import build_simplified_review, user_facing_generation_error

from packages.story_core.writing_packet import build_codex_writing_packet

from packages.story_core.world_enrichment import WorldEnrichmentError, enrich_project_rulebook, enrich_project_world



try:

    from scripts.novel_agent import call_openclaw_review

except Exception:  # pragma: no cover - OpenClaw is optional in API tests.

    call_openclaw_review = None





router = APIRouter()

store = SQLiteStoryStore()

engine = StoryEngine()

_generation_executor = ThreadPoolExecutor(max_workers=2)

_generation_jobs: dict[str, dict[str, object]] = {}

_active_generation_jobs: dict[str, str] = {}

_generation_jobs_lock = Lock()

_automation_executor = ThreadPoolExecutor(max_workers=1)

_automation_jobs: dict[str, dict[str, object]] = {}

_active_automation_jobs: dict[str, str] = {}

_automation_jobs_lock = Lock()

_project_update_locks: dict[str, RLock] = {}

_project_update_locks_guard = Lock()

GENERATION_JOB_STALE_SECONDS = 15 * 60

GENERATION_JOB_STEP_LIMIT = 200





def _project_update_lock(project_id: str) -> RLock:

    with _project_update_locks_guard:

        return _project_update_locks.setdefault(project_id, RLock())



def _serialize_project_update(function: Any) -> Any:

    @wraps(function)

    def locked(project_id: str, *args: Any, **kwargs: Any) -> Any:

        with _project_update_lock(project_id):

            return function(project_id, *args, **kwargs)

    return locked



def _now_iso() -> str:

    return datetime.now(timezone.utc).isoformat()





def _sanitize_generation_job_step_artifact(value: object) -> Any | list[Any] | str | int | float | bool | None:

    if isinstance(value, dict):

        normalized: dict[str, Any] = {}

        for artifact_key, artifact_value in value.items():

            key = str(artifact_key)

            normalized_value = _sanitize_generation_job_step_artifact(artifact_value)

            if normalized_value is not None:

                normalized[key] = normalized_value

        return normalized or None

    if isinstance(value, list):

        items: list[Any] = []

        for index, item in enumerate(value):

            if index >= 24:

                break

            normalized_item = _sanitize_generation_job_step_artifact(item)

            if normalized_item is not None:

                items.append(normalized_item)

        return items

    if isinstance(value, str):

        text = value.strip()

        if not text:

            return None

        if len(text) > 280:

            text = f"{text[:260]}..."

        return text

    if isinstance(value, (int, float, bool)) or value is None:

        return value

    return str(value)





def _infer_generation_source(message: str, stage: str | None = None) -> str:
    lowered = message.lower()
    if stage == "review":
        return "reviewer"
    if any(keyword in lowered for keyword in ["model", "llm", "timeout", "request", "response"]):
        return "llm"
    if any(keyword in lowered for keyword in ["memory", "ledger", "state", "sync", "persist"]):
        return "memory"
    if any(
        keyword in lowered
        for keyword in ["review", "reviewer", "quality", "ai flavor", "reader", "ai", "revision", "editor", "hard", "soft"]
    ):
        return "reviewer"
    if any(keyword in lowered for keyword in ["compose", "body", "style", "chapter", "draft", "rewrit", "revision", "expand"]):
        return "writer"
    return "orchestrator"


def _infer_generation_stage(message: str) -> str:
    lowered = message.lower()
    if "plan" in lowered or "planning" in lowered:
        return "director"
    if any(keyword in lowered for keyword in ["review", "quality", "soft review", "hard", "hard review", "revision", "revision_plan"]):
        return "review"
    if any(keyword in lowered for keyword in ["memory", "ledger", "state", "sync", "persist", "character card", "character_cards"]):
        return "memory"
    if any(keyword in lowered for keyword in ["writing", "style", "style adapt", "compress", "rewrite", "expand", "chapter", "body"]):
        return "writer"
    return "orchestrator"

def _normalize_generation_job_step_item(value: object) -> dict[str, object]:

    if not isinstance(value, dict):

        return {}

    message = str(value.get("message", "")).strip()

    if not message:

        return {}

    status = str(value.get("status", "running")).strip().lower()

    normalized_status = status if status in {"running", "done", "error", "queued"} else "running"

    normalized: dict[str, object] = {

        "message": message,

        "status": normalized_status,

        "at": str(value.get("at", "")) or _now_iso(),

    }

    raw_stage = value.get("stage")

    if isinstance(raw_stage, str) and raw_stage.strip():

        normalized["stage"] = raw_stage.strip()

    raw_source = value.get("source")

    if isinstance(raw_source, str) and raw_source.strip():

        normalized["source"] = raw_source.strip()

    raw_artifact = value.get("artifact")

    compact_artifact = _sanitize_generation_job_step_artifact(raw_artifact)

    if compact_artifact is not None:

        normalized["artifact"] = compact_artifact

    return normalized





def _normalise_generation_job_steps(job: dict[str, object]) -> list[dict[str, object]]:

    steps: list[dict[str, object]] = []

    for item in job.get("steps", []):

        normalized_step = _normalize_generation_job_step_item(item)

        if not normalized_step:

            continue

        steps.append(normalized_step)

    if len(steps) != (len(job.get("steps", [])) if isinstance(job.get("steps"), list) else 0):

        job["steps"] = steps

    return steps





def _serialize_chapter_bundle(bundle, world_facts: list[str]) -> dict:

    data = bundle.model_dump()

    source = ""

    if isinstance(data.get("chapter_intent"), dict):

        source = str(data["chapter_intent"].get("source") or "")

    if not source and isinstance(data.get("simulation_status"), dict):

        source = str(data["simulation_status"].get("source") or "")

    if source.startswith("manual"):

        quality_report = validate_bundle(data)

        quality_report["writing_review"] = {

            "pass": bool(quality_report.get("ok")),

            "issues": [],

            "source": source,

            "manual_review_bypass": True,

        }

    else:

        quality_report = dict(bundle.quality_report) if isinstance(bundle.quality_report, dict) else validate_bundle(data)

    quality_report["simplified_review"] = build_simplified_review(quality_report)

    data["quality_report"] = quality_report

    return data





class CreateStoryRequest(BaseModel):

    story_id: str

    outline: str

    genre: str

    style: str

    agent_settings: AgentSettings = Field(default_factory=AgentSettings)

    characters: list[CharacterState] = Field(default_factory=list)





class CreateProjectRequest(BaseModel):

    project_id: str

    title: str

    source_path: str = ""

    seed_outline: str = ""

    world_summary: str = ""

    current_focus: str = ""

    author_constraints: list[str] = Field(default_factory=list)

    world_blueprint: dict = Field(default_factory=dict)

    character_profiles: list[dict] = Field(default_factory=list)

    relationship_graph: list[dict] = Field(default_factory=list)

    enabled_skill_ids: list[str] = Field(default_factory=list)
    enabled_skill_module_ids: list[str] = Field(default_factory=list)

    pipeline_stage: str = "imported"

    active_story_id: str = ""





class ActivateProjectStoryRequest(BaseModel):

    story_id: str





class UpdateProjectRequest(BaseModel):

    title: str | None = None

    source_path: str | None = None

    seed_outline: str | None = None

    world_summary: str | None = None

    current_focus: str | None = None

    author_constraints: list[str] | None = None

    world_blueprint: dict | None = None

    character_profiles: list[dict] | None = None

    relationship_graph: list[dict] | None = None

    enabled_skill_ids: list[str] | None = None
    enabled_skill_module_ids: list[str] | None = None

    status: str | None = None

    pipeline_stage: str | None = None

    active_story_id: str | None = None





class StoryResponse(BaseModel):

    story_id: str

    outline: str

    genre: str

    style: str

    current_chapter: int

    agent_settings: dict = Field(default_factory=dict)

    agent_runtime: dict = Field(default_factory=dict)

    author_constraints: list[str] = Field(default_factory=list)

    writing_lessons: list[str] = Field(default_factory=list)

    world_facts: list[str] = Field(default_factory=list)

    characters: list[dict] = Field(default_factory=list)

    history: list[dict] = Field(default_factory=list)

    parent_story_id: str | None = None

    branched_from_chapter: int | None = None





class BranchStoryRequest(BaseModel):

    new_story_id: str

    from_chapter: int = Field(ge=0)





class StorySummaryResponse(BaseModel):

    story_id: str

    current_chapter: int

    parent_story_id: str | None = None

    branched_from_chapter: int | None = None





class ProjectSummaryResponse(BaseModel):

    project_id: str

    title: str

    status: str = "draft"

    pipeline_stage: str = "imported"

    active_story_id: str = ""

    current_chapter: int = 0

    source_path: str = ""

    project_lifecycle: str = "active"

    archived_at: str = ""

    trashed_at: str = ""





class ProjectResponse(BaseModel):

    project_id: str

    title: str

    source_path: str = ""

    seed_outline: str = ""

    world_summary: str = ""

    current_focus: str = ""

    author_constraints: list[str] = Field(default_factory=list)

    world_blueprint: dict = Field(default_factory=dict)

    character_profiles: list[dict] = Field(default_factory=list)

    relationship_graph: list[dict] = Field(default_factory=list)

    enabled_skill_ids: list[str] = Field(default_factory=list)
    enabled_skill_module_ids: list[str] = Field(default_factory=list)
    skill_module_selection_mode: Literal["legacy_all", "explicit"] = "explicit"

    status: str = "draft"

    pipeline_stage: str = "imported"

    active_story_id: str = ""

    project_lifecycle: str = "active"

    archived_at: str = ""

    trashed_at: str = ""

    branches: list[StorySummaryResponse] = Field(default_factory=list)





class RenameStoryRequest(BaseModel):

    new_story_id: str





class DeleteStoryResponse(BaseModel):

    deleted: bool

    story_id: str





class DeleteProjectResponse(BaseModel):

    deleted: bool

    project_id: str

    deleted_story_ids: list[str] = Field(default_factory=list)





class PromptTemplateUpdateRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)


class AgentContextResponse(BaseModel):

    schema_version: str = "agent-context/v1"

    project: dict = Field(default_factory=dict)

    active_story: dict | None = None

    branches: list[dict] = Field(default_factory=list)

    world: dict = Field(default_factory=dict)

    recent_chapters: list[dict] = Field(default_factory=list)

    controls: dict = Field(default_factory=dict)





class AgentReviewResponse(BaseModel):

    schema_version: str = "agent-review/v1"

    project: dict = Field(default_factory=dict)

    story: dict = Field(default_factory=dict)

    chapter: dict = Field(default_factory=dict)

    review: dict = Field(default_factory=dict)

    recommendation: dict = Field(default_factory=dict)

    controls: dict = Field(default_factory=dict)





class AgentReviseRequest(BaseModel):

    chapter_number: int | None = None

    instructions: list[str] = Field(default_factory=list)

    include_body: bool = False





class AgentRevisionResponse(BaseModel):

    schema_version: str = "agent-revision/v1"

    project: dict = Field(default_factory=dict)

    story: dict = Field(default_factory=dict)

    chapter: dict = Field(default_factory=dict)

    review: dict = Field(default_factory=dict)

    revision: dict = Field(default_factory=dict)

    controls: dict = Field(default_factory=dict)





class GenerationJobResponse(BaseModel):

    job_id: str

    story_id: str

    status: str

    progress: str = ""

    chapter_number: int | None = None

    error: str = ""

    steps: list[dict[str, object]] = Field(default_factory=list)

    created_at: str

    updated_at: str





class ProjectAutomationJobRequest(BaseModel):

    max_revisions: int = Field(default=2, ge=0, le=5)

    review_provider: str = "local"

    include_body: bool = False

    openclaw_agent: str = "main"

    openclaw_timeout: int = Field(default=600, ge=30, le=1800)



    @field_validator("review_provider", mode="before")

    @classmethod

    def normalize_review_provider(cls, value: object) -> str:

        provider = str(value or "local").strip().lower()

        # Automation now uses the built-in Codex/self reviewer by default.

        # OpenClaw remains available through the explicit CLI compatibility path.

        if provider in {"", "self", "codex", "openclaw"}:

            return "local"

        return provider





class ProjectAutomationJobResponse(BaseModel):

    job_id: str

    project_id: str

    story_id: str

    status: str

    phase: str

    progress: str = ""

    chapter_number: int | None = None

    revision_attempts: int = 0

    max_revisions: int = 0

    final_action: str = ""

    review_provider: str = "local"

    error: str = ""

    created_at: str

    updated_at: str





def _append_generation_job_step(

    job: dict[str, object],

    message: str | dict[str, object],

    *,

    status: str = "running",

    stage: str | None = None,

    source: str | None = None,

    artifact: object = None,

) -> None:

    if isinstance(message, dict):

        raw = dict(message)

        cleaned = str(raw.get("message", "")).strip()

        if not status:

            status = str(raw.get("status", "running")).strip().lower()

        if not stage:

            raw_stage = raw.get("stage")

            if isinstance(raw_stage, str) and raw_stage.strip():

                stage = raw_stage.strip()

        if not source:

            raw_source = raw.get("source")

            if isinstance(raw_source, str) and raw_source.strip():

                source = raw_source.strip()

        if artifact is None:

            artifact = raw.get("artifact")

    else:

        cleaned = str(message or "").strip()

    if not cleaned:

        return

    steps = job.get("steps")

    if not isinstance(steps, list):

        steps = []

        job["steps"] = steps

    normalized_status = status if status in {"running", "done", "error", "queued"} else "running"

    normalized_stage = stage.strip() if isinstance(stage, str) else ""

    normalized_source = source.strip() if isinstance(source, str) else ""

    if not normalized_stage:

        normalized_stage = _infer_generation_stage(cleaned)

    if not normalized_source:

        normalized_source = _infer_generation_source(cleaned, normalized_stage)

    normalized_artifact = _sanitize_generation_job_step_artifact(artifact) if artifact is not None else None

    normalized = {

        "message": cleaned,

        "status": normalized_status,

        "at": _now_iso(),

        "stage": normalized_stage,

        "source": normalized_source,

    }

    if normalized_artifact is not None:

        normalized["artifact"] = normalized_artifact

    if steps and isinstance(steps[-1], dict) and str(steps[-1].get("message", "")).strip() == cleaned:

        steps[-1] = normalized

    else:

        steps.append(normalized)

    if len(steps) > GENERATION_JOB_STEP_LIMIT:

        steps.pop(0)





def _generation_job_response(job: dict[str, object]) -> GenerationJobResponse:

    steps = _normalise_generation_job_steps(job)

    return GenerationJobResponse(

        job_id=str(job.get("job_id", "")),

        story_id=str(job.get("story_id", "")),

        status=str(job.get("status", "")),

        progress=str(job.get("progress", "")),

        chapter_number=job.get("chapter_number") if isinstance(job.get("chapter_number"), int) else None,

        error=str(job.get("error", "")),

        steps=steps,

        created_at=str(job.get("created_at", "")),

        updated_at=str(job.get("updated_at", "")),

    )





def _parse_iso_datetime(value: object) -> datetime | None:

    try:

        return datetime.fromisoformat(str(value))

    except ValueError:

        return None





def _reconcile_generation_job_locked(job: dict[str, object]) -> None:
    """Repair stale job state after client timeouts or overlapping generate calls.

    Uvicorn keeps a timed-out sync request running in the worker thread. If that
    request writes the chapter while a later background job is still running, the
    UI should not stay stuck on "generating" forever.
    """

    if job.get("status") not in {"queued", "running"}:
        return
    story_id = str(job.get("story_id", ""))
    record = store.get(story_id) if story_id else None
    starting_chapter = int(job.get("starting_chapter") or 0)
    current_chapter = record.story.current_chapter if record is not None else starting_chapter
    if current_chapter > starting_chapter:
        _append_generation_job_step(
            job,
            {
                "message": "任务执行完成",
                "stage": "orchestrator",
                "source": "story-route",
                "artifact": {"reason": "chapter_progress_detected"},
            },
            status="done",
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
        if _active_generation_jobs.get(story_id) == job.get("job_id"):
            _active_generation_jobs.pop(story_id, None)
        return

    updated_at = _parse_iso_datetime(job.get("updated_at"))
    if updated_at is None:
        return
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    if (datetime.now(timezone.utc) - updated_at).total_seconds() > GENERATION_JOB_STALE_SECONDS:
        _append_generation_job_step(
            job,
            {
                "message": "任务执行超时",
                "stage": "orchestrator",
                "source": "story-route",
                "artifact": {
                    "reason": "stale_timeout",
                    "story_id": story_id,
                    "job_id": job.get("job_id"),
                },
            },
            status="error",
        )
        job.update(
            {
                "status": "failed",
                "progress": "生成超时",
                "error": "generation_job_stale_timeout",
                "updated_at": _now_iso(),
            }
        )
        if _active_generation_jobs.get(story_id) == job.get("job_id"):
            _active_generation_jobs.pop(story_id, None)


def _automation_job_response(job: dict[str, object]) -> ProjectAutomationJobResponse:

    return ProjectAutomationJobResponse(

        job_id=str(job.get("job_id", "")),

        project_id=str(job.get("project_id", "")),

        story_id=str(job.get("story_id", "")),

        status=str(job.get("status", "")),

        phase=str(job.get("phase", "")),

        progress=str(job.get("progress", "")),

        chapter_number=job.get("chapter_number") if isinstance(job.get("chapter_number"), int) else None,

        revision_attempts=int(job.get("revision_attempts") or 0),

        max_revisions=int(job.get("max_revisions") or 0),

        final_action=str(job.get("final_action", "")),

        review_provider=str(job.get("review_provider", "local")),

        error=str(job.get("error", "")),

        created_at=str(job.get("created_at", "")),

        updated_at=str(job.get("updated_at", "")),

    )





def _update_generation_job(job_id: str, **updates: object) -> None:

    with _generation_jobs_lock:

        job = _generation_jobs.get(job_id)

        if job is None:

            return

        job.update(updates)

        job["updated_at"] = _now_iso()





def _update_automation_job(job_id: str, **updates: object) -> None:

    with _automation_jobs_lock:

        job = _automation_jobs.get(job_id)

        if job is None:

            return

        job.update(updates)

        job["updated_at"] = _now_iso()





def _simulation_failed_detail(exc: SimulationFailedError) -> str:

    bundle = exc.bundle

    failed_agents = bundle.simulation_status.get("fallback_agents", [])

    agent_map = bundle.simulation_status.get("agents", {})

    reasons: list[str] = []

    for name in failed_agents:

        info = agent_map.get(name, {}) if isinstance(agent_map, dict) else {}

        reason = str(info.get("fallback_reason", "")).strip()

        if reason:

            reasons.append(f"{name}: {reason}")

        else:

            reasons.append(str(name))

    detail = "本轮世界推进失败，本章未写入。"

    if reasons:
        detail = f"{detail} " + "；".join(reasons[:4])

    return detail





def _mark_project_simulating(story_id: str) -> None:

    project_id = store.find_project_id_by_story(story_id)

    if not project_id:

        return

    project = store.get_project(project_id)

    if project is None:

        return

    project.status = "simulating"

    project.pipeline_stage = "simulating"

    project.active_story_id = story_id

    store.update_project(project)





def _generate_story_chapter(story_id: str):

    bundle = store.generate_next(story_id, engine)

    _mark_project_simulating(story_id)

    return bundle





def _sync_project_context_for_story(project: NovelProject, story: StoryState, *, has_history: bool = False) -> None:

    """Make project settings authoritative before any context is displayed."""

    _sync_project_generation_context(story, project, has_history=has_history)

    _sync_project_character_profiles(story, project)





def _story_state_before_chapter(record, chapter_number: int) -> StoryState:

    """Return the story snapshot that existed immediately before a chapter."""



    target = max(1, int(chapter_number))

    if target == 1 or not record.history:

        return record.initial_story.model_copy(deep=True)

    previous = [bundle for bundle in record.history if bundle.chapter_number < target]

    if not previous:

        return record.initial_story.model_copy(deep=True)

    return max(previous, key=lambda bundle: bundle.chapter_number).updated_story.model_copy(deep=True)





def _run_generation_job(job_id: str, story_id: str) -> None:
    def report_progress(message: str | dict[str, object]) -> None:
        if isinstance(message, dict):
            progress_message = str(message.get("message", "")).strip()
            stage = message.get("stage")
            source = message.get("source")
            artifact = message.get("artifact")
        else:
            progress_message = str(message).strip()
            stage = None
            source = None
            artifact = None
        if not progress_message:
            return
        _update_generation_job(job_id, status="running", progress=progress_message)
        with _generation_jobs_lock:
            job = _generation_jobs.get(job_id)
            if job is not None:
                _append_generation_job_step(
                    job,
                    progress_message,
                    status="running",
                    stage=stage if isinstance(stage, str) else None,
                    source=source if isinstance(source, str) else None,
                    artifact=artifact,
                )

    report_progress(
        {
            "message": "开始生成任务",
            "stage": "director",
            "source": "story-route",
            "artifact": {
                "job_id": job_id,
                "story_id": story_id,
                "used_modules": ["director_agent", "writer_agent", "memory_agent", "reviewer_agent"],
                "inputs": {
                    "story_id": story_id,
                    "pipeline": "generate_next_chapter",
                },
                "outputs": {
                    "flow": ["读取角色卡", "读取大纲", "生成剧情", "写作正文", "复核修订", "写入章节"],
                },
            },
        }
    )
    try:
        with generation_progress(report_progress):
            bundle = _generate_story_chapter(story_id)
    except SimulationFailedError as exc:
        _update_generation_job(job_id, status="failed", progress="生成失败", error=_simulation_failed_detail(exc))
        with _generation_jobs_lock:
            job = _generation_jobs.get(job_id)
            if job is not None:
                _append_generation_job_step(
                    job,
                    {
                        "message": "生成失败",
                        "stage": "orchestrator",
                        "source": "story-route",
                        "artifact": {
                            "error": _simulation_failed_detail(exc),
                            "job_id": job_id,
                            "story_id": story_id,
                        },
                    },
                    status="error",
                )
    except Exception as exc:  # pragma: no cover - background safety net
        _update_generation_job(job_id, status="failed", progress="生成失败", error=user_facing_generation_error(exc))
        with _generation_jobs_lock:
            job = _generation_jobs.get(job_id)
            if job is not None:
                _append_generation_job_step(
                    job,
                    {
                        "message": "生成失败",
                        "stage": "orchestrator",
                        "source": "story-route",
                        "artifact": {
                            "error": user_facing_generation_error(exc),
                            "job_id": job_id,
                            "story_id": story_id,
                        },
                    },
                    status="error",
                )
    else:
        _update_generation_job(
            job_id,
            status="completed",
            progress="生成完成",
            chapter_number=bundle.chapter_number,
            error="",
        )
        with _generation_jobs_lock:
            job = _generation_jobs.get(job_id)
            if job is not None:
                _append_generation_job_step(
                    job,
                    {
                        "message": "生成完成",
                        "stage": "orchestrator",
                        "source": "story-route",
                        "artifact": {
                            "job_id": job_id,
                            "story_id": story_id,
                            "chapter_number": bundle.chapter_number,
                        },
                    },
                    status="done",
                )
    finally:
        with _generation_jobs_lock:
            if _active_generation_jobs.get(story_id) == job_id:
                _active_generation_jobs.pop(story_id, None)


def _automation_revision_instructions(result: dict) -> list[str]:

    instructions: list[str] = []

    must_fix = result.get("must_fix", [])

    if isinstance(must_fix, list):

        instructions.extend(f"Automation must fix: {item}" for item in must_fix if str(item).strip())

    revision_instructions = result.get("revision_instructions", [])

    if isinstance(revision_instructions, list):

        instructions.extend(

            f"Automation revision instruction: {item}"

            for item in revision_instructions

            if str(item).strip()

        )

    return instructions or ["Automation review requested a bounded revision while preserving continuity."]





def _local_automation_review_result(project: NovelProject, record, bundle, *, include_body: bool) -> dict:

    review = _build_agent_review(project, record, bundle, include_body=include_body).model_dump()

    recommendation = review.get("recommendation", {})

    if not isinstance(recommendation, dict):

        recommendation = {}

    local_action = str(recommendation.get("action", "revise"))

    action = "approve" if local_action == "continue" else "revise"

    return {

        "schema_version": "automation-review-result/v1",

        "action": action,

        "summary": recommendation.get("reason", ""),

        "must_fix": recommendation.get("must_fix", []) if isinstance(recommendation.get("must_fix", []), list) else [],

        "revision_instructions": recommendation.get("revision_plan", [])

        if isinstance(recommendation.get("revision_plan", []), list)

        else [],

        "risk_flags": [],

    }





def _openclaw_automation_review_result(project: NovelProject, record, bundle, *, include_body: bool) -> dict:

    if call_openclaw_review is None:

        return {

            "schema_version": "automation-review-result/v1",

            "action": "pause",

            "summary": "OpenClaw reviewer is not available in this API process.",

            "must_fix": [],

            "revision_instructions": [],

            "risk_flags": ["openclaw_unavailable"],

        }

    review_package = {

        "schema_version": "openclaw-review-request/v1",

        "provider_target": "openclaw",

        "project_id": project.project_id,

        "expected_response_schema": "openclaw-review-result/v1",

        "context": _build_agent_context(project, recent_chapters=3, include_body=include_body).model_dump(),

        "review": _build_agent_review(project, record, bundle, include_body=include_body).model_dump(),

        "instructions": {

            "role": "independent_webnovel_editor",

            "allowed_actions": ["approve", "revise", "pause"],

            "return_json_only": True,

        },

    }

    try:

        return call_openclaw_review(

            review_package,

            openclaw_command="openclaw",

            openclaw_agent="main",

            timeout_seconds=600,

            local=True,

        )

    except Exception as exc:

        return {

            "schema_version": "automation-review-result/v1",

            "action": "pause",

            "summary": f"OpenClaw review failed: {exc}",

            "must_fix": [],

            "revision_instructions": [],

            "risk_flags": ["openclaw_failed"],

        }





def _automation_review_result(project: NovelProject, record, bundle, *, provider: str, include_body: bool) -> dict:

    if provider == "openclaw":

        return _openclaw_automation_review_result(project, record, bundle, include_body=include_body)

    return _local_automation_review_result(project, record, bundle, include_body=include_body)





def _run_project_automation_job(job_id: str, payload: ProjectAutomationJobRequest) -> None:

    project_id = str(_automation_jobs[job_id]["project_id"])

    story_id = str(_automation_jobs[job_id]["story_id"])

    revision_attempts = 0



    def report_progress(message: str) -> None:

        _update_automation_job(job_id, status="running", progress=message)



    try:

        _update_automation_job(job_id, status="running", phase="environment", progress="preparing story environment")

        project = store.get_project(project_id)

        record = store.get(story_id)

        if project is None:

            raise RuntimeError("project_not_found")

        if record is None:

            raise RuntimeError("story_not_found")



        _update_automation_job(job_id, phase="generating", progress="generating chapter")

        with generation_progress(report_progress):

            bundle = _generate_story_chapter(story_id)

        _update_automation_job(

            job_id,

            phase="reviewing",

            progress="reviewing generated chapter",

            chapter_number=bundle.chapter_number,

        )



        while True:

            project = store.get_project(project_id)

            record = store.get(story_id)

            if project is None or record is None or not record.history:

                raise RuntimeError("automation_state_missing")

            bundle = record.history[-1]

            result = _automation_review_result(

                project,

                record,

                bundle,

                provider=payload.review_provider,

                include_body=payload.include_body,

            )

            action = str(result.get("action", "pause"))

            _update_automation_job(

                job_id,

                final_action=action,

                chapter_number=bundle.chapter_number,

                progress=f"review action: {action}",

            )

            if action == "approve":

                _update_automation_job(

                    job_id,

                    status="completed",

                    phase="completed",

                    progress="automation completed",

                    revision_attempts=revision_attempts,

                )

                break

            if action != "revise":

                _update_automation_job(

                    job_id,

                    status="paused",

                    phase="paused",

                    progress=str(result.get("summary", "") or "automation paused by reviewer"),

                    revision_attempts=revision_attempts,

                )

                break

            if revision_attempts >= payload.max_revisions:

                _update_automation_job(

                    job_id,

                    status="paused",

                    phase="paused",

                    progress="automation paused: revision limit reached",

                    revision_attempts=revision_attempts,

                )

                break



            _update_automation_job(job_id, phase="revising", progress="applying reviewer revision")

            _revise_latest_chapter(

                project,

                record,

                bundle,

                AgentReviseRequest(

                    chapter_number=bundle.chapter_number,

                    instructions=_automation_revision_instructions(result),

                    include_body=False,

                ),

            )

            revision_attempts += 1

            _update_automation_job(

                job_id,

                phase="reviewing",

                progress="reviewing revised chapter",

                revision_attempts=revision_attempts,

            )

    except SimulationFailedError as exc:

        _update_automation_job(job_id, status="failed", phase="failed", progress="generation failed", error=_simulation_failed_detail(exc))

    except HTTPException as exc:

        _update_automation_job(job_id, status="failed", phase="failed", progress="automation failed", error=str(exc.detail))

    except Exception as exc:  # pragma: no cover - background safety net

        _update_automation_job(job_id, status="failed", phase="failed", progress="automation failed", error=str(exc))

    finally:

        with _automation_jobs_lock:

            if _active_automation_jobs.get(project_id) == job_id:

                _active_automation_jobs.pop(project_id, None)





def _serialize_story(story_id: str) -> StoryResponse:

    record = store.get(story_id)

    if record is None:

        raise HTTPException(status_code=404, detail="story_not_found")

    return StoryResponse(

        story_id=record.story.story_id,

        outline=record.story.outline,

        genre=record.story.genre,

        style=record.story.style,

        current_chapter=record.story.current_chapter,

        agent_settings=record.story.agent_settings.model_dump(),

        agent_runtime=record.story.agent_runtime.model_dump(),

        author_constraints=list(record.story.author_constraints),

        writing_lessons=list(record.story.writing_lessons),

        world_facts=list(record.story.world_facts),

        characters=[character.model_dump() for character in record.story.characters],

        history=[_serialize_chapter_bundle(bundle, record.story.world_facts) for bundle in record.history],

        parent_story_id=record.parent_story_id,

        branched_from_chapter=record.branched_from_chapter,

    )





def _serialize_story_summary(record) -> StorySummaryResponse:

    return StorySummaryResponse(

        story_id=record.story.story_id,

        current_chapter=record.story.current_chapter,

        parent_story_id=record.parent_story_id,

        branched_from_chapter=record.branched_from_chapter,

    )





def _serialize_project(project: NovelProject) -> ProjectResponse:

    branches = [_serialize_story_summary(record) for record in store.list_project_stories(project.project_id)]

    return ProjectResponse(

        project_id=project.project_id,

        title=project.title,

        source_path=project.source_path,

        seed_outline=project.seed_outline,

        world_summary=project.world_summary,

        current_focus=project.current_focus,

        author_constraints=project.author_constraints,

        world_blueprint=project.world_blueprint,

        character_profiles=project.character_profiles,

        relationship_graph=project.relationship_graph,

        enabled_skill_ids=project.enabled_skill_ids,
        enabled_skill_module_ids=(
            list(project.enabled_skill_module_ids)
            if project.enabled_skill_module_ids is not None
            else []
        ),
        skill_module_selection_mode=(
            "legacy_all"
            if project.enabled_skill_module_ids is None
            else "explicit"
        ),

        status=project.status,

        pipeline_stage=project.pipeline_stage,

        active_story_id=project.active_story_id,

        project_lifecycle=project.project_lifecycle,

        archived_at=project.archived_at,

        trashed_at=project.trashed_at,

        branches=branches,

    )





def _serialize_project_summary(project: NovelProjectSummary | NovelProject) -> ProjectSummaryResponse:

    current_chapter = 0

    if project.active_story_id:

        active_story = store.get(project.active_story_id, include_history=False)

        if active_story is not None:

            current_chapter = active_story.story.current_chapter

    return ProjectSummaryResponse(

        project_id=project.project_id,

        title=project.title,

        status=project.status,

        pipeline_stage=project.pipeline_stage,

        active_story_id=project.active_story_id,

        current_chapter=current_chapter,

        source_path=project.source_path,

        project_lifecycle=project.project_lifecycle,

        archived_at=project.archived_at,

        trashed_at=project.trashed_at,

    )





def _quality_context(quality_report: dict) -> dict:

    writing_review = quality_report.get("writing_review", {}) if isinstance(quality_report, dict) else {}

    if not isinstance(writing_review, dict):

        writing_review = {}

    context = {

        "ok": quality_report.get("ok") if isinstance(quality_report, dict) else None,

        "issues": quality_report.get("issues", []) if isinstance(quality_report, dict) else [],

        "writing_review": {

            "pass": writing_review.get("pass"),

            "scores": writing_review.get("scores", {}),

            "issues": writing_review.get("issues", []),

            "revision_plan": writing_review.get("revision_plan", []),

            "prose_quality_review": writing_review.get("prose_quality_review", {}),

            "adversarial_cut_review": writing_review.get("adversarial_cut_review", {}),

            "world_state_review": writing_review.get("world_state_review", {}),

            "reader_agent_review": writing_review.get("reader_agent_review", {}),

            "editor_agent_review": writing_review.get("editor_agent_review", {}),

            "reviewer_agent_review": writing_review.get("reviewer_agent_review", {}),

        },

        "simplified_review": build_simplified_review(quality_report),

    }

    if isinstance(quality_report, dict):

        for key in ("reader_agent_review", "editor_agent_review", "reviewer_agent_review", "ai_flavor_review", "cold_reader_review"):

            if isinstance(quality_report.get(key), dict):

                context[key] = quality_report[key]

        revision_safety = quality_report.get("revision_safety")

        if isinstance(revision_safety, dict):

            context["revision_safety"] = revision_safety

    return context





def _chapter_context(bundle, *, include_body: bool) -> dict:

    chapter_summary = bundle.chapter_summary if isinstance(bundle.chapter_summary, dict) else {}

    event_plan = bundle.event_plan if isinstance(bundle.event_plan, dict) else {}

    context = {

        "chapter_number": bundle.chapter_number,

        "chapter_title": bundle.chapter_title,

        "body_chars": len(bundle.body or ""),

        "summary": chapter_summary.get("summary", ""),

        "facts": chapter_summary.get("facts", []),

        "unresolved_threads": chapter_summary.get("unresolved_threads", []),

        "next_focus": chapter_summary.get("next_focus", ""),

        "next_outline": bundle.next_outline,

        "event_plan": {

            "next_focus": event_plan.get("next_focus", ""),

            "world_reactions": event_plan.get("world_reactions", []),

            "stakes": event_plan.get("stakes", ""),

        },

        "quality_report": _quality_context(bundle.quality_report if isinstance(bundle.quality_report, dict) else {}),

    }

    if include_body:

        context["body"] = bundle.body

    return context





def _world_gaps(project: NovelProject, active_story: StoryState | None) -> list[dict]:

    world = project.world_blueprint if isinstance(project.world_blueprint, dict) else {}

    living_world = world.get("living_world") if isinstance(world.get("living_world"), dict) else {}

    gaps: list[dict] = []

    def add(area: str, message: str, suggested_action: str, severity: str = "medium") -> None:
        gaps.append({
            "area": area,
            "severity": severity,
            "message": str(message),
            "suggested_action": str(suggested_action),
        })

    if not project.character_profiles:
        add("character_profiles", "角色资料不足，模型难以稳定区分人物动机、性格和说话方式。", "补齐主角、主要角色、NPC 的角色档案。", "high")

    if not project.relationship_graph:
        add("relationship_graph", "角色-势力关系图为空，长篇会容易单线推进。", "补齐关系图中的信任、敌对、依赖、冲突、同盟关系。", "high")

    if not isinstance(world.get("npc_system"), dict) or not world.get("npc_system"):
        add("npc_system", "NPC 系统缺失，世界会缺少任务来源与边界。", "补齐 NPC 服务、任务入口、信息边界与行动限制。", "high")

    if not isinstance(world.get("quest_network"), dict) or not world.get("quest_network"):
        add("quest_network", "任务链缺失，章节目标和衔接不清晰。", "补齐任务类型、阶段、失败代价、NPC 牵引。", "high")

    if not isinstance(world.get("map_ecology"), dict) or not world.get("map_ecology"):
        add("map_ecology", "地图生态缺失，区域、资源和密度不足。", "补齐区域、资源点、怪物生态与商家分布。", "medium")

    if not isinstance(living_world.get("economy"), dict) or not living_world.get("economy"):
        add("economy", "经济系统不足，交易和收益变化不够完整。", "补齐定价机制、物流流程、手续费和波动规则。", "medium")

    if not project.author_constraints:
        add("author_constraints", "作者约束为空，模型无法长期稳定执行题材规则。", "补齐约束规则、禁忌项、核心术语与世界边界。", "medium")

    if active_story is not None and not active_story.world_facts:
        add("world_facts", "活跃故事缺少世界事实，后续生成可能无法完整引用世界规则。", "补齐世界事实并重做世界事实同步。")

    return gaps

def _story_context(story: StoryState) -> dict:

    return {

        "story_id": story.story_id,

        "outline": story.outline,

        "genre": story.genre,

        "style": story.style,

        "current_chapter": story.current_chapter,

        "author_constraints": list(story.author_constraints),

        "world_facts": list(story.world_facts),

        "progression_ledger": story.progression_ledger,

        "characters": [character.model_dump() for character in story.characters],

        "timeline": [event.model_dump() for event in story.timeline[-8:]],

        "foreshadowing": [item.model_dump() for item in story.foreshadowing[-12:]],

        "chapter_summaries": [summary.model_dump() for summary in story.chapter_summaries[-8:]],

        "memory_index": [entry.model_dump() for entry in story.memory_index[-8:]],

        "arc_recaps": [recap.model_dump() for recap in story.arc_recaps[-3:]],

        "agent_runtime": story.agent_runtime.model_dump(),

    }





def _build_agent_context(project: NovelProject, *, recent_chapters: int, include_body: bool) -> AgentContextResponse:

    recent_limit = max(1, min(int(recent_chapters), 10))

    branches = [_serialize_story_summary(record).model_dump() for record in store.list_project_stories(project.project_id)]

    active_record = store.get(project.active_story_id) if project.active_story_id else None

    active_story = active_record.story if active_record else None

    if active_story is not None:
        _sync_project_context_for_story(project, active_story, has_history=bool(active_record.history))

    recent = []

    if active_record is not None:
        recent = [_chapter_context(bundle, include_body=include_body) for bundle in active_record.history[-recent_limit:]]

    gaps = _world_gaps(project, active_story)

    return AgentContextResponse(
        project={
            "project_id": project.project_id,
            "title": project.title,
            "status": project.status,
            "pipeline_stage": project.pipeline_stage,
            "active_story_id": project.active_story_id,
            "source_path": project.source_path,
            "seed_outline": project.seed_outline,
            "world_summary": project.world_summary,
            "current_focus": project.current_focus,
            "author_constraints": list(project.author_constraints),
        },
        active_story=_story_context(active_story) if active_story is not None else None,
        branches=branches,
        world={
            "blueprint": project.world_blueprint,
            "character_profiles": project.character_profiles,
            "relationship_graph": project.relationship_graph,
            "gaps": gaps,
        },
        recent_chapters=recent,
        controls={
            "suggested_tools": [
                "inspect_world_gaps",
                "review_chapter",
                "revise_chapter",
                "generate_chapter",
                "rollback_chapter",
                "update_constraints",
            ],
            "next_actions": [
                "优先处理 high severity 的 world.gaps 条目，避免世界状态失真。",
                "复查最近章节后决定继续生成还是改写。",
                "生成前确认 current_focus 与下章目标一致。",
            ],
        },
    )

def _select_review_chapter(record, chapter_number: int | None):

    if not record.history:

        raise HTTPException(status_code=404, detail="chapter_not_found")

    if chapter_number is None:

        return record.history[-1]

    for bundle in record.history:

        if bundle.chapter_number == chapter_number:

            return bundle

    raise HTTPException(status_code=404, detail="chapter_not_found")





def _review_recommendation(quality_report: dict) -> dict:

    simplified = build_simplified_review(quality_report)

    blocking = [item["message"] for item in simplified["issues"] if item.get("severity") == "blocking"]

    action = "revise" if simplified["has_hard_errors"] else "continue"

    return {
        "action": action,
        "reason": (
            "审查通过，继续生成下一步。"
            if action == "continue"
            else "仍有阻断问题，先做修正后再生成。"
        ),
        "must_fix": blocking,
        "revision_plan": [item["suggestion"] for item in simplified["issues"] if item.get("severity") == "blocking"],
    }

def _build_agent_review(project: NovelProject, record, bundle, *, include_body: bool) -> AgentReviewResponse:

    serialized = _serialize_chapter_bundle(bundle, record.story.world_facts)

    quality_report = serialized.get("quality_report", {})

    if not isinstance(quality_report, dict):

        quality_report = {}

    chapter = _chapter_context(bundle, include_body=include_body)
    chapter["quality_report"] = _quality_context(quality_report)
    packet_story = _story_state_before_chapter(record, bundle.chapter_number)
    _sync_project_context_for_story(project, packet_story, has_history=bundle.chapter_number > 1)
    writing_packet = build_codex_writing_packet(packet_story, bundle, chapter_number=bundle.chapter_number)
    governance_gate = writing_packet.get("governance_gate", {}) if isinstance(writing_packet, dict) else {}

    return AgentReviewResponse(

        project={

            "project_id": project.project_id,

            "title": project.title,

            "status": project.status,

            "pipeline_stage": project.pipeline_stage,

            "active_story_id": project.active_story_id,

        },

        story={

            "story_id": record.story.story_id,

            "outline": record.story.outline,

            "genre": record.story.genre,

            "style": record.story.style,

            "current_chapter": record.story.current_chapter,

        },

        chapter=chapter,

        review={

            "quality": chapter["quality_report"],

            "writing_review": chapter["quality_report"].get("writing_review", {}),

            "world_state_review": chapter["quality_report"].get("writing_review", {}).get("world_state_review", {}),

        },

        recommendation=_review_recommendation(quality_report),

        controls={

            "governance_gate": governance_gate,

            "suggested_tools": [

                "revise_chapter",

                "generate_chapter",

                "rollback_chapter",

                "update_constraints",

                "inspect_world_gaps",

            ],

            "safe_default": "按 recommendation.must_fix 列表处理当前章，修复后继续生成下一章。",

        },

    )



def _build_agent_revision_response(

    project: NovelProject,

    record,

    bundle,

    *,

    previous_body_chars: int,

    instructions: list[str],

    include_body: bool,

    source: str = "writer_agent",

) -> AgentRevisionResponse:

    serialized = _serialize_chapter_bundle(bundle, record.story.world_facts)

    quality_report = serialized.get("quality_report", {})

    if not isinstance(quality_report, dict):

        quality_report = {}

    chapter = _chapter_context(bundle, include_body=include_body)

    chapter["quality_report"] = _quality_context(quality_report)

    return AgentRevisionResponse(

        project={

            "project_id": project.project_id,

            "title": project.title,

            "status": project.status,

            "pipeline_stage": project.pipeline_stage,

            "active_story_id": project.active_story_id,

        },

        story={

            "story_id": record.story.story_id,

            "outline": record.story.outline,

            "genre": record.story.genre,

            "style": record.story.style,

            "current_chapter": record.story.current_chapter,

        },

        chapter=chapter,

        review={

            "quality": chapter["quality_report"],

            "writing_review": chapter["quality_report"].get("writing_review", {}),

        },

        revision={

            "changed": previous_body_chars != len(bundle.body or ""),

            "previous_body_chars": previous_body_chars,

            "revised_body_chars": len(bundle.body or ""),

            "instructions": instructions,

            "source": source,

        },

        controls={

            "suggested_tools": [

                "review_chapter",

                "generate_chapter",

                "rollback_chapter",

                "update_constraints",

            ],

            "safe_default": "复查修正后再生成，当前章通过后继续下一章。",

        },

    )



def _revise_latest_chapter(project: NovelProject, record, bundle, payload: AgentReviseRequest) -> AgentRevisionResponse:

    latest_chapter = record.history[-1].chapter_number if record.history else None

    if bundle.chapter_number != latest_chapter:

        raise HTTPException(status_code=409, detail="chapter_not_latest")



    serialized = _serialize_chapter_bundle(bundle, record.story.world_facts)

    quality_report = serialized.get("quality_report", {})

    if not isinstance(quality_report, dict):

        quality_report = {}

    review = quality_report.get("writing_review", {})

    if not isinstance(review, dict):

        review = {}



    previous_body_chars = len(bundle.body or "")

    revised_body, revised_quality, error = engine.orchestrator.revise_chapter_body(

        record.story,

        bundle,

        review,

        payload.instructions,

    )

    if error:

        raise HTTPException(status_code=502, detail=f"revision_failed: {error}")



    revised_bundle = bundle.model_copy(deep=True)

    revised_bundle.body = revised_body

    revised_bundle.quality_report = revised_quality

    if bundle.chapter_number <= 1:

        base_story = record.initial_story.model_copy(deep=True)

    else:

        base_story = record.history[bundle.chapter_number - 2].updated_story.model_copy(deep=True)

    _sync_project_context_for_story(project, base_story, has_history=bundle.chapter_number > 1)

    revised_bundle = engine.orchestrator.refresh_revised_bundle_metadata(base_story, revised_bundle)

    updated_record = store.replace_chapter_bundle(record.story.story_id, revised_bundle)

    return _build_agent_revision_response(

        project,

        updated_record,

        revised_bundle,

        previous_body_chars=previous_body_chars,

        instructions=payload.instructions,

        include_body=payload.include_body,

        source="writer_agent",

    )





@router.post("/projects")

def create_project(payload: CreateProjectRequest) -> ProjectResponse:

    project = NovelProject(

        project_id=payload.project_id,

        title=payload.title,

        source_path=payload.source_path,

        seed_outline=payload.seed_outline,

        world_summary=payload.world_summary,

        current_focus=payload.current_focus,

        author_constraints=payload.author_constraints,

        world_blueprint=payload.world_blueprint,

        character_profiles=payload.character_profiles,

        relationship_graph=payload.relationship_graph,

        enabled_skill_ids=payload.enabled_skill_ids,
        enabled_skill_module_ids=payload.enabled_skill_module_ids,

        status="simulating" if payload.active_story_id else "draft",

        pipeline_stage=payload.pipeline_stage if not payload.active_story_id else "environment_ready",

        active_story_id=payload.active_story_id,

    )

    store.create_project(project)

    if payload.active_story_id:

        store.attach_story_to_project(payload.project_id, payload.active_story_id)

        store.sync_project_context(payload.project_id)

    return _serialize_project(project)





@router.get("/projects")

def list_projects(lifecycle: Literal["active", "archived", "trashed"] = "active") -> list[ProjectSummaryResponse]:

    return [_serialize_project_summary(project) for project in store.list_projects(lifecycle=lifecycle)]



def _assert_project_lifecycle_mutation_allowed(project: NovelProject) -> None:

    with _automation_jobs_lock:

        automation_job_id = _active_automation_jobs.get(project.project_id)

        automation_job = _automation_jobs.get(automation_job_id or "")

        if automation_job and automation_job.get("status") in {"queued", "running"}:

            raise HTTPException(status_code=409, detail="project_generation_in_progress")

    story_ids = {record.story.story_id for record in store.list_project_stories(project.project_id)}

    with _generation_jobs_lock:

        for story_id in story_ids:

            job_id = _active_generation_jobs.get(story_id)

            job = _generation_jobs.get(job_id or "")

            if job and job.get("status") in {"queued", "running"}:

                raise HTTPException(status_code=409, detail="project_generation_in_progress")



def _project_for_lifecycle_mutation(project_id: str) -> NovelProject:

    project = store.get_project(project_id)

    if project is None:

        raise HTTPException(status_code=404, detail="project_not_found")

    _assert_project_lifecycle_mutation_allowed(project)

    return project



@router.post("/projects/{project_id}/archive")

def archive_project(project_id: str) -> ProjectResponse:

    project = _project_for_lifecycle_mutation(project_id)

    if project.project_lifecycle == "trashed":

        raise HTTPException(status_code=409, detail="project_is_trashed")

    project.project_lifecycle = "archived"

    project.archived_at = datetime.now(timezone.utc).isoformat()

    store.update_project(project)

    return _serialize_project(project)



@router.post("/projects/{project_id}/trash")

def trash_project(project_id: str) -> ProjectResponse:

    project = _project_for_lifecycle_mutation(project_id)

    if project.project_lifecycle != "trashed":

        project.pre_trash_lifecycle = "archived" if project.project_lifecycle == "archived" else "active"

    project.project_lifecycle = "trashed"

    project.trashed_at = datetime.now(timezone.utc).isoformat()

    store.update_project(project)

    return _serialize_project(project)



@router.post("/projects/{project_id}/restore")

def restore_project(project_id: str) -> ProjectResponse:

    project = _project_for_lifecycle_mutation(project_id)

    project.project_lifecycle = project.pre_trash_lifecycle if project.project_lifecycle == "trashed" else "active"

    project.archived_at = "" if project.project_lifecycle == "active" else project.archived_at

    project.trashed_at = ""

    store.update_project(project)

    return _serialize_project(project)





@router.delete("/projects/{project_id}")

def delete_project(project_id: str, confirm_title: str) -> DeleteProjectResponse:

    project = store.get_project(project_id)

    if project is None:

        raise HTTPException(status_code=404, detail="project_not_found")

    _assert_project_lifecycle_mutation_allowed(project)

    if project.project_lifecycle != "trashed":

        raise HTTPException(status_code=409, detail="project_must_be_trashed")

    if confirm_title != project.title:

        raise HTTPException(status_code=422, detail="project_title_confirmation_mismatch")

    story_ids = [record.story.story_id for record in store.list_project_stories(project_id)]

    store.delete_project(project_id, delete_stories=True)

    return DeleteProjectResponse(deleted=True, project_id=project_id, deleted_story_ids=story_ids)





@router.get("/projects/{project_id}")

def get_project(project_id: str) -> ProjectResponse:

    project = store.get_project(project_id)

    if project is None:

        raise HTTPException(status_code=404, detail="project_not_found")

    if project.project_lifecycle == "trashed":

        raise HTTPException(status_code=404, detail="project_not_found")

    return _serialize_project(project)





@router.get("/projects/{project_id}/agent-context")

def get_project_agent_context(

    project_id: str,

    recent_chapters: int = 3,

    include_body: bool = False,

) -> AgentContextResponse:

    store.sync_project_context(project_id)

    project = store.get_project(project_id)

    if project is None:

        raise HTTPException(status_code=404, detail="project_not_found")

    return _build_agent_context(project, recent_chapters=recent_chapters, include_body=include_body)





@router.get("/projects/{project_id}/agent-review")

def get_project_agent_review(

    project_id: str,

    chapter_number: int | None = None,

    include_body: bool = False,

) -> AgentReviewResponse:

    project = store.get_project(project_id)

    if project is None:

        raise HTTPException(status_code=404, detail="project_not_found")

    record = store.get(project.active_story_id) if project.active_story_id else None

    if record is None:

        raise HTTPException(status_code=404, detail="story_not_found")

    bundle = _select_review_chapter(record, chapter_number)

    return _build_agent_review(project, record, bundle, include_body=include_body)





@router.get("/projects/{project_id}/writing-packet")

def get_project_writing_packet(project_id: str, chapter_number: int | None = None) -> dict:

    project = store.get_project(project_id)

    if project is None:

        raise HTTPException(status_code=404, detail="project_not_found")

    record = store.get(project.active_story_id) if project.active_story_id else None

    if record is None:

        raise HTTPException(status_code=404, detail="story_not_found")

    target_chapter = chapter_number or (record.story.current_chapter + 1)

    bundle = None

    if record.history:

        if target_chapter <= record.story.current_chapter:

            bundle = _select_review_chapter(record, target_chapter)

        elif target_chapter == record.story.current_chapter + 1:

            bundle = record.history[-1]

        else:

            raise HTTPException(status_code=400, detail="target_chapter_too_far")

    packet_story = _story_state_before_chapter(record, target_chapter)

    _sync_project_context_for_story(project, packet_story, has_history=target_chapter > 1)

    packet = build_codex_writing_packet(packet_story, bundle, chapter_number=target_chapter)

    blueprint = (
        project.world_blueprint
        if isinstance(project.world_blueprint, dict)
        else {}
    )
    genre_ids = blueprint.get("genre_plugin_ids")
    raw_genre_id = (
        str(genre_ids[0]).strip()
        if isinstance(genre_ids, list) and genre_ids
        else str(packet_story.genre or "").strip()
    )
    genre_id = resolve_novel_type_id(raw_genre_id) or raw_genre_id
    writer_skill_context = writer_skill_pack_prompt_context(
        project.enabled_skill_ids,
        enabled_module_ids=project.enabled_skill_module_ids,
        genre_id=genre_id,
        max_chars_per_pack=2600,
    )
    packet["skill_context"] = (
        {"writer": writer_skill_context}
        if writer_skill_context
        else {}
    )

    return packet





@router.get("/projects/{project_id}/prompt-preview")

def get_project_prompt_preview(project_id: str, chapter_number: int | None = None) -> dict:

    from packages.story_core.orchestrator import (

        StoryOrchestrator,

        _character_context_for_prompt,

        _genre_context_for_prompt,

        _story_snapshot,

    )

    from packages.story_core.prompt_modules import modules_for_stage, prompt_module_catalog

    from packages.story_core.writing_taskbook import format_taskbook_brief_section



    project = store.get_project(project_id)

    if project is None:

        raise HTTPException(status_code=404, detail="project_not_found")

    record = store.sync_project_context(project_id)

    if record is None:

        raise HTTPException(status_code=404, detail="story_not_found")



    target = int(chapter_number or record.story.current_chapter or 1)

    bundle = next((item for item in record.history if item.chapter_number == target), None)

    if bundle is None and target > record.story.current_chapter + 1:

        raise HTTPException(status_code=400, detail="target_chapter_too_far")

    preview_story = _story_state_before_chapter(record, target)

    _sync_project_context_for_story(project, preview_story, has_history=target > 1)



    bundle_data = bundle.model_dump() if bundle is not None else {}

    plan = {
        key: bundle_data.get(key)
        for key in (
            "character_moves",
            "chapter_intent",
            "memory_constraints",
            "event_plan",
            "chapter_seed",
            "simulation_plan",
            "world_events",
            "scene_cards",
        )
        if bundle_data.get(key) not in (None, "", [], {})
    }

    taskbook = plan.get("writing_taskbook")

    body = str(bundle_data.get("body") or "")

    review = bundle_data.get("quality_report") if isinstance(bundle_data.get("quality_report"), dict) else {}

    packet = build_codex_writing_packet(preview_story, bundle, chapter_number=target)

    packet_preview = {
        key: packet.get(key)
        for key in (
            "chapter_number",
            "chapter_title",
            "goal",
            "target_chars",
            "story",
            "plot_simulation",
            "scene_contracts",
            "hard_locks",
            "style_rules",
            "author_constraints",
            "world_facts",
            "continuity",
        )
        if packet.get(key) not in (None, "", [], {})
    }


    def entry(

        *,

        key: str,

        title: str,

        agent: str,

        stage: str,

        content: str,

        source: str,

        description: str,

        module_keys: list[str] | None = None,

    ) -> dict:

        return {

            "key": key,

            "title": title,

            "agent": agent,

            "stage": stage,

            "source": source,

            "description": description,

            "content": content,

            "chars": len(content),

            "module_keys": module_keys or [],

        }



    orchestrator = StoryOrchestrator()

    modules = [

        entry(

            key="core_context",

            title="核心上下文",

            agent="context",

            stage="story_context",

            content=json.dumps(_story_snapshot(preview_story), ensure_ascii=False, indent=2),

            source="orchestrator._story_snapshot",

            description="主线、世界事件、账本和最近记忆摘要。",

        ),

        entry(

            key="character_context",

            title="本章角色侧写",

            agent="context",

            stage="角色侧写",

            content=json.dumps(_character_context_for_prompt(preview_story, plan), ensure_ascii=False, indent=2),

            source="orchestrator._character_context_for_prompt",

            description="提取当前章节需要的角色信息与约束。",

        ),

        entry(

            key="genre_context",

            title="题材写法",

            agent="context",

            stage="题材策略",

            content=json.dumps(_genre_context_for_prompt(preview_story, target, plan), ensure_ascii=False, indent=2),

            source="orchestrator._genre_context_for_prompt",

            description="按当前小说类型给出写作边界与风格要求，避免混用风格。",

        ),

        entry(

            key="packet_context",

            title="写作预览",

            agent="codex",

            stage="写作预览",

            content=json.dumps(packet_preview, ensure_ascii=False, indent=2),

            source="writing_packet.compact_preview",

            description="展示面板使用的压缩写作快照，不含完整正文。",

        ),

    ]

    if isinstance(review, dict) and review:

        modules.append(

            entry(

                key="review_context",

                title="审查报告",

                agent="review",

                stage="审查报告",

                content=json.dumps(review, ensure_ascii=False, indent=2),

                source="chapter.quality_report",

                description="只在改写阶段读取，不改变正文生成。",

            )

        )

    if isinstance(taskbook, dict):

        modules.append(

            entry(

                key="writing_taskbook",

                title="本章方向",

                agent="context",

                stage="本章方向",

                content=format_taskbook_brief_section(taskbook),

                source="chapter.writing_taskbook",

                description="保留本章目标、场景推进与收束，不重复混用风格规则。",

            )

        )



    prompts = [

        entry(

            key="director_plan",

            title="章节规划补全 Prompt",

            agent="director",

            stage="规划生成",

            content=orchestrator._plan_prompt(preview_story, target),

            source="rebuilt_from_database_story",

            description="生成本章结构化计划，控制节奏和主轴冲突。",

            module_keys=["core_context", "genre_context"],

        ),

        entry(

            key="writer_body",

            title="整章正文 Prompt",

            agent="writer",

            stage="正文生成",

            content=orchestrator._body_prompt(preview_story, target, plan),

            source="rebuilt_from_database_story",

            description="整章正文实际提示词，按输出要求、本章方向、本章事实、出场人物和正文写法五块装配。",

            module_keys=["core_context", "character_context", "genre_context", "writing_taskbook"],

        ),

    ]

    if body.strip():

        body_placeholder = f"[原正文由 source_body 标注，面板不展示正文。当前正文长度 {len(body)} 字。]"

        prompts.extend(

            [

                entry(

                    key="revision",

                    title="审查改写 Prompt",

                    agent="writer",

                    stage="审查改写",

                    content=orchestrator._revision_prompt(preview_story, target, body_placeholder, plan, review),

                    source="rebuilt_from_database_chapter",

                    description="章节未通过时进入改写流程，先回看问题再给修订方向。",

                    module_keys=["core_context", "character_context", "genre_context", "review_context"],

                ),

            ]

        )

    prompts.append(

        entry(

            key="review_agents",

            title="阅读/编辑/审查 Agent 说明",

            agent="review",

            stage="质量审查",

            content="阅读、编辑和审查 Agent 读取当前正文与质量报告，当前无额外提示文本。",

            source="local_rule_based_review",

            description="说明审查阶段读取什么、如何给修订建议。",

            module_keys=["review_context"],

        )

    )



    return {

        "schema_version": "project-prompt-preview/v1",

        "project_id": project_id,

        "chapter_number": target,

        "chapter_title": bundle.chapter_title if bundle is not None else "",

        "source": "rebuilt_from_database_project",

        "has_chapter": bundle is not None,

        "module_catalog": prompt_module_catalog(),

        "stage_modules": {

            stage: [module.key for module in modules_for_stage(stage)]

            for stage in ("planning", "writing", "revision", "validation")

        },

        "modules": modules,

        "prompts": prompts,

    }



@router.post("/projects/{project_id}/agent-revise")

def revise_project_chapter(project_id: str, payload: AgentReviseRequest) -> AgentRevisionResponse:

    project = store.get_project(project_id)

    if project is None:

        raise HTTPException(status_code=404, detail="project_not_found")

    record = store.get(project.active_story_id) if project.active_story_id else None

    if record is None:

        raise HTTPException(status_code=404, detail="story_not_found")

    bundle = _select_review_chapter(record, payload.chapter_number)

    return _revise_latest_chapter(project, record, bundle, payload)





@router.post("/projects/{project_id}/automation-jobs")

def start_project_automation_job(

    project_id: str,

    payload: ProjectAutomationJobRequest = ProjectAutomationJobRequest(),

) -> ProjectAutomationJobResponse:

    project = store.get_project(project_id)

    if project is None:

        raise HTTPException(status_code=404, detail="project_not_found")

    if payload.review_provider not in {"local", "openclaw"}:

        raise HTTPException(status_code=400, detail="unsupported_review_provider")

    if not project.active_story_id:

        raise HTTPException(status_code=409, detail="active_story_required")

    if store.get(project.active_story_id) is None:

        raise HTTPException(status_code=404, detail="story_not_found")



    with _automation_jobs_lock:

        active_job_id = _active_automation_jobs.get(project_id)

        if active_job_id:

            active_job = _automation_jobs.get(active_job_id)

            if active_job and active_job.get("status") in {"queued", "running"}:

                return _automation_job_response(active_job)



        now = _now_iso()

        job_id = f"aj-{uuid4().hex[:12]}"

        job: dict[str, object] = {

            "job_id": job_id,

            "project_id": project_id,

            "story_id": project.active_story_id,

            "status": "queued",

            "phase": "queued",

            "progress": "automation queued",

            "chapter_number": None,

            "revision_attempts": 0,

            "max_revisions": payload.max_revisions,

            "final_action": "",

            "review_provider": payload.review_provider,

            "error": "",

            "created_at": now,

            "updated_at": now,

        }

        _automation_jobs[job_id] = job

        _active_automation_jobs[project_id] = job_id

        response = _automation_job_response(job)



    _automation_executor.submit(_run_project_automation_job, job_id, payload)

    return response





@router.get("/projects/{project_id}/automation-jobs/{job_id}")

def get_project_automation_job(project_id: str, job_id: str) -> ProjectAutomationJobResponse:

    with _automation_jobs_lock:

        job = _automation_jobs.get(job_id)

        if job is None or job.get("project_id") != project_id:

            raise HTTPException(status_code=404, detail="automation_job_not_found")

        return _automation_job_response(job)





@router.patch("/projects/{project_id}")

@router.put("/projects/{project_id}")

@_serialize_project_update

def update_project(project_id: str, payload: UpdateProjectRequest) -> ProjectResponse:

    project = store.get_project(project_id)

    if project is None:

        raise HTTPException(status_code=404, detail="project_not_found")



    if payload.title is not None:

        project.title = payload.title

    if payload.source_path is not None:

        project.source_path = payload.source_path

    if payload.seed_outline is not None:

        project.seed_outline = payload.seed_outline

    if payload.world_summary is not None:

        project.world_summary = payload.world_summary

    if payload.current_focus is not None:

        project.current_focus = payload.current_focus

    if payload.author_constraints is not None:

        project.author_constraints = payload.author_constraints

    if payload.world_blueprint is not None:
        world_blueprint_patch = dict(payload.world_blueprint)
        if "writing_style" in world_blueprint_patch:
            raw_writing_style = str(world_blueprint_patch.get("writing_style") or "").strip()
            normalized_writing_style = normalize_book_style(raw_writing_style)
            if raw_writing_style and not normalized_writing_style:
                raise HTTPException(status_code=400, detail="invalid_writing_style")
            world_blueprint_patch["writing_style"] = normalized_writing_style
        if "genre_plugin_ids" in world_blueprint_patch:
            raw_genre_ids = world_blueprint_patch.get("genre_plugin_ids")
            if raw_genre_ids is None:
                genre_values: list[Any] = []
            elif isinstance(raw_genre_ids, str):
                genre_values = [raw_genre_ids]
            elif isinstance(raw_genre_ids, list):
                genre_values = raw_genre_ids
            else:
                raise HTTPException(status_code=400, detail="invalid_novel_type")
            normalized_genre_ids: list[str] = []
            for value in genre_values:
                if not str(value or "").strip():
                    continue
                resolved_id = resolve_novel_type_id(value)
                if not resolved_id:
                    raise HTTPException(status_code=400, detail="invalid_novel_type")
                if resolved_id not in normalized_genre_ids:
                    normalized_genre_ids.append(resolved_id)
            world_blueprint_patch["genre_plugin_ids"] = normalized_genre_ids
        current_blueprint = project.world_blueprint if isinstance(project.world_blueprint, dict) else {}
        project.world_blueprint = {**current_blueprint, **world_blueprint_patch}

    if payload.character_profiles is not None:

        project.character_profiles = payload.character_profiles

    if payload.relationship_graph is not None:

        project.relationship_graph = payload.relationship_graph

    if payload.enabled_skill_ids is not None:

        project.enabled_skill_ids = payload.enabled_skill_ids

    if payload.enabled_skill_module_ids is not None:

        project.enabled_skill_module_ids = payload.enabled_skill_module_ids

    if payload.status is not None:

        project.status = payload.status

    if payload.pipeline_stage is not None:

        project.pipeline_stage = payload.pipeline_stage

    if payload.active_story_id is not None:

        project.active_story_id = payload.active_story_id



    store.update_project(project)
    if payload.world_blueprint is not None and "writing_style" in payload.world_blueprint:
        store.sync_project_context(project_id)

    return _serialize_project(project)





@router.post("/projects/{project_id}/enrich-world")

def enrich_project_world_route(project_id: str) -> ProjectResponse:

    project = store.get_project(project_id)

    if project is None:

        raise HTTPException(status_code=404, detail="project_not_found")

    if project.active_story_id:

        raise HTTPException(status_code=409, detail="world_enrichment_only_before_first_chapter")



    try:

        enriched = enrich_project_world(project)

    except WorldEnrichmentError as exc:

        detail = str(exc) or "world_enrichment_failed"

        status_code = 400 if detail == "missing_api_key" else 502

        raise HTTPException(status_code=status_code, detail=detail) from exc

    except Exception as exc:

        raise HTTPException(status_code=502, detail=f"world_enrichment_failed: {exc}") from exc



    enriched.pipeline_stage = "world_ready"

    store.update_project(enriched)

    return _serialize_project(enriched)





@router.post("/projects/{project_id}/enrich-rulebook")

def enrich_project_rulebook_route(project_id: str) -> ProjectResponse:

    project = store.get_project(project_id)

    if project is None:

        raise HTTPException(status_code=404, detail="project_not_found")



    try:

        enriched = enrich_project_rulebook(project)

    except WorldEnrichmentError as exc:

        detail = str(exc) or "world_rulebook_enrichment_failed"

        status_code = 400 if detail == "missing_api_key" else 502

        raise HTTPException(status_code=status_code, detail=detail) from exc

    except Exception as exc:

        raise HTTPException(status_code=502, detail=f"world_rulebook_enrichment_failed: {exc}") from exc



    if enriched.active_story_id:

        enriched.pipeline_stage = "simulating"

        enriched.status = "simulating"

    else:

        enriched.pipeline_stage = "world_ready"

    store.update_project(enriched)

    return _serialize_project(enriched)





@router.post("/projects/{project_id}/activate")

def activate_project_story(project_id: str, payload: ActivateProjectStoryRequest) -> ProjectResponse:

    if store.get_project(project_id) is None:

        raise HTTPException(status_code=404, detail="project_not_found")

    if store.get(payload.story_id) is None:

        raise HTTPException(status_code=404, detail="story_not_found")

    store.attach_story_to_project(project_id, payload.story_id)

    project = store.set_project_active_story(project_id, payload.story_id)

    return _serialize_project(project)





@router.post("/stories")

def create_story(payload: CreateStoryRequest) -> StoryResponse:

    agent_settings = payload.agent_settings

    if agent_settings == AgentSettings():

        agent_settings = get_runtime_strategy_settings()

    story = StoryState(

        story_id=payload.story_id,

        outline=payload.outline,

        genre=payload.genre,

        style=payload.style,

        current_chapter=0,

        agent_settings=agent_settings,

        characters=payload.characters,

    )

    store.create(story)

    return _serialize_story(payload.story_id)





@router.get("/stories")

def list_stories() -> list[StorySummaryResponse]:

    return [_serialize_story_summary(record) for record in store.list()]





@router.get("/stories/{story_id}")

def get_story(story_id: str) -> StoryResponse:

    return _serialize_story(story_id)





@router.post("/stories/{story_id}/generate")

def generate_next_chapter(story_id: str) -> dict:

    if store.get(story_id) is None:

        raise HTTPException(status_code=404, detail="story_not_found")

    try:

        bundle = _generate_story_chapter(story_id)

        return bundle.model_dump()

    except SimulationFailedError as exc:

        raise HTTPException(status_code=503, detail=_simulation_failed_detail(exc)) from exc





@router.post("/stories/{story_id}/generation-jobs")

def start_generation_job(story_id: str) -> GenerationJobResponse:
    if store.get(story_id) is None:
        raise HTTPException(status_code=404, detail="story_not_found")
    with _generation_jobs_lock:
        active_job_id = _active_generation_jobs.get(story_id)
        if active_job_id:
            active_job = _generation_jobs.get(active_job_id)
            if active_job:
                _reconcile_generation_job_locked(active_job)
            if active_job and active_job.get("status") in {"queued", "running"}:
                return _generation_job_response(active_job)

        now = _now_iso()
        record = store.get(story_id)
        job_id = f"gj-{uuid4().hex[:12]}"
        job: dict[str, object] = {
            "job_id": job_id,
            "story_id": story_id,
            "status": "queued",
            "progress": "重写任务启动",
            "chapter_number": None,
            "error": "",
            "steps": [
                {
                    "message": "重写任务启动",
                    "status": "queued",
                    "at": now,
                    "stage": "director",
                    "source": "story-route",
                    "artifact": {
                        "reason": "job_created",
                        "story_id": story_id,
                        "modules": ["outline_agent", "character_agent", "world_simulation", "memory", "writer_agent"],
                        "references": {
                            "character_cards": True,
                            "outline": True,
                            "world_state": True,
                        },
                        "inputs": {"current_chapter": record.story.current_chapter if record else 0},
                    },
                }
            ],
            "starting_chapter": record.story.current_chapter if record else 0,
            "created_at": now,
            "updated_at": now,
        }
        _generation_jobs[job_id] = job
        _active_generation_jobs[story_id] = job_id
        response = _generation_job_response(job)

    _generation_executor.submit(_run_generation_job, job_id, story_id)
    return response


@router.get("/stories/{story_id}/generation-jobs/current")

def get_current_generation_job(story_id: str) -> GenerationJobResponse:

    with _generation_jobs_lock:

        job: dict[str, object] | None = None

        active_job_id = _active_generation_jobs.get(story_id)

        if active_job_id:

            job = _generation_jobs.get(active_job_id)

        if job is None:

            candidates = [item for item in _generation_jobs.values() if item.get("story_id") == story_id]

            if candidates:

                job = max(candidates, key=lambda item: str(item.get("updated_at", "")))

        if job is None:

            raise HTTPException(status_code=404, detail="generation_job_not_found")

        _reconcile_generation_job_locked(job)

        return _generation_job_response(job)





@router.get("/stories/{story_id}/generation-jobs/{job_id}")

def get_generation_job(story_id: str, job_id: str) -> GenerationJobResponse:

    with _generation_jobs_lock:

        job = _generation_jobs.get(job_id)

        if job is None or job.get("story_id") != story_id:

            raise HTTPException(status_code=404, detail="generation_job_not_found")

        _reconcile_generation_job_locked(job)

        return _generation_job_response(job)





@router.post("/stories/{story_id}/rollback")

def rollback(story_id: str) -> StoryResponse:

    if store.get(story_id) is None:

        raise HTTPException(status_code=404, detail="story_not_found")

    store.rollback_last(story_id)

    return _serialize_story(story_id)





@router.post("/stories/{story_id}/branch")

def branch_story(story_id: str, payload: BranchStoryRequest) -> StoryResponse:

    if store.get(story_id) is None:

        raise HTTPException(status_code=404, detail="story_not_found")

    try:

        store.branch_from(story_id, payload.new_story_id, payload.from_chapter)

    except ValueError as exc:

        raise HTTPException(status_code=409, detail="story_exists") from exc

    except IndexError as exc:

        raise HTTPException(status_code=404, detail="chapter_not_found") from exc

    project_id = store.find_project_id_by_story(story_id)

    if project_id:

        store.attach_story_to_project(project_id, payload.new_story_id)

        store.set_project_active_story(project_id, payload.new_story_id)

    return _serialize_story(payload.new_story_id)





@router.post("/stories/{story_id}/rename")

def rename_story(story_id: str, payload: RenameStoryRequest) -> StoryResponse:

    if store.get(story_id) is None:

        raise HTTPException(status_code=404, detail="story_not_found")

    try:

        store.rename(story_id, payload.new_story_id)

    except ValueError as exc:

        raise HTTPException(status_code=409, detail="story_exists") from exc

    return _serialize_story(payload.new_story_id)





@router.delete("/stories/{story_id}")

def delete_story(story_id: str) -> DeleteStoryResponse:

    if store.get(story_id) is None:

        raise HTTPException(status_code=404, detail="story_not_found")

    try:

        deleted = store.delete(story_id)

    except ValueError as exc:

        detail = str(exc)

        if detail == "cannot_delete_root":

            raise HTTPException(status_code=409, detail=detail) from exc

        raise HTTPException(status_code=409, detail="story_has_children") from exc

    return DeleteStoryResponse(deleted=True, story_id=deleted.story.story_id)





@router.post("/stories/{story_id}/characters/{character_name}/freeze")

def freeze_character(story_id: str, character_name: str) -> StoryResponse:

    if store.get(story_id) is None:

        raise HTTPException(status_code=404, detail="story_not_found")

    try:

        store.freeze_character(story_id, character_name)

    except KeyError as exc:

        raise HTTPException(status_code=404, detail="character_not_found") from exc

    return _serialize_story(story_id)





@router.get("/prompt-templates")
def read_global_prompt_templates() -> dict[str, object]:
    templates = []
    for template in load_global_prompt_templates():
        default = get_default_prompt_template(template.key)
        templates.append(
            {
                **template.as_dict(),
                "source": "global_default" if template.content == default.content else "global_override",
            }
        )
    return {"schema_version": "prompt-templates/v1", "templates": templates}


@router.put("/prompt-templates/{template_key}")
def update_global_prompt_template(
    template_key: str,
    payload: PromptTemplateUpdateRequest,
) -> dict[str, object]:
    try:
        template = save_global_prompt_template(template_key, payload.content)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**template.as_dict(), "source": "global_override"}





def init_story_routes() -> APIRouter:

    return router



