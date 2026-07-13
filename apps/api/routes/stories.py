from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import re
from threading import Lock
import urllib.error
import urllib.request
from uuid import uuid4

from fastapi import APIRouter, HTTPException
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
    NovelProject,
    NovelProjectSummary,
    StoryState,
    default_fast_model_name,
    default_model_name,
)
from packages.story_core.orchestrator import _merge_writing_review_quality, _review_chapter_body
from packages.story_core.quality import validate_bundle
from packages.story_core.http_retry import RetryConfig, post_json_with_retry
from packages.story_core.runtime_config import (
    OpenAIRuntimeSettings,
    get_all_runtime_settings,
    get_runtime_strategy_settings,
    resolve_openai_runtime_settings,
    set_runtime_strategy_settings,
    set_all_runtime_settings,
)
from packages.story_core.skill_packs import skill_pack_prompt_context
from packages.story_core.simplified_review import build_simplified_review
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
GENERATION_JOB_STALE_SECONDS = 15 * 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    status: str = "draft"
    pipeline_stage: str = "imported"
    active_story_id: str = ""
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


class RuntimeSettingsResponse(BaseModel):
    global_: OpenAIRuntimeSettings = Field(alias="global")
    agents: dict[str, OpenAIRuntimeSettings] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class RuntimeStrategyResponse(BaseModel):
    mode: str = "LLM-assisted"
    global_model: str = Field(default_factory=default_model_name)
    character_model: str = Field(default_factory=default_fast_model_name)
    director_model: str = Field(default_factory=default_model_name)
    writer_model: str = Field(default_factory=default_model_name)
    memory_model: str = Field(default_factory=default_model_name)
    temperature: float | str = 0.7
    new_character_policy: str = "Director review"


class RuntimeStrategyRequest(RuntimeStrategyResponse):
    pass


class RuntimeSettingsRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    global_: OpenAIRuntimeSettings | None = Field(default=None, alias="global")
    agents: dict[str, OpenAIRuntimeSettings] = Field(default_factory=dict)
    strategy: RuntimeStrategyRequest | None = None

    model_config = ConfigDict(populate_by_name=True)


class RuntimeSettingsTestRequest(BaseModel):
    agent_name: str
    model_name: str | None = None
    runtime_settings: RuntimeSettingsRequest = Field(default_factory=RuntimeSettingsRequest)


class RuntimeSettingsTestResponse(BaseModel):
    ok: bool
    agent_name: str
    message: str


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


class ManualDraftRequest(BaseModel):
    chapter_number: int
    body: str = Field(min_length=1)
    instructions: list[str] = Field(default_factory=list)
    include_body: bool = True


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


def _generation_job_response(job: dict[str, object]) -> GenerationJobResponse:
    return GenerationJobResponse(
        job_id=str(job.get("job_id", "")),
        story_id=str(job.get("story_id", "")),
        status=str(job.get("status", "")),
        progress=str(job.get("progress", "")),
        chapter_number=job.get("chapter_number") if isinstance(job.get("chapter_number"), int) else None,
        error=str(job.get("error", "")),
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
    detail = "本轮世界推演失败，章节未写入。"
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
    def report_progress(message: str) -> None:
        _update_generation_job(job_id, status="running", progress=message)

    report_progress("启动生成任务...")
    try:
        with generation_progress(report_progress):
            bundle = _generate_story_chapter(story_id)
    except SimulationFailedError as exc:
        _update_generation_job(job_id, status="failed", progress="生成失败", error=_simulation_failed_detail(exc))
    except Exception as exc:  # pragma: no cover - background safety net
        _update_generation_job(job_id, status="failed", progress="生成失败", error=str(exc))
    else:
        _update_generation_job(
            job_id,
            status="completed",
            progress="生成完成",
            chapter_number=bundle.chapter_number,
            error="",
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
        status=project.status,
        pipeline_stage=project.pipeline_stage,
        active_story_id=project.active_story_id,
        branches=branches,
    )


def _serialize_project_summary(project: NovelProjectSummary | NovelProject) -> ProjectSummaryResponse:
    current_chapter = 0
    if project.active_story_id:
        active_story = store.get(project.active_story_id)
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
        gaps.append(
            {
                "area": area,
                "severity": severity,
                "message": message,
                "suggested_action": suggested_action,
            }
        )

    if not project.character_profiles:
        add("character_profiles", "角色档案不足，Agent 很难稳定区分动机、私心和说话方式。", "补全主角、重要配角、商人/公会/NPC 的角色档案。", "high")
    if not project.relationship_graph:
        add("relationship_graph", "角色与势力关系图为空，长篇容易变成单线推进。", "补充信任、利益、误会、债务或敌对关系。")
    if not isinstance(world.get("npc_system"), dict) or not world.get("npc_system"):
        add("npc_system", "NPC 系统缺失，网游世界会缺少服务边界、任务入口和信息限制。", "生成命名 NPC、服务、知识边界、任务钩子。", "high")
    if not isinstance(world.get("quest_network"), dict) or not world.get("quest_network"):
        add("quest_network", "任务链缺失，章节目标和奖励/代价容易虚。", "补充任务类型、阶段、失败代价、NPC 关联。")
    if not isinstance(world.get("map_ecology"), dict) or not world.get("map_ecology"):
        add("map_ecology", "地图生态缺失，刷怪、资源点和玩家密度不够真实。", "补充区域、资源、怪物、风险、玩家密度。")
    if not isinstance(living_world.get("economy"), dict) or not living_world.get("economy"):
        add("economy", "经济系统不足，交易行价格和收益容易失真。", "补充币制、流通、手续费、价格波动和风控规则。")
    if not project.author_constraints:
        add("author_constraints", "作者约束为空，Agent 无法长期遵守题材硬规则。", "写入题材规则、禁写项、术语统一和平台节奏。")
    if active_story is not None and not active_story.world_facts:
        add("world_facts", "活跃故事尚未吸收世界事实，生成时可能看不见完整世界规则。", "先进行世界增强或重新同步故事环境。")
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
                "先处理 high severity 的 world.gaps。",
                "审稿最近章节后再决定继续生成或改稿。",
                "生成前确认 current_focus 与下一章目标一致。",
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
        "reason": "章节审稿通过，可以继续生成。" if action == "continue" else "章节存在需要优先修正的问题。",
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
            "safe_default": "先按 recommendation.must_fix 修订当前章，再继续生成下一章。",
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
            "safe_default": "修订后再次审稿，通过后再继续生成下一章。",
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


def _replace_latest_chapter_with_manual_body(
    project: NovelProject,
    record,
    bundle,
    payload: ManualDraftRequest,
    *,
    source: str = "manual_draft",
) -> AgentRevisionResponse:
    latest_chapter = record.history[-1].chapter_number if record.history else None
    if bundle.chapter_number != latest_chapter:
        raise HTTPException(status_code=409, detail="chapter_not_latest")
    if payload.chapter_number != bundle.chapter_number:
        raise HTTPException(status_code=400, detail="chapter_number_mismatch")

    cleaned_body = payload.body.strip()
    if not cleaned_body:
        raise HTTPException(status_code=400, detail="empty_body")

    previous_body_chars = len(bundle.body or "")
    manual_bundle = bundle.model_copy(deep=True)
    manual_bundle.body = cleaned_body
    manual_bundle.chapter_title = _manual_chapter_title(cleaned_body, payload.chapter_number, manual_bundle.chapter_title)
    manual_bundle.event_plan = _manual_event_plan(project, manual_bundle.event_plan)
    manual_bundle.quality_report = {}
    if bundle.chapter_number <= 1:
        base_story = record.initial_story.model_copy(deep=True)
    else:
        base_story = record.history[bundle.chapter_number - 2].updated_story.model_copy(deep=True)
    _sync_project_context_for_story(project, base_story, has_history=bundle.chapter_number > 1)
    manual_bundle = engine.orchestrator.refresh_revised_bundle_metadata(base_story, manual_bundle)
    manual_bundle.chapter_title = _manual_chapter_title(cleaned_body, payload.chapter_number, manual_bundle.chapter_title)
    manual_bundle.event_plan = _manual_event_plan(project, manual_bundle.event_plan)
    manual_bundle = _complete_manual_bundle_metadata(project, manual_bundle)
    serialized = _serialize_chapter_bundle(manual_bundle, manual_bundle.updated_story.world_facts)
    quality_report = serialized.get("quality_report", {})
    manual_bundle.quality_report = quality_report if isinstance(quality_report, dict) else {}
    updated_record = store.replace_chapter_bundle(record.story.story_id, manual_bundle)
    return _build_agent_revision_response(
        project,
        updated_record,
        manual_bundle,
        previous_body_chars=previous_body_chars,
        instructions=payload.instructions or ["manual_codex_draft"],
        include_body=payload.include_body,
        source=source,
    )


def _append_manual_chapter(
    project: NovelProject,
    record,
    payload: ManualDraftRequest,
    *,
    source: str = "manual_draft",
) -> AgentRevisionResponse:
    latest_chapter = record.history[-1].chapter_number if record.history else 0
    if payload.chapter_number != latest_chapter + 1:
        raise HTTPException(status_code=404, detail="chapter_not_found")

    cleaned_body = payload.body.strip()
    if not cleaned_body:
        raise HTTPException(status_code=400, detail="empty_body")

    base_story = record.story.model_copy(deep=True)
    _sync_project_context_for_story(project, base_story, has_history=bool(record.history))
    chapter_title = _manual_chapter_title(cleaned_body, payload.chapter_number, "")
    event_plan = _manual_event_plan(project, {"next_focus": project.current_focus})
    manual_bundle = ChapterBundle(
        chapter_number=payload.chapter_number,
        body=cleaned_body,
        chapter_title=chapter_title,
        cadence="measured",
        chapter_intent={
            "chapter_title": chapter_title,
            "next_focus": project.current_focus,
            "source": source,
        },
        character_moves=[],
        memory_constraints={},
        event_plan=event_plan,
        chapter_seed={},
        simulation_plan={},
        world_events=[],
        scene_cards=[],
        simulation_status={"ok": True, "source": source},
        action_briefs=[],
        conflict_summary={},
        event_beat={},
        character_cards=[],
        foreshadowing=[],
        next_outline="",
        updated_story=base_story.model_copy(deep=True),
        chapter_summary={},
        quality_report={},
    )
    manual_bundle = engine.orchestrator.refresh_revised_bundle_metadata(base_story, manual_bundle)
    manual_bundle.chapter_title = _manual_chapter_title(cleaned_body, payload.chapter_number, manual_bundle.chapter_title)
    manual_bundle.event_plan = _manual_event_plan(project, manual_bundle.event_plan)
    manual_bundle = _complete_manual_bundle_metadata(project, manual_bundle)
    serialized = _serialize_chapter_bundle(manual_bundle, manual_bundle.updated_story.world_facts)
    quality_report = serialized.get("quality_report", {})
    manual_bundle.quality_report = quality_report if isinstance(quality_report, dict) else {}
    updated_record = store.append_chapter_bundle(record.story.story_id, manual_bundle)
    return _build_agent_revision_response(
        project,
        updated_record,
        manual_bundle,
        previous_body_chars=0,
        instructions=payload.instructions or ["manual_codex_draft"],
        include_body=payload.include_body,
        source=source,
    )


def _manual_chapter_title(body: str, chapter_number: int, fallback: str = "") -> str:
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    chapter_prefix = rf"\u7b2c\s*{chapter_number}\s*\u7ae0"
    spaced_title = re.match(rf"^({chapter_prefix}\s+\S{{1,24}})", first_line)
    if spaced_title:
        return spaced_title.group(1).strip()
    sentence_title = re.match(rf"^({chapter_prefix}[^。！？.!?\n]{{0,32}})", first_line)
    if sentence_title:
        return sentence_title.group(1).strip()
    return fallback or f"\u7b2c{chapter_number}\u7ae0"


def _manual_event_plan(project: NovelProject, current: dict | None) -> dict:
    event_plan = dict(current or {})
    event_plan.setdefault("next_focus", project.current_focus)
    event_plan.setdefault(
        "world_reactions",
        [
            "NPC service records update through task ledgers and service boundaries.",
            "Player economy reacts through visible prices, batch thresholds, and collection points.",
            "Guild pressure remains indirect through resource-point order and weak observation.",
        ],
    )
    event_plan.setdefault("stakes", project.current_focus or "Manual chapter must preserve continuity and leave a concrete next pressure.")
    return event_plan


def _complete_manual_bundle_metadata(project: NovelProject, bundle: ChapterBundle) -> ChapterBundle:
    """Fill the validator-facing fields for human/Codex-written chapters."""
    next_focus = bundle.chapter_summary.get("next_focus") or project.current_focus or bundle.next_outline
    primary_conflict = bundle.chapter_summary.get("primary_conflict") or {
        "type": "resource_gate",
        "summary": next_focus or "The protagonist must convert early gains into a stable next-step route.",
    }
    secondary_conflict = bundle.chapter_summary.get("secondary_conflict") or {
        "type": "visibility_pressure",
        "summary": "NPC ledgers, player prices, and guild-side observation create weak but visible pressure.",
    }
    event_beat = bundle.chapter_summary.get("event_beat") or bundle.event_beat or {
        "trigger": "manual_chapter",
        "result": next_focus or "The chapter updates the route, inventory, and next hook.",
    }
    bundle.conflict_summary = bundle.conflict_summary or {
        "primary": primary_conflict,
        "secondary": secondary_conflict,
    }
    bundle.event_beat = bundle.event_beat or event_beat
    bundle.next_outline = bundle.next_outline or next_focus or project.current_focus
    chapter_summary = dict(bundle.chapter_summary or {})
    chapter_summary.setdefault("chapter_number", bundle.chapter_number)
    if not chapter_summary.get("chapter_title"):
        chapter_summary["chapter_title"] = bundle.chapter_title
    if not chapter_summary.get("cadence"):
        chapter_summary["cadence"] = bundle.cadence
    if not chapter_summary.get("summary"):
        chapter_summary["summary"] = bundle.chapter_intent.get("next_focus") or bundle.next_outline
    if not chapter_summary.get("facts"):
        chapter_summary["facts"] = bundle.updated_story.world_facts[:3] or [bundle.next_outline]
    if not chapter_summary.get("unresolved_threads"):
        chapter_summary["unresolved_threads"] = [bundle.next_outline] if bundle.next_outline else []
    if not chapter_summary.get("next_focus"):
        chapter_summary["next_focus"] = next_focus
    if not chapter_summary.get("primary_conflict"):
        chapter_summary["primary_conflict"] = primary_conflict
    if not chapter_summary.get("secondary_conflict"):
        chapter_summary["secondary_conflict"] = secondary_conflict
    if not chapter_summary.get("event_beat"):
        chapter_summary["event_beat"] = event_beat
    bundle.chapter_summary = chapter_summary
    return bundle


def _serialize_runtime_settings() -> dict[str, object]:
    runtime = get_all_runtime_settings()
    return {
        "global": runtime["global"].model_dump(),
        "agents": {
            name: agent.model_dump()
            for name, agent in runtime["agents"].items()
        },
        "strategy": runtime["strategy"].model_dump(),
    }


def _runtime_target_label(agent_name: str) -> str:
    return {
        "global": "全局默认",
        "character": "角色代理",
        "director": "导演代理",
        "writer": "写作代理",
        "memory": "记忆代理",
    }.get(agent_name, agent_name)


def _runtime_model_for_target(agent_name: str, provided_model: str | None = None) -> str:
    if provided_model:
        return provided_model
    strategy = get_runtime_strategy_settings()
    if agent_name == "character":
        return strategy.character_model or strategy.global_model
    if agent_name == "director":
        return strategy.director_model or strategy.global_model
    if agent_name == "writer":
        return strategy.writer_model or strategy.global_model
    if agent_name == "memory":
        return strategy.memory_model or strategy.global_model
    return strategy.global_model


def _probe_via_chat_completions(base_url: str, api_key: str, model_name: str) -> None:
    payload = json.dumps(
        {
            "model": model_name,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10):
        return None


def _probe_via_models(base_url: str, api_key: str) -> None:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=10):
        return None


def _probe_via_codexcli(command: str, model_name: str) -> None:
    config = RetryConfig()
    config.timeout = 120
    post_json_with_retry(
        "",
        "/chat/completions",
        {
            "model": model_name,
            "messages": [{"role": "user", "content": "只回复 pong"}],
            "max_tokens": 8,
        },
        "",
        config=config,
        provider="codexcli",
        codex_command=command,
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
def list_projects() -> list[ProjectSummaryResponse]:
    return [_serialize_project_summary(project) for project in store.list_projects()]


@router.delete("/projects/{project_id}")
def delete_project(project_id: str) -> DeleteProjectResponse:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project_not_found")
    story_ids = [record.story.story_id for record in store.list_project_stories(project_id)]
    store.delete_project(project_id, delete_stories=True)
    return DeleteProjectResponse(deleted=True, project_id=project_id, deleted_story_ids=story_ids)


@router.get("/projects/{project_id}")
def get_project(project_id: str) -> ProjectResponse:
    store.sync_project_context(project_id)
    project = store.get_project(project_id)
    if project is None:
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
    skill_context = {
        purpose: skill_pack_prompt_context(project.enabled_skill_ids, purpose=purpose, max_chars_per_pack=2600)
        for purpose in ("writer", "dialogue", "style", "genre", "continuity", "reviewer")
    }
    packet["skill_context"] = {key: value for key, value in skill_context.items() if value}
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
    from packages.story_core.style_adaptation import build_style_adapt_prompt
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

    modules = [
        entry(
            key="core_context",
            title="核心上下文模块",
            agent="context",
            stage="核心上下文",
            content=json.dumps(_story_snapshot(preview_story), ensure_ascii=False, indent=2),
            source="orchestrator._story_snapshot",
            description="主线、世界事实、账本和最近记忆。",
        ),
        entry(
            key="character_context",
            title="本章人物模块",
            agent="context",
            stage="人物角色卡",
            content=json.dumps(_character_context_for_prompt(preview_story, plan), ensure_ascii=False, indent=2),
            source="orchestrator._character_context_for_prompt",
            description="只提取当前章节需要的人物侧写。",
        ),
        entry(
            key="genre_context",
            title="题材写法模块",
            agent="context",
            stage="题材写法",
            content=json.dumps(_genre_context_for_prompt(preview_story, target, plan), ensure_ascii=False, indent=2),
            source="orchestrator._genre_context_for_prompt",
            description="按当前小说类型选择写法，不混用其他题材规则。",
        ),
        entry(
            key="packet_context",
            title="写作包预览模块",
            agent="codex",
            stage="写作包",
            content=json.dumps(packet_preview, ensure_ascii=False, indent=2),
            source="writing_packet.compact_preview",
            description="面板使用的压缩写作包，不展示原正文全文。",
        ),
    ]
    if isinstance(review, dict) and review:
        modules.append(
            entry(
                key="review_context",
                title="审稿报告模块",
                agent="review",
                stage="审稿报告",
                content=json.dumps(review, ensure_ascii=False, indent=2),
                source="chapter.quality_report",
                description="只在改稿阶段读取。",
            )
        )
    if isinstance(taskbook, dict):
        modules.append(
            entry(
                key="writing_taskbook",
                title="本章方向模块",
                agent="context",
                stage="本章方向",
                content=format_taskbook_brief_section(taskbook),
                source="chapter.writing_taskbook",
                description="只保留本章目标、场面推进和收束，不重复通用风格规则。",
            )
        )

    orchestrator = StoryOrchestrator()
    prompts = [
        entry(
            key="director_plan",
            title="导演/剧情计划 Prompt",
            agent="director",
            stage="剧情计划生成",
            content=orchestrator._plan_prompt(preview_story, target),
            source="rebuilt_from_database_story",
            description="生成本章结构化剧情计划。",
            module_keys=["core_context", "genre_context"],
        ),
        entry(
            key="writer_body",
            title="整章正文 Prompt",
            agent="writer",
            stage="整章正文生成",
            content=orchestrator._body_prompt(preview_story, target, plan),
            source="rebuilt_from_database_story",
            description="整章正文实际提示词，按输出要求、本章方向、本章事实、出场人物和正文写法五块装配。",
            module_keys=["core_context", "character_context", "genre_context", "writing_taskbook"],
        ),
    ]
    if body.strip():
        body_placeholder = f"[原正文由 source_body 注入；面板不展示正文全文；当前正文 {len(body)} 字。]"
        prompts.extend(
            [
                entry(
                    key="revision",
                    title="审稿改稿 Prompt",
                    agent="writer",
                    stage="审稿改稿",
                    content=orchestrator._revision_prompt(preview_story, target, body_placeholder, plan, review),
                    source="rebuilt_from_database_chapter",
                    description="章节审稿未通过时使用。",
                    module_keys=["core_context", "character_context", "genre_context", "review_context"],
                ),
                entry(
                    key="style_adapt",
                    title="风格适配 Prompt",
                    agent="writer",
                    stage="风格适配",
                    content=build_style_adapt_prompt(body_placeholder, plan),
                    source="rebuilt_conditional_prompt",
                    description="只调整表达，不改变章节事实。",
                    module_keys=["source_body", "writing_taskbook"],
                ),
            ]
        )
    prompts.append(
        entry(
            key="review_agents",
            title="读者/编辑/审稿 Agent 说明",
            agent="review",
            stage="质量审稿",
            content="读者、编辑和审稿 Agent 读取章节正文与质量报告执行检查；当前没有额外隐藏正文提示词。",
            source="local_rule_based_review",
            description="说明审稿阶段读取什么。",
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


@router.post("/projects/{project_id}/manual-draft")
def submit_project_manual_draft(project_id: str, payload: ManualDraftRequest) -> AgentRevisionResponse:
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project_not_found")
    record = store.get(project.active_story_id) if project.active_story_id else None
    if record is None:
        raise HTTPException(status_code=404, detail="story_not_found")
    latest_chapter = record.history[-1].chapter_number if record.history else 0
    if payload.chapter_number == latest_chapter + 1:
        return _append_manual_chapter(project, record, payload)
    bundle = _select_review_chapter(record, payload.chapter_number)
    return _replace_latest_chapter_with_manual_body(project, record, bundle, payload)


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
        project.world_blueprint = payload.world_blueprint
    if payload.character_profiles is not None:
        project.character_profiles = payload.character_profiles
    if payload.relationship_graph is not None:
        project.relationship_graph = payload.relationship_graph
    if payload.enabled_skill_ids is not None:
        project.enabled_skill_ids = payload.enabled_skill_ids
    if payload.status is not None:
        project.status = payload.status
    if payload.pipeline_stage is not None:
        project.pipeline_stage = payload.pipeline_stage
    if payload.active_story_id is not None:
        project.active_story_id = payload.active_story_id

    store.update_project(project)
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
            "progress": "已进入生成队列...",
            "chapter_number": None,
            "error": "",
            "starting_chapter": record.story.current_chapter if record else 0,
            "created_at": now,
            "updated_at": now,
        }
        _generation_jobs[job_id] = job
        _active_generation_jobs[story_id] = job_id
        response = _generation_job_response(job)

    _generation_executor.submit(_run_generation_job, job_id, story_id)
    return response


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


@router.get("/runtime-settings")
def read_runtime_settings() -> dict[str, object]:
    return _serialize_runtime_settings()


@router.put("/runtime-settings")
def update_runtime_settings(payload: RuntimeSettingsRequest) -> dict[str, object]:
    data = payload.model_dump(by_alias=True)
    if data.get("global") is None and payload.api_key is not None and payload.base_url is not None:
        data["global"] = {
            "api_key": payload.api_key,
            "base_url": payload.base_url,
        }
    elif data.get("global") is None and (payload.api_key is not None or payload.base_url is not None):
        data["global"] = {
            "api_key": payload.api_key or "",
            "base_url": payload.base_url or "https://api.openai.com/v1",
        }
    if "agents" not in data:
        data["agents"] = {}
    set_all_runtime_settings(data)
    return _serialize_runtime_settings()


@router.get("/runtime-strategy")
def read_runtime_strategy() -> dict[str, object]:
    return get_runtime_strategy_settings().model_dump()


@router.put("/runtime-strategy")
def update_runtime_strategy(payload: RuntimeStrategyRequest) -> dict[str, object]:
    set_runtime_strategy_settings(payload.model_dump())
    return get_runtime_strategy_settings().model_dump()


@router.post("/runtime-settings/test")
def test_runtime_settings(payload: RuntimeSettingsTestRequest) -> RuntimeSettingsTestResponse:
    agent_name = payload.agent_name
    if agent_name not in {"character", "director", "writer", "memory", "global"}:
        raise HTTPException(status_code=400, detail="invalid_agent_name")

    overrides = payload.runtime_settings.model_dump(by_alias=True, exclude_none=True)
    if not (
        overrides.get("api_key")
        or overrides.get("base_url")
        or overrides.get("provider")
        or overrides.get("codex_command")
        or overrides.get("global")
        or overrides.get("agents")
        or overrides.get("strategy")
    ):
        overrides = None
    if agent_name == "global":
        resolved = resolve_openai_runtime_settings(overrides=overrides)
    else:
        resolved = resolve_openai_runtime_settings(agent_name=agent_name, overrides=overrides)

    if resolved.provider == "codexcli":
        try:
            _probe_via_codexcli(
                resolved.codex_command or "codex",
                _runtime_model_for_target(agent_name, payload.model_name),
            )
        except Exception as exc:
            return RuntimeSettingsTestResponse(
                ok=False,
                agent_name=agent_name,
                message=f"Codex CLI 测试失败：{str(exc)[:200]}",
            )
        return RuntimeSettingsTestResponse(
            ok=True,
            agent_name=agent_name,
            message=f"{_runtime_target_label(agent_name)} Codex CLI 正常",
        )

    if not resolved.api_key or not resolved.base_url:
        return RuntimeSettingsTestResponse(
            ok=False,
            agent_name=agent_name,
            message="缺少 API 密钥或接口地址",
        )

    try:
        model_name = _runtime_model_for_target(agent_name, payload.model_name)
        if model_name:
            try:
                _probe_via_chat_completions(
                    base_url=resolved.base_url,
                    api_key=resolved.api_key,
                    model_name=model_name,
                )
            except urllib.error.HTTPError as exc:
                if exc.code not in {404, 405}:
                    raise
                _probe_via_models(base_url=resolved.base_url, api_key=resolved.api_key)
        else:
            _probe_via_models(base_url=resolved.base_url, api_key=resolved.api_key)
        return RuntimeSettingsTestResponse(
            ok=True,
            agent_name=agent_name,
            message=f"{_runtime_target_label(agent_name)} 连接正常",
        )
    except Exception as exc:  # pragma: no cover - surfaced in UI and tests
        return RuntimeSettingsTestResponse(
            ok=False,
            agent_name=agent_name,
            message=f"{_runtime_target_label(agent_name)} 连接失败：{exc}",
        )


def init_story_routes() -> APIRouter:
    return router
