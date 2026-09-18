"""Phase 3E regressions for trusted continuity snapshot boundaries."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.story_core.continuity.snapshot import ChapterSnapshot
from packages.story_core.continuity.store import ContinuityStore
from packages.story_core.continuity.delta import ContinuityDelta, EntityAddition
from packages.story_core.fact_resource_ledger import FactResourceDelta, FactResourceExtraction
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.persistence.project_transaction import slice_state_for_snapshot


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


def _snapshot(
    store: ContinuityStore,
    chapter: int,
    marker: str,
    *,
    body: str | None = None,
) -> ChapterSnapshot:
    snapshot_body = body or "body"
    snapshot = ChapterSnapshot(
        chapter_number=chapter,
        candidate_id=f"candidate-{chapter}",
        operation="generate",
        confirmed_at="2026-01-01T00:00:00+00:00",
        body_sha256=sha256(snapshot_body.encode("utf-8")).hexdigest(),
        body_chars=len(snapshot_body),
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


def test_continuity_store_distinguishes_missing_and_valid_stale_metadata(tmp_path):
    store = ContinuityStore(tmp_path)
    _snapshot(store, 1, "one")

    missing = store.read_stale_metadata()
    assert missing.status == "MISSING"
    assert store.read_fresh_snapshot(1) is not None

    _write_json(
        store.stale_path,
        {"schema_version": "continuity-stale/v1", "chapters": [1]},
    )
    valid = store.read_stale_metadata()
    assert valid.status == "VALID"
    assert list(valid.chapters) == [1]
    assert store.read_fresh_snapshot(1) is None


def test_snapshot_integrity_validates_body_and_identity(tmp_path):
    store = ContinuityStore(tmp_path)
    body = "已确认的第一章正文"
    snapshot = _snapshot(store, 1, "one", body=body)

    result = store.read_snapshot_integrity(
        1,
        expected_body_sha256=sha256(body.encode("utf-8")).hexdigest(),
        expected_body_chars=len(body),
        expected_candidate_id=snapshot.candidate_id,
    )

    assert result.status == "VALID"
    assert result.snapshot is not None
    assert result.snapshot.chapter_number == 1


def test_snapshot_integrity_rejects_body_hash_and_length_mismatch(tmp_path):
    store = ContinuityStore(tmp_path)
    _snapshot(store, 1, "one", body="已确认正文")

    hash_result = store.read_snapshot_integrity(
        1,
        expected_body_sha256=sha256("外部修改正文".encode("utf-8")).hexdigest(),
        expected_body_chars=5,
    )
    assert hash_result.status == "BODY_MISMATCH"

    length_result = store.read_snapshot_integrity(
        1,
        expected_body_sha256=sha256("已确认正文".encode("utf-8")).hexdigest(),
        expected_body_chars=999,
    )
    assert length_result.status == "BODY_MISMATCH"


def test_snapshot_integrity_rejects_malformed_and_wrong_path_identity(tmp_path):
    store = ContinuityStore(tmp_path)
    store.snapshot_path(1).parent.mkdir(parents=True, exist_ok=True)
    store.snapshot_path(1).write_text("{not-json", encoding="utf-8")
    assert store.read_snapshot_integrity(1).status == "CORRUPT"

    _snapshot(store, 1, "one", body="正文")
    payload = json.loads(store.snapshot_path(1).read_text(encoding="utf-8"))
    payload["chapter_number"] = 2
    store.snapshot_path(1).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    assert store.read_snapshot_integrity(1).status == "IDENTITY_MISMATCH"


def test_snapshot_integrity_rejects_candidate_identity_when_proven(tmp_path):
    store = ContinuityStore(tmp_path)
    _snapshot(store, 1, "one", body="正文")

    result = store.read_snapshot_integrity(1, expected_candidate_id="confirmed-other")

    assert result.status == "IDENTITY_MISMATCH"


def test_corrupt_stale_metadata_blocks_fresh_reads_and_reconstruction(tmp_path):
    store = _make_project(tmp_path, current_chapter=2)
    for chapter in (1, 2):
        store.confirm_candidate(_candidate(store, chapter).candidate_id)
    store.continuity_store.stale_path.write_text("{not-json", encoding="utf-8")

    metadata = store.continuity_store.read_stale_metadata()
    assert metadata.status == "CORRUPT"
    assert store.continuity_store.read_fresh_snapshot(1) is None
    assert store.continuity_store.latest_fresh_snapshot_before(3) is None
    assert store.continuity_store.is_stale(1) is True
    with pytest.raises(ValueError, match="^continuity_freshness_metadata_unavailable$"):
        store._regeneration_base_state(2, store.state())


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"schema_version": "wrong", "chapters": []},
        {"schema_version": "continuity-stale/v1"},
        {"schema_version": "continuity-stale/v1", "chapters": "1"},
        {"schema_version": "continuity-stale/v1", "chapters": [True]},
        {"schema_version": "continuity-stale/v1", "chapters": [0]},
    ],
)
def test_invalid_stale_metadata_shape_is_not_fresh(tmp_path, payload):
    store = ContinuityStore(tmp_path)
    _snapshot(store, 1, "one")
    _write_json(store.stale_path, payload)

    assert store.read_stale_metadata().status == "CORRUPT"
    assert store.read_fresh_snapshot(1) is None
    assert store.latest_fresh_snapshot_before(3) is None


def test_unreadable_stale_metadata_is_not_fresh(tmp_path, monkeypatch):
    store = ContinuityStore(tmp_path)
    _snapshot(store, 1, "one")
    store.stale_path.write_text(
        json.dumps({"schema_version": "continuity-stale/v1", "chapters": []}),
        encoding="utf-8",
    )
    original_read_text = Path.read_text

    def fail_stale_read(path, *args, **kwargs):
        if Path(path) == store.stale_path:
            raise OSError("stale_metadata_unreadable")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_stale_read)

    assert store.read_stale_metadata().status == "UNREADABLE"
    assert store.read_fresh_snapshot(1) is None
    assert store.latest_fresh_snapshot_before(3) is None


def test_corrupt_stale_metadata_is_not_overwritten_by_mark_or_clear(tmp_path):
    store = ContinuityStore(tmp_path)
    store.stale_path.parent.mkdir(parents=True, exist_ok=True)
    store.stale_path.write_text("partial-write", encoding="utf-8")
    before = store.stale_path.read_bytes()

    with pytest.raises(ValueError, match="^continuity_freshness_metadata_unavailable$"):
        store.mark_stale([1])
    assert store.stale_path.read_bytes() == before

    with pytest.raises(ValueError, match="^continuity_freshness_metadata_unavailable$"):
        store.clear_stale([1])
    assert store.stale_path.read_bytes() == before


def test_corrupt_stale_metadata_makes_historical_confirmation_stale_only(tmp_path):
    store = _make_project(tmp_path, current_chapter=2)
    for chapter in (1, 2):
        store.confirm_candidate(_candidate(store, chapter).candidate_id)
    store.continuity_store.stale_path.write_text("{not-json", encoding="utf-8")
    before = store.continuity_store.stale_path.read_bytes()
    candidate = _candidate(store, 1, operation="regenerate")

    result = store.confirm_candidate(candidate.candidate_id)

    assert result["candidate"]["status"] == "confirmed"
    assert result["continuity_snapshot"]["mode"] == "STALE_ONLY"
    assert "CONTINUITY_FRESHNESS_METADATA_UNAVAILABLE" in result["continuity_snapshot"]["findings"]
    assert store.continuity_store.read_fresh_snapshot(1) is None
    assert store.continuity_store.stale_path.read_bytes() == before


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
            "body": f"body-{chapter}",
            "chapter_summary": {"summary": f"chapter {chapter}", "facts": [], "next_focus": "continue"},
        })
    for chapter, marker in ((1, "fresh-1"), (2, "fresh-2"), (3, "stale-3"), (4, "stale-4")):
        _snapshot(store.continuity_store, chapter, marker, body=f"body-{chapter}")
    store.continuity_store.mark_stale([3, 4])

    base = store._regeneration_base_state(5, store.state())

    assert base["current_chapter"] == 4
    assert base["progression_ledger"]["marker"] == "fresh-2"
    assert [item["chapter_number"] for item in base["chapter_summaries"]] == [3, 4]


def test_snapshot_body_mismatch_is_skipped_without_repairing_the_snapshot(tmp_path):
    store = _make_project(tmp_path, current_chapter=2)
    body = "原始正文"
    _write_json(
        tmp_path / ".story-system" / "chapters" / "0001.json",
        {"chapter_number": 1, "chapter_title": "第一章", "body": "外部修改正文"},
    )
    _snapshot(store.continuity_store, 1, "old", body=body)
    before = store.continuity_store.snapshot_path(1).read_bytes()

    assert store._latest_validated_fresh_snapshot_before(2) is None
    assert store.continuity_store.snapshot_path(1).read_bytes() == before


def test_corrupt_nearest_snapshot_uses_earlier_valid_boundary(tmp_path):
    store = _make_project(tmp_path, current_chapter=3)
    for chapter in (1, 2, 3):
        _write_json(
            tmp_path / ".story-system" / "chapters" / f"{chapter:04d}.json",
            {
                "chapter_number": chapter,
                "chapter_title": f"第{chapter}章",
                "body": f"正文-{chapter}",
                "chapter_summary": {
                    "summary": f"chapter {chapter}",
                    "facts": [],
                    "next_focus": "continue",
                },
            },
        )
    _snapshot(store.continuity_store, 1, "valid-1", body="正文-1")
    corrupt_path = store.continuity_store.snapshot_path(2)
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_text("{partial", encoding="utf-8")
    before = corrupt_path.read_bytes()

    rebuilt = store._reconstruct_state_at_end(2, store.state())

    assert rebuilt is not None
    _state, source_chapter = rebuilt
    assert source_chapter == 1
    assert corrupt_path.read_bytes() == before


def test_no_valid_snapshot_or_explicit_baseline_makes_regeneration_unavailable(tmp_path):
    store = _make_project(tmp_path, current_chapter=1)
    (tmp_path / ".story-system" / "MASTER_SETTING.json").unlink()
    corrupt_path = store.continuity_store.snapshot_path(1)
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_text("{partial", encoding="utf-8")

    with pytest.raises(ValueError, match="^continuity_history_baseline_unavailable$"):
        store._regeneration_base_state(2, store.state())


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


def _replace_chapter_body(store: FileProjectStore, chapter_number: int, body: str) -> None:
    path = store.story_system_dir / "chapters" / f"{chapter_number:04d}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    body_path = payload.get("body_path")
    if body_path:
        (store.root / str(body_path)).write_text(body, encoding="utf-8")
    else:
        payload["body"] = body
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_replay_rejects_middle_chapter_body_mismatch_even_with_healthy_downstream(tmp_path):
    store = _make_project(tmp_path)
    for chapter in (1, 2, 3):
        store.confirm_candidate(_candidate(store, chapter, tag=f"正文-{chapter}").candidate_id)
    _replace_chapter_body(store, 2, _body("外部修改第二章"))
    store.continuity_store.mark_stale([3])

    assert store._reconstruct_state_at_end(3, store.state()) is None


def test_replay_rejects_malformed_middle_chapter_json_without_skipping_it(tmp_path):
    store = _make_project(tmp_path)
    for chapter in (1, 2, 3):
        store.confirm_candidate(_candidate(store, chapter, tag=f"正文-{chapter}").candidate_id)
    chapter_path = tmp_path / ".story-system" / "chapters" / "0002.json"
    chapter_path.write_text("{malformed", encoding="utf-8")
    store.continuity_store.mark_stale([3])

    assert store._reconstruct_state_at_end(3, store.state()) is None


def test_replay_rejects_chapter_path_identity_mismatch(tmp_path):
    store = _make_project(tmp_path)
    for chapter in (1, 2, 3):
        store.confirm_candidate(_candidate(store, chapter, tag=f"正文-{chapter}").candidate_id)
    chapter_path = tmp_path / ".story-system" / "chapters" / "0002.json"
    payload = json.loads(chapter_path.read_text(encoding="utf-8"))
    payload["chapter_number"] = 99
    chapter_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    store.continuity_store.mark_stale([2, 3])

    assert store._reconstruct_state_at_end(3, store.state()) is None


def test_replay_rejects_unique_confirmed_candidate_body_mismatch(tmp_path):
    store = _make_project(tmp_path)
    for chapter in (1, 2, 3):
        store.confirm_candidate(_candidate(store, chapter, tag=f"正文-{chapter}").candidate_id)
    _replace_chapter_body(store, 2, _body("候选正文被替换"))
    store.continuity_store.mark_stale([3])

    assert store._reconstruct_state_at_end(3, store.state()) is None


def test_replay_rejects_fresh_snapshot_witness_mismatch(tmp_path):
    store = _make_project(tmp_path)
    for chapter in (1, 2, 3):
        store.confirm_candidate(_candidate(store, chapter, tag=f"正文-{chapter}").candidate_id)
    snapshot_path = store.continuity_store.snapshot_path(2)
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["body_chars"] += 1
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    store.continuity_store.mark_stale([3])

    assert store._reconstruct_state_at_end(3, store.state()) is None


def test_stale_snapshot_old_body_is_not_used_as_replay_witness(tmp_path):
    store = _make_project(tmp_path)
    for chapter in (1, 2):
        store.confirm_candidate(_candidate(store, chapter, tag=f"正文-{chapter}").candidate_id)
    snapshot_path = store.continuity_store.snapshot_path(1)
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["body_sha256"] = sha256("旧正文".encode("utf-8")).hexdigest()
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    store.continuity_store.mark_stale([1])

    rebuilt = store._reconstruct_state_at_end(1, store.state())

    assert rebuilt is not None
    assert rebuilt[1] == 0
    assert snapshot_path.read_bytes() != b""


def test_replay_accepts_direct_generated_or_legacy_chapter_without_candidate_draft(tmp_path):
    store = _make_project(tmp_path)
    body = _body("直写章节")
    _write_json(
        tmp_path / ".story-system" / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "第一章",
            "body": body,
        },
    )
    _snapshot(store.continuity_store, 1, "one", body=body)

    rebuilt = store._reconstruct_state_at_end(1, store.state())

    assert rebuilt is not None
    assert rebuilt[1] == 1


def test_historical_confirmation_degrades_to_stale_only_when_prior_replay_is_broken(tmp_path):
    store = _make_project(tmp_path)
    for chapter in (1, 2, 3):
        store.confirm_candidate(_candidate(store, chapter, tag=f"正文-{chapter}").candidate_id)
    _replace_chapter_body(store, 2, _body("确认前第二章被修改"))
    replacement = _candidate(store, 3, operation="regenerate", tag="重写第三章")

    result = store.confirm_candidate(replacement.candidate_id)

    assert result["candidate"]["status"] == "confirmed"
    assert result["continuity_snapshot"]["mode"] == "STALE_ONLY"


def test_historical_replay_matches_normal_confirmed_end_transition(tmp_path):
    store = _make_project(tmp_path)
    for chapter in (1, 2, 3):
        store.confirm_candidate(
            _candidate(store, chapter, tag=f"确定性章节-{chapter}").candidate_id
        )

    expected = store.continuity_store.read_snapshot(3).state_after
    store.continuity_store.mark_stale([2, 3])

    rebuilt = store._reconstruct_state_at_end(3, store.state())

    assert rebuilt is not None
    replayed, source_chapter = rebuilt
    assert source_chapter == 1
    assert slice_state_for_snapshot(replayed) == expected


def test_historical_replay_does_not_read_latest_project_context(tmp_path, monkeypatch):
    store = _make_project(tmp_path)
    for chapter in (1, 2):
        store.confirm_candidate(_candidate(store, chapter).candidate_id)
    store.continuity_store.mark_stale([2])
    trusted_input = store.state()

    def fail_latest_project():
        raise AssertionError("historical replay must not read latest project context")

    monkeypatch.setattr(store, "project", fail_latest_project)

    rebuilt = store._reconstruct_state_at_end(2, trusted_input)

    assert rebuilt is not None
    replayed, source_chapter = rebuilt
    assert source_chapter == 1
    assert replayed["current_chapter"] == 2


def test_historical_replay_does_not_import_future_latest_state_context(tmp_path):
    store = _make_project(tmp_path)
    for chapter in (1, 2):
        store.confirm_candidate(_candidate(store, chapter).candidate_id)

    expected = store.continuity_store.read_snapshot(2).state_after
    store.continuity_store.mark_stale([1, 2])

    latest_state = store.state()
    latest_state["characters"] = [
        *(latest_state.get("characters") or []),
        {
            "name": "未来污染角色",
            "role": "NPC",
            "character_type": "future-only",
        },
    ]
    _write_json(tmp_path / ".webnovel" / "state.json", latest_state)

    rebuilt = store._reconstruct_state_at_end(2, store.state())

    assert rebuilt is not None
    replayed, source_chapter = rebuilt
    assert source_chapter == 0
    assert slice_state_for_snapshot(replayed) == expected
    assert all(
        str(item.get("name") or "") != "未来污染角色"
        for item in replayed.get("characters", [])
        if isinstance(item, dict)
    )


def test_historical_replay_does_not_reapply_factresource_or_canon_hooks(
    tmp_path,
    monkeypatch,
):
    store = _make_project(tmp_path)
    for chapter in (1, 2):
        store.confirm_candidate(_candidate(store, chapter).candidate_id)
    store.continuity_store.mark_stale([2])

    def fail_fact_resource(*_args, **_kwargs):
        raise AssertionError("historical replay must not commit FactResource authority")

    def fail_canon(*_args, **_kwargs):
        raise AssertionError("historical replay must not commit Canon authority")

    monkeypatch.setattr(store, "_apply_candidate_fact_resource_writes", fail_fact_resource)
    monkeypatch.setattr(store, "_apply_candidate_canon_delta", fail_canon)

    rebuilt = store._reconstruct_state_at_end(2, store.state())

    assert rebuilt is not None


def test_persisted_progression_authority_is_replayed_once_without_reextraction(tmp_path):
    store = _make_project(tmp_path)
    state = store.persisted_state()
    state["progression_ledger"] = {
        "protagonist": {
            "level": "Lv.12",
            "history": [
                {
                    "chapter": 0,
                    "current": {"level": "Lv.12"},
                }
            ],
        }
    }
    _write_json(tmp_path / ".webnovel" / "state.json", state)

    chapter = {
        "chapter_number": 1,
        "chapter_title": "结构化等级推进",
        "body": "这一章没有可供重新抽取的等级文本。",
        "chapter_summary": {
            "chapter_number": 1,
            "chapter_title": "结构化等级推进",
            "summary": "结构化等级推进",
            "facts": [],
            "next_focus": "continue",
        },
        "fact_resource_extraction": FactResourceExtraction(
            chapter_number=1,
            deltas=[
                FactResourceDelta(
                    chapter=1,
                    category="level",
                    resource_key="level",
                    operation="SET",
                    before=12,
                    change=13,
                    after=13,
                    evidence="persisted structured authority",
                )
            ],
        ).model_dump(mode="json"),
    }

    replayed = store._apply_confirmed_chapter_transition(
        deepcopy(state),
        chapter,
        replay_persisted_authority=True,
        project_context={},
    )

    assert replayed is not None
    assert replayed["progression_ledger"]["protagonist"]["level"] == "Lv.13"
    history = replayed["progression_ledger"]["protagonist"]["history"]
    assert len([item for item in history if item.get("chapter") == 1]) == 1


def test_legacy_confirmed_candidate_extraction_is_replayed_in_memory_only(tmp_path):
    store = _make_project(tmp_path)
    initial_state = store.persisted_state()
    initial_state["progression_ledger"] = {
        "protagonist": {
            "level": "Lv.12",
            "history": [{"chapter": 0, "current": {"level": "Lv.12"}}],
        }
    }
    master = store.master_setting()
    master["state"] = deepcopy(initial_state)
    _write_json(tmp_path / ".webnovel" / "state.json", initial_state)
    _write_json(tmp_path / ".story-system" / "MASTER_SETTING.json", master)

    candidate = _candidate(store, 1, tag="旧候选结构化等级")
    candidate.fact_resource_extraction = FactResourceExtraction(
        chapter_number=1,
        deltas=[
            FactResourceDelta(
                chapter=1,
                category="level",
                resource_key="level",
                operation="SET",
                before=12,
                change=13,
                after=13,
                evidence="legacy persisted candidate extraction",
            )
        ],
    )
    store.candidate_store.save(candidate)
    store.confirm_candidate(candidate.candidate_id)

    chapter_path = tmp_path / ".story-system" / "chapters" / "0001.json"
    chapter_payload = json.loads(chapter_path.read_text(encoding="utf-8"))
    chapter_payload.pop("fact_resource_extraction", None)
    chapter_payload.pop("fact_resource_candidate_id", None)
    _write_json(chapter_path, chapter_payload)
    artifact_before_replay = chapter_path.read_bytes()
    store.continuity_store.mark_stale([1])

    rebuilt = store._reconstruct_state_at_end(1, store.state())

    assert rebuilt is not None
    replayed, source_chapter = rebuilt
    assert source_chapter == 0
    assert replayed["progression_ledger"]["protagonist"]["level"] == "Lv.13"
    assert chapter_path.read_bytes() == artifact_before_replay


def test_legacy_replay_rejects_malformed_artifact_extraction_instead_of_fallback(tmp_path):
    store = _make_project(tmp_path)
    candidate = _candidate(store, 1, tag="旧候选结构化等级")
    candidate.fact_resource_extraction = FactResourceExtraction(
        chapter_number=1,
        deltas=[
            FactResourceDelta(
                chapter=1,
                category="level",
                resource_key="level",
                operation="SET",
                before=1,
                change=2,
                after=2,
                evidence="persisted candidate extraction",
            )
        ],
    )
    store.candidate_store.save(candidate)
    store.confirm_candidate(candidate.candidate_id)

    chapter_path = tmp_path / ".story-system" / "chapters" / "0001.json"
    chapter_payload = json.loads(chapter_path.read_text(encoding="utf-8"))
    chapter_payload["fact_resource_extraction"] = "corrupt"
    _write_json(chapter_path, chapter_payload)
    store.continuity_store.mark_stale([1])

    assert store._reconstruct_state_at_end(1, store.state()) is None


def test_legacy_replay_fails_safe_when_confirmed_candidate_identity_is_ambiguous(tmp_path):
    store = _make_project(tmp_path)
    candidate = _candidate(store, 1, tag="首个确认候选")
    candidate.fact_resource_extraction = FactResourceExtraction(
        chapter_number=1,
        deltas=[
            FactResourceDelta(
                chapter=1,
                category="level",
                resource_key="level",
                operation="SET",
                before=1,
                change=2,
                after=2,
                evidence="ambiguous legacy extraction",
            )
        ],
    )
    store.candidate_store.save(candidate)
    store.confirm_candidate(candidate.candidate_id)

    duplicate = _candidate(store, 1, tag="第二个确认候选")
    duplicate.status = "confirmed"
    duplicate.fact_resource_extraction = candidate.fact_resource_extraction
    store.candidate_store.save(duplicate)

    chapter_path = tmp_path / ".story-system" / "chapters" / "0001.json"
    chapter_payload = json.loads(chapter_path.read_text(encoding="utf-8"))
    chapter_payload.pop("fact_resource_extraction", None)
    chapter_payload.pop("fact_resource_candidate_id", None)
    _write_json(chapter_path, chapter_payload)
    store.continuity_store.mark_stale([1])

    assert store._reconstruct_state_at_end(1, store.state()) is None


def test_historical_replay_matches_confirmed_progression_authority_snapshot(tmp_path):
    store = _make_project(tmp_path)
    state = store.persisted_state()
    state["progression_ledger"] = {
        "protagonist": {
            "level": "Lv.12",
            "history": [
                {"chapter": 0, "current": {"level": "Lv.12"}},
            ],
        }
    }
    master = store.master_setting()
    master["state"] = deepcopy(state)
    _write_json(tmp_path / ".webnovel" / "state.json", state)
    _write_json(tmp_path / ".story-system" / "MASTER_SETTING.json", master)

    store.confirm_candidate(_candidate(store, 1).candidate_id)
    replacement = _candidate(store, 2, tag="结构化等级变更")
    replacement.fact_resource_extraction = FactResourceExtraction(
        chapter_number=2,
        deltas=[
            FactResourceDelta(
                chapter=2,
                category="level",
                resource_key="level",
                operation="SET",
                before=12,
                change=13,
                after=13,
                evidence="persisted level authority",
            )
        ],
    )
    store.candidate_store.save(replacement)
    store.confirm_candidate(replacement.candidate_id)

    expected = store.continuity_store.read_snapshot(2).state_after
    store.continuity_store.mark_stale([2])
    rebuilt = store._reconstruct_state_at_end(2, store.state())

    assert rebuilt is not None
    replayed, source_chapter = rebuilt
    assert source_chapter == 1
    assert slice_state_for_snapshot(replayed) == expected
    history = replayed["progression_ledger"]["protagonist"]["history"]
    assert len([item for item in history if item.get("chapter") == 2]) == 1
