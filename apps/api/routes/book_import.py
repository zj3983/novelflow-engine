from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from packages.story_core.book_import import scan_book_folder


router = APIRouter()


class BookImportRequest(BaseModel):
    source_path: str = Field(min_length=1)


class BookFolderReportResponse(BaseModel):
    source_path: str
    exists: bool = False
    missing_required_files: list[str] = Field(default_factory=list)
    missing_optional_files: list[str] = Field(default_factory=list)
    unusable_required_files: list[str] = Field(default_factory=list)
    empty_files: list[str] = Field(default_factory=list)
    present_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    can_bootstrap: bool = False


class BookBootstrapDraftResponse(BaseModel):
    source_path: str
    outline: str = ""
    summary: str = ""
    characters: list[str] = Field(default_factory=list)


class BookBootstrapResponse(BaseModel):
    report: BookFolderReportResponse
    draft: BookBootstrapDraftResponse


def _resolve_source_dir(source_path: str) -> Path:
    try:
        base = Path(source_path).expanduser().resolve(strict=False)
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid_source_path: {source_path} ({exc!s})") from exc

    if not base.is_absolute():
        raise HTTPException(status_code=400, detail=f"invalid_source_path: {source_path}")
    return base


def _public_report(report) -> BookFolderReportResponse:
    # Drop large/non-UI fields like `documents`; keep payload JSON-friendly and small.
    return BookFolderReportResponse(
        source_path=report.source_path,
        exists=report.exists,
        missing_required_files=list(report.missing_required_files),
        missing_optional_files=list(report.missing_optional_files),
        unusable_required_files=list(report.unusable_required_files),
        empty_files=list(report.empty_files),
        present_files=list(report.present_files),
        warnings=list(report.warnings),
        can_bootstrap=report.can_bootstrap,
    )


@router.post("/book-import/scan")
def scan(payload: BookImportRequest) -> BookFolderReportResponse:
    base = _resolve_source_dir(payload.source_path)
    result = scan_book_folder(base)
    return _public_report(result.report)


@router.post("/book-import/bootstrap")
def bootstrap(payload: BookImportRequest) -> BookBootstrapResponse:
    base = _resolve_source_dir(payload.source_path)
    if not base.exists() or not base.is_dir():
        raise HTTPException(status_code=404, detail=f"source_path_not_found: {base}")
    result = scan_book_folder(base)
    return BookBootstrapResponse(
        report=_public_report(result.report),
        draft=BookBootstrapDraftResponse(
            source_path=result.bootstrap.source_path,
            outline=result.bootstrap.outline,
            summary=result.bootstrap.summary,
            characters=list(result.bootstrap.characters),
        ),
    )


def init_book_import_routes() -> APIRouter:
    return router
