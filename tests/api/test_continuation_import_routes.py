from __future__ import annotations

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
    assert traversal.json()["detail"].startswith("path_outside_allowed_roots")
    assert invalid_type.status_code == 422
    assert invalid_type.json()["detail"] == "unsupported_source_type"


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
