from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.story_core.continuation_analysis import ContinuationAnalysis
from packages.story_core.continuation_import import ContinuationChapter
from packages.story_core.continuation_sessions import ContinuationImportSession
from packages.story_core.file_project_store import FileProjectStore


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
        source_fingerprint="source-fingerprint",
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


def test_confirmed_session_creates_readable_file_project(tmp_path: Path) -> None:
    from packages.story_core.continuation_project import create_continuation_project

    session = _ready_session()
    created = create_continuation_project(
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
    created = create_continuation_project(
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


@pytest.mark.parametrize("chapter_number", [4, 99])
def test_conversion_rejects_invalid_continuation_point(
    tmp_path: Path, chapter_number: int
) -> None:
    from packages.story_core.continuation_project import create_continuation_project

    with pytest.raises(ValueError, match="invalid_continuation_point"):
        create_continuation_project(
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
        create_continuation_project(tmp_path, parsed, _settings(3))
    with pytest.raises(ValueError, match="continuation_analysis_not_confirmed"):
        create_continuation_project(tmp_path, unconfirmed, _settings(3))


def test_conversion_rejects_blocking_analysis_conflicts(tmp_path: Path) -> None:
    from packages.story_core.continuation_project import create_continuation_project

    with pytest.raises(ValueError, match="continuation_analysis_needs_confirmation"):
        create_continuation_project(
            tmp_path,
            _ready_session(needs_confirmation=True),
            _settings(3),
        )


def test_imported_filenames_are_safe_and_unicode_is_preserved(tmp_path: Path) -> None:
    from packages.story_core.continuation_project import create_continuation_project

    created = create_continuation_project(
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
    created = create_continuation_project(
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
    created = create_continuation_project(
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
    create_continuation_project(
        tmp_path,
        session,
        _settings(3),
        project_id_factory=lambda: "p-first",
    )

    with pytest.raises(FileExistsError, match="continuation_session_already_converted"):
        create_continuation_project(
            tmp_path,
            session,
            _settings(3),
            project_id_factory=lambda: "p-second",
        )
    with pytest.raises(FileExistsError, match="project_id_conflict"):
        create_continuation_project(
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
            project_id_factory=lambda: "p-atomic-failure",
        )

    assert list(tmp_path.iterdir()) == []
