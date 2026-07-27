from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from packages.story_core.continuation_analysis import ChapterAnalysis, ContinuationAnalysis


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("NOVEL_AUTOGROWTH_ALLOWED_FS_ROOTS", str(allowed))
    monkeypatch.setenv(
        "NOVEL_AUTOGROWTH_CONTINUATION_IMPORTS_DIR", str(tmp_path / "sessions")
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def allowed_root(tmp_path: Path) -> Path:
    return tmp_path / "allowed"


def _write_book(path: Path) -> None:
    path.write_text(
        "第一章 开端\n正文一\n第二章 相遇\n正文二",
        encoding="utf-8",
    )


class _SuccessfulAnalyzer:
    calls = 0

    def analyze_chapters(self, chapters):
        type(self).calls += 1
        return [ChapterAnalysis(chapter_id=chapter.chapter_id, summary=chapter.title) for chapter in chapters]

    def merge(self, chapter_results, recent_chapters):
        return ContinuationAnalysis(
            story_overview="已分析",
            continuation_start={"chapter_id": recent_chapters[-1].chapter_id},
        )


class _FailingAnalyzer:
    def analyze_chapters(self, chapters):
        raise ValueError("provider_secret_must_not_leak: token=abc")

    def merge(self, chapter_results, recent_chapters):
        raise AssertionError("unreachable")


class _TitleAnalyzer:
    def __init__(self) -> None:
        self.calls = 0

    def analyze_chapters(self, chapters):
        self.calls += 1
        return [
            ChapterAnalysis(chapter_id=chapter.chapter_id, summary=chapter.title)
            for chapter in chapters
        ]

    def merge(self, chapter_results, recent_chapters):
        return ContinuationAnalysis(
            story_overview="|".join(result.summary for result in chapter_results),
            continuation_start={"chapter_id": recent_chapters[-1].chapter_id},
        )


def test_source_browser_lists_roots_supported_files_and_directories(
    client: TestClient, allowed_root: Path
) -> None:
    (allowed_root / "novel.txt").write_text("第一章 A\n正文", encoding="utf-8")
    (allowed_root / "notes.json").write_text("{}", encoding="utf-8")
    (allowed_root / "chapters").mkdir()

    roots = client.post("/continuation-imports/list-sources", json={"source_path": ""})
    listed = client.post(
        "/continuation-imports/list-sources", json={"source_path": str(allowed_root)}
    )

    assert roots.status_code == 200
    assert [Path(item["path"]).resolve() for item in roots.json()["directories"]] == [
        allowed_root.resolve()
    ]
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()["directories"]] == ["chapters"]
    assert [item["name"] for item in listed.json()["files"]] == ["novel.txt"]


def test_scan_rejects_traversal_and_unsupported_file(
    client: TestClient, allowed_root: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("no", encoding="utf-8")
    unsupported = allowed_root / "book.pdf"
    unsupported.write_bytes(b"pdf")

    traversal = client.post(
        "/continuation-imports/scan", json={"source_path": str(outside)}
    )
    invalid_type = client.post(
        "/continuation-imports/scan", json={"source_path": str(unsupported)}
    )

    assert traversal.status_code == 403
    assert traversal.json()["detail"] == "path_outside_allowed_roots"
    assert str(outside.resolve()) not in traversal.text
    assert invalid_type.status_code == 422
    assert invalid_type.json()["detail"] == "unsupported_source_type"


def test_scan_and_create_reject_nested_supported_symlink_outside_allowed_root(
    client: TestClient, allowed_root: Path, tmp_path: Path
) -> None:
    source_dir = allowed_root / "chapters"
    source_dir.mkdir()
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("第一章 外部秘密\n绝不能读取", encoding="utf-8")
    linked = source_dir / "linked.txt"
    try:
        linked.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    scanned = client.post(
        "/continuation-imports/scan", json={"source_path": str(source_dir)}
    )
    created = client.post(
        "/continuation-imports", json={"source_path": str(source_dir)}
    )

    assert scanned.status_code == 403
    assert scanned.json()["detail"] == "path_outside_allowed_roots"
    assert "绝不能读取" not in scanned.text
    assert created.status_code == 403
    assert created.json()["detail"] == "path_outside_allowed_roots"
    assert "绝不能读取" not in created.text


def test_scan_rejects_nested_windows_junction_before_descending(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.routes import continuation_imports

    source_dir = allowed_root / "chapters"
    junction = source_dir / "junction"
    junction.mkdir(parents=True)
    (junction / "chapter.txt").write_text("第一章 不应读取\n正文", encoding="utf-8")
    original = continuation_imports._is_link_or_junction
    monkeypatch.setattr(
        continuation_imports,
        "_is_link_or_junction",
        lambda path: path == junction or original(path),
    )

    response = client.post(
        "/continuation-imports/scan", json={"source_path": str(source_dir)}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "path_outside_allowed_roots"
    assert "不应读取" not in response.text


def test_scan_rechecks_source_tree_after_parser_to_detect_link_swap(
    client: TestClient,
    allowed_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.routes import continuation_imports

    source_dir = allowed_root / "chapters"
    source_dir.mkdir()
    chapter = source_dir / "chapter.txt"
    chapter.write_text("第一章 原正文\n正文", encoding="utf-8")
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("第一章 外部秘密\n绝不能返回", encoding="utf-8")
    original_scan = continuation_imports.scan_continuation_source

    def swap_after_scan(*args, **kwargs):
        result = original_scan(*args, **kwargs)
        chapter.unlink()
        chapter.symlink_to(outside)
        return result

    monkeypatch.setattr(
        continuation_imports, "scan_continuation_source", swap_after_scan
    )

    response = client.post(
        "/continuation-imports/scan", json={"source_path": str(source_dir)}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "path_outside_allowed_roots"
    assert "绝不能返回" not in response.text


def test_create_rejects_link_swap_between_scan_and_session_backup(
    client: TestClient,
    allowed_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.story_core.continuation_sessions import ContinuationSessionStore

    source_dir = allowed_root / "chapters"
    source_dir.mkdir()
    chapter = source_dir / "chapter.txt"
    content = "第一章 相同正文\n不能因内容相同而放行"
    chapter.write_text(content, encoding="utf-8")
    outside = tmp_path / "outside-same-content.txt"
    outside.write_text(content, encoding="utf-8")
    original_create = ContinuationSessionStore.create

    def swap_before_backup(store, scan):
        chapter.unlink()
        chapter.symlink_to(outside)
        return original_create(store, scan)

    monkeypatch.setattr(ContinuationSessionStore, "create", swap_before_backup)

    response = client.post(
        "/continuation-imports", json={"source_path": str(source_dir)}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "path_outside_allowed_roots"
    assert "outside-same-content" not in response.text


@pytest.mark.parametrize("source_kind", ["file", "directory"])
def test_scan_rejects_file_swapped_to_outside_link_during_secure_open(
    client: TestClient,
    allowed_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_kind: str,
) -> None:
    from packages.story_core import continuation_sessions

    source_dir = allowed_root / "chapters"
    source_dir.mkdir()
    chapter = source_dir / "chapter.txt"
    _write_book(chapter)
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("SECRET_BODY_MUST_NOT_LEAK", encoding="utf-8")
    source = chapter if source_kind == "file" else source_dir
    original_open = continuation_sessions.os.open
    swapped = False

    def swap_then_restore(path, flags, *args, **kwargs):
        nonlocal swapped
        candidate = Path(path)
        if candidate == chapter and not swapped:
            swapped = True
            chapter.unlink()
            chapter.symlink_to(outside)
            try:
                return original_open(path, flags, *args, **kwargs)
            finally:
                chapter.unlink()
                _write_book(chapter)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(continuation_sessions.os, "open", swap_then_restore)

    response = client.post(
        "/continuation-imports/scan", json={"source_path": str(source)}
    )

    assert swapped
    assert response.status_code == 403
    assert response.json()["detail"] == "path_outside_allowed_roots"
    assert "SECRET_BODY_MUST_NOT_LEAK" not in response.text


def test_scan_reports_missing_path(client: TestClient, allowed_root: Path) -> None:
    response = client.post(
        "/continuation-imports/scan",
        json={"source_path": str(allowed_root / "missing.txt")},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "source_path_not_found"


def test_missing_session_and_unready_analysis_have_stable_errors(
    client: TestClient, allowed_root: Path
) -> None:
    missing = client.get("/continuation-imports/ci-missing")
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    unready = client.get(f"/continuation-imports/{session['session_id']}/analysis")

    assert missing.status_code == 404
    assert missing.json()["detail"] == "session_not_found"
    assert unready.status_code == 409
    assert unready.json()["detail"] == "analysis_not_ready"


def test_create_get_and_revision_protected_chapter_edit(
    client: TestClient, allowed_root: Path
) -> None:
    source = allowed_root / "book.txt"
    _write_book(source)
    created = client.post("/continuation-imports", json={"source_path": str(source)})
    assert created.status_code == 201
    session = created.json()

    fetched = client.get(f"/continuation-imports/{session['session_id']}")
    chapters = fetched.json()["chapters"]
    chapters[0]["title"] = "新开端"
    updated = client.put(
        f"/continuation-imports/{session['session_id']}/chapters",
        json={"expected_revision": session["revision"], "chapters": chapters},
    )
    conflict = client.put(
        f"/continuation-imports/{session['session_id']}/chapters",
        json={"expected_revision": session["revision"], "chapters": chapters},
    )

    assert fetched.status_code == 200
    assert updated.status_code == 200
    assert updated.json()["chapters"][0]["title"] == "新开端"
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "session_revision_conflict"


def test_analyze_is_idempotent_and_persists_success(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports

    _SuccessfulAnalyzer.calls = 0
    monkeypatch.setattr(continuation_imports, "build_continuation_analyzer", _SuccessfulAnalyzer)
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()

    first = client.post(f"/continuation-imports/{session['session_id']}/analyze")
    second = client.post(f"/continuation-imports/{session['session_id']}/analyze")
    fetched = client.get(f"/continuation-imports/{session['session_id']}")

    assert first.status_code == 202
    assert second.status_code == 202
    assert fetched.json()["status"] == "ready"
    assert fetched.json()["analysis"]["story_overview"] == "已分析"
    assert _SuccessfulAnalyzer.calls == 1


def test_editing_ready_chapters_invalidates_analysis_and_reanalyzes(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports

    analyzer = _TitleAnalyzer()
    monkeypatch.setattr(
        continuation_imports, "build_continuation_analyzer", lambda: analyzer
    )
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    client.post(f"/continuation-imports/{session['session_id']}/analyze")
    ready = client.get(f"/continuation-imports/{session['session_id']}").json()
    chapters = ready["chapters"]
    chapters[0]["title"] = "重写后的开端"

    edited = client.put(
        f"/continuation-imports/{session['session_id']}/chapters",
        json={"expected_revision": ready["revision"], "chapters": chapters},
    )

    assert edited.status_code == 200
    assert edited.json()["status"] == "parsed"
    assert edited.json()["analysis"] == {}
    assert edited.json()["analysis_progress"] == {}
    client.post(f"/continuation-imports/{session['session_id']}/analyze")
    rerun = client.get(f"/continuation-imports/{session['session_id']}").json()
    assert rerun["status"] == "ready"
    assert rerun["analysis"]["story_overview"].startswith("重写后的开端|")
    assert analyzer.calls == 2


def test_concurrent_analyze_requests_are_both_idempotently_accepted(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.routes import continuation_imports
    from packages.story_core.continuation_sessions import ContinuationSessionStore

    monkeypatch.setattr(continuation_imports, "build_continuation_analyzer", _SuccessfulAnalyzer)
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    original_get = ContinuationSessionStore.get
    barrier = threading.Barrier(2)
    counter_lock = threading.Lock()
    blocked_calls = 0

    def synchronized_get(store, session_id):
        nonlocal blocked_calls
        result = original_get(store, session_id)
        should_wait = False
        with counter_lock:
            if session_id == session["session_id"] and blocked_calls < 2:
                blocked_calls += 1
                should_wait = True
        if should_wait:
            barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(ContinuationSessionStore, "get", synchronized_get)

    def start_analysis() -> int:
        with TestClient(app, raise_server_exceptions=False) as thread_client:
            return thread_client.post(
                f"/continuation-imports/{session['session_id']}/analyze"
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: start_analysis(), range(2)))

    assert statuses == [202, 202]


def test_persisted_analyzing_without_local_task_is_reenqueued_after_restart(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports

    analyzer = _TitleAnalyzer()
    monkeypatch.setattr(
        continuation_imports, "build_continuation_analyzer", lambda: analyzer
    )
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    store = continuation_imports._session_store()
    store.update(
        session["session_id"],
        lambda current: setattr(current, "status", "analyzing"),
        expected_revision=session["revision"],
    )

    response = client.post(f"/continuation-imports/{session['session_id']}/analyze")
    recovered = client.get(f"/continuation-imports/{session['session_id']}").json()

    assert response.status_code == 202
    assert recovered["status"] == "ready"
    assert analyzer.calls == 1


def test_active_analysis_is_not_duplicated(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports

    started = threading.Event()
    release = threading.Event()

    class BlockingAnalyzer(_TitleAnalyzer):
        def analyze_chapters(self, chapters):
            started.set()
            assert release.wait(timeout=5)
            return super().analyze_chapters(chapters)

    analyzer = BlockingAnalyzer()
    monkeypatch.setattr(
        continuation_imports, "build_continuation_analyzer", lambda: analyzer
    )
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()

    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            client.post, f"/continuation-imports/{session['session_id']}/analyze"
        )
        assert started.wait(timeout=5)
        second = client.post(f"/continuation-imports/{session['session_id']}/analyze")
        release.set()
        first_response = first.result(timeout=5)

    assert first_response.status_code == 202
    assert second.status_code == 202
    assert analyzer.calls == 1


def test_background_failure_preserves_session_and_safe_error(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports

    monkeypatch.setattr(continuation_imports, "build_continuation_analyzer", _FailingAnalyzer)
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()

    started = client.post(f"/continuation-imports/{session['session_id']}/analyze")
    fetched = client.get(f"/continuation-imports/{session['session_id']}")

    assert started.status_code == 202
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "failed"
    assert fetched.json()["chapters"]
    assert fetched.json()["error"] == "continuation_analysis_failed"
    assert "token=abc" not in fetched.text


def test_analyze_does_not_hold_lease_when_background_registration_fails(
    client: TestClient, allowed_root: Path
) -> None:
    from apps.api.routes import continuation_imports
    from packages.story_core.continuation_sessions import try_acquire_analysis_lease

    class BrokenBackgroundTasks:
        def add_task(self, *args, **kwargs) -> None:
            raise RuntimeError("scheduler unavailable")

    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    with pytest.raises(RuntimeError, match="scheduler unavailable"):
        continuation_imports.analyze(session["session_id"], BrokenBackgroundTasks())

    store = continuation_imports._session_store()
    lease = try_acquire_analysis_lease(store.root, session["session_id"])
    assert lease is not None
    lease.release()


def test_dropped_background_callback_can_be_scheduled_again_and_complete(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.routes import continuation_imports

    class DroppingBackgroundTasks:
        def __init__(self) -> None:
            self.calls = 0

        def add_task(self, *args, **kwargs) -> None:
            self.calls += 1

    class RunningBackgroundTasks:
        def __init__(self) -> None:
            self.calls = 0

        def add_task(self, function, *args, **kwargs) -> None:
            self.calls += 1
            function(*args, **kwargs)

    analyzer = _TitleAnalyzer()
    monkeypatch.setattr(
        continuation_imports, "build_continuation_analyzer", lambda: analyzer
    )
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    dropped = DroppingBackgroundTasks()
    running = RunningBackgroundTasks()

    first = continuation_imports.analyze(session["session_id"], dropped)
    second = continuation_imports.analyze(session["session_id"], running)

    assert first.status == "analyzing"
    assert dropped.calls == 1
    assert second.status == "analyzing"
    assert running.calls == 1
    assert analyzer.calls == 1
    assert continuation_imports._session_store().get(session["session_id"]).status == "ready"


def test_late_duplicate_background_callback_does_not_rerun_provider(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.routes import continuation_imports

    class CapturingBackgroundTasks:
        def __init__(self) -> None:
            self.tasks = []

        def add_task(self, function, *args, **kwargs) -> None:
            self.tasks.append((function, args, kwargs))

    analyzer = _TitleAnalyzer()
    monkeypatch.setattr(
        continuation_imports, "build_continuation_analyzer", lambda: analyzer
    )
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    queued = CapturingBackgroundTasks()

    continuation_imports.analyze(session["session_id"], queued)
    continuation_imports.analyze(session["session_id"], queued)
    assert len(queued.tasks) == 2

    for function, args, kwargs in queued.tasks:
        function(*args, **kwargs)

    assert analyzer.calls == 1
    assert continuation_imports._session_store().get(session["session_id"]).status == "ready"


def test_failed_job_does_not_overwrite_a_newer_ready_state(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.routes import continuation_imports

    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    store = continuation_imports._session_store()

    def become_ready_then_fail(active_store, session_id, analyzer) -> None:
        current = active_store.get(session_id)

        def ready(value) -> None:
            value.status = "ready"
            value.analysis = {"newer": True}

        active_store.update(session_id, ready, expected_revision=current.revision)
        raise RuntimeError("old worker failed")

    monkeypatch.setattr(continuation_imports, "_session_store", lambda: store)
    monkeypatch.setattr(
        continuation_imports, "run_continuation_analysis", become_ready_then_fail
    )

    continuation_imports._run_analysis_job(session["session_id"])

    current = store.get(session["session_id"])
    assert current.status == "ready"
    assert current.analysis == {"newer": True}


def test_analyze_does_not_hold_registry_lock_during_session_update(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports
    from packages.story_core.continuation_sessions import ContinuationSessionStore

    monkeypatch.setattr(continuation_imports, "build_continuation_analyzer", _SuccessfulAnalyzer)

    first_source = allowed_root / "first.txt"
    second_source = allowed_root / "second.txt"
    _write_book(first_source)
    _write_book(second_source)
    first = client.post("/continuation-imports", json={"source_path": str(first_source)}).json()
    second = client.post("/continuation-imports", json={"source_path": str(second_source)}).json()
    entered = threading.Event()
    release = threading.Event()
    original_update = ContinuationSessionStore.update

    def blocking_update(store, session_id, *args, **kwargs):
        if session_id == first["session_id"]:
            entered.set()
            assert release.wait(timeout=5)
        return original_update(store, session_id, *args, **kwargs)

    monkeypatch.setattr(ContinuationSessionStore, "update", blocking_update)

    def post_analyze(session_id: str):
        with TestClient(app, raise_server_exceptions=False) as thread_client:
            return thread_client.post(f"/continuation-imports/{session_id}/analyze")

    with ThreadPoolExecutor(max_workers=2) as executor:
        blocked = executor.submit(post_analyze, first["session_id"])
        assert entered.wait(timeout=5)
        independent = executor.submit(post_analyze, second["session_id"])
        response = independent.result(timeout=2)
        release.set()
        blocked.result(timeout=5)

    assert response.status_code == 202


def test_analysis_can_be_confirmed_with_revision_protection(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports

    monkeypatch.setattr(continuation_imports, "build_continuation_analyzer", _SuccessfulAnalyzer)
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    client.post(f"/continuation-imports/{session['session_id']}/analyze")
    ready = client.get(f"/continuation-imports/{session['session_id']}").json()
    analysis = client.get(
        f"/continuation-imports/{session['session_id']}/analysis"
    ).json()
    analysis["story_overview"] = "人工确认后的概况"

    saved = client.put(
        f"/continuation-imports/{session['session_id']}/analysis",
        json={"expected_revision": ready["revision"], "analysis": analysis},
    )

    assert saved.status_code == 200
    assert saved.json()["analysis"]["story_overview"] == "人工确认后的概况"


def test_requests_forbid_extra_fields(client: TestClient) -> None:
    response = client.post(
        "/continuation-imports/scan", json={"source_path": "x", "surprise": True}
    )
    assert response.status_code == 422


def test_chapter_edit_request_forbids_nested_extra_fields(
    client: TestClient, allowed_root: Path
) -> None:
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    chapters = session["chapters"]
    chapters[0]["unexpected"] = True

    response = client.put(
        f"/continuation-imports/{session['session_id']}/chapters",
        json={"expected_revision": session["revision"], "chapters": chapters},
    )

    assert response.status_code == 422
