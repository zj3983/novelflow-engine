from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


SUPPORTED_SUFFIXES = {".md", ".txt"}
DEFAULT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk")
_NUMBER_CHARS = "0-9零〇一二两三四五六七八九十百千万"
_CHAPTER_TITLE_RE = re.compile(
    rf"^\s*(?:#{{1,6}}\s*)?第\s*(?P<number>[{_NUMBER_CHARS}]+)\s*[章节回卷](?P<title>.*)$"
)
_MARKDOWN_TITLE_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.+?)\s*#*\s*$")
_NATURAL_NUMBER_RE = re.compile(rf"第\s*([{_NUMBER_CHARS}]+)\s*[章节回卷]|(\d+)")


class ContinuationChapter(BaseModel):
    chapter_id: str
    number: int
    title: str
    body: str
    source_name: str
    source_start: int = 0
    source_end: int = 0
    fingerprint: str


class ContinuationScanResult(BaseModel):
    source_path: str
    source_kind: Literal["file", "directory"]
    encoding: str
    chapters: list[ContinuationChapter] = Field(default_factory=list)
    total_chars: int = 0
    warnings: list[str] = Field(default_factory=list)
    duplicate_groups: list[list[str]] = Field(default_factory=list)
    numbering_gaps: list[int] = Field(default_factory=list)
    can_analyze: bool = False


def decode_novel_bytes(payload: bytes, forced_encoding: str | None = None) -> tuple[str, str]:
    encodings = (forced_encoding,) if forced_encoding else DEFAULT_ENCODINGS
    for encoding in encodings:
        try:
            return payload.decode(encoding, errors="strict"), encoding
        except (LookupError, UnicodeDecodeError):
            continue
    raise ValueError("source_encoding_unknown")


def _chinese_number(value: str) -> int:
    if value.isdigit():
        return int(value)

    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    total = 0
    section = 0
    digit = 0
    for char in value:
        if char in digits:
            digit = digits[char]
            continue
        unit = units[char]
        if unit == 10000:
            section = (section + digit) * unit
            total += section
            section = 0
        else:
            section += (digit or 1) * unit
        digit = 0
    return total + section + digit


def _number_from_text(value: str) -> int | None:
    match = _NATURAL_NUMBER_RE.search(value)
    if not match:
        return None
    return _chinese_number(match.group(1) or match.group(2))


def _natural_key(path: Path, base: Path) -> tuple[object, ...]:
    relative = str(path.relative_to(base)).replace("\\", "/")
    parts = re.split(r"(\d+)", relative.casefold())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _line_boundaries(text: str) -> list[tuple[int, int, str]]:
    boundaries: list[tuple[int, int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        chapter_match = _CHAPTER_TITLE_RE.match(content)
        markdown_match = _MARKDOWN_TITLE_RE.match(content)
        if chapter_match:
            boundaries.append((offset, offset + len(line), content.strip().lstrip("#").strip()))
        elif markdown_match:
            boundaries.append((offset, offset + len(line), markdown_match.group("title").strip()))
        offset += len(line)
    return boundaries


def _build_chapter(
    *,
    number: int,
    title: str,
    body: str,
    source_name: str,
    source_start: int,
    source_end: int,
) -> ContinuationChapter:
    clean_body = body.strip()
    fingerprint = hashlib.sha256(clean_body.encode("utf-8")).hexdigest()
    identity = f"{source_name}\0{number}\0{title}\0{source_start}\0{source_end}\0{fingerprint}"
    chapter_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return ContinuationChapter(
        chapter_id=chapter_id,
        number=number,
        title=title,
        body=clean_body,
        source_name=source_name,
        source_start=source_start,
        source_end=source_end,
        fingerprint=fingerprint,
    )


def _chapters_from_text(
    text: str,
    source_name: str,
    fallback_number: int,
    fallback_title: str,
) -> tuple[list[ContinuationChapter], bool]:
    boundaries = _line_boundaries(text)
    if not boundaries:
        if not text:
            return [], False
        number = _number_from_text(fallback_title) or fallback_number
        return [
            _build_chapter(
                number=number,
                title=fallback_title,
                body=text,
                source_name=source_name,
                source_start=0,
                source_end=len(text),
            )
        ], False

    chapters: list[ContinuationChapter] = []
    for index, (_, body_start, title) in enumerate(boundaries):
        body_end = boundaries[index + 1][0] if index + 1 < len(boundaries) else len(text)
        number = _number_from_text(title) or fallback_number + index
        chapters.append(
            _build_chapter(
                number=number,
                title=title,
                body=text[body_start:body_end],
                source_name=source_name,
                source_start=body_start,
                source_end=body_end,
            )
        )
    return chapters, True


def _diagnostics(chapters: list[ContinuationChapter]) -> tuple[list[str], list[list[str]], list[int]]:
    warnings: list[str] = []
    grouped: dict[str, list[str]] = defaultdict(list)
    for chapter in chapters:
        if chapter.body:
            grouped[chapter.fingerprint].append(chapter.chapter_id)
    duplicate_groups = [ids for ids in grouped.values() if len(ids) > 1]
    if duplicate_groups:
        warnings.append("duplicate_chapters")
    if any(not chapter.body for chapter in chapters):
        warnings.append("empty_chapters")

    numbers = sorted({chapter.number for chapter in chapters if chapter.number > 0})
    numbering_gaps: list[int] = []
    if len(numbers) > 1:
        present = set(numbers)
        numbering_gaps = [number for number in range(numbers[0], numbers[-1] + 1) if number not in present]
    if numbering_gaps:
        warnings.append("numbering_gaps")
    return warnings, duplicate_groups, numbering_gaps


def scan_continuation_source(
    path: Path | str,
    forced_encoding: str | None = None,
) -> ContinuationScanResult:
    source = Path(path).expanduser().resolve(strict=False)
    source_kind: Literal["file", "directory"] = "directory" if source.is_dir() else "file"
    if source_kind == "directory":
        files = sorted(
            (item for item in source.rglob("*") if item.is_file() and item.suffix.casefold() in SUPPORTED_SUFFIXES),
            key=lambda item: _natural_key(item, source),
        )
    elif source.is_file() and source.suffix.casefold() in SUPPORTED_SUFFIXES:
        files = [source]
    else:
        files = []

    if not files:
        return ContinuationScanResult(
            source_path=str(source),
            source_kind=source_kind,
            encoding="",
            warnings=["no_supported_files"],
        )

    chapters: list[ContinuationChapter] = []
    encodings: list[str] = []
    total_chars = 0
    unconfirmed = False
    for file_index, file_path in enumerate(files, start=1):
        text, encoding = decode_novel_bytes(file_path.read_bytes(), forced_encoding)
        encodings.append(encoding)
        total_chars += len(text)
        source_name = file_path.name if source_kind == "file" else file_path.relative_to(source).as_posix()
        parsed, confirmed = _chapters_from_text(text, source_name, file_index, file_path.stem)
        chapters.extend(parsed)
        if source_kind == "file" and text and not confirmed:
            unconfirmed = True

    warnings, duplicate_groups, numbering_gaps = _diagnostics(chapters)
    if not chapters:
        warnings.insert(0, "empty_source")
    if unconfirmed:
        warnings.insert(0, "chapter_boundaries_unconfirmed")
    encoding = encodings[0] if len(set(encodings)) == 1 else "mixed"
    blocking = {"empty_source", "empty_chapters", "duplicate_chapters", "chapter_boundaries_unconfirmed"}
    return ContinuationScanResult(
        source_path=str(source),
        source_kind=source_kind,
        encoding=encoding,
        chapters=chapters,
        total_chars=total_chars,
        warnings=warnings,
        duplicate_groups=duplicate_groups,
        numbering_gaps=numbering_gaps,
        can_analyze=bool(chapters) and not blocking.intersection(warnings),
    )
