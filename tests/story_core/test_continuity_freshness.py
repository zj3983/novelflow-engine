"""Phase 3E regressions for trusted continuity snapshot boundaries."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.story_core.continuity.snapshot import ChapterSnapshot
from packages.story_core.continuity.store import ContinuityStore
from packages.story_core.continuity.delta import ContinuityDelta, EntityAddition
from packages.story_core.fact_resource_ledger import FactResourceDelta, FactResourceExtraction
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


def test_historical_candidate_updated_story_is_not_trusted_as_snapshot_authority(tmp_path):
    store = _make_project(tmp_path)
    for chapter in (1, 2, 3):
        store.confirm_candidate(_candidate(store, chapter, tag=f"正文-{chapter}").candidate_id)

    replacement = _candidate(store, 1, operation="regenerate", tag="候选第一章")
    candidate_story = deepcopy(store.persisted_state())
    candidate_story["current_chapter"] = 1
    candidate_story["progression_ledger"] = {
        "chapter_one_only": "CHAPTER_ONE_ONLY",
        "future_only": "FUTURE_ONLY_PROGRESSION",
    }
    candidate_story["characters"] = [
        {"name": "FUTURE_ONLY_CHARACTER", "role": "npc"},
    ]
    replacement.submission_payload["updated_story"] = candidate_story
    replacement.submission_payload["chapter_summary"] = {
        "chapter_number": 1,
        "chapter_title": "候选第一章",
        "summary": "CHAPTER_ONE_ONLY",
        "facts": ["CHAPTER_ONE_ONLY"],
        "next_focus": "继续推进",
    }
    store.candidate_store.save(replacement)

    result = store.confirm_candidate(replacement.candidate_id)

    assert result["candidate"]["status"] == "confirmed"
    snapshot = store.continuity_store.read_fresh_snapshot(1)
    assert snapshot is not None
    snapshot_text = json.dumps(snapshot.state_after, ensure_ascii=False)
    assert "CHAPTER_ONE_ONLY" in snapshot_text
    assert "FUTURE_ONLY_PROGRESSION" not in snapshot_text
    assert "FUTURE_ONLY_CHARACTER" not in snapshot_text


def test_historical_fact_resource_authority_is_reflected_in_end_n_snapshot(tmp_path):
    store = _make_project(tmp_path)
    initial_state = store.persisted_state()
    initial_state["progression_ledger"] = {
        "economy": {
            "game_currency": "10金币",
            "history": [{"chapter": 0, "current": {"currency": "10金币"}}],
        }
    }
    master = store.master_setting()
    master["state"] = deepcopy(initial_state)
    _write_json(tmp_path / ".webnovel" / "state.json", initial_state)
    _write_json(tmp_path / ".story-system" / "MASTER_SETTING.json", master)
    for chapter in (1, 2, 3):
        store.confirm_candidate(_candidate(store, chapter, tag=f"正文-{chapter}").candidate_id)

    replacement = _candidate(store, 1, operation="regenerate", tag="结构化货币替换")
    replacement.fact_resource_extraction = FactResourceExtraction(
        chapter_number=1,
        deltas=[
            FactResourceDelta(
                chapter=1,
                category="currency",
                resource_key="currency",
                operation="SET",
                before=10,
                change=25,
                after=25,
                evidence="结构化 authority 直接设置余额为25金币",
            )
        ],
    )
    replacement.continuity_delta = ContinuityDelta(chapter_number=1)
    store.candidate_store.save(replacement)

    result = store.confirm_candidate(replacement.candidate_id)

    assert result["candidate"]["status"] == "confirmed"
    snapshot = store.continuity_store.read_fresh_snapshot(1)
    assert snapshot is not None
    snapshot_text = json.dumps(snapshot.state_after, ensure_ascii=False)
    assert "25金币" in snapshot_text
    assert "FUTURE_ONLY" not in snapshot_text
    assert store.continuity_store.get_stale_chapters() == [2, 3]


def test_historical_canon_authority_without_as_of_projection_is_stale_only(tmp_path):
    store = _make_project(tmp_path)
    for chapter in (1, 2, 3):
        store.confirm_candidate(_candidate(store, chapter, tag=f"正文-{chapter}").candidate_id)

    replacement = _candidate(store, 1, operation="regenerate", tag="Canon替换")
    replacement.continuity_delta = ContinuityDelta(
        chapter_number=1,
        entity_additions=[
            EntityAddition(
                chapter_number=1,
                source_sentence="钱七出场",
                confidence=0.95,
                entity_id="char-qian",
                kind="character",
                canonical_name="钱七",
            )
        ],
    )
    store.candidate_store.save(replacement)

    result = store.confirm_candidate(replacement.candidate_id)

    assert result["candidate"]["status"] == "confirmed"
    assert store.continuity_store.read_fresh_snapshot(1) is None
    assert store.continuity_store.get_stale_chapters() == [1, 2, 3]
    canon = json.loads(
        (tmp_path / ".story-system" / "canon" / "registry.json").read_text(encoding="utf-8")
    )
    assert canon["by_id"]["char-qian"]["display_name"] == "钱七"


def test_canon_noop_retry_keeps_nonempty_historical_delta_stale_only(tmp_path, monkeypatch):
    store = _make_project(tmp_path)
    for chapter in (1, 2):
        store.confirm_candidate(_candidate(store, chapter, tag=f"旧正文-{chapter}").candidate_id)

    replacement = _candidate(store, 1, operation="regenerate", tag="Canon重试")
    replacement.continuity_delta = ContinuityDelta(
        chapter_number=1,
        entity_additions=[
            EntityAddition(
                chapter_number=1,
                source_sentence="钱七出场",
                confidence=0.95,
                entity_id="char-qian-retry",
                kind="character",
                canonical_name="钱七",
            )
        ],
    )
    store.candidate_store.save(replacement)

    original_save = store.candidate_store.save

    def fail_final_candidate_save(candidate):
        if candidate.candidate_id == replacement.candidate_id and candidate.status == "confirmed":
            raise OSError("candidate_final_save_failed")
        return original_save(candidate)

    monkeypatch.setattr(store.candidate_store, "save", fail_final_candidate_save)
    with pytest.raises(OSError, match="candidate_final_save_failed"):
        store.confirm_candidate(replacement.candidate_id)

    assert store.candidate_store.get(replacement.candidate_id).status == "pending"
    history_path = tmp_path / ".story-system" / "canon" / "history.json"
    registry_path = tmp_path / ".story-system" / "canon" / "registry.json"
    history_after_first_commit = history_path.read_bytes()
    registry_after_first_commit = registry_path.read_bytes()
    history_payload = json.loads(history_after_first_commit.decode("utf-8"))
    assert len(
        [
            event
            for event in history_payload["events"]
            if event.get("candidate_id") == replacement.candidate_id
        ]
    ) == 1

    monkeypatch.setattr(store.candidate_store, "save", original_save)
    retry = store.confirm_candidate(replacement.candidate_id)

    assert retry["continuity_snapshot"]["mode"] == "STALE_ONLY"
    assert store.continuity_store.read_fresh_snapshot(1) is None
    assert store.continuity_store.get_stale_chapters() == [1, 2]
    assert history_path.read_bytes() == history_after_first_commit
    assert registry_path.read_bytes() == registry_after_first_commit
    history_after_retry = json.loads(history_path.read_text(encoding="utf-8"))
    assert len(
        [
            event
            for event in history_after_retry["events"]
            if event.get("candidate_id") == replacement.candidate_id
        ]
    ) == 1


def test_reconstruction_ignores_legacy_updated_story_without_continuity_snapshots(tmp_path):
    store = _make_project(tmp_path)
    current_state = store.persisted_state()
    current_state["current_chapter"] = 2
    _write_json(tmp_path / ".webnovel" / "state.json", current_state)
    for chapter in (1, 2):
        state = deepcopy(store.persisted_state())
        state["current_chapter"] = chapter
        state["progression_ledger"] = {
            "replayed": f"chapter-{chapter}",
            "future_only": "FUTURE_ONLY_CHAPTER_8_STATE" if chapter == 2 else None,
        }
        state["characters"] = (
            [{"name": "FUTURE_ONLY_CHARACTER", "role": "npc"}]
            if chapter == 2
            else []
        )
        _write_json(
            tmp_path / ".story-system" / "chapters" / f"{chapter:04d}.json",
            {
                "chapter_number": chapter,
                "chapter_title": f"第{chapter}章",
                "body": _body(f"正文-{chapter}"),
                "chapter_summary": {
                    "chapter_number": chapter,
                    "chapter_title": f"第{chapter}章",
                    "summary": f"可重放章节-{chapter}",
                    "facts": [f"可重放事实-{chapter}"],
                    "next_focus": "继续",
                },
                "updated_story": state,
            },
        )

    rebuilt = store._reconstruct_state_at_end(2, store.state())

    assert rebuilt is not None
    state, source_chapter = rebuilt
    assert source_chapter == 0
    assert state["current_chapter"] == 2
    state_text = json.dumps(state, ensure_ascii=False)
    assert "FUTURE_ONLY_CHAPTER_8_STATE" not in state_text
    assert "FUTURE_ONLY_CHARACTER" not in state_text
    assert "可重放事实-2" in state_text


def test_legacy_updated_story_does_not_rescue_missing_trusted_baseline(tmp_path):
    store = _make_project(tmp_path, current_chapter=2)
    (tmp_path / ".story-system" / "MASTER_SETTING.json").unlink()
    legacy_state = deepcopy(store.persisted_state())
    legacy_state["current_chapter"] = 1
    legacy_state["progression_ledger"] = {"future_only": "FUTURE_ONLY_LEGACY_STATE"}
    _write_json(
        tmp_path / ".story-system" / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "旧第一章",
            "body": _body("旧第一章正文"),
            "updated_story": legacy_state,
        },
    )
    candidate = _candidate(store, 1, operation="regenerate")

    plan = store._plan_continuity_snapshot(candidate)

    assert plan.mode == "STALE_ONLY"
    assert "CONTINUITY_HISTORY_BASELINE_UNAVAILABLE" in plan.findings
    with pytest.raises(ValueError, match="^continuity_history_baseline_unavailable$"):
        store._regeneration_base_state(2, store.state())


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


def test_direct_historical_regenerate_cannot_mark_continuity_fresh_without_authority_plans(
    tmp_path,
    monkeypatch,
):
    store = _make_project(tmp_path)
    for chapter in (1, 2):
        store.confirm_candidate(_candidate(store, chapter, tag=f"旧正文-{chapter}").candidate_id)
    before_registry = (
        tmp_path / ".story-system" / "canon" / "registry.json"
    ).read_bytes()
    monkeypatch.setattr(store, "rolling_fill_status", lambda _target: {"status": "present"})
    monkeypatch.setattr(store, "require_volume_detail_for_prose", lambda _target: {})

    class Engine:
        def generate_next_chapter(self, story):
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="直接重生成第一章",
                body=_body("直接历史重生成"),
                quality_report={"ok": True},
                chapter_summary={
                    "summary": "新的第一章正文",
                    "facts": [],
                    "next_focus": "continue",
                },
                updated_story=story.model_copy(update={"current_chapter": 1}),
                continuity_delta=ContinuityDelta(
                    chapter_number=1,
                    entity_additions=[
                        EntityAddition(
                            chapter_number=1,
                            source_sentence="钱七出场",
                            confidence=0.95,
                            entity_id="char-qian-direct",
                            kind="character",
                            canonical_name="钱七",
                        )
                    ],
                ).model_dump(mode="json"),
            )

    result = store.regenerate_chapter(1, engine=Engine(), persist=True)

    assert result["continuity_snapshot"]["mode"] == "STALE_ONLY"
    assert store.continuity_store.read_fresh_snapshot(1) is None
    assert store.continuity_store.get_stale_chapters() == [1, 2]
    assert (
        tmp_path / ".story-system" / "canon" / "registry.json"
    ).read_bytes() == before_registry
