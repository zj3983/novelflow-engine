from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import NoReturn

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.fs_access import allowed_fs_roots, require_allowed_path
from packages.story_core.continuation_analysis import (
    ContinuationAnalysis,
    LLMContinuationAnalyzer,
    run_continuation_analysis,
)
from packages.story_core.continuation_import import (
    SUPPORTED_SUFFIXES,
    ContinuationChapter,
    ContinuationScanResult,
    scan_continuation_source,
)
from packages.story_core.continuation_sessions import (
    ContinuationImportSession,
    ContinuationSessionStore,
    secure_read_bytes,
    try_acquire_analysis_lease,
)


router = APIRouter(prefix="/continuation-imports", tags=["continuation-imports"])

_ANALYSIS_JOB_GENERATION = "_analysis_job_generation"
_ANALYSIS_JOB_STATE = "_analysis_job_state"


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourcePathRequest(_RequestModel):
    source_path: str = ""


class ScanRequest(_RequestModel):
    source_path: str = Field(min_length=1)
    forced_encoding: str | None = None


class ContinuationChapterRequest(_RequestModel):
    chapter_id: str
    number: int
    title: str
    body: str
    source_name: str
    source_start: int = 0
    source_end: int = 0
    fingerprint: str


class ReplaceChaptersRequest(_RequestModel):
    expected_revision: int = Field(ge=1)
    chapters: list[ContinuationChapterRequest]


class UpdateAnalysisRequest(_RequestModel):
    expected_revision: int = Field(ge=1)
    analysis: ContinuationAnalysis


class SourceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    path: str


class SourceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_path: str = ""
    directories: list[SourceItem] = Field(default_factory=list)
    files: list[SourceItem] = Field(default_factory=list)


class AnalysisJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    status: str


def _session_store() -> ContinuationSessionStore:
    configured = os.getenv("NOVEL_AUTOGROWTH_CONTINUATION_IMPORTS_DIR", "").strip()
    root = Path(configured) if configured else Path("data") / "continuation-imports"
    return ContinuationSessionStore(root)


def build_continuation_analyzer() -> LLMContinuationAnalyzer:
    return LLMContinuationAnalyzer()


def _error_code(exc: BaseException) -> str:
    message = str(exc).strip()
    return message.split(":", 1)[0] if message else exc.__class__.__name__


def _raise_domain_error(exc: BaseException) -> NoReturn:
    code = _error_code(exc)
    if isinstance(exc, FileNotFoundError) or code in {
        "source_path_not_found",
        "continuation import session not found",
    }:
        detail = "session_not_found" if isinstance(exc, FileNotFoundError) else code
        raise HTTPException(status_code=404, detail=detail) from exc
    if code == "path_outside_allowed_roots":
        raise HTTPException(status_code=403, detail=code) from exc
    if code in {
        "analysis_not_ready",
        "continuation_analysis_invalid_status",
        "session_lock_timeout",
        "session_revision_conflict",
        "source_changed_since_scan",
    }:
        raise HTTPException(status_code=409, detail=code) from exc
    if code in {
        "unsupported_source_type",
        "source_encoding_unknown",
        "source_files_missing",
        "chapters_empty",
        "chapter_number_invalid",
        "chapter_number_duplicate",
        "chapter_id_duplicate",
        "chapter_title_empty",
        "chapter_body_empty",
    }:
        raise HTTPException(status_code=422, detail=code) from exc
    raise HTTPException(status_code=400, detail=code) from exc


def _resolve_source(source_path: str) -> Path:
    candidate = Path(source_path).expanduser()
    if _is_link_or_junction(candidate):
        raise HTTPException(status_code=403, detail="path_outside_allowed_roots")
    try:
        source = require_allowed_path(candidate)
    except (OSError, RuntimeError, ValueError) as exc:
        _raise_domain_error(exc)
    if not source.exists():
        raise HTTPException(status_code=404, detail="source_path_not_found")
    if source.is_file() and source.suffix.casefold() not in SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=422, detail="unsupported_source_type")
    if not source.is_file() and not source.is_dir():
        raise HTTPException(status_code=422, detail="unsupported_source_type")
    return source


def _is_link_or_junction(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", lambda candidate: False)
    try:
        return path.is_symlink() or bool(is_junction(path))
    except OSError:
        return True


def _validate_source_tree(source: Path) -> None:
    if _is_link_or_junction(source):
        raise ValueError("path_outside_allowed_roots")
    if source.is_file():
        require_allowed_path(source)
        return

    for current_root, directory_names, file_names in os.walk(source, topdown=True):
        current = Path(current_root)
        require_allowed_path(current)
        safe_directories: list[str] = []
        for name in directory_names:
            child = current / name
            if _is_link_or_junction(child):
                raise ValueError("path_outside_allowed_roots")
            require_allowed_path(child)
            safe_directories.append(name)
        directory_names[:] = safe_directories
        for name in file_names:
            child = current / name
            if child.suffix.casefold() not in SUPPORTED_SUFFIXES:
                continue
            if _is_link_or_junction(child):
                raise ValueError("path_outside_allowed_roots")
            require_allowed_path(child)


def _scan(payload: ScanRequest) -> ContinuationScanResult:
    source = _resolve_source(payload.source_path)
    fixed_root = source.parent if source.is_file() else source

    def read_source_bytes(path: Path) -> bytes:
        try:
            return secure_read_bytes(path, fixed_root=fixed_root)
        except ValueError as exc:
            if _error_code(exc) == "invalid_session_path":
                raise ValueError("path_outside_allowed_roots") from None
            raise

    try:
        _validate_source_tree(source)
        result = scan_continuation_source(
            source,
            forced_encoding=payload.forced_encoding,
            read_bytes=read_source_bytes,
        )
        _validate_source_tree(source)
        return result
    except (OSError, UnicodeError, ValueError) as exc:
        _raise_domain_error(exc)


def _safe_child_item(path: Path) -> SourceItem | None:
    try:
        resolved = require_allowed_path(path)
    except (OSError, ValueError):
        return None
    if path.is_symlink():
        return None
    return SourceItem(name=path.name, path=str(resolved))


@router.post("/list-sources", response_model=SourceListResponse)
def list_sources(payload: SourcePathRequest) -> SourceListResponse:
    if not payload.source_path.strip():
        directories = [
            SourceItem(name=str(root), path=str(root))
            for root in allowed_fs_roots()
            if root.is_dir()
        ]
        directories.sort(key=lambda item: (item.name.casefold(), item.name))
        return SourceListResponse(directories=directories)

    source = _resolve_source(payload.source_path)
    if not source.is_dir():
        raise HTTPException(status_code=422, detail="source_directory_required")
    directories: list[SourceItem] = []
    files: list[SourceItem] = []
    try:
        children = sorted(
            source.iterdir(), key=lambda path: (path.name.casefold(), path.name)
        )
        for child in children:
            item = _safe_child_item(child)
            if item is None:
                continue
            if child.is_dir():
                directories.append(item)
            elif child.is_file() and child.suffix.casefold() in SUPPORTED_SUFFIXES:
                files.append(item)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="source_path_permission_denied") from exc
    return SourceListResponse(
        current_path=str(source), directories=directories, files=files
    )


@router.post("/scan", response_model=ContinuationScanResult)
def scan(payload: ScanRequest) -> ContinuationScanResult:
    return _scan(payload)


@router.post(
    "",
    response_model=ContinuationImportSession,
    status_code=status.HTTP_201_CREATED,
)
def create_import(payload: ScanRequest) -> ContinuationImportSession:
    try:
        return _session_store().create(_scan(payload))
    except HTTPException:
        raise
    except (OSError, ValueError) as exc:
        _raise_domain_error(exc)


@router.get("/{session_id}", response_model=ContinuationImportSession)
def get_import(session_id: str) -> ContinuationImportSession:
    try:
        return _session_store().get(session_id)
    except (OSError, ValueError) as exc:
        _raise_domain_error(exc)


@router.put("/{session_id}/chapters", response_model=ContinuationImportSession)
def replace_chapters(
    session_id: str, payload: ReplaceChaptersRequest
) -> ContinuationImportSession:
    try:
        return _session_store().replace_chapters(
            session_id,
            [
                ContinuationChapter.model_validate(chapter.model_dump())
                for chapter in payload.chapters
            ],
            expected_revision=payload.expected_revision,
            invalidate_analysis=True,
        )
    except (OSError, ValueError) as exc:
        _raise_domain_error(exc)


def _job_generation(session: ContinuationImportSession) -> str:
    return str(session.analysis_progress.get(_ANALYSIS_JOB_GENERATION, ""))


def _job_state(session: ContinuationImportSession) -> str:
    return str(session.analysis_progress.get(_ANALYSIS_JOB_STATE, ""))


def _mark_analysis_failed(
    store: ContinuationSessionStore, session_id: str, generation: str
) -> None:
    try:
        current = store.get(session_id)
        if (
            current.status != "analyzing"
            or _job_generation(current) != generation
            or _job_state(current) != "running"
        ):
            return

        def fail(session: ContinuationImportSession) -> None:
            if (
                session.status != "analyzing"
                or _job_generation(session) != generation
                or _job_state(session) != "running"
            ):
                raise ValueError("stale_analysis_job")
            session.status = "failed"
            session.error = "continuation_analysis_failed"
            session.analysis = {}

        store.update(session_id, fail, expected_revision=current.revision)
    except (OSError, ValueError):
        return


def _claim_analysis_job(
    store: ContinuationSessionStore, session_id: str, generation: str
) -> bool:
    try:
        current = store.get(session_id)
        if (
            current.status != "analyzing"
            or _job_generation(current) != generation
            or _job_state(current) != "queued"
        ):
            return False

        def claim(session: ContinuationImportSession) -> None:
            if (
                session.status != "analyzing"
                or _job_generation(session) != generation
                or _job_state(session) != "queued"
            ):
                raise ValueError("stale_analysis_job")
            session.analysis_progress[_ANALYSIS_JOB_STATE] = "running"

        store.update(session_id, claim, expected_revision=current.revision)
        return True
    except (OSError, ValueError):
        return False


def _run_analysis_job(session_id: str, generation: str) -> None:
    store: ContinuationSessionStore | None = None
    lease = None
    claimed = False
    try:
        store = _session_store()
        lease = try_acquire_analysis_lease(store.root, session_id)
        if lease is None:
            return
        claimed = _claim_analysis_job(store, session_id, generation)
        if not claimed:
            return
        run_continuation_analysis(store, session_id, build_continuation_analyzer())
    except Exception:
        if store is not None and claimed:
            _mark_analysis_failed(store, session_id, generation)
    finally:
        if lease is not None:
            lease.release()


def _queue_new_generation(
    store: ContinuationSessionStore,
    session: ContinuationImportSession,
) -> tuple[ContinuationImportSession, str]:
    generation = f"caj-{uuid.uuid4().hex}"

    def queue(current: ContinuationImportSession) -> None:
        current.status = "analyzing"
        current.error = ""
        current.analysis = {}
        current.analysis_progress[_ANALYSIS_JOB_GENERATION] = generation
        current.analysis_progress[_ANALYSIS_JOB_STATE] = "queued"

    updated = store.update(
        session.session_id,
        queue,
        expected_revision=session.revision,
    )
    return updated, generation


def _prepare_analysis_job(
    store: ContinuationSessionStore, session_id: str
) -> tuple[str, str, bool]:
    for _ in range(8):
        session = store.get(session_id)
        if session.status == "ready":
            return "ready", "", False
        if session.status == "analyzing":
            lease = try_acquire_analysis_lease(store.root, session_id)
            if lease is None:
                return "analyzing", _job_generation(session), False
            try:
                session = store.get(session_id)
                if session.status == "ready":
                    return "ready", "", False
                if session.status != "analyzing":
                    continue
                generation = _job_generation(session)
                if generation and _job_state(session) == "queued":
                    return "analyzing", generation, True
                try:
                    _, generation = _queue_new_generation(store, session)
                    return "analyzing", generation, True
                except ValueError as exc:
                    if _error_code(exc) != "session_revision_conflict":
                        raise
                    continue
            finally:
                lease.release()
        try:
            _, generation = _queue_new_generation(store, session)
            return "analyzing", generation, True
        except ValueError as exc:
            if _error_code(exc) != "session_revision_conflict":
                raise
    raise ValueError("session_revision_conflict")


@router.post(
    "/{session_id}/analyze",
    response_model=AnalysisJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def analyze(session_id: str, background_tasks: BackgroundTasks) -> AnalysisJobResponse:
    store = _session_store()
    try:
        job_status, generation, should_queue = _prepare_analysis_job(store, session_id)
    except (OSError, ValueError) as exc:
        _raise_domain_error(exc)
    if job_status == "ready":
        return AnalysisJobResponse(session_id=session_id, status="ready")
    if should_queue:
        background_tasks.add_task(_run_analysis_job, session_id, generation)
    return AnalysisJobResponse(session_id=session_id, status="analyzing")


@router.get("/{session_id}/analysis", response_model=ContinuationAnalysis)
def get_analysis(session_id: str) -> ContinuationAnalysis:
    try:
        session = _session_store().get(session_id)
        if not session.analysis:
            raise ValueError("analysis_not_ready")
        return ContinuationAnalysis.model_validate(session.analysis)
    except (OSError, ValueError) as exc:
        _raise_domain_error(exc)


@router.put("/{session_id}/analysis", response_model=ContinuationImportSession)
def update_analysis(
    session_id: str, payload: UpdateAnalysisRequest
) -> ContinuationImportSession:
    store = _session_store()
    try:

        def replace(current: ContinuationImportSession) -> None:
            if current.status != "ready" or not current.analysis:
                raise ValueError("analysis_not_ready")
            current.analysis = payload.analysis.model_dump(mode="json")
            current.error = ""

        return store.update(
            session_id, replace, expected_revision=payload.expected_revision
        )
    except (OSError, ValueError) as exc:
        _raise_domain_error(exc)


def init_continuation_import_routes() -> APIRouter:
    return router
