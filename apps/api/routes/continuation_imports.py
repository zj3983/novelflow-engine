from __future__ import annotations

import os
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
)


router = APIRouter(prefix="/continuation-imports", tags=["continuation-imports"])


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourcePathRequest(_RequestModel):
    source_path: str = ""


class ScanRequest(_RequestModel):
    source_path: str = Field(min_length=1)
    forced_encoding: str | None = None


class ReplaceChaptersRequest(_RequestModel):
    expected_revision: int = Field(ge=1)
    chapters: list[ContinuationChapter]


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
        raise HTTPException(status_code=403, detail=str(exc)) from exc
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


def _scan(payload: ScanRequest) -> ContinuationScanResult:
    source = _resolve_source(payload.source_path)
    try:
        return scan_continuation_source(source, forced_encoding=payload.forced_encoding)
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
            payload.chapters,
            expected_revision=payload.expected_revision,
        )
    except (OSError, ValueError) as exc:
        _raise_domain_error(exc)


def _mark_analysis_failed(store: ContinuationSessionStore, session_id: str) -> None:
    try:
        current = store.get(session_id)

        def fail(session: ContinuationImportSession) -> None:
            session.status = "failed"
            session.error = "continuation_analysis_failed"
            session.analysis = {}

        store.update(session_id, fail, expected_revision=current.revision)
    except (OSError, ValueError):
        return


def _run_analysis_job(session_id: str) -> None:
    store = _session_store()
    try:
        run_continuation_analysis(store, session_id, build_continuation_analyzer())
    except Exception:
        current = None
        try:
            current = store.get(session_id)
        except (OSError, ValueError):
            pass
        if current is not None and current.status != "failed":
            _mark_analysis_failed(store, session_id)


@router.post(
    "/{session_id}/analyze",
    response_model=AnalysisJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def analyze(session_id: str, background_tasks: BackgroundTasks) -> AnalysisJobResponse:
    store = _session_store()
    try:
        session = store.get(session_id)
        if session.status in {"analyzing", "ready"}:
            return AnalysisJobResponse(session_id=session_id, status=session.status)

        def mark(current: ContinuationImportSession) -> None:
            current.status = "analyzing"
            current.error = ""

        store.update(session_id, mark, expected_revision=session.revision)
    except (OSError, ValueError) as exc:
        _raise_domain_error(exc)
    background_tasks.add_task(_run_analysis_job, session_id)
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
