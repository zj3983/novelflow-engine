"""Tests for the canonical project context reader.

The reader is the single source of truth for how agents see
project artifacts. Every read must:

1. Be a path the caller explicitly declared.
2. Stay inside the project root.
3. Return parsed JSON or Markdown text with SHA-256 and char
   count, so the workbench and the migration script can later
   prove what was consumed.
4. Tolerate UTF-8 BOM in existing project data.
5. Record missing optional artifacts instead of inventing
   content.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from packages.story_core.context.contracts import ArtifactRead
from packages.story_core.context.project_reader import ProjectContextReader


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_reader_returns_parsed_json_with_hash_and_chars(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    expected = {"chapter_number": 3, "goal": "测试"}
    _write_bytes(project / "outline.json", json.dumps(expected, ensure_ascii=False).encode("utf-8"))

    reader = ProjectContextReader(project)
    payload = reader.read_json("outline.json", kind="outline")

    assert payload == expected
    assert isinstance(payload, dict)
    assert payload["chapter_number"] == 3

    record = reader.last_read()
    assert record is not None
    assert record.kind == "outline"
    assert record.path == "outline.json"
    assert record.sha256 == hashlib.sha256(
        json.dumps(expected, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert record.chars == len(json.dumps(expected, ensure_ascii=False))


def test_reader_returns_markdown_text_with_hash(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    md = "第一行\n第二行。\n"
    _write_bytes(project / "chapter.md", md.encode("utf-8"))

    reader = ProjectContextReader(project)
    text = reader.read_text("chapter.md", kind="chapter")

    assert text == md

    record = reader.last_read()
    assert record is not None
    assert record.kind == "chapter"
    assert record.path == "chapter.md"
    assert record.sha256 == hashlib.sha256(md.encode("utf-8")).hexdigest()


def test_reader_tolerates_utf8_bom(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    raw = json.dumps({"title": "旧档案"}, ensure_ascii=False)
    _write_bytes(project / "outline.json", b"\xef\xbb\xbf" + raw.encode("utf-8"))

    reader = ProjectContextReader(project)
    payload = reader.read_json("outline.json", kind="outline")

    assert payload == {"title": "旧档案"}


def test_reader_rejects_path_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    reader = ProjectContextReader(project)
    with pytest.raises(ValueError, match="artifact_path_outside_project"):
        reader.read_text("../secret.txt", kind="world")


def test_reader_rejects_absolute_paths_outside_project(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")

    reader = ProjectContextReader(project)
    with pytest.raises(ValueError, match="artifact_path_outside_project"):
        reader.read_text(str(outside), kind="world")


def test_reader_reads_only_declared_paths(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_bytes(project / "outline.json", b'{"a": 1}')
    _write_bytes(project / "world.md", b"world")

    reader = ProjectContextReader(project, declared=("outline.json",))
    reader.read_json("outline.json", kind="outline")

    with pytest.raises(ValueError, match="artifact_not_declared"):
        reader.read_text("world.md", kind="world")


def test_reader_records_missing_optional_artifact_without_inventing_content(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    reader = ProjectContextReader(project)

    result = reader.try_read_text("missing.md", kind="foreshadowing")

    assert result is None
    record = reader.last_read()
    assert record is not None
    assert record.kind == "foreshadowing"
    assert record.path == "missing.md"
    assert record.chars == 0
    assert record.sha256 == ""


def test_reader_trace_records_multiple_reads_in_order(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    _write_bytes(project / "outline.json", b'{"a": 1}')
    _write_bytes(project / "world.md", b"world")

    reader = ProjectContextReader(project)
    reader.read_json("outline.json", kind="outline")
    reader.read_text("world.md", kind="world")

    assert [r.kind for r in reader.trace] == ["outline", "world"]
    assert all(isinstance(r, ArtifactRead) for r in reader.trace)
