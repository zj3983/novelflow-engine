from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import multiprocessing
import time
from concurrent.futures import ThreadPoolExecutor
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


def _scan(source: Path) -> ContinuationScanResult:
    from packages.story_core.continuation_import import scan_continuation_source

    return scan_continuation_source(source)


def _store(root: Path, *session_ids: str, **store_options):
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
        **store_options,
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


def test_replace_rejects_empty_file_changed_to_empty_directory(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_bytes(b"")
    store = _store(tmp_path / "sessions")
    session = store.create(_scan(source))
    session_file = tmp_path / "sessions" / session.session_id / "session.json"
    before = session_file.read_bytes()
    source.unlink()
    source.mkdir()

    with pytest.raises(ValueError, match="^source_changed_since_scan$"):
        store.replace_chapters(session.session_id, [_chapter(1)])

    assert session_file.read_bytes() == before
    assert store.get(session.session_id) == session


def test_update_rejects_empty_directory_changed_to_empty_file(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    store = _store(tmp_path / "sessions")
    session = store.create(_scan(source))
    session_file = tmp_path / "sessions" / session.session_id / "session.json"
    before = session_file.read_bytes()
    source.rmdir()
    source.write_bytes(b"")

    with pytest.raises(ValueError, match="^source_changed_since_scan$"):
        store.update(session.session_id, lambda current: setattr(current, "status", "ready"))

    assert session_file.read_bytes() == before
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
    source.write_text("第一章 标题\n正文", encoding="utf-8")
    store = _store(tmp_path / "sessions")

    session = store.create(_scan(source))
    raw = (tmp_path / "sessions" / session.session_id / "session.json").read_text(encoding="utf-8")

    assert "正文" in raw
    assert "\\u6b63" not in raw
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


def test_two_store_updates_without_expected_revision_serialize_without_lost_fields(
    tmp_path: Path,
) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    root = tmp_path / "sessions"
    first_store = _store(root)
    second_store = _store(root)
    session = first_store.create(_scan(source))
    first_entered = threading.Event()
    release_first = threading.Event()

    def first_mutation(current):
        first_entered.set()
        release_first.wait(timeout=1)
        current.analysis["first"] = True

    def second_mutation(current):
        current.analysis["second"] = True
        release_first.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first_store.update, session.session_id, first_mutation)
        assert first_entered.wait(timeout=1)
        second_future = executor.submit(second_store.update, session.session_id, second_mutation)
        first_future.result(timeout=3)
        second_future.result(timeout=3)

    loaded = first_store.get(session.session_id)
    assert loaded.revision == 3
    assert loaded.analysis == {"first": True, "second": True}


def test_two_store_updates_with_same_expected_revision_conflict(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    root = tmp_path / "sessions"
    first_store = _store(root)
    second_store = _store(root)
    session = first_store.create(_scan(source))
    first_entered = threading.Event()
    release_first = threading.Event()

    def first_mutation(current):
        first_entered.set()
        release_first.wait(timeout=1)
        current.analysis["first"] = True

    def second_mutation(current):
        current.analysis["second"] = True
        release_first.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(first_store.update, session.session_id, first_mutation, 1)
        assert first_entered.wait(timeout=1)
        second_future = executor.submit(second_store.update, session.session_id, second_mutation, 1)
        outcomes = []
        for future in (first_future, second_future):
            try:
                outcomes.append(future.result(timeout=3))
            except ValueError as exc:
                outcomes.append(str(exc))

    assert sum(outcome == "session_revision_conflict" for outcome in outcomes) == 1
    assert sum(not isinstance(outcome, str) for outcome in outcomes) == 1
    assert first_store.get(session.session_id).revision == 2


def test_create_rejects_source_changed_after_scan_without_creating_session(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("第一章 初见\n旧正文", encoding="utf-8")
    scan = _scan(source)
    source.write_text("第一章 初见\n新正文", encoding="utf-8")
    root = tmp_path / "sessions"
    store = _store(root)

    with pytest.raises(ValueError, match="^source_changed_since_scan$"):
        store.create(scan)

    assert not (root / "ci-test-session").exists()
    assert list(root.glob(".ci-test-session.*")) == []


def test_create_session_json_failure_is_clean_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import packages.story_core.continuation_sessions as sessions_module

    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    root = tmp_path / "sessions"
    store = _store(root, "ci-retry", "ci-retry")
    original_write = sessions_module._write_json_atomic

    def fail_session_json(path, payload):
        if path.name == "session.json":
            raise OSError("session write failed")
        original_write(path, payload)

    monkeypatch.setattr(sessions_module, "_write_json_atomic", fail_session_json)
    with pytest.raises(OSError, match="session write failed"):
        store.create(_scan(source))

    assert not (root / "ci-retry").exists()
    assert list(root.glob(".ci-retry.*")) == []
    monkeypatch.setattr(sessions_module, "_write_json_atomic", original_write)
    assert store.create(_scan(source)).session_id == "ci-retry"


def test_create_publish_failure_is_clean_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import packages.story_core.continuation_sessions as sessions_module

    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    root = tmp_path / "sessions"
    store = _store(root, "ci-publish", "ci-publish")
    original_rename = os.rename

    def fail_publish(source_path, destination_path):
        raise OSError("publish failed")

    monkeypatch.setattr(sessions_module.os, "rename", fail_publish)
    with pytest.raises(OSError, match="publish failed"):
        store.create(_scan(source))

    assert not (root / "ci-publish").exists()
    assert list(root.glob(".ci-publish.*")) == []
    monkeypatch.setattr(sessions_module.os, "rename", original_rename)
    assert store.create(_scan(source)).session_id == "ci-publish"


def _created_session_paths(tmp_path: Path):
    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    root = tmp_path / "sessions"
    store = _store(root)
    session = store.create(_scan(source))
    session_root = root / session.session_id
    return store, session, session_root


def test_get_rejects_manifest_path_traversal_without_revision_change(tmp_path: Path) -> None:
    store, session, session_root = _created_session_paths(tmp_path)
    session_file = session_root / "session.json"
    before = session_file.read_bytes()
    manifest_path = session_root / "source" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["relative_path"] = "../../outside.txt"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="^source_manifest_invalid$"):
        store.get(session.session_id)

    assert session_file.read_bytes() == before


def test_get_rejects_manifest_source_kind_inconsistent_with_backup(tmp_path: Path) -> None:
    store, session, session_root = _created_session_paths(tmp_path)
    session_file = session_root / "session.json"
    before = session_file.read_bytes()
    manifest_path = session_root / "source" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_kind"] = "directory"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="^source_manifest_invalid$"):
        store.get(session.session_id)

    assert session_file.read_bytes() == before


@pytest.mark.parametrize("damage", ["delete", "tamper"])
def test_get_rejects_missing_or_tampered_backup_without_revision_change(
    tmp_path: Path, damage: str
) -> None:
    store, session, session_root = _created_session_paths(tmp_path)
    session_file = session_root / "session.json"
    before = session_file.read_bytes()
    backup = session_root / "source" / "original" / "novel.txt"
    if damage == "delete":
        backup.unlink()
    else:
        backup.write_text("篡改", encoding="utf-8")

    with pytest.raises(ValueError, match="^source_backup_invalid$"):
        store.update(session.session_id, lambda current: setattr(current, "status", "ready"))

    assert session_file.read_bytes() == before


def test_containment_helper_rejects_path_outside_root(tmp_path: Path) -> None:
    from packages.story_core.continuation_sessions import _resolve_contained_path

    root = (tmp_path / "root").resolve()
    root.mkdir()

    with pytest.raises(ValueError, match="^invalid_session_path$"):
        _resolve_contained_path(root, root / ".." / "outside")


def test_get_rejects_symlinked_session_directory(tmp_path: Path) -> None:
    store, session, session_root = _created_session_paths(tmp_path)
    outside = tmp_path / "outside-session"
    session_root.rename(outside)
    try:
        os.symlink(outside, session_root, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        outside.rename(session_root)
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="^invalid_session_path$"):
        store.get(session.session_id)


def test_create_rejects_directory_member_renamed_after_scan(tmp_path: Path) -> None:
    source = tmp_path / "source"
    original_parent = source / "old"
    renamed_parent = source / "new"
    original_parent.mkdir(parents=True)
    original = original_parent / "chapter.txt"
    original.write_text("正文", encoding="utf-8")
    scan = _scan(source)
    renamed_parent.mkdir()
    original.rename(renamed_parent / "chapter.txt")
    store = _store(tmp_path / "sessions")

    with pytest.raises(ValueError, match="^source_changed_since_scan$"):
        store.create(scan)


def test_create_rejects_single_file_offset_shift_after_scan(tmp_path: Path) -> None:
    source = tmp_path / "novel.md"
    source.write_text("# Chapter\nBody", encoding="utf-8")
    scan = _scan(source)
    assert scan.chapters
    source.write_text("\n# Chapter\nBody", encoding="utf-8")
    store = _store(tmp_path / "sessions")

    with pytest.raises(ValueError, match="^source_changed_since_scan$"):
        store.create(scan)


def test_update_mutation_can_get_same_session_reentrantly(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    store = _store(
        tmp_path / "sessions",
        lock_timeout=0.5,
        lock_poll_interval=0.01,
    )
    session = store.create(_scan(source))

    def mutate(current):
        nested = store.get(session.session_id)
        current.analysis["nested_revision"] = nested.revision

    updated = store.update(session.session_id, mutate)

    assert updated.revision == 2
    assert updated.analysis == {"nested_revision": 1}


def test_waiting_store_retries_until_longer_lock_is_released(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    root = tmp_path / "sessions"
    first_store = _store(root, lock_timeout=1, lock_poll_interval=0.01)
    second_store = _store(root, lock_timeout=1, lock_poll_interval=0.01)
    session = first_store.create(_scan(source))
    entered = threading.Event()
    release = threading.Event()

    def hold_lock(current):
        entered.set()
        assert release.wait(timeout=1)
        current.analysis["first"] = True

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(first_store.update, session.session_id, hold_lock)
        assert entered.wait(timeout=1)
        second = executor.submit(
            second_store.update,
            session.session_id,
            lambda current: current.analysis.update({"second": True}),
        )
        time.sleep(0.05)
        assert not second.done()
        release.set()
        first.result(timeout=2)
        second.result(timeout=2)

    loaded = first_store.get(session.session_id)
    assert loaded.revision == 3
    assert loaded.analysis == {"first": True, "second": True}


def test_lock_timeout_is_stable_and_lock_recovers(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("原稿", encoding="utf-8")
    root = tmp_path / "sessions"
    holder_store = _store(root, lock_timeout=1, lock_poll_interval=0.01)
    waiting_store = _store(root, lock_timeout=0.05, lock_poll_interval=0.005)
    session = holder_store.create(_scan(source))
    entered = threading.Event()
    release = threading.Event()

    def hold_lock(current):
        entered.set()
        assert release.wait(timeout=1)
        current.analysis["holder"] = True

    with ThreadPoolExecutor(max_workers=1) as executor:
        held = executor.submit(holder_store.update, session.session_id, hold_lock)
        assert entered.wait(timeout=1)
        with pytest.raises(ValueError, match="^session_lock_timeout$"):
            waiting_store.update(
                session.session_id,
                lambda current: current.analysis.update({"timed_out": True}),
            )
        release.set()
        held.result(timeout=2)

    recovered = waiting_store.update(
        session.session_id,
        lambda current: current.analysis.update({"recovered": True}),
    )
    assert recovered.revision == 3
    assert recovered.analysis == {"holder": True, "recovered": True}


def test_secure_open_rejects_session_directory_swapped_after_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import packages.story_core.continuation_sessions as sessions_module

    store, session, session_root = _created_session_paths(tmp_path)
    outside = tmp_path / "outside-session"
    shutil.copytree(session_root, outside)
    probe = tmp_path / "symlink-probe"
    try:
        os.symlink(outside, probe, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    else:
        probe.unlink()

    parked = tmp_path / "parked-session"
    swapped = False

    def swap_after_check(path: Path) -> None:
        nonlocal swapped
        if swapped or path.name != "session.json":
            return
        session_root.rename(parked)
        os.symlink(outside, session_root, target_is_directory=True)
        swapped = True

    monkeypatch.setattr(
        sessions_module,
        "_before_secure_open",
        swap_after_check,
        raising=False,
    )

    with pytest.raises(ValueError, match="^invalid_session_path$"):
        store.get(session.session_id)
    assert swapped is True
def _try_analysis_lease_in_child(root: str, session_id: str, queue) -> None:
    from packages.story_core.continuation_sessions import try_acquire_analysis_lease

    lease = try_acquire_analysis_lease(Path(root), session_id)
    queue.put(lease is not None)
    if lease is not None:
        lease.release()


def test_analysis_lease_is_nonblocking_across_processes(tmp_path: Path) -> None:
    from packages.story_core.continuation_sessions import try_acquire_analysis_lease

    root = tmp_path / "sessions"
    root.mkdir()
    lease = try_acquire_analysis_lease(root, "ci-cross-process")
    assert lease is not None
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    process = context.Process(
        target=_try_analysis_lease_in_child,
        args=(str(root), "ci-cross-process", queue),
    )
    process.start()
    process.join(timeout=10)
    try:
        assert process.exitcode == 0
        assert queue.get(timeout=2) is False
    finally:
        lease.release()

    reacquired = try_acquire_analysis_lease(root, "ci-cross-process")
    assert reacquired is not None
    reacquired.release()


def test_analysis_lease_is_nonblocking_in_same_process(tmp_path: Path) -> None:
    from packages.story_core.continuation_sessions import try_acquire_analysis_lease

    root = tmp_path / "sessions"
    root.mkdir()
    first = try_acquire_analysis_lease(root, "ci-same-process")
    assert first is not None
    try:
        assert try_acquire_analysis_lease(root, "ci-same-process") is None
    finally:
        first.release()
