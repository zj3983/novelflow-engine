"""Phase 3E regressions for trusted continuity snapshot boundaries."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from packages.story_core.continuity.snapshot import ChapterSnapshot
from packages.story_core.continuity.store import ContinuityStore
from packages.story_core.continuity.delta import ContinuityDelta
from packages.story_core.file_project_store import FileProjectStore


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _body(tag: str) -> str:
    return (f"{tag}。他确认眼前的结果，承担代价，并把下一步安排落到行动上。" * 700)[:5200]


def _make_project(root: Path, *, current_chapter: int = 0) -> FileProjectStore:
    project = {"project_id": "phase3e-story", "title": "Phase 3E", "active_story_id": "phase3e-story"}
    state = {
        "story_id": "phase3e-story",
        "outline": "A continuity boundary test.",
        "genre": "urban",
        "style": "plain",
        "current_chapter": current_chapter,
        "world_facts": [],
        "characters": [],
        "progression_ledger": {},
        "timeline": [],
        "foreshadowing": [],
        "chapter_summaries": [],
        "memory_index": [],
        "arc_recaps": [],
    }
    _write_json(root / ".story-system" / "MASTER_SETTING.json", {
        "schema_version": "story-system-master-setting/v1",
        "project": project,
        "state": deepcopy(state),
    })
    _write_json(root / ".webnovel" / "project.json", project)
    _write_json(root / ".webnovel" / "state.json", state)
    return FileProjectStore(root)


def _candidate(store: FileProjectStore, chapter: int, *, operation: str = "generate", tag: str | None = None):
    bundle = SimpleNamespace(
        chapter_number=chapter,
        chapter_title=f"第{chapter}章",
        title=f"第{chapter}章",
        body=_body(tag or f"第{chapter}章正文"),
        quality_report={"ok": True},
        context_snapshot_id=f"ctx-{chapter}",
    )
    return store._save_candidate_from_bundle(bundle, project_id="phase3e-story", operation=operation)


def _snapshot(store: ContinuityStore, chapter: int, marker: str) -> ChapterSnapshot:
    snapshot = ChapterSnapshot(
        chapter_number=chapter,
        candidate_id=f"candidate-{chapter}",
        operation="generate",
        confirmed_at="2026-01-01T00:00:00+00:00",
        body_sha256="body",
        body_chars=4,
        state_after={"current_chapter": chapter, "progression_ledger": {"marker": marker}},
    )
    store.write_snapshot(snapshot)
    return snapshot


def test_continuity_store_fresh_reads_skip_stale_snapshots(tmp_path):
    store = ContinuityStore(tmp_path)
    _snapshot(store, 1, "one")
    _snapshot(store, 2, "two")

    store.mark_stale([2])

    assert store.read_fresh_snapshot(1).chapter_number == 1
    assert store.read_fresh_snapshot(2) is None
    assert store.latest_fresh_snapshot_before(3).chapter_number == 1


def test_normal_append_writes_a_fresh_end_chapter_snapshot(tmp_path):
    store = _make_project(tmp_path)
    candidate = _candidate(store, 1)

    store.confirm_candidate(candidate.candidate_id)

    snapshot = store.continuity_store.read_fresh_snapshot(1)
    assert snapshot is not None
    assert snapshot.state_after["current_chapter"] == 1
    assert store.continuity_store.get_stale_chapters() == []


def test_historical_confirmation_writes_snapshot_at_end_target_without_future_state(tmp_path):
    store = _make_project(tmp_path)
    for chapter in (1, 2, 3):
        store.confirm_candidate(_candidate(store, chapter, tag=f"正文-{chapter}" ).candidate_id)

    state_before = json.loads((tmp_path / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    state_before["progression_ledger"] = {"future_only": "FUTURE_ONLY_CH3"}
    state_before["characters"] = [{"name": "FUTURE_ONLY_CHARACTER", "role": "npc"}]
    _write_json(tmp_path / ".webnovel" / "state.json", state_before)

    downstream_files = {
        path: path.read_bytes()
        for directory in (tmp_path / ".story-system" / "chapters", tmp_path / "chapters")
        for path in directory.glob("000[23]*")
    }

    replacement = _candidate(store, 1, operation="regenerate", tag="替换第一章")
    result = store.confirm_candidate(replacement.candidate_id)

    assert result["candidate"]["status"] == "confirmed"
    snapshot = store.continuity_store.read_snapshot(1)
    assert snapshot is not None
    assert snapshot.state_after.get("current_chapter") == 1
    assert "FUTURE_ONLY_CH3" not in json.dumps(snapshot.state_after, ensure_ascii=False)
    assert "FUTURE_ONLY_CHARACTER" not in json.dumps(snapshot.state_after, ensure_ascii=False)
    assert store.continuity_store.get_stale_chapters() == [2, 3]
    assert {path: path.read_bytes() for path in downstream_files} == downstream_files


def test_stale_marker_failure_rolls_back_historical_confirmation(tmp_path, monkeypatch):
    store = _make_project(tmp_path)
    for chapter in (1, 2):
        store.confirm_candidate(_candidate(store, chapter).candidate_id)
    replacement = _candidate(store, 1, operation="regenerate")
    before = {
        path: path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    def fail_mark_stale(_chapters):
        raise OSError("injected_stale_write_failure")

    monkeypatch.setattr(store.continuity_store, "mark_stale", fail_mark_stale)

    try:
        store.confirm_candidate(replacement.candidate_id)
    except OSError as exc:
        assert str(exc) == "injected_stale_write_failure"
    else:  # pragma: no cover - the injected write must fail
        raise AssertionError("historical confirmation unexpectedly succeeded")

    after = {
        path: path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert store.candidate_store.get(replacement.candidate_id).status == "pending"


def test_reconfirming_a_stale_chapter_refreshes_only_that_boundary(tmp_path):
    store = _make_project(tmp_path)
    for chapter in (1, 2, 3):
        store.confirm_candidate(_candidate(store, chapter).candidate_id)
    rewrite_one = _candidate(store, 1, operation="regenerate", tag="重写第一章")
    store.confirm_candidate(rewrite_one.candidate_id)
    assert store.continuity_store.get_stale_chapters() == [2, 3]
    snapshot_one_after_rewrite = store.continuity_store.snapshot_path(1).read_bytes()

    rewrite_two = _candidate(store, 2, operation="regenerate", tag="重写第二章")
    store.confirm_candidate(rewrite_two.candidate_id)

    assert store.continuity_store.read_fresh_snapshot(2) is not None
    assert store.continuity_store.get_stale_chapters() == [3]
    assert store.continuity_store.snapshot_path(1).read_bytes() == snapshot_one_after_rewrite


def test_regeneration_base_uses_nearest_fresh_snapshot_and_replays_past_stale_chapters(tmp_path):
    store = _make_project(tmp_path, current_chapter=4)
    for chapter in (1, 2, 3, 4):
        _write_json(tmp_path / ".story-system" / "chapters" / f"{chapter:04d}.json", {
            "chapter_number": chapter,
            "chapter_title": f"第{chapter}章",
            "chapter_summary": {"summary": f"chapter {chapter}", "facts": [], "next_focus": "continue"},
        })
    _snapshot(store.continuity_store, 1, "fresh-1")
    _snapshot(store.continuity_store, 2, "fresh-2")
    _snapshot(store.continuity_store, 3, "stale-3")
    _snapshot(store.continuity_store, 4, "stale-4")
    store.continuity_store.mark_stale([3, 4])

    base = store._regeneration_base_state(5, store.state())

    assert base["current_chapter"] == 4
    assert base["progression_ledger"]["marker"] == "fresh-2"
    assert [item["chapter_number"] for item in base["chapter_summaries"]] == [3, 4]


def test_historical_plan_degrades_to_stale_only_without_trusted_boundary(tmp_path):
    store = _make_project(tmp_path, current_chapter=3)
    (tmp_path / ".story-system" / "MASTER_SETTING.json").unlink()
    candidate = _candidate(store, 1, operation="regenerate")

    plan = store._plan_continuity_snapshot(candidate)

    assert plan.mode == "STALE_ONLY"
    assert "CONTINUITY_HISTORY_BASELINE_UNAVAILABLE" in plan.findings
    assert plan.snapshot_payload is None


def test_direct_generated_chapter_gets_snapshot_and_can_be_replaced_historically(tmp_path, monkeypatch):
    store = _make_project(tmp_path)
    monkeypatch.setattr(store, "rolling_fill_status", lambda _target: {"status": "present"})
    monkeypatch.setattr(store, "require_volume_detail_for_prose", lambda _target: {})

    class Engine:
        def generate_next_chapter(self, story):
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="直接生成",
                body=_body("直接生成正文"),
                quality_report={"ok": True},
                chapter_summary={
                    "summary": "direct chapter",
                    "facts": [],
                    "next_focus": "continue",
                },
                updated_story=story.model_copy(update={"current_chapter": 1}),
                continuity_delta=ContinuityDelta(chapter_number=1).model_dump(mode="json"),
            )

    generated = store.generate_next_chapter(engine=Engine())
    assert generated["chapter_number"] == 1
    assert store.continuity_store.read_snapshot(1).candidate_id == "generated:1"

    replacement = _candidate(store, 1, operation="regenerate", tag="直接生成替换")
    replacement.continuity_delta = ContinuityDelta(chapter_number=1)
    store.candidate_store.save(replacement)

    confirmed = store.confirm_candidate(replacement.candidate_id)

    assert confirmed["candidate"]["status"] == "confirmed"
    assert store.continuity_store.read_snapshot(1).candidate_id == replacement.candidate_id
