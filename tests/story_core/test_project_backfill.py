from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from packages.story_core.project_backfill import (
    ChapterEvidence,
    ProjectEvidenceIndex,
    build_evidence_index,
    chapter_hashes,
)


def _write_canonical_chapter(
    project_root: Path,
    chapter_number: int,
    *,
    title: str,
    body_bytes: bytes,
    metadata: dict[str, object] | None = None,
) -> None:
    markdown_path = project_root / "chapters" / f"{chapter_number:04d}-{title}.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_bytes(body_bytes)

    payload: dict[str, object] = {
        "schema_version": "chapter/v2",
        "chapter_number": chapter_number,
        "chapter_title": title,
        "body_path": markdown_path.relative_to(project_root).as_posix(),
        "body_sha256": hashlib.sha256(body_bytes).hexdigest(),
    }
    payload.update(metadata or {})
    chapter_path = project_root / ".story-system" / "chapters" / f"{chapter_number:04d}.json"
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    chapter_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _chapter_files(project_root: Path) -> dict[str, bytes]:
    paths = [
        *(project_root / ".story-system" / "chapters").glob("*.json"),
        *(project_root / "chapters").glob("*.md"),
    ]
    return {
        path.relative_to(project_root).as_posix(): path.read_bytes()
        for path in sorted(paths)
    }


def test_build_evidence_index_reads_three_complete_chapters_without_mutation(tmp_path: Path) -> None:
    for chapter_number in range(1, 4):
        _write_canonical_chapter(
            tmp_path,
            chapter_number,
            title=f"第{chapter_number}章",
            body_bytes=f"第{chapter_number}章正文。\r\n第二行。".encode(),
            metadata={"chapter_summary": {"summary": f"第{chapter_number}章摘要"}},
        )
    before = _chapter_files(tmp_path)

    index = build_evidence_index(tmp_path)

    assert isinstance(index, ProjectEvidenceIndex)
    assert [item.chapter_number for item in index.chapters] == [1, 2, 3]
    assert [item.title for item in index.chapters] == ["第1章", "第2章", "第3章"]
    assert [item.summary for item in index.chapters] == [
        "第1章摘要",
        "第2章摘要",
        "第3章摘要",
    ]
    assert all(isinstance(item, ChapterEvidence) and item.body and item.body_hash for item in index.chapters)
    assert _chapter_files(tmp_path) == before


def test_build_evidence_index_reads_optional_structured_fields(tmp_path: Path) -> None:
    _write_canonical_chapter(
        tmp_path,
        1,
        title="落锁",
        body_bytes="林修关上店门。".encode(),
        metadata={
            "chapter_summary": {
                "summary": "林修保住了维修铺。",
                "character_updates": [{"name": "林修", "change": "决定追查旧账"}],
                "foreshadowing": [{"text": "柜台下的铜钥匙", "status": "open"}],
            },
            "updated_story": {
                "timeline": [{"chapter_number": 1, "summary": "维修铺暂时停业"}],
            },
        },
    )

    chapter = build_evidence_index(tmp_path).chapters[0]

    assert chapter.timeline == ({"chapter_number": 1, "summary": "维修铺暂时停业"},)
    assert chapter.character_updates == ({"name": "林修", "change": "决定追查旧账"},)
    assert chapter.foreshadowing == ({"text": "柜台下的铜钥匙", "status": "open"},)


def test_build_evidence_index_sorts_chapters_numerically(tmp_path: Path) -> None:
    for chapter_number in (10, 2, 1):
        _write_canonical_chapter(
            tmp_path,
            chapter_number,
            title=str(chapter_number),
            body_bytes=f"正文{chapter_number}".encode(),
        )

    assert [item.chapter_number for item in build_evidence_index(tmp_path).chapters] == [1, 2, 10]


def test_missing_optional_fields_are_empty_collections(tmp_path: Path) -> None:
    _write_canonical_chapter(tmp_path, 1, title="空白", body_bytes="只有正文。".encode())

    chapter = build_evidence_index(tmp_path).chapters[0]

    assert chapter.summary == ""
    assert chapter.timeline == ()
    assert chapter.character_updates == ()
    assert chapter.foreshadowing == ()


def test_chapter_hashes_use_raw_canonical_markdown_bytes(tmp_path: Path) -> None:
    raw_body = b"first line\r\nsecond line\r\n"
    _write_canonical_chapter(tmp_path, 1, title="Raw", body_bytes=raw_body)

    assert chapter_hashes(tmp_path) == {1: hashlib.sha256(raw_body).hexdigest()}


def test_evidence_data_structures_are_immutable(tmp_path: Path) -> None:
    _write_canonical_chapter(tmp_path, 1, title="冻结", body_bytes="正文。".encode())
    index = build_evidence_index(tmp_path)

    with pytest.raises(FrozenInstanceError):
        index.project_root = Path("elsewhere")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        index.chapters[0].title = "被修改"  # type: ignore[misc]
    assert isinstance(index.chapters, tuple)
