"""Project-store integration tests for Phase 3D Canon reconciliation."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.story_core.candidate_draft import CandidateDraft
from packages.story_core.continuity.delta import (
    ContinuityDelta,
    EntityAddition,
    EntityUpdate,
)
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.generation_progress import generation_progress


def _long_body(tag: str) -> str:
    return (f"{tag}章节。" * 800)[:5200]


def _seed_candidate(
    store: FileProjectStore,
    *,
    chapter_number: int,
    tag: str,
    delta: ContinuityDelta | None = None,
    operation: str = "generate",
) -> CandidateDraft:
    bundle = SimpleNamespace(
        chapter_number=chapter_number,
        chapter_title=f"第{chapter_number}章",
        title=f"第{chapter_number}章",
        body=_long_body(tag),
        quality_report={"ok": True},
        context_snapshot_id="ctx-phase3d",
    )
    with generation_progress(lambda *_: None):
        candidate = store._save_candidate_from_bundle(bundle, project_id=store.root.name)
    if delta is not None:
        candidate.continuity_delta = delta
    if operation != candidate.operation:
        candidate.operation = operation
    store.candidate_store.save(candidate)
    return candidate


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _addition(chapter: int, entity_id: str, name: str, *, title: str = "") -> EntityAddition:
    return EntityAddition(
        chapter_number=chapter,
        source_sentence=f"{name}登场",
        entity_id=entity_id,
        kind="character",
        canonical_name=name,
        attributes={"title": title} if title else {},
    )


def test_normal_confirmation_bootstraps_and_appends_canon_journal_atomically(tmp_path) -> None:
    store = FileProjectStore(tmp_path)
    delta = ContinuityDelta(
        chapter_number=1,
        entity_additions=[_addition(1, "char-zhao", "赵六")],
    )
    candidate = _seed_candidate(store, chapter_number=1, tag="第一章", delta=delta)

    result = store.confirm_candidate(candidate.candidate_id)

    baseline_path = store.story_system_dir / "canon" / "baseline.json"
    history_path = store.story_system_dir / "canon" / "history.json"
    registry_path = store.story_system_dir / "canon" / "registry.json"
    assert baseline_path.is_file() and history_path.is_file() and registry_path.is_file()
    history = _read_json(history_path)
    assert history["latest_confirmed_chapter"] == 1
    assert len(history["events"]) == 1
    assert history["events"][0]["candidate_id"] == candidate.candidate_id
    assert _read_json(registry_path)["by_id"]["char-zhao"]["display_name"] == "赵六"
    assert _read_json(store.webnovel_dir / "state.json")["characters"][0]["canon_entity_id"] == "char-zhao"
    assert result["candidate"]["status"] == "confirmed"


def test_duplicate_confirmation_does_not_append_history_or_projection_again(tmp_path) -> None:
    store = FileProjectStore(tmp_path)
    candidate = _seed_candidate(
        store,
        chapter_number=1,
        tag="第一章",
        delta=ContinuityDelta(
            chapter_number=1,
            entity_additions=[_addition(1, "char-zhao", "赵六")],
        ),
    )
    store.confirm_candidate(candidate.candidate_id)
    history_path = store.story_system_dir / "canon" / "history.json"
    registry_path = store.story_system_dir / "canon" / "registry.json"
    before_history = history_path.read_bytes()
    before_registry = registry_path.read_bytes()

    result = store.confirm_candidate(candidate.candidate_id)

    assert result["candidate"]["status"] == "confirmed"
    assert history_path.read_bytes() == before_history
    assert registry_path.read_bytes() == before_registry
    assert len(_read_json(history_path)["audit"]) == 0


def test_historical_rewrite_replaces_event_and_replays_downstream_delta(tmp_path) -> None:
    store = FileProjectStore(tmp_path)
    first = _seed_candidate(
        store,
        chapter_number=1,
        tag="第一章",
        delta=ContinuityDelta(
            chapter_number=1,
            entity_additions=[
                _addition(1, "char-zhao", "赵六", title="掌柜"),
                _addition(1, "char-main", "林昭"),
            ],
        ),
    )
    store.confirm_candidate(first.candidate_id)
    second = _seed_candidate(
        store,
        chapter_number=2,
        tag="第二章",
        delta=ContinuityDelta(
            chapter_number=2,
            entity_updates=[
                EntityUpdate(
                    chapter_number=2,
                    source_sentence="林昭获得新称号",
                    entity_id="char-main",
                    changes={"rank": 3},
                )
            ],
        ),
    )
    store.confirm_candidate(second.candidate_id)

    rewrite = _seed_candidate(
        store,
        chapter_number=1,
        tag="重写第一章",
        operation="regenerate",
        delta=ContinuityDelta(
            chapter_number=1,
            entity_additions=[
                _addition(1, "char-qian", "钱七", title="执事"),
                _addition(1, "char-main", "林昭"),
            ],
        ),
    )
    result = store.confirm_candidate(rewrite.candidate_id)

    assert result["candidate"]["status"] == "confirmed"
    registry = _read_json(store.story_system_dir / "canon" / "registry.json")
    assert "char-zhao" not in registry["by_id"]
    assert registry["by_id"]["char-qian"]["display_name"] == "钱七"
    history = _read_json(store.story_system_dir / "canon" / "history.json")
    assert [event["candidate_id"] for event in history["events"]] == [
        rewrite.candidate_id,
        second.candidate_id,
    ]
    assert registry["by_id"]["char-main"]["extensions"]["rank"] == 3
    projected_names = {
        card["name"]
        for card in _read_json(store.webnovel_dir / "state.json").get("characters", [])
    }
    assert "赵六" not in projected_names
    assert "钱七" in projected_names


def test_historical_rewrite_dependency_conflict_has_zero_mutation(tmp_path) -> None:
    store = FileProjectStore(tmp_path)
    first = _seed_candidate(
        store,
        chapter_number=1,
        tag="第一章",
        delta=ContinuityDelta(
            chapter_number=1,
            entity_additions=[_addition(1, "char-zhao", "赵六")],
        ),
    )
    store.confirm_candidate(first.candidate_id)
    second = _seed_candidate(
        store,
        chapter_number=2,
        tag="第二章",
        delta=ContinuityDelta(
            chapter_number=2,
            entity_updates=[
                EntityUpdate(
                    chapter_number=2,
                    source_sentence="赵六改名",
                    entity_id="char-zhao",
                    changes={"title": "掌柜"},
                )
            ],
        ),
    )
    store.confirm_candidate(second.candidate_id)
    before = {
        path: path.read_bytes()
        for path in (
            store.story_system_dir / "canon" / "history.json",
            store.story_system_dir / "canon" / "registry.json",
            store.story_system_dir / "chapters" / "0001.json",
        )
    }
    rewrite = _seed_candidate(
        store,
        chapter_number=1,
        tag="冲突重写",
        operation="regenerate",
        delta=ContinuityDelta(
            chapter_number=1,
            entity_additions=[_addition(1, "char-qian", "钱七")],
        ),
    )

    result = store.confirm_candidate(rewrite.candidate_id)

    assert result["canon_reconciliation"]["status"] == "CONFLICT"
    assert result["canon_reconciliation"]["first_conflict_chapter"] == 2
    assert result["candidate"]["status"] == "pending"
    assert all(path.read_bytes() == payload for path, payload in before.items())
    assert _read_json(store.story_system_dir / "canon" / "registry.json")["by_id"].get("char-zhao")


def test_history_write_failure_rolls_back_registry_history_and_chapter(tmp_path, monkeypatch) -> None:
    store = FileProjectStore(tmp_path)
    first = _seed_candidate(
        store,
        chapter_number=1,
        tag="第一章",
        delta=ContinuityDelta(
            chapter_number=1,
            entity_additions=[_addition(1, "char-zhao", "赵六")],
        ),
    )
    store.confirm_candidate(first.candidate_id)
    second = _seed_candidate(
        store,
        chapter_number=2,
        tag="第二章",
        delta=ContinuityDelta(chapter_number=2),
    )
    store.confirm_candidate(second.candidate_id)
    rewrite = _seed_candidate(
        store,
        chapter_number=1,
        tag="回滚重写",
        operation="regenerate",
        delta=ContinuityDelta(
            chapter_number=1,
            entity_additions=[_addition(1, "char-qian", "钱七")],
        ),
    )
    paths = [
        store.story_system_dir / "canon" / "history.json",
        store.story_system_dir / "canon" / "registry.json",
        store.story_system_dir / "chapters" / "0001.json",
    ]
    before = {path: path.read_bytes() for path in paths}
    original_write = store._write_json_atomic

    def fail_registry(path, payload):  # noqa: ANN001
        if Path(path).name == "registry.json":
            raise RuntimeError("canon_projection_write_failed")
        return original_write(path, payload)

    monkeypatch.setattr(store, "_write_json_atomic", fail_registry)
    with pytest.raises(RuntimeError, match="canon_projection_write_failed"):
        store.confirm_candidate(rewrite.candidate_id)

    assert all(path.read_bytes() == payload for path, payload in before.items())
    assert store.candidate_store.get(rewrite.candidate_id).status == "pending"


def test_ambiguous_legacy_canon_does_not_bootstrap_from_current_projection(tmp_path) -> None:
    store = FileProjectStore(tmp_path)
    registry = store._load_canon_registry()
    registry.add_character(name="未来角色", entity_id="char-future", lifecycle="active")
    store._save_canon_registry(registry)
    # A chapter already exists, but the project has no Phase 3D history.  The
    # current registry therefore cannot be proven to be a Chapter 0 baseline.
    chapter_path = store.story_system_dir / "chapters" / "0001.json"
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    chapter_path.write_text(json.dumps({"chapter_number": 1}), encoding="utf-8")

    assert store._build_bootstrap_canon_bundle() is None
    assert not (store.story_system_dir / "canon" / "baseline.json").exists()
    assert not (store.story_system_dir / "canon" / "history.json").exists()


def test_controlled_bootstrap_requires_replay_equality(tmp_path) -> None:
    store = FileProjectStore(tmp_path)
    store._write_json(
        store.story_system_dir / "MASTER_SETTING.json",
        {
            "canon_baseline": {
                "schema_version": "canon-registry/v1",
                "by_id": {},
                "relationships": [],
                "timeline": [],
                "foreshadowing": [],
            }
        },
    )
    candidate = _seed_candidate(
        store,
        chapter_number=1,
        tag="受控迁移",
        delta=ContinuityDelta(
            chapter_number=1,
            entity_additions=[_addition(1, "char-zhao", "赵六")],
        ),
    )
    candidate.confirm()
    store.candidate_store.save(candidate)
    store._apply_candidate_canon_delta(candidate)

    bundle = store._build_bootstrap_canon_bundle()

    assert bundle is not None
    baseline, history = bundle
    assert baseline.registry["by_id"] == {}
    assert history.events[0].candidate_id == candidate.candidate_id
    assert history.latest_confirmed_chapter == 1

    # A projection with an unexplained extra entity is not accepted as a
    # complete replay of the confirmed candidate history.
    registry = store._load_canon_registry()
    registry.add_character(name="未解释角色", entity_id="char-extra", lifecycle="active")
    store._save_canon_registry(registry)
    assert store._build_bootstrap_canon_bundle() is None


def test_manual_character_projection_is_never_removed_by_canon_replay(tmp_path) -> None:
    store = FileProjectStore(tmp_path)
    manual = {"name": "手工角色", "role": "protagonist"}
    store._write_json(store.webnovel_dir / "project.json", {"project_id": tmp_path.name, "character_profiles": [manual]})
    store._write_json(store.webnovel_dir / "state.json", {"story_id": tmp_path.name, "current_chapter": 0, "characters": [manual]})
    first = _seed_candidate(
        store,
        chapter_number=1,
        tag="第一章",
        delta=ContinuityDelta(
            chapter_number=1,
            entity_additions=[_addition(1, "char-zhao", "赵六")],
        ),
    )
    store.confirm_candidate(first.candidate_id)
    second = _seed_candidate(store, chapter_number=2, tag="第二章", delta=ContinuityDelta(chapter_number=2))
    store.confirm_candidate(second.candidate_id)
    rewrite = _seed_candidate(
        store,
        chapter_number=1,
        tag="重写第一章",
        operation="regenerate",
        delta=ContinuityDelta(
            chapter_number=1,
            entity_additions=[_addition(1, "char-qian", "钱七")],
        ),
    )

    store.confirm_candidate(rewrite.candidate_id)

    names = {
        item["name"]
        for item in _read_json(store.webnovel_dir / "state.json").get("characters", [])
    }
    assert "手工角色" in names
    assert "赵六" not in names
    assert "钱七" in names
