from __future__ import annotations

import json
import hashlib
import multiprocessing
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from packages.story_core.continuation_analysis import ContinuationAnalysis
from packages.story_core.continuation_import import ContinuationChapter
from packages.story_core.continuation_sessions import ContinuationImportSession
from packages.story_core.file_project_store import FileProjectStore


_SOURCE_BYTES = "第一章原始字节\r\n第二行".encode("utf-8")
_SOURCE_FINGERPRINT = hashlib.sha256(_SOURCE_BYTES).hexdigest()


def _chapter(number: int, title: str, body: str) -> ContinuationChapter:
    return ContinuationChapter(
        chapter_id=f"chapter-{number}",
        number=number,
        title=title,
        body=body,
        source_name="原著.txt",
        source_start=number * 100,
        source_end=number * 100 + len(body),
        fingerprint=f"fingerprint-{number}",
    )


def _ready_session(*, needs_confirmation: bool = False) -> ContinuationImportSession:
    chapters = [
        _chapter(1, "雨夜来客", "雨落长街。沈砚推开旧书店的门。"),
        _chapter(2, "纸上迷城", "地图上的墨线忽然亮起，通往失落的城。"),
        _chapter(3, "不能使用的标题/..\\:*?\"<>|", "钟声之后，追兵封住了渡口。"),
    ]
    analysis = ContinuationAnalysis.model_validate(
        {
            "story_overview": "沈砚追查一张会变化的地图。",
            "characters": [
                {
                    "name": "沈砚",
                    "role": "protagonist",
                    "summary": "谨慎的旧书店学徒",
                    "confidence": "confirmed",
                    "states": [{"claim": "被追兵围堵", "confidence": "confirmed"}],
                    "relationships": [
                        {"claim": "与守钟人互相试探", "confidence": "confirmed"}
                    ],
                }
            ],
            "world": [{"claim": "地图会随钟声改变", "confidence": "confirmed"}],
            "power_system": [{"claim": "墨契需要以记忆为代价", "confidence": "confirmed"}],
            "timeline": [
                {
                    "text": "沈砚得到地图",
                    "sequence": "第一章",
                    "confidence": "confirmed",
                }
            ],
            "open_hooks": [
                {"text": "地图尽头是谁", "status": "open", "confidence": "confirmed"}
            ],
            "style_profile": {
                "narrative_voice": "克制",
                "point_of_view": "第三人称限知",
                "pacing": "紧凑",
                "dialogue_style": "短句",
                "prose_features": ["环境推动悬念"],
                "confidence": "confirmed",
            },
            "continuation_start": {
                "chapter_id": "chapter-3",
                "situation": "追兵封锁渡口",
                "guidance": "让地图秘密与追兵正面碰撞",
            },
            "needs_confirmation": (
                [{"claim": "追兵身份冲突", "source": "characters.0"}]
                if needs_confirmation
                else []
            ),
        }
    )
    return ContinuationImportSession(
        session_id="ci-ready-session",
        revision=7,
        status="ready",
        source_path=str(Path("C:/小说/迷城.txt")),
        source_fingerprint=_SOURCE_FINGERPRINT,
        encoding="utf-8",
        chapters=chapters,
        analysis=analysis.model_dump(mode="json"),
        analysis_progress={"analysis_confirmed": True},
    )


def _settings(start_after_chapter: int):
    from packages.story_core.continuation_project import ContinuationSettings

    return ContinuationSettings(
        start_after_chapter=start_after_chapter,
        fidelity="faithful",
        target_chars=4500,
        direction="沿原有冲突继续",
        planned_chapters=20,
        must_preserve=["地图以记忆为代价"],
        forbidden_content=["复活已死亡角色"],
        generate_outline=True,
        outline_chapters=10,
    )


def _source_snapshot():
    from packages.story_core.continuation_sessions import (
        ContinuationSourceSnapshot,
        ContinuationSourceSnapshotFile,
    )

    payload = _SOURCE_BYTES
    fingerprint = _SOURCE_FINGERPRINT
    return ContinuationSourceSnapshot(
        source_kind="file",
        source_fingerprint=_SOURCE_FINGERPRINT,
        encoding="utf-8",
        files=[
            ContinuationSourceSnapshotFile(
                relative_path="迷城.txt",
                fingerprint=fingerprint,
                payload=payload,
            )
        ],
    )


def _create_project(export_root, session, settings, **kwargs):
    from packages.story_core.continuation_project import create_continuation_project

    return create_continuation_project(
        export_root,
        session,
        settings,
        source_snapshot=_source_snapshot(),
        **kwargs,
    )


def _conversion_process_worker(
    export_root: str,
    session_payload: dict,
    settings_payload: dict,
    snapshot_payload: dict,
    project_id: str,
    start_event,
    result_queue,
) -> None:
    from packages.story_core.continuation_project import (
        ContinuationSettings,
        create_continuation_project,
    )
    from packages.story_core.continuation_sessions import (
        ContinuationImportSession,
        ContinuationSourceSnapshot,
    )

    start_event.wait(10)
    try:
        created = create_continuation_project(
            export_root,
            ContinuationImportSession.model_validate(session_payload),
            ContinuationSettings.model_validate(settings_payload),
            source_snapshot=ContinuationSourceSnapshot.model_validate(snapshot_payload),
            project_id_factory=lambda: project_id,
        )
        result_queue.put(("ok", created.project_id))
    except Exception as exc:
        result_queue.put(("error", str(exc)))


def test_confirmed_session_creates_readable_file_project(tmp_path: Path) -> None:
    from packages.story_core.continuation_project import create_continuation_project

    session = _ready_session()
    created = _create_project(
        export_root=tmp_path / "projects",
        session=session,
        settings=_settings(3),
        project_id_factory=lambda: "p-continuation-test",
    )

    store = FileProjectStore(created.root)
    assert store.exists()
    assert store.summary()["current_chapter"] == 3
    assert store.chapter_numbers() == [1, 2, 3]
    assert store.chapter(2)["body"] == session.chapters[1].body
    project = store.project()
    state = store.state()
    assert project["continuation"]["fidelity"] == "faithful"
    assert project["continuation"]["session_id"] == session.session_id
    assert project["continuation"]["excluded_source_chapters"] == []
    assert state["characters"][0]["name"] == "沈砚"
    assert "地图会随钟声改变" in state["world_facts"]
    assert state["foreshadowing"][0]["text"] == "地图尽头是谁"
    assert created.next_path == "/projects/file%3Ap-continuation-test/outline"


def test_conversion_excludes_source_chapters_after_branch_point(tmp_path: Path) -> None:
    from packages.story_core.continuation_project import create_continuation_project

    session = _ready_session()
    session.analysis["world"].append(
        {
            "claim": "第三章才揭露的未来事实",
            "confidence": "confirmed",
            "evidence": [
                {
                    "chapter_id": "chapter-3",
                    "excerpt_start": 0,
                    "excerpt_end": 2,
                    "quote": "钟声",
                }
            ],
        }
    )
    created = _create_project(
        export_root=tmp_path,
        session=session,
        settings=_settings(1),
        project_id_factory=lambda: "p-continuation-branch",
    )

    store = FileProjectStore(created.root)
    continuation = store.project()["continuation"]
    assert store.chapter_numbers() == [1]
    assert continuation["branch_point"] == 1
    assert continuation["excluded_source_chapters"] == [2, 3]
    assert continuation["excluded_source_chapter_ids"] == ["chapter-2", "chapter-3"]
    assert store.state()["current_chapter"] == 1
    assert "第三章才揭露的未来事实" not in store.state()["world_facts"]
    active_analysis = json.loads(
        (created.root / ".story-system/continuation-analysis.json").read_text("utf-8")
    )
    source_analysis = json.loads(
        (created.root / "source/analysis.json").read_text("utf-8")
    )
    assert all(
        item["claim"] != "第三章才揭露的未来事实"
        for item in active_analysis["world"]
    )
    assert source_analysis["world"][-1]["claim"] == "第三章才揭露的未来事实"


def test_branch_project_and_writing_packet_never_include_future_source_text(
    tmp_path: Path,
) -> None:
    from packages.story_core.continuation_project import create_continuation_project

    session = _ready_session()
    accepted_evidence = [
        {
            "chapter_id": "chapter-1",
            "excerpt_start": 0,
            "excerpt_end": 2,
            "quote": "雨落",
        }
    ]
    future_evidence = [
        {
            "chapter_id": "chapter-3",
            "excerpt_start": 0,
            "excerpt_end": 2,
            "quote": "钟声",
        }
    ]
    character = session.analysis["characters"][0]
    character["evidence"] = accepted_evidence
    character["states"].append(
        {
            "claim": "FUTURE_SECRET_STATE",
            "confidence": "confirmed",
            "evidence": future_evidence,
        }
    )
    character["relationships"].append(
        {
            "claim": "沈砚与守钟人是FUTURE_SECRET_RELATION",
            "confidence": "confirmed",
            "evidence": future_evidence,
        }
    )
    for field, payload in (
        (
            "world",
            {
                "claim": "FUTURE_SECRET_WORLD",
                "confidence": "confirmed",
                "evidence": future_evidence,
            },
        ),
        (
            "power_system",
            {
                "claim": "FUTURE_SECRET_POWER",
                "confidence": "confirmed",
                "evidence": future_evidence,
            },
        ),
        (
            "timeline",
            {
                "text": "FUTURE_SECRET_TIMELINE",
                "sequence": "第三章",
                "confidence": "confirmed",
                "evidence": future_evidence,
            },
        ),
        (
            "open_hooks",
            {
                "text": "FUTURE_SECRET_HOOK",
                "status": "open",
                "confidence": "confirmed",
                "evidence": future_evidence,
            },
        ),
    ):
        session.analysis[field].append(payload)
    session.analysis["style_profile"]["narrative_voice"] = "FUTURE_SECRET_STYLE"
    session.analysis["style_profile"]["evidence"] = future_evidence
    session.analysis["continuation_start"] = {
        "chapter_id": "chapter-3",
        "situation": "FUTURE_SECRET_SITUATION",
        "guidance": "FUTURE_SECRET_GUIDANCE",
        "constraints": [
            {
                "claim": "FUTURE_SECRET_CONSTRAINT",
                "confidence": "confirmed",
                "evidence": future_evidence,
            }
        ],
    }

    created = _create_project(
        tmp_path,
        session,
        _settings(1).model_copy(update={"direction": ""}),
        project_id_factory=lambda: "p-no-future-secret",
    )

    store = FileProjectStore(created.root)
    active_payloads = {
        "project": store.project(),
        "state": store.state(),
        "analysis": json.loads(
            (created.root / ".story-system/continuation-analysis.json").read_text(
                "utf-8"
            )
        ),
        "writing_packet": store.writing_packet(2),
    }
    for name, payload in active_payloads.items():
        assert "FUTURE_SECRET" not in json.dumps(payload, ensure_ascii=False), name
    archived = (created.root / "source/analysis.json").read_text("utf-8")
    assert "FUTURE_SECRET_GUIDANCE" in archived


@pytest.mark.parametrize("chapter_number", [4, 99])
def test_conversion_rejects_invalid_continuation_point(
    tmp_path: Path, chapter_number: int
) -> None:
    from packages.story_core.continuation_project import create_continuation_project

    with pytest.raises(ValueError, match="invalid_continuation_point"):
        _create_project(
            tmp_path,
            _ready_session(),
            _settings(chapter_number),
            project_id_factory=lambda: "p-invalid-point",
        )


def test_conversion_requires_ready_and_human_confirmed_analysis(tmp_path: Path) -> None:
    from packages.story_core.continuation_project import create_continuation_project

    parsed = _ready_session().model_copy(update={"status": "parsed"})
    unconfirmed = _ready_session()
    unconfirmed.analysis_progress = {}

    with pytest.raises(ValueError, match="continuation_session_not_ready"):
        _create_project(tmp_path, parsed, _settings(3))
    with pytest.raises(ValueError, match="continuation_analysis_not_confirmed"):
        _create_project(tmp_path, unconfirmed, _settings(3))


def test_conversion_rejects_blocking_analysis_conflicts(tmp_path: Path) -> None:
    from packages.story_core.continuation_project import create_continuation_project

    with pytest.raises(ValueError, match="continuation_analysis_needs_confirmation"):
        _create_project(
            tmp_path,
            _ready_session(needs_confirmation=True),
            _settings(3),
        )


def test_imported_filenames_are_safe_and_unicode_is_preserved(tmp_path: Path) -> None:
    from packages.story_core.continuation_project import create_continuation_project

    created = _create_project(
        tmp_path,
        _ready_session(),
        _settings(3),
        project_id_factory=lambda: "p-unicode",
    )

    markdowns = sorted((created.root / "chapters").glob("*.md"))
    assert len(markdowns) == 3
    assert all(path.parent == created.root / "chapters" for path in markdowns)
    assert all(not any(char in path.name for char in '\\/:*?"<>|') for path in markdowns)
    assert markdowns[-1].read_text(encoding="utf-8") == "钟声之后，追兵封住了渡口。"


def test_source_manifest_and_index_record_imported_and_excluded_chapters(
    tmp_path: Path,
) -> None:
    from packages.story_core.continuation_project import create_continuation_project

    session = _ready_session()
    created = _create_project(
        tmp_path,
        session,
        _settings(2),
        project_id_factory=lambda: "p-source-index",
    )

    manifest = json.loads((created.root / "source/manifest.json").read_text("utf-8"))
    index = json.loads(
        (created.root / ".story-system/source-index.json").read_text("utf-8")
    )
    assert manifest["source_fingerprint"] == session.source_fingerprint
    assert [item["status"] for item in index["chapters"]] == [
        "imported",
        "imported",
        "excluded_after_branch",
    ]
    assert index["chapters"][2]["chapter_id"] == "chapter-3"
    assert all("body" not in item for item in index["chapters"])
    excluded_reference = created.root / index["chapters"][2]["reference_path"]
    assert excluded_reference.read_text("utf-8") == session.chapters[2].body


def test_original_source_snapshot_preserves_bytes_paths_and_file_hashes(
    tmp_path: Path,
) -> None:
    import hashlib

    from packages.story_core.continuation_project import create_continuation_project
    from packages.story_core.continuation_sessions import (
        ContinuationSourceSnapshot,
        ContinuationSourceSnapshotFile,
    )

    first = b"raw\r\nbytes\x00one"
    second = "中文原始内容".encode("gb18030")
    files = [
        ("卷一/01.txt", first),
        ("02.md", second),
    ]
    combined = hashlib.sha256()
    for relative_path, payload in sorted(files):
        combined.update(relative_path.encode("utf-8"))
        combined.update(b"\0")
        combined.update(hashlib.sha256(payload).hexdigest().encode("ascii"))
        combined.update(b"\n")
    source_fingerprint = combined.hexdigest()
    snapshot = ContinuationSourceSnapshot(
        source_kind="directory",
        source_fingerprint=source_fingerprint,
        encoding="mixed",
        files=[
            ContinuationSourceSnapshotFile(
                relative_path="卷一/01.txt",
                fingerprint=hashlib.sha256(first).hexdigest(),
                payload=first,
            ),
            ContinuationSourceSnapshotFile(
                relative_path="02.md",
                fingerprint=hashlib.sha256(second).hexdigest(),
                payload=second,
            ),
        ],
    )

    session = _ready_session().model_copy(
        update={"source_fingerprint": source_fingerprint, "encoding": "mixed"}
    )
    created = create_continuation_project(
        tmp_path,
        session,
        _settings(3),
        source_snapshot=snapshot,
        project_id_factory=lambda: "p-originals",
    )

    assert (created.root / "source/original/卷一/01.txt").read_bytes() == first
    assert (created.root / "source/original/02.md").read_bytes() == second
    manifest = json.loads((created.root / "source/manifest.json").read_text("utf-8"))
    assert manifest["source_kind"] == "directory"
    assert [(item["relative_path"], item["fingerprint"]) for item in manifest["files"]] == [
        ("卷一/01.txt", hashlib.sha256(first).hexdigest()),
        ("02.md", hashlib.sha256(second).hexdigest()),
    ]


def test_same_session_concurrent_direct_conversion_only_publishes_one_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.story_core import continuation_project

    original_write = continuation_project._write_continuation_project

    def slow_write(*args, **kwargs):
        import time

        time.sleep(0.2)
        return original_write(*args, **kwargs)

    monkeypatch.setattr(continuation_project, "_write_continuation_project", slow_write)
    session = _ready_session()

    def convert(project_id: str):
        return continuation_project.create_continuation_project(
            tmp_path,
            session,
            _settings(3),
            source_snapshot=_source_snapshot(),
            project_id_factory=lambda: project_id,
        )

    successes = []
    errors = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(convert, "p-race-one"),
            executor.submit(convert, "p-race-two"),
        ]
        for future in futures:
            try:
                successes.append(future.result(timeout=10))
            except FileExistsError as exc:
                errors.append(str(exc))

    assert len(successes) == 1
    assert errors == ["continuation_session_already_converted"]
    published = [path for path in tmp_path.iterdir() if path.name.startswith("p-")]
    assert len(published) == 1


def test_same_session_cross_process_conversion_only_publishes_one_project(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    result_queue = context.Queue()
    session_payload = _ready_session().model_dump(mode="python")
    settings_payload = _settings(3).model_dump(mode="python")
    snapshot_payload = _source_snapshot().model_dump(mode="python")
    processes = [
        context.Process(
            target=_conversion_process_worker,
            args=(
                str(tmp_path),
                session_payload,
                settings_payload,
                snapshot_payload,
                project_id,
                start_event,
                result_queue,
            ),
        )
        for project_id in ("p-process-one", "p-process-two")
    ]
    for process in processes:
        process.start()
    start_event.set()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    results = [result_queue.get(timeout=5) for _ in processes]

    assert sorted(status for status, _ in results) == ["error", "ok"]
    assert [message for status, message in results if status == "error"] == [
        "continuation_session_already_converted"
    ]
    assert len([path for path in tmp_path.iterdir() if path.name.startswith("p-")]) == 1


def test_relationship_graph_and_timeline_keep_evidence_chapter_and_sequence(
    tmp_path: Path,
) -> None:
    session = _ready_session()
    evidence = [
        {
            "chapter_id": "chapter-2",
            "excerpt_start": 0,
            "excerpt_end": 2,
            "quote": "地图",
        }
    ]
    session.analysis["characters"].append(
        {
            "name": "守钟人",
            "role": "antagonist",
            "summary": "守住旧城秘密",
            "confidence": "confirmed",
            "evidence": evidence,
        }
    )
    session.analysis["characters"][0]["relationships"] = [
        {
            "claim": "沈砚与守钟人互相试探",
            "confidence": "confirmed",
            "evidence": evidence,
        }
    ]
    session.analysis["timeline"] = [
        {
            "text": "地图第一次发光",
            "sequence": "第二章夜里",
            "confidence": "confirmed",
            "evidence": evidence,
        }
    ]

    created = _create_project(
        tmp_path,
        session,
        _settings(3),
        project_id_factory=lambda: "p-mappings",
    )
    store = FileProjectStore(created.root)

    edge = store.project()["relationship_graph"][0]
    assert {edge["source"], edge["target"]} == {"沈砚", "守钟人"}
    assert edge["current_state"] == "沈砚与守钟人互相试探"
    assert edge["first_chapter"] == 2
    assert store.state()["timeline"] == [
        {
            "chapter_number": 2,
            "summary": "地图第一次发光",
            "impact": "第二章夜里",
        }
    ]


def test_inferred_analysis_is_preserved_but_not_promoted_to_formal_state(
    tmp_path: Path,
) -> None:
    from packages.story_core.continuation_project import create_continuation_project

    session = _ready_session()
    session.analysis["world"].append(
        {"claim": "城主可能就是守钟人", "confidence": "inferred", "evidence": []}
    )
    session.analysis["open_hooks"].append(
        {
            "text": "未经确认的暗门",
            "status": "uncertain",
            "confidence": "inferred",
            "evidence": [],
        }
    )
    created = _create_project(
        tmp_path,
        session,
        _settings(3),
        project_id_factory=lambda: "p-inferred",
    )

    state = FileProjectStore(created.root).state()
    analysis = json.loads((created.root / "source/analysis.json").read_text("utf-8"))
    assert "城主可能就是守钟人" not in state["world_facts"]
    assert all(item["text"] != "未经确认的暗门" for item in state["foreshadowing"])
    assert analysis["world"][-1]["claim"] == "城主可能就是守钟人"


def test_same_session_or_project_cannot_be_created_twice(tmp_path: Path) -> None:
    from packages.story_core.continuation_project import create_continuation_project

    session = _ready_session()
    _create_project(
        tmp_path,
        session,
        _settings(3),
        project_id_factory=lambda: "p-first",
    )

    with pytest.raises(FileExistsError, match="continuation_session_already_converted"):
        _create_project(
            tmp_path,
            session,
            _settings(3),
            project_id_factory=lambda: "p-second",
        )
    with pytest.raises(FileExistsError, match="project_id_conflict"):
        _create_project(
            tmp_path,
            _ready_session().model_copy(update={"session_id": "ci-other"}),
            _settings(3),
            project_id_factory=lambda: "p-first",
        )


def test_validation_failure_leaves_no_partial_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from packages.story_core import continuation_project

    def fail_validation(*_args, **_kwargs):
        raise ValueError("invalid_staged_project")

    monkeypatch.setattr(
        continuation_project, "_validate_continuation_project", fail_validation
    )
    with pytest.raises(ValueError, match="invalid_staged_project"):
        continuation_project.create_continuation_project(
            tmp_path,
            _ready_session(),
            _settings(3),
            source_snapshot=_source_snapshot(),
            project_id_factory=lambda: "p-atomic-failure",
        )

    assert not any(path.name.startswith("p-") for path in tmp_path.iterdir())
    assert not list(tmp_path.glob(".*.tmp-*"))
