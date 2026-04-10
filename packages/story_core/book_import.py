from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


REQUIRED_FILES: tuple[str, ...] = ("current_focus.md", "volume_outline.md")
OPTIONAL_FILES: tuple[str, ...] = (
    "author_intent.md",
    "book_rules.md",
    "story_bible.md",
    "current_state.md",
    "pending_hooks.md",
    "subplot_board.md",
    "character_matrix.md",
)

KNOWN_FILES: tuple[str, ...] = REQUIRED_FILES + OPTIONAL_FILES


class BookFolderReport(BaseModel):
    source_path: str
    exists: bool = False
    missing_required_files: list[str] = Field(default_factory=list)
    missing_optional_files: list[str] = Field(default_factory=list)
    present_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    documents: dict[str, str] = Field(default_factory=dict)
    can_bootstrap: bool = False


class BookBootstrapDraft(BaseModel):
    source_path: str
    outline: str = ""
    summary: str = ""
    characters: list[str] = Field(default_factory=list)


class BookFolderParseResult(BaseModel):
    report: BookFolderReport
    bootstrap: BookBootstrapDraft


def _safe_read_text(path: Path, warnings: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        warnings.append(f"Could not decode {path.name} as utf-8; read with replacement characters.")
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        warnings.append(f"Could not read {path.name}: {exc!s}")
        return ""


def _parse_character_matrix(text: str) -> list[str]:
    """Very small helper that extracts character names from simple markdown.

    Supported patterns:
    - a markdown table where the first column is the name
    - bullet lines like "- Name"
    """

    seen: set[str] = set()
    names: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        candidate = ""
        if line.startswith("|") and "|" in line[1:]:
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not cells:
                continue
            first = cells[0]
            lower_first = first.lower()
            if lower_first in {"name", "角色", "姓名"}:
                continue
            if first and set(first) <= {"-"}:
                continue
            candidate = first
        elif line.startswith(("-", "*")):
            candidate = line.lstrip("-* ").strip()

        if candidate and candidate not in seen:
            seen.add(candidate)
            names.append(candidate)

    return names


def scan_book_folder(source_path: Path | str) -> BookFolderParseResult:
    base = Path(source_path)

    report = BookFolderReport(source_path=str(base))
    if not base.exists() or not base.is_dir():
        report.exists = False
        report.missing_required_files = sorted(REQUIRED_FILES)
        report.missing_optional_files = sorted(OPTIONAL_FILES)
        report.can_bootstrap = False
        bootstrap = BookBootstrapDraft(source_path=str(base))
        return BookFolderParseResult(report=report, bootstrap=bootstrap)

    report.exists = True

    for filename in KNOWN_FILES:
        file_path = base / filename
        if not file_path.exists():
            continue
        report.present_files.append(filename)
        content = _safe_read_text(file_path, report.warnings)
        if content != "":
            report.documents[filename] = content

    report.present_files = sorted(report.present_files)
    report.missing_required_files = sorted([name for name in REQUIRED_FILES if name not in report.present_files])
    report.missing_optional_files = sorted([name for name in OPTIONAL_FILES if name not in report.present_files])
    report.can_bootstrap = report.exists and not report.missing_required_files

    volume_outline = report.documents.get("volume_outline.md", "").strip()
    current_focus = report.documents.get("current_focus.md", "").strip()
    outline_parts = [part for part in (volume_outline, current_focus) if part]
    outline = "\n\n".join(outline_parts)

    summary = report.documents.get("author_intent.md", "").strip()
    if not summary:
        summary = report.documents.get("story_bible.md", "").strip()

    characters_text = report.documents.get("character_matrix.md", "")
    characters = _parse_character_matrix(characters_text) if characters_text else []

    bootstrap = BookBootstrapDraft(
        source_path=str(base),
        outline=outline,
        summary=summary,
        characters=characters,
    )
    return BookFolderParseResult(report=report, bootstrap=bootstrap)

