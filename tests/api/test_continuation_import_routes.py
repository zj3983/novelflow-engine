from __future__ import annotations

import json
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
    monkeypatch.setenv(
        "NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path / "projects")
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
        running = continuation_imports._session_store().get(session["session_id"])
        second = client.post(f"/continuation-imports/{session['session_id']}/analyze")
        after_second = continuation_imports._session_store().get(session["session_id"])
        release.set()
        first_response = first.result(timeout=5)

    assert first_response.status_code == 202
    assert second.status_code == 202
    assert analyzer.calls == 1
    assert after_second.analysis_progress["_analysis_job_generation"] == (
        running.analysis_progress["_analysis_job_generation"]
    )


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


def test_old_callback_after_chapter_edit_does_not_call_provider(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports

    class CapturingTasks:
        def __init__(self) -> None:
            self.tasks = []

        def add_task(self, function, *args, **kwargs) -> None:
            self.tasks.append((function, args, kwargs))

    analyzer = _TitleAnalyzer()
    monkeypatch.setattr(continuation_imports, "build_continuation_analyzer", lambda: analyzer)
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    queued = CapturingTasks()
    continuation_imports.analyze(session["session_id"], queued)
    current = continuation_imports._session_store().get(session["session_id"])
    chapters = [chapter.model_copy(deep=True) for chapter in current.chapters]
    chapters[0].title = "edited after queue"
    continuation_imports._session_store().replace_chapters(
        session["session_id"],
        chapters,
        expected_revision=current.revision,
        invalidate_analysis=True,
    )

    function, args, kwargs = queued.tasks[0]
    function(*args, **kwargs)

    assert analyzer.calls == 0


def test_duplicate_callbacks_for_failed_generation_call_provider_once(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports

    class CapturingTasks:
        def __init__(self) -> None:
            self.tasks = []

        def add_task(self, function, *args, **kwargs) -> None:
            self.tasks.append((function, args, kwargs))

    class CountingFailure(_FailingAnalyzer):
        calls = 0

        def analyze_chapters(self, chapters):
            type(self).calls += 1
            return super().analyze_chapters(chapters)

    CountingFailure.calls = 0
    monkeypatch.setattr(continuation_imports, "build_continuation_analyzer", CountingFailure)
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    queued = CapturingTasks()
    continuation_imports.analyze(session["session_id"], queued)
    continuation_imports.analyze(session["session_id"], queued)
    assert len(queued.tasks) == 2

    for function, args, kwargs in queued.tasks:
        function(*args, **kwargs)

    assert CountingFailure.calls == 1
    assert continuation_imports._session_store().get(session["session_id"]).status == "failed"


def test_failed_generation_requires_new_post_before_provider_retry(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports

    class CapturingTasks:
        def __init__(self) -> None:
            self.tasks = []

        def add_task(self, function, *args, **kwargs) -> None:
            self.tasks.append((function, args, kwargs))

    class FailThenSucceed(_TitleAnalyzer):
        def analyze_chapters(self, chapters):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("first generation fails")
            return [
                ChapterAnalysis(chapter_id=chapter.chapter_id, summary=chapter.title)
                for chapter in chapters
            ]

    analyzer = FailThenSucceed()
    monkeypatch.setattr(continuation_imports, "build_continuation_analyzer", lambda: analyzer)
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    first = CapturingTasks()
    continuation_imports.analyze(session["session_id"], first)
    first.tasks[0][0](*first.tasks[0][1], **first.tasks[0][2])
    failed = continuation_imports._session_store().get(session["session_id"])
    first_generation = failed.analysis_progress["_analysis_job_generation"]

    second = CapturingTasks()
    continuation_imports.analyze(session["session_id"], second)
    queued = continuation_imports._session_store().get(session["session_id"])
    assert queued.analysis_progress["_analysis_job_generation"] != first_generation
    second.tasks[0][0](*second.tasks[0][1], **second.tasks[0][2])

    assert analyzer.calls == 2
    assert continuation_imports._session_store().get(session["session_id"]).status == "ready"


def test_running_generation_without_lease_is_replaced_and_requeued(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports

    class CapturingTasks:
        def __init__(self) -> None:
            self.tasks = []

        def add_task(self, function, *args, **kwargs) -> None:
            self.tasks.append((function, args, kwargs))

    analyzer = _TitleAnalyzer()
    monkeypatch.setattr(continuation_imports, "build_continuation_analyzer", lambda: analyzer)
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    store = continuation_imports._session_store()

    def crashed(current) -> None:
        current.status = "analyzing"
        current.analysis_progress["_analysis_job_generation"] = "old-generation"
        current.analysis_progress["_analysis_job_state"] = "running"

    store.update(session["session_id"], crashed, expected_revision=session["revision"])
    tasks = CapturingTasks()
    continuation_imports.analyze(session["session_id"], tasks)
    recovered = store.get(session["session_id"])

    assert recovered.analysis_progress["_analysis_job_generation"] != "old-generation"
    assert recovered.analysis_progress["_analysis_job_state"] == "queued"
    assert len(tasks.tasks) == 1
    tasks.tasks[0][0](*tasks.tasks[0][1], **tasks.tasks[0][2])
    assert analyzer.calls == 1


def test_concurrent_posts_create_one_effective_generation(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports
    from packages.story_core.continuation_sessions import ContinuationSessionStore

    class CapturingTasks:
        def __init__(self) -> None:
            self.tasks = []

        def add_task(self, function, *args, **kwargs) -> None:
            self.tasks.append((function, args, kwargs))

    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    original_get = ContinuationSessionStore.get
    barrier = threading.Barrier(2)
    calls = 0
    guard = threading.Lock()

    def synchronized_get(store, session_id):
        nonlocal calls
        value = original_get(store, session_id)
        with guard:
            should_wait = session_id == session["session_id"] and calls < 2
            if should_wait:
                calls += 1
        if should_wait:
            barrier.wait(timeout=5)
        return value

    monkeypatch.setattr(ContinuationSessionStore, "get", synchronized_get)
    tasks = [CapturingTasks(), CapturingTasks()]
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda item: continuation_imports.analyze(session["session_id"], item),
                tasks,
            )
        )

    generations = [item.tasks[0][1][1] for item in tasks]
    current = original_get(continuation_imports._session_store(), session["session_id"])
    assert [response.status for response in responses] == ["analyzing", "analyzing"]
    assert generations[0] == generations[1]
    assert current.analysis_progress["_analysis_job_generation"] == generations[0]


def test_new_generation_waits_for_old_generation_lease_handoff(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports
    from packages.story_core.continuation_sessions import try_acquire_analysis_lease

    class CapturingTasks:
        def __init__(self) -> None:
            self.tasks = []

        def add_task(self, function, *args, **kwargs) -> None:
            self.tasks.append((function, args, kwargs))

    analyzer = _TitleAnalyzer()
    monkeypatch.setattr(continuation_imports, "build_continuation_analyzer", lambda: analyzer)
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    old_tasks = CapturingTasks()
    continuation_imports.analyze(session["session_id"], old_tasks)
    store = continuation_imports._session_store()
    old_lease = try_acquire_analysis_lease(store.root, session["session_id"])
    assert old_lease is not None
    current = store.get(session["session_id"])
    chapters = [chapter.model_copy(deep=True) for chapter in current.chapters]
    chapters[0].title = "new generation chapter"
    store.replace_chapters(
        session["session_id"],
        chapters,
        expected_revision=current.revision,
        invalidate_analysis=True,
    )
    new_tasks = CapturingTasks()
    continuation_imports.analyze(session["session_id"], new_tasks)
    _, args, _ = new_tasks.tasks[0]
    waiting = threading.Event()
    continue_waiting = threading.Event()

    def wait_for_handoff(_seconds: float) -> None:
        waiting.set()
        assert continue_waiting.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            continuation_imports._run_analysis_job,
            args[0],
            args[1],
            0.001,
            wait_for_handoff,
        )
        assert waiting.wait(timeout=5)
        assert not future.done()
        old_lease.release()
        continue_waiting.set()
        future.result(timeout=5)

    assert analyzer.calls == 1
    assert store.get(session["session_id"]).status == "ready"


def test_failed_retry_waits_until_old_worker_releases_lease(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports
    from packages.story_core.continuation_sessions import try_acquire_analysis_lease

    class CapturingTasks:
        def __init__(self) -> None:
            self.tasks = []

        def add_task(self, function, *args, **kwargs) -> None:
            self.tasks.append((function, args, kwargs))

    analyzer = _TitleAnalyzer()
    monkeypatch.setattr(continuation_imports, "build_continuation_analyzer", lambda: analyzer)
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    first = CapturingTasks()
    continuation_imports.analyze(session["session_id"], first)
    store = continuation_imports._session_store()
    old_lease = try_acquire_analysis_lease(store.root, session["session_id"])
    assert old_lease is not None
    current = store.get(session["session_id"])

    def expose_failure(value) -> None:
        value.status = "failed"
        value.analysis_progress["_analysis_job_state"] = "running"

    store.update(
        session["session_id"], expose_failure, expected_revision=current.revision
    )
    retry = CapturingTasks()
    continuation_imports.analyze(session["session_id"], retry)
    _, args, _ = retry.tasks[0]
    waiting = threading.Event()
    continue_waiting = threading.Event()

    def wait_for_handoff(_seconds: float) -> None:
        waiting.set()
        assert continue_waiting.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            continuation_imports._run_analysis_job,
            args[0],
            args[1],
            0.001,
            wait_for_handoff,
        )
        assert waiting.wait(timeout=5)
        old_lease.release()
        continue_waiting.set()
        future.result(timeout=5)

    assert analyzer.calls == 1
    assert store.get(session["session_id"]).status == "ready"


def test_same_generation_duplicate_callback_exits_after_running_claim(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports

    class CapturingTasks:
        def __init__(self) -> None:
            self.tasks = []

        def add_task(self, function, *args, **kwargs) -> None:
            self.tasks.append((function, args, kwargs))

    started = threading.Event()
    release = threading.Event()

    class BlockingAnalyzer(_TitleAnalyzer):
        def analyze_chapters(self, chapters):
            started.set()
            assert release.wait(timeout=5)
            return super().analyze_chapters(chapters)

    analyzer = BlockingAnalyzer()
    monkeypatch.setattr(continuation_imports, "build_continuation_analyzer", lambda: analyzer)
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    tasks = CapturingTasks()
    continuation_imports.analyze(session["session_id"], tasks)
    continuation_imports.analyze(session["session_id"], tasks)
    assert len(tasks.tasks) == 2

    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(tasks.tasks[0][0], *tasks.tasks[0][1], **tasks.tasks[0][2])
        assert started.wait(timeout=5)
        tasks.tasks[1][0](*tasks.tasks[1][1], **tasks.tasks[1][2])
        release.set()
        first.result(timeout=5)

    assert analyzer.calls == 1


def test_lease_handoff_timeout_leaves_generation_queued(
    client: TestClient, allowed_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.routes import continuation_imports
    from packages.story_core.continuation_sessions import try_acquire_analysis_lease

    class CapturingTasks:
        def __init__(self) -> None:
            self.tasks = []

        def add_task(self, function, *args, **kwargs) -> None:
            self.tasks.append((function, args, kwargs))

    analyzer = _TitleAnalyzer()
    monkeypatch.setattr(continuation_imports, "build_continuation_analyzer", lambda: analyzer)
    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    tasks = CapturingTasks()
    continuation_imports.analyze(session["session_id"], tasks)
    store = continuation_imports._session_store()
    lease = try_acquire_analysis_lease(store.root, session["session_id"])
    assert lease is not None
    _, args, _ = tasks.tasks[0]
    try:
        continuation_imports._run_analysis_job(
            args[0],
            args[1],
            lease_poll_interval=0.01,
            lease_max_wait=0.03,
        )
    finally:
        lease.release()

    current = store.get(session["session_id"])
    assert current.status == "analyzing"
    assert current.analysis_progress["_analysis_job_state"] == "queued"
    assert analyzer.calls == 0


def test_zero_poll_interval_is_clamped_and_does_not_busy_wait(
    client: TestClient, allowed_root: Path
) -> None:
    from apps.api.routes import continuation_imports
    from packages.story_core.continuation_sessions import try_acquire_analysis_lease

    class CapturingTasks:
        def __init__(self) -> None:
            self.tasks = []

        def add_task(self, function, *args, **kwargs) -> None:
            self.tasks.append((function, args, kwargs))

    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    tasks = CapturingTasks()
    continuation_imports.analyze(session["session_id"], tasks)
    store = continuation_imports._session_store()
    lease = try_acquire_analysis_lease(store.root, session["session_id"])
    assert lease is not None
    now = 0.0
    sleeps: list[float] = []

    def monotonic() -> float:
        return now

    def wait(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    _, args, _ = tasks.tasks[0]
    try:
        continuation_imports._run_analysis_job(
            args[0],
            args[1],
            lease_poll_interval=0,
            wait=wait,
            lease_max_wait=0.025,
            monotonic=monotonic,
        )
    finally:
        lease.release()

    assert sleeps
    assert all(seconds > 0 for seconds in sleeps)
    assert min(sleeps) >= 0.004999
    assert len(sleeps) <= 3


def test_zero_lease_max_wait_returns_without_polling(
    client: TestClient, allowed_root: Path
) -> None:
    from apps.api.routes import continuation_imports
    from packages.story_core.continuation_sessions import try_acquire_analysis_lease

    class CapturingTasks:
        def __init__(self) -> None:
            self.tasks = []

        def add_task(self, function, *args, **kwargs) -> None:
            self.tasks.append((function, args, kwargs))

    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    tasks = CapturingTasks()
    continuation_imports.analyze(session["session_id"], tasks)
    store = continuation_imports._session_store()
    lease = try_acquire_analysis_lease(store.root, session["session_id"])
    assert lease is not None
    sleeps: list[float] = []
    _, args, _ = tasks.tasks[0]
    try:
        continuation_imports._run_analysis_job(
            args[0],
            args[1],
            lease_poll_interval=0,
            wait=sleeps.append,
            lease_max_wait=0,
        )
    finally:
        lease.release()

    assert sleeps == []
    assert store.get(session["session_id"]).analysis_progress[
        "_analysis_job_state"
    ] == "queued"


def test_lease_wait_exits_early_when_generation_state_changes(
    client: TestClient, allowed_root: Path
) -> None:
    from apps.api.routes import continuation_imports
    from packages.story_core.continuation_sessions import try_acquire_analysis_lease

    class CapturingTasks:
        def __init__(self) -> None:
            self.tasks = []

        def add_task(self, function, *args, **kwargs) -> None:
            self.tasks.append((function, args, kwargs))

    source = allowed_root / "book.txt"
    _write_book(source)
    session = client.post("/continuation-imports", json={"source_path": str(source)}).json()
    tasks = CapturingTasks()
    continuation_imports.analyze(session["session_id"], tasks)
    store = continuation_imports._session_store()
    lease = try_acquire_analysis_lease(store.root, session["session_id"])
    assert lease is not None
    waits = 0

    def invalidate(_seconds: float) -> None:
        nonlocal waits
        waits += 1
        current = store.get(session["session_id"])

        def reset(value) -> None:
            value.status = "parsed"
            value.analysis_progress = {}

        store.update(session["session_id"], reset, expected_revision=current.revision)

    _, args, _ = tasks.tasks[0]
    try:
        continuation_imports._run_analysis_job(
            args[0],
            args[1],
            lease_poll_interval=0.01,
            wait=invalidate,
            lease_max_wait=10,
        )
    finally:
        lease.release()

    assert waits == 1
    assert store.get(session["session_id"]).status == "parsed"


def test_failed_job_does_not_overwrite_a_newer_ready_state(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.routes import continuation_imports

    class CapturingTasks:
        def __init__(self) -> None:
            self.tasks = []

        def add_task(self, function, *args, **kwargs) -> None:
            self.tasks.append((function, args, kwargs))

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

    tasks = CapturingTasks()
    continuation_imports.analyze(session["session_id"], tasks)
    tasks.tasks[0][0](*tasks.tasks[0][1], **tasks.tasks[0][2])

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


def _analyzed_import(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict:
    from apps.api.routes import continuation_imports

    monkeypatch.setattr(
        continuation_imports, "build_continuation_analyzer", _SuccessfulAnalyzer
    )
    source = allowed_root / "续写原著.txt"
    _write_book(source)
    session = client.post(
        "/continuation-imports", json={"source_path": str(source)}
    ).json()
    analyzed = client.post(f"/continuation-imports/{session['session_id']}/analyze")
    assert analyzed.status_code == 202
    return client.get(f"/continuation-imports/{session['session_id']}").json()


def _confirm_analysis(client: TestClient, session: dict) -> dict:
    analysis = client.get(
        f"/continuation-imports/{session['session_id']}/analysis"
    ).json()
    response = client.put(
        f"/continuation-imports/{session['session_id']}/analysis",
        json={"expected_revision": session["revision"], "analysis": analysis},
    )
    assert response.status_code == 200
    return response.json()


def _create_project_payload(chapter_number: int = 2) -> dict:
    return {
        "expected_revision": 4,
        "settings": {
            "start_after_chapter": chapter_number,
            "fidelity": "faithful",
            "target_chars": 4500,
            "direction": "沿原有冲突继续",
            "planned_chapters": 20,
            "must_preserve": [],
            "forbidden_content": [],
            "generate_outline": False,
            "outline_chapters": 0,
            "novel_type_id": "generic_webnovel",
        },
    }


def test_create_project_requires_confirmed_analysis(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _analyzed_import(client, allowed_root, monkeypatch)
    payload = _create_project_payload()
    payload["expected_revision"] = session["revision"]

    response = client.post(
        f"/continuation-imports/{session['session_id']}/create-project",
        json=payload,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "continuation_analysis_not_confirmed"


def test_confirmed_import_creates_listed_file_project_and_outline_path(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _confirm_analysis(
        client, _analyzed_import(client, allowed_root, monkeypatch)
    )
    payload = _create_project_payload()
    payload["expected_revision"] = session["revision"]

    response = client.post(
        f"/continuation-imports/{session['session_id']}/create-project",
        json=payload,
    )

    assert response.status_code == 201
    created = response.json()
    assert created["project_id"].startswith("file:p-")
    assert created["next_path"].endswith("/outline")
    assert Path(created["source_path"]).is_dir()
    listed = client.get("/file-projects").json()
    assert any(item["project_id"] == created["project_id"] for item in listed)


def test_create_project_rejects_invalid_branch_conflicts_and_extra_fields(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _confirm_analysis(
        client, _analyzed_import(client, allowed_root, monkeypatch)
    )
    invalid = _create_project_payload(99)
    invalid["expected_revision"] = session["revision"]
    extra = _create_project_payload()
    extra["expected_revision"] = session["revision"]
    extra["settings"]["unexpected"] = True

    invalid_response = client.post(
        f"/continuation-imports/{session['session_id']}/create-project",
        json=invalid,
    )
    extra_response = client.post(
        f"/continuation-imports/{session['session_id']}/create-project",
        json=extra,
    )

    assert invalid_response.status_code == 422
    assert invalid_response.json()["detail"] == "invalid_continuation_point"
    assert extra_response.status_code == 422


def test_create_project_rejects_confirmed_payload_with_blocking_conflicts(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _analyzed_import(client, allowed_root, monkeypatch)
    analysis = client.get(
        f"/continuation-imports/{session['session_id']}/analysis"
    ).json()
    analysis["needs_confirmation"] = [
        {"claim": "人物身份冲突", "source": "characters.0"}
    ]
    confirmed = client.put(
        f"/continuation-imports/{session['session_id']}/analysis",
        json={"expected_revision": session["revision"], "analysis": analysis},
    ).json()
    payload = _create_project_payload()
    payload["expected_revision"] = confirmed["revision"]

    response = client.post(
        f"/continuation-imports/{session['session_id']}/create-project", json=payload
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "continuation_analysis_needs_confirmation"


def test_create_project_rejects_duplicate_session_with_stable_conflict(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _confirm_analysis(
        client, _analyzed_import(client, allowed_root, monkeypatch)
    )
    payload = _create_project_payload()
    payload["expected_revision"] = session["revision"]
    first = client.post(
        f"/continuation-imports/{session['session_id']}/create-project", json=payload
    )
    second = client.post(
        f"/continuation-imports/{session['session_id']}/create-project", json=payload
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["detail"] == "continuation_session_already_converted"


def test_create_project_rejects_live_source_change_before_claim(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _confirm_analysis(
        client, _analyzed_import(client, allowed_root, monkeypatch)
    )
    Path(session["source_path"]).write_text("第一章 已变化\n新的正文", encoding="utf-8")
    payload = _create_project_payload()
    payload["expected_revision"] = session["revision"]

    response = client.post(
        f"/continuation-imports/{session['session_id']}/create-project", json=payload
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "source_changed_since_scan"


def test_create_project_uses_session_original_backup_bytes(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _confirm_analysis(
        client, _analyzed_import(client, allowed_root, monkeypatch)
    )
    original = Path(session["source_path"]).read_bytes()
    payload = _create_project_payload()
    payload["expected_revision"] = session["revision"]

    response = client.post(
        f"/continuation-imports/{session['session_id']}/create-project", json=payload
    )

    assert response.status_code == 201
    project_root = Path(response.json()["source_path"])
    manifest = json.loads((project_root / "source/manifest.json").read_text("utf-8"))
    original_file = project_root / "source/original" / manifest["files"][0]["relative_path"]
    assert original_file.read_bytes() == original


def test_same_session_concurrent_api_conversion_has_one_success(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _confirm_analysis(
        client, _analyzed_import(client, allowed_root, monkeypatch)
    )
    payload = _create_project_payload()
    payload["expected_revision"] = session["revision"]
    barrier = threading.Barrier(2)

    def post_create():
        with TestClient(app, raise_server_exceptions=False) as thread_client:
            barrier.wait(timeout=5)
            return thread_client.post(
                f"/continuation-imports/{session['session_id']}/create-project",
                json=payload,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = [future.result(timeout=15) for future in [
            executor.submit(post_create),
            executor.submit(post_create),
        ]]

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert len(client.get("/file-projects").json()) == 1


@pytest.mark.parametrize(
    "finalize_error",
    [OSError("finalize disk secret"), ValueError("finalize value secret")],
    ids=["oserror", "valueerror"],
)
def test_finalize_failure_recovers_existing_project_without_copying(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    finalize_error: Exception,
) -> None:
    from packages.story_core.continuation_sessions import ContinuationSessionStore

    session = _confirm_analysis(
        client, _analyzed_import(client, allowed_root, monkeypatch)
    )
    original_finalize = ContinuationSessionStore.finalize_project_conversion
    calls = 0

    def fail_once(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise finalize_error
        return original_finalize(self, *args, **kwargs)

    monkeypatch.setattr(ContinuationSessionStore, "finalize_project_conversion", fail_once)
    payload = _create_project_payload()
    payload["expected_revision"] = session["revision"]
    first = client.post(
        f"/continuation-imports/{session['session_id']}/create-project", json=payload
    )
    claimed = client.get(f"/continuation-imports/{session['session_id']}").json()
    assert claimed["analysis_progress"]["project_conversion"]["status"] == "claimed"
    claimed_project_id = claimed["analysis_progress"]["project_conversion"]["project_id"]
    retry = _create_project_payload()
    retry["expected_revision"] = claimed["revision"]
    second = client.post(
        f"/continuation-imports/{session['session_id']}/create-project", json=retry
    )

    assert first.status_code == 500
    assert "secret" not in first.text
    assert second.status_code == 201
    assert len(client.get("/file-projects").json()) == 1
    assert second.json()["project_id"] == f"file:{claimed_project_id}"


def test_finalize_succeeds_after_live_source_is_deleted_post_publish(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.story_core.continuation_sessions import ContinuationSessionStore

    session = _confirm_analysis(
        client, _analyzed_import(client, allowed_root, monkeypatch)
    )
    original_finalize = ContinuationSessionStore.finalize_project_conversion

    def delete_then_finalize(self, session_id, **kwargs):
        Path(session["source_path"]).unlink(missing_ok=True)
        return original_finalize(self, session_id, **kwargs)

    monkeypatch.setattr(
        ContinuationSessionStore, "finalize_project_conversion", delete_then_finalize
    )
    payload = _create_project_payload()
    payload["expected_revision"] = session["revision"]

    response = client.post(
        f"/continuation-imports/{session['session_id']}/create-project", json=payload
    )

    assert response.status_code == 201
    saved = client.get(f"/continuation-imports/{session['session_id']}").json()
    assert saved["analysis_progress"]["project_conversion"]["status"] == "succeeded"


def test_unknown_conversion_oserror_returns_stable_500_without_details(
    client: TestClient,
    allowed_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from packages.story_core.continuation_sessions import ContinuationSessionStore

    session = _confirm_analysis(
        client, _analyzed_import(client, allowed_root, monkeypatch)
    )
    monkeypatch.setattr(
        ContinuationSessionStore,
        "claim_project_conversion",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk path secret")),
    )
    payload = _create_project_payload()
    payload["expected_revision"] = session["revision"]

    response = client.post(
        f"/continuation-imports/{session['session_id']}/create-project", json=payload
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "continuation_project_internal_error"
    assert "secret" not in response.text
