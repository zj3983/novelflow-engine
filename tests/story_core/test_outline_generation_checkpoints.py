from __future__ import annotations

import json

from packages.story_core.outline_generation_checkpoints import (
    OUTLINE_GENERATION_PHASES,
    OutlineCheckpointStore,
)


def test_checkpoint_store_saves_completed_payload_and_status_atomically(tmp_path) -> None:
    store = OutlineCheckpointStore(tmp_path / "outline-generation")
    store.prepare("fingerprint-a")
    store.mark_running("outline_foundation")
    store.complete("outline_foundation", {"outline": {"overall": {"story": "旧案"}}})

    status = store.status()
    phase = status["phases"][0]
    assert status["fingerprint"] == "fingerprint-a"
    assert phase["id"] == "outline_foundation"
    assert phase["status"] == "completed"
    assert phase["started_at"]
    assert phase["completed_at"]
    assert store.completed_payloads()["outline_foundation"]["outline"]["overall"]["story"] == "旧案"
    assert json.loads((store.root / "manifest.json").read_text(encoding="utf-8"))["phases"][0]["status"] == "completed"


def test_checkpoint_store_invalidates_requested_phase_and_every_later_phase(tmp_path) -> None:
    store = OutlineCheckpointStore(tmp_path / "outline-generation")
    store.prepare("fingerprint-a")
    for phase in OUTLINE_GENERATION_PHASES:
        store.complete(phase, {phase: True})

    store.invalidate_from("character_roster")

    assert set(store.completed_payloads()) == {"outline_foundation"}
    statuses = {item["id"]: item["status"] for item in store.status()["phases"]}
    assert statuses == {
        "outline_foundation": "completed",
        "character_roster": "waiting",
        "chapter_window": "waiting",
    }


def test_checkpoint_store_records_failure_without_dropping_earlier_payloads(tmp_path) -> None:
    store = OutlineCheckpointStore(tmp_path / "outline-generation")
    store.prepare("fingerprint-a")
    store.complete("outline_foundation", {"outline": {}})
    store.mark_running("character_roster")
    store.fail("character_roster", "模型返回的角色卡不完整")

    status = store.status()
    failed = next(item for item in status["phases"] if item["id"] == "character_roster")
    assert failed["status"] == "failed"
    assert failed["error"] == "模型返回的角色卡不完整"
    assert failed["completed_at"]
    assert set(store.completed_payloads()) == {"outline_foundation"}


def test_checkpoint_store_resets_all_phases_when_fingerprint_changes(tmp_path) -> None:
    store = OutlineCheckpointStore(tmp_path / "outline-generation")
    store.prepare("fingerprint-a")
    store.complete("outline_foundation", {"outline": {}})

    store.prepare("fingerprint-b")

    assert store.status()["fingerprint"] == "fingerprint-b"
    assert store.completed_payloads() == {}
    assert all(item["status"] == "waiting" for item in store.status()["phases"])
