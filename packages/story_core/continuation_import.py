from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


SUPPORTED_SUFFIXES = {".md", ".txt"}
DEFAULT_ENCODINGS = ("utf-8", "gb18030", "gbk")
_BOM_ENCODINGS = (
    (b"\xff\xfe\x00\x00", "utf-32", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32", "utf-32-be"),
    (b"\xef\xbb\xbf", "utf-8-sig", "utf-8-sig"),
    (b"\xff\xfe", "utf-16", "utf-16-le"),
    (b"\xfe\xff", "utf-16", "utf-16-be"),
)
_NUMBER_CHARS = "0-9零〇一二两三四五六七八九十百千万"
_CHAPTER_TITLE_RE = re.compile(
    rf"^\s*第\s*(?P<number>[{_NUMBER_CHARS}]+)\s*[章节回卷](?P<title>.*)$"
)
_MARKDOWN_TITLE_RE = re.compile(r"^\s{0,3}(?P<marks>#{1,6})[ \t]+(?P<title>.+?)\s*$")
_FENCE_RE = re.compile(r"^\s{0,3}(?P<fence>`{3,}|~{3,})")
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


@dataclass(frozen=True)
class _Heading:
    start: int
    body_start: int
    title: str
    level: int | None
    explicit: bool


def decode_novel_bytes(payload: bytes, forced_encoding: str | None = None) -> tuple[str, str]:
    if not forced_encoding:
        for bom, codec, label in _BOM_ENCODINGS:
            if payload.startswith(bom):
                try:
                    text = payload.decode(codec, errors="strict")
                except UnicodeDecodeError as exc:
                    raise ValueError("source_encoding_unknown") from exc
                if _is_low_quality_text(text):
                    raise ValueError("source_encoding_unknown")
                return text, label

    encodings = (forced_encoding,) if forced_encoding else DEFAULT_ENCODINGS
    for encoding in encodings:
        try:
            text = payload.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue
        if not _is_low_quality_text(text):
            return text, encoding
    raise ValueError("source_encoding_unknown")


def _is_low_quality_text(text: str) -> bool:
    for char in text:
        if char in "\t\n\r":
            continue
        category = unicodedata.category(char)
        if category.startswith("C"):
            return True
    return False


def _chinese_number(value: str) -> int:
    if value.isdigit():
        return int(value)

    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    if any(char.isascii() and char.isdigit() for char in value):
        raise ValueError("chapter_number_invalid")
    if any(char not in digits and char not in units for char in value):
        raise ValueError("chapter_number_invalid")
    if not any(char in units for char in value):
        return int("".join(str(digits[char]) for char in value))

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
    try:
        return _chinese_number(match.group(1) or match.group(2))
    except ValueError:
        return None


def _natural_key(path: Path, base: Path) -> tuple[object, ...]:
    relative = path.relative_to(base).as_posix()
    normalized_relative = unicodedata.normalize("NFKC", relative).casefold()
    parts = re.split(r"(\d+)", normalized_relative)
    natural_parts = tuple(int(part) if part.isdigit() else part for part in parts)
    return natural_parts, normalized_relative, relative


def _line_boundaries(text: str) -> list[tuple[int, int, str]]:
    candidates: list[_Heading] = []
    offset = 0
    fence_char = ""
    fence_length = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        fence_match = _FENCE_RE.match(content)
        if fence_match:
            fence = fence_match.group("fence")
            if not fence_char:
                fence_char = fence[0]
                fence_length = len(fence)
            elif fence[0] == fence_char and len(fence) >= fence_length:
                fence_char = ""
                fence_length = 0
            offset += len(line)
            continue
        if fence_char:
            offset += len(line)
            continue

        markdown_match = _MARKDOWN_TITLE_RE.match(content)
        level = len(markdown_match.group("marks")) if markdown_match else None
        if markdown_match:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", markdown_match.group("title")).strip()
        else:
            title = content.strip()
        chapter_match = _CHAPTER_TITLE_RE.match(title)
        if chapter_match:
            try:
                _chinese_number(chapter_match.group("number"))
            except ValueError:
                pass
            else:
                candidates.append(_Heading(offset, offset + len(line), title, level, True))
        elif markdown_match:
            candidates.append(_Heading(offset, offset + len(line), title, level, False))
        offset += len(line)

    explicit = [candidate for candidate in candidates if candidate.explicit]
    if explicit:
        selected = explicit
    else:
        levels = [candidate.level for candidate in candidates if candidate.level is not None]
        chapter_level = min(levels) if levels else None
        selected = [candidate for candidate in candidates if candidate.level == chapter_level]
    return [(heading.start, heading.body_start, heading.title) for heading in selected]


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
    return ContinuationChapter(
        chapter_id="",
        number=number,
        title=title,
        body=clean_body,
        source_name=source_name,
        source_start=source_start,
        source_end=source_end,
        fingerprint=fingerprint,
    )


def _assign_chapter_ids(chapters: list[ContinuationChapter]) -> None:
    occurrences: dict[tuple[int, str, str], int] = defaultdict(int)
    for chapter in chapters:
        normalized_title = " ".join(unicodedata.normalize("NFKC", chapter.title).split()).casefold()
        logical_key = (chapter.number, normalized_title, chapter.fingerprint)
        occurrence = occurrences[logical_key]
        occurrences[logical_key] += 1
        identity = f"{chapter.number}\0{normalized_title}\0{chapter.fingerprint}\0{occurrence}"
        chapter.chapter_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()


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
        if text and not confirmed:
            unconfirmed = True

    _assign_chapter_ids(chapters)
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
