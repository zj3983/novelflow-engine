from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from packages.story_core.book_import import BookFolderParseResult, _parse_character_matrix, scan_book_folder


SUPPORTED_SOURCE_SUFFIXES: tuple[str, ...] = (".md", ".txt", ".json", ".yaml", ".yml")


class BookBrowserItem(BaseModel):
    item_id: str
    title: str
    kind: str
    filename: str
    path: str
    preview: str = ""
    chapter_number: int | None = None
    content: str = ""
    parsed_characters: list[str] = Field(default_factory=list)


class BookBrowserSection(BaseModel):
    section_id: str
    title: str
    items: list[BookBrowserItem] = Field(default_factory=list)


class BookBrowserCatalogResponse(BaseModel):
    source_path: str
    exists: bool = False
    can_bootstrap: bool = False
    sections: list[BookBrowserSection] = Field(default_factory=list)


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
    parsed_characters = _parse_character_matrix(content) if filename == "character_matrix.md" else []
    return BookBrowserItem(
        item_id=f"source:{filename}",
        title=filename,
        kind="source_document",
        filename=filename,
        path=str(base / filename),
        preview=_short_preview(content),
        content=content,
        parsed_characters=parsed_characters,
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


def _runtime_item(base: Path, path: Path, content: str) -> BookBrowserItem:
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


def build_book_browser_catalog(base: Path) -> BookBrowserCatalogResponse:
    result: BookFolderParseResult = scan_book_folder(base)
    report = result.report

    source_doc_items = [
        _document_item(base, filename, report.documents.get(filename, ""))
        for filename in sorted(report.documents.keys())
        if Path(filename).suffix.lower() in SUPPORTED_SOURCE_SUFFIXES
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
                runtime_items.append(
                    _runtime_item(base, path, path.read_text(encoding="utf-8", errors="replace"))
                )

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
