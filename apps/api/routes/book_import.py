from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from packages.story_core.book_import import (
    BookBootstrapCharacter,
    BookCharacterProfile,
    BookWorldBlueprint,
    normalize_book_source_path,
    scan_book_folder,
)
from packages.story_core.book_browser import (
    BookBrowserCatalogResponse,
    BookBrowserItem,
    BookBrowserSection,
)


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
    title: str = ""
    outline: str = ""
    summary: str = ""
    world_summary: str = ""
    current_focus: str = ""
    author_constraints: list[str] = Field(default_factory=list)
    characters: list[BookBootstrapCharacter] = Field(default_factory=list)
    character_profiles: list[BookCharacterProfile] = Field(default_factory=list)
    world_blueprint: BookWorldBlueprint = Field(default_factory=BookWorldBlueprint)


class BookBootstrapResponse(BaseModel):
    report: BookFolderReportResponse
    draft: BookBootstrapDraftResponse


class BookBrowserCatalogRequest(BaseModel):
    source_path: str = Field(min_length=1)


class FolderItem(BaseModel):
    name: str
    path: str
    is_drive: bool = False


class FolderListResponse(BaseModel):
    drives: list[FolderItem] = Field(default_factory=list)
    folders: list[FolderItem] = Field(default_factory=list)
    current_path: str = ""


def _resolve_source_dir(source_path: str) -> Path:
    try:
        base = normalize_book_source_path(source_path)
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


def _short_preview(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    return compact[:limit]


def _chapter_number_from_name(filename: str) -> int | None:
    match = re.search(r"chapter-(\d+)", filename, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _runtime_title(filename: str) -> str:
    number = _chapter_number_from_name(filename)
    return f"Chapter {number}" if number is not None else filename


def _document_item(base: Path, filename: str, content: str) -> BookBrowserItem:
    return BookBrowserItem(
        item_id=f"source:{filename}",
        title=filename,
        kind="source_document",
        filename=filename,
        path=str(base / filename),
        preview=_short_preview(content),
        content=content,
    )


def _state_item(base: Path, path: Path, content: str) -> BookBrowserItem:
    return BookBrowserItem(
        item_id=f"state:{path.name}",
        title=path.name,
        kind="state_file",
        filename=path.name,
        path=str(path),
        preview=_short_preview(content),
        content=content,
    )


def _runtime_item(path: Path, content: str) -> BookBrowserItem:
    chapter_number = _chapter_number_from_name(path.name)
    return BookBrowserItem(
        item_id=f"runtime:{path.name}",
        title=_runtime_title(path.name),
        kind="runtime_chapter_artifact",
        filename=path.name,
        path=str(path),
        preview=_short_preview(content),
        chapter_number=chapter_number,
        content=content,
    )


def _build_catalog(base: Path, report) -> BookBrowserCatalogResponse:
    source_doc_items = [
        _document_item(base, filename, report.documents.get(filename, ""))
        for filename in sorted(report.documents.keys())
    ]

    state_dir = base / "state"
    state_items: list[BookBrowserItem] = []
    if state_dir.exists() and state_dir.is_dir():
        for path in sorted(state_dir.iterdir()):
            if path.is_file():
                state_items.append(_state_item(base, path, path.read_text(encoding="utf-8", errors="replace")))

    runtime_dir = base / "runtime"
    runtime_items: list[BookBrowserItem] = []
    if runtime_dir.exists() and runtime_dir.is_dir():
        for path in sorted(runtime_dir.iterdir()):
            if path.is_file() and path.name.startswith("chapter-"):
                runtime_items.append(_runtime_item(path, path.read_text(encoding="utf-8", errors="replace")))

    return BookBrowserCatalogResponse(
        source_path=str(base),
        exists=report.exists,
        can_bootstrap=report.can_bootstrap,
        sections=[
            BookBrowserSection(section_id="source_docs", title="源书目录", items=source_doc_items),
            BookBrowserSection(section_id="source_state", title="状态文件", items=state_items),
            BookBrowserSection(section_id="runtime_chapters", title="运行章节", items=runtime_items),
        ],
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
            title=result.bootstrap.title,
            outline=result.bootstrap.outline,
            summary=result.bootstrap.summary,
            world_summary=result.bootstrap.world_summary,
            current_focus=result.bootstrap.current_focus,
            author_constraints=list(result.bootstrap.author_constraints),
            characters=list(result.bootstrap.characters),
            character_profiles=list(result.bootstrap.character_profiles),
            world_blueprint=result.bootstrap.world_blueprint,
        ),
    )


@router.post("/book-import/catalog")
def catalog(payload: BookBrowserCatalogRequest):
    base = _resolve_source_dir(payload.source_path)
    result = scan_book_folder(base)
    return _build_catalog(base, result.report)


class FolderListRequest(BaseModel):
    source_path: str = ""


@router.post("/book-import/list-folders")
def list_folders(payload: FolderListRequest) -> FolderListResponse:
    """列出指定路径下的文件夹，用于前端文件夹选择器"""
    target = payload.source_path.strip()

    # 列出磁盘驱动器 (Windows)
    if not target or target == "":
        drives = []
        for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            drive_path = f"{letter}:\\"
            if os.path.exists(drive_path):
                drives.append(FolderItem(name=f"{letter}: 盘", path=drive_path, is_drive=True))
        return FolderListResponse(drives=drives, current_path="")

    # 列出目标路径下的文件夹
    target_path = Path(target)
    if not target_path.exists() or not target_path.is_dir():
        raise HTTPException(status_code=404, detail=f"路径不存在: {target}")

    folders = []
    try:
        for item in sorted(target_path.iterdir()):
            if item.is_dir():
                folders.append(FolderItem(name=item.name, path=str(item)))
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"无权限访问: {target}")

    return FolderListResponse(folders=folders, current_path=str(target_path))


def init_book_import_routes() -> APIRouter:
    return router
