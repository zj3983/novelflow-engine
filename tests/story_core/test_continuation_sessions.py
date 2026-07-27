from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.story_core.continuation_import import ContinuationChapter, ContinuationScanResult


def _chapter(number: int, *, chapter_id: str | None = None) -> ContinuationChapter:
    body = f"第{number}章正文"
    return ContinuationChapter(
        chapter_id=chapter_id or f"chapter-{number}",
        number=number,
        title=f"第{number}章 标题",
        body=body,
        source_name="novel.txt",
        source_start=0,
        source_end=len(body),
        fingerprint=hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )


def _scan(source: Path, chapters: list[ContinuationChapter] | None = None) -> ContinuationScanResult:
    return ContinuationScanResult(
        source_path=str(source.resolve()),
        source_kind="directory" if source.is_dir() else "file",
        encoding="utf-8",
        chapters=chapters or [_chapter(1), _chapter(2)],
        can_analyze=True,
    )


def _store(root: Path, *session_ids: str):
    from packages.story_core.continuation_sessions import ContinuationSessionStore

    ids = iter(session_ids or ["ci-test-session"])
    timestamps = iter(
        [
            "2026-07-27T01:00:00Z",
            "2026-07-27T01:01:00Z",
            "2026-07-27T01:02:00Z",
            "2026-07-27T01:03:00Z",
        ]
    )
    return ContinuationSessionStore(
        root,
        session_id_factory=lambda: next(ids),
        clock=lambda: next(timestamps),
    )


def test_create_and_get_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("中文原稿", encoding="utf-8")
    store = _store(tmp_path / "sessions")

    created = store.create(_scan(source))
    loaded = store.get(created.session_id)

    assert loaded == created
    assert loaded.schema_version == "continuation-import-session/v1"
    assert loaded.revision == 1
    assert loaded.status == "parsed"
    assert loaded.source_fingerprint == hashlib.sha256(source.read_bytes()).hexdigest()
    assert (tmp_path / "sessions" / created.session_id / "session.json").is_file()


def test_replace_chapters_sorts_and_edits_without_touching_source(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_bytes("原始内容".encode("utf-8"))
    original = source.read_bytes()
    store = _store(tmp_path / "sessions")
    session = store.create(_scan(source))
    second = _chapter(2)
    second.title = "修改后的标题"

    replaced = store.replace_chapters(session.session_id, [second, _chapter(1)], expected_revision=1)

    assert [chapter.number for chapter in replaced.chapters] == [1, 2]
    assert replaced.chapters[1].title == "修改后的标题"
    assert replaced.revision == 2
    assert replaced.updated_at == "2026-07-27T01:01:00Z"
    assert source.read_bytes() == original


def test_create_copies_original_files_and_writes_manifest(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "parts").mkdir(parents=True)
    (source / "parts" / "one.txt").write_text("第一章", encoding="utf-8")
    (source / "two.md").write_text("第二章", encoding="utf-8")
    (source / "ignored.json").write_text("{}", encoding="utf-8")
    store = _store(tmp_path / "sessions")

    session = store.create(_scan(source))
    session_root = tmp_path / "sessions" / session.session_id
    manifest = json.loads((session_root / "source" / "manifest.json").read_text(encoding="utf-8"))

    assert (session_root / "source" / "original" / "parts" / "one.txt").read_text(encoding="utf-8") == "第一章"
    assert (session_root / "source" / "original" / "two.md").read_text(encoding="utf-8") == "第二章"
    assert not (session_root / "source" / "original" / "ignored.json").exists()
    assert manifest["source_path"] == str(source.resolve())
    assert manifest["source_kind"] == "directory"
    assert manifest["source_fingerprint"] == session.source_fingerprint
    assert manifest["encoding"] == "utf-8"
    assert [item["relative_path"] for item in manifest["files"]] == ["parts/one.txt", "two.md"]
    assert all(len(item["fingerprint"]) == 64 for item in manifest["files"])


def test_expected_revision_conflict_does_not_write(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    store = _store(tmp_path / "sessions")
    session = store.create(_scan(source))
    before = store.get(session.session_id)

    with pytest.raises(ValueError, match="^session_revision_conflict$"):
        store.replace_chapters(session.session_id, [_chapter(3)], expected_revision=99)

    assert store.get(session.session_id) == before


def test_expected_revision_conflict_precedes_chapter_validation(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    store = _store(tmp_path / "sessions")
    session = store.create(_scan(source))

    with pytest.raises(ValueError, match="^session_revision_conflict$"):
        store.replace_chapters(session.session_id, [], expected_revision=99)

    assert store.get(session.session_id) == session


def test_replace_rejects_source_changed_since_scan_without_writing(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    store = _store(tmp_path / "sessions")
    session = store.create(_scan(source))
    source.write_text("原稿已改变", encoding="utf-8")

    with pytest.raises(ValueError, match="^source_changed_since_scan$"):
        store.replace_chapters(session.session_id, [_chapter(1)], expected_revision=1)

    assert store.get(session.session_id) == session


def test_replace_treats_deleted_source_as_changed(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    store = _store(tmp_path / "sessions")
    session = store.create(_scan(source))
    source.unlink()

    with pytest.raises(ValueError, match="^source_changed_since_scan$"):
        store.replace_chapters(session.session_id, [_chapter(1)])

    assert store.get(session.session_id) == session


@pytest.mark.parametrize("session_id", ["../escape", "..", ".", "ci/a", "ci\\a", "", "other-id"])
def test_get_rejects_illegal_session_ids(tmp_path: Path, session_id: str) -> None:
    store = _store(tmp_path / "sessions")

    with pytest.raises(ValueError, match="^session_id_invalid$"):
        store.get(session_id)


def test_get_missing_session_raises_file_not_found(tmp_path: Path) -> None:
    store = _store(tmp_path / "sessions")

    with pytest.raises(FileNotFoundError, match="ci-missing"):
        store.get("ci-missing")


@pytest.mark.parametrize(
    ("chapters", "error"),
    [
        ([], "chapters_empty"),
        ([_chapter(0)], "chapter_number_invalid"),
        ([_chapter(1), _chapter(1, chapter_id="different")], "chapter_number_duplicate"),
        ([_chapter(1), _chapter(2, chapter_id="chapter-1")], "chapter_id_duplicate"),
    ],
)
def test_replace_rejects_invalid_chapter_collections(
    tmp_path: Path, chapters: list[ContinuationChapter], error: str
) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    store = _store(tmp_path / "sessions")
    session = store.create(_scan(source))

    with pytest.raises(ValueError, match=f"^{error}$"):
        store.replace_chapters(session.session_id, chapters)

    assert store.get(session.session_id) == session


@pytest.mark.parametrize(("field", "error"), [("title", "chapter_title_empty"), ("body", "chapter_body_empty")])
def test_replace_rejects_blank_chapter_text(tmp_path: Path, field: str, error: str) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    store = _store(tmp_path / "sessions")
    session = store.create(_scan(source))
    chapter = _chapter(1)
    setattr(chapter, field, " \n\t")

    with pytest.raises(ValueError, match=f"^{error}$"):
        store.replace_chapters(session.session_id, [chapter])


def test_update_changes_status_and_analysis_progress(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    store = _store(tmp_path / "sessions")
    session = store.create(_scan(source))

    def mutate(current):
        current.status = "analyzing"
        current.analysis_progress = {"completed": 2, "total": 8}

    updated = store.update(session.session_id, mutate, expected_revision=1)

    assert updated.status == "analyzing"
    assert updated.analysis_progress == {"completed": 2, "total": 8}
    assert updated.revision == 2
    assert store.get(session.session_id) == updated


def test_atomic_replace_failure_preserves_original_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import packages.story_core.continuation_sessions as sessions_module

    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    store = _store(tmp_path / "sessions")
    session = store.create(_scan(source))
    session_file = tmp_path / "sessions" / session.session_id / "session.json"
    before = session_file.read_bytes()

    def fail_replace(source_path, destination_path):
        raise OSError("replace failed")

    monkeypatch.setattr(sessions_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        store.update(session.session_id, lambda current: setattr(current, "status", "ready"))

    assert session_file.read_bytes() == before
    assert list(session_file.parent.glob(".session.json.*.tmp")) == []


def test_json_preserves_chinese_text_without_ascii_escaping(tmp_path: Path) -> None:
    source = tmp_path / "小说.txt"
    source.write_text("原稿", encoding="utf-8")
    store = _store(tmp_path / "sessions")

    session = store.create(_scan(source, [_chapter(1)]))
    raw = (tmp_path / "sessions" / session.session_id / "session.json").read_text(encoding="utf-8")

    assert "第1章 标题" in raw
    assert "\\u7b2c" not in raw
    assert raw.endswith("\n")


def test_directory_fingerprint_is_order_independent_and_tracks_content_and_paths(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "b.md").write_text("B", encoding="utf-8")
    (first / "a.txt").write_text("A", encoding="utf-8")
    (second / "a.txt").write_text("A", encoding="utf-8")
    (second / "b.md").write_text("B", encoding="utf-8")
    store = _store(tmp_path / "sessions", "ci-first", "ci-second", "ci-content", "ci-path")

    first_fingerprint = store.create(_scan(first)).source_fingerprint
    second_fingerprint = store.create(_scan(second)).source_fingerprint
    (second / "a.txt").write_text("changed", encoding="utf-8")
    content_fingerprint = store.create(_scan(second)).source_fingerprint
    (second / "a.txt").write_text("A", encoding="utf-8")
    (second / "b.md").rename(second / "nested.md")
    path_fingerprint = store.create(_scan(second)).source_fingerprint

    assert first_fingerprint == second_fingerprint
    assert content_fingerprint != second_fingerprint
    assert path_fingerprint != second_fingerprint


def test_two_gets_return_equal_independent_models(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    store = _store(tmp_path / "sessions")
    session = store.create(_scan(source))

    first = store.get(session.session_id)
    second = store.get(session.session_id)

    assert first == second
    assert first is not second


def test_get_validates_session_schema(tmp_path: Path) -> None:
    from packages.story_core.continuation_sessions import ContinuationImportSession

    with pytest.raises(ValidationError):
        ContinuationImportSession.model_validate(
            {
                "schema_version": "continuation-import-session/v2",
                "session_id": "ci-invalid",
                "source_path": "novel.txt",
                "source_fingerprint": "abc",
                "encoding": "utf-8",
                "chapters": [],
            }
        )
