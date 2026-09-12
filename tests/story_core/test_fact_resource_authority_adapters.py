from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from packages.story_core.fact_resource_ledger import (
    FactResourceExtraction,
    FactResourceLedger,
    apply_fact_resource_authority_writes,
    get_fact_resource_snapshot,
    plan_fact_resource_authority_writes,
)
from packages.story_core.file_project_store import FileProjectStore


def _long_body(text: str) -> str:
    return text + ("他把现场痕迹逐一记下，确认每一个细节都没有被遗漏。" * 180)


def _authority_state() -> dict:
    return {
        "story_id": "authority-test",
        "outline": "",
        "genre": "网游",
        "style": "白描",
        "current_chapter": 10,
        "characters": [
            {
                "name": "林照",
                "role": "protagonist",
                "game_state": {},
            }
        ],
        "progression_ledger": {
            "protagonist": {
                "level": "Lv.12",
                "history": [
                    {
                        "chapter": 10,
                        "current": {
                            "level": "Lv.12",
                            "experience": 100,
                            "inventory": {"记录水晶": 20},
                            "currency": "20金币",
                            "quests": {"采集": "3/10"},
                        },
                    }
                ],
            },
            "economy": {
                "inventory": {"记录水晶": 20},
                "game_currency": "20金币",
            },
            "quests": {"采集": "3/10"},
        },
        "equipment_cards": [
            {
                "id": "frost-sword",
                "name": "寒霜剑",
                "equipment_type": "weapon",
                "first_appearance_chapter": 10,
                "last_update_chapter": 10,
                "current_owner": "林渊",
                "history": [
                    {"chapter": 10, "current_owner": "林渊", "status": "未装备"}
                ],
            }
        ],
    }


def _authority_project() -> dict:
    return {
        "project_id": "authority-test",
        "title": "权威源测试",
        "relationship_graph": [
            {
                "id": "rel-lin-wang",
                "source": "林照",
                "target": "王铁匠",
                "first_chapter": 10,
                "changes": [
                    {"chapter_number": 10, "trust": 42, "tension": 50}
                ],
            }
        ],
    }


def _write_authority_project(tmp_path):
    store = FileProjectStore(tmp_path)
    store.webnovel_dir.mkdir(parents=True, exist_ok=True)
    store._write_json(store.webnovel_dir / "project.json", _authority_project())
    store._write_json(store.webnovel_dir / "state.json", _authority_state())
    return store


def _candidate(store: FileProjectStore, body: str, *, chapter: int = 11, claims=None):
    payload = SimpleNamespace(
        chapter_number=chapter,
        chapter_title="权威写入",
        body=_long_body(body),
        quality_report={"ok": True},
    )
    if claims is not None:
        payload.fact_resource_claims = claims
    return store._save_candidate_from_bundle(payload, project_id="authority-test")


def test_level_authority_is_validated_and_committed_once(tmp_path):
    store = _write_authority_project(tmp_path)
    candidate = _candidate(store, "升到13级。")

    assert candidate.fact_resource_review["ok"] is True
    assert store.state()["progression_ledger"]["protagonist"]["level"] == "Lv.12"
    store.confirm_candidate(candidate.candidate_id)

    state = store.persisted_state()
    history = state["progression_ledger"]["protagonist"]["history"]
    assert len([item for item in history if item.get("chapter") == 11]) == 1
    assert state["progression_ledger"]["protagonist"]["level"] == "Lv.13"
    assert get_fact_resource_snapshot(tmp_path, as_of_chapter=11).value_for("level", "level") == 13
    ledger = FactResourceLedger.load(store.fact_resource_ledger_path)
    assert ledger is None or not any(item.category == "level" for item in ledger.history)

    store.confirm_candidate(candidate.candidate_id)
    retry_history = store.persisted_state()["progression_ledger"]["protagonist"]["history"]
    assert len([item for item in retry_history if item.get("chapter") == 11]) == 1


def test_experience_authority_is_written_without_generic_history(tmp_path):
    store = _write_authority_project(tmp_path)
    candidate = _candidate(store, "经验增加10点。")
    store.confirm_candidate(candidate.candidate_id)

    state = store.persisted_state()
    progression = state["progression_ledger"]["protagonist"]
    assert progression["experience"] == 110
    assert next(
        item for item in progression["history"] if item.get("chapter") == 11
    )["current"]["experience"] == 110
    assert get_fact_resource_snapshot(tmp_path, as_of_chapter=11).value_for(
        "experience", "experience"
    ) == 110
    ledger = FactResourceLedger.load(store.fact_resource_ledger_path)
    assert ledger is None or not any(item.category == "experience" for item in ledger.history)


def test_inventory_currency_and_quest_use_progression_authority_only(tmp_path):
    store = _write_authority_project(tmp_path)
    inventory = _candidate(store, "消耗5枚记录水晶，还剩15枚记录水晶。")
    store.confirm_candidate(inventory.candidate_id)
    state = store.persisted_state()
    assert state["progression_ledger"]["economy"]["inventory"]["记录水晶"] == 15
    assert get_fact_resource_snapshot(tmp_path, as_of_chapter=11).value_for("inventory", "记录水晶") == 15

    currency = _candidate(store, "花费5金币，余额为15金币。", chapter=12)
    store.confirm_candidate(currency.candidate_id)
    state = store.persisted_state()
    assert state["progression_ledger"]["economy"]["game_currency"] == "15金币"

    quest = _candidate(
        store,
        "任务记录更新。",
        chapter=13,
        claims=[
            {
                "explicit": True,
                "category": "quest",
                "resource_key": "采集",
                "operation": "PROGRESS_ADD",
                "before": 3,
                "change": 2,
                "after": 5,
                "confidence": 0.96,
                "metadata": {"target": 10},
                "evidence": "采集任务进度+2",
            }
        ],
    )
    store.confirm_candidate(quest.candidate_id)
    state = store.persisted_state()
    assert state["progression_ledger"]["quests"]["采集"] == "5/10"
    assert get_fact_resource_snapshot(tmp_path, as_of_chapter=13).value_for("quest", "采集") == 5

    ledger = FactResourceLedger.load(store.fact_resource_ledger_path)
    assert ledger is None or not any(
        item.category in {"inventory", "currency", "quest"} for item in ledger.history
    )


def test_equipment_owner_and_state_are_written_to_one_card_history(tmp_path):
    store = _write_authority_project(tmp_path)
    transfer = _candidate(store, "将寒霜剑交给顾闻舟。")
    store.confirm_candidate(transfer.candidate_id)
    card = store.persisted_state()["equipment_cards"][0]
    transfer_events = [item for item in card["history"] if item.get("chapter") == 11]
    assert len(transfer_events) == 1
    assert transfer_events[0]["current_owner"] == "顾闻舟"
    assert card["current_owner"] == "顾闻舟"

    equip = _candidate(store, "装备上寒霜剑。", chapter=12)
    store.confirm_candidate(equip.candidate_id)
    card = store.persisted_state()["equipment_cards"][0]
    state_events = [item for item in card["history"] if item.get("chapter") == 12]
    assert len(state_events) == 1
    assert card["status"] == "已装备"
    assert card["equipped"] is True
    assert get_fact_resource_snapshot(tmp_path, as_of_chapter=12).find("equipment_state", "寒霜剑").value is True


def test_relationship_numeric_delta_is_appended_once(tmp_path):
    store = _write_authority_project(tmp_path)
    candidate = _candidate(store, "王铁匠信任值+5。")
    store.confirm_candidate(candidate.candidate_id)

    graph = store._read_json(store.webnovel_dir / "project.json", {})["relationship_graph"]
    changes = graph[0]["changes"]
    assert len(changes) == 2
    assert changes[-1]["trust"] == 47
    assert graph[0]["trust"] == 47
    assert get_fact_resource_snapshot(tmp_path, as_of_chapter=11).value_for(
        "relationship_numeric", "trust", subject="王铁匠"
    ) == 47
    store.confirm_candidate(candidate.candidate_id)
    graph_retry = store._read_json(store.webnovel_dir / "project.json", {})["relationship_graph"]
    assert len(graph_retry[0]["changes"]) == 2


def test_discard_does_not_mutate_any_authoritative_source(tmp_path):
    store = _write_authority_project(tmp_path)
    before_state = json.dumps(store.persisted_state(), ensure_ascii=False, sort_keys=True)
    before_project = json.dumps(store._read_json(store.webnovel_dir / "project.json", {}), ensure_ascii=False, sort_keys=True)
    for body in (
        "升到13级。",
        "消耗5枚记录水晶，还剩15枚记录水晶。",
        "将寒霜剑交给顾闻舟。",
        "王铁匠信任值+5。",
    ):
        candidate = _candidate(store, body)
        store.discard_candidate(candidate.candidate_id)
    assert json.dumps(store.persisted_state(), ensure_ascii=False, sort_keys=True) == before_state
    assert json.dumps(store._read_json(store.webnovel_dir / "project.json", {}), ensure_ascii=False, sort_keys=True) == before_project


def test_authority_adapter_plan_reports_unsupported_shape_without_mutation():
    state = _authority_state()
    state["progression_ledger"]["protagonist"]["history"] = "legacy-unstructured-history"
    extraction = FactResourceExtraction(
        chapter_number=11,
        deltas=[
            {
                "category": "level",
                "resource_key": "level",
                "operation": "SET",
                "before": 12,
                "after": 13,
                "change": 13,
                "evidence": "升到13级",
            }
        ],
    )
    plan = plan_fact_resource_authority_writes(
        state,
        _authority_project(),
        extraction,
    )
    assert any(item.code == "EXISTING_AUTHORITY_CONFIRMATION_REQUIRED" for item in plan.findings)
    original = json.dumps(state, ensure_ascii=False, sort_keys=True)
    with pytest.raises(ValueError, match="existing_authority_confirmation_required"):
        apply_fact_resource_authority_writes(state, _authority_project(), plan)
    assert json.dumps(state, ensure_ascii=False, sort_keys=True) == original


def test_transaction_failure_rolls_back_authority_and_chapter(tmp_path, monkeypatch):
    store = _write_authority_project(tmp_path)
    candidate = _candidate(store, "升到13级。")
    before_state = json.dumps(store.persisted_state(), ensure_ascii=False, sort_keys=True)

    original_apply = store._apply_candidate_fact_resource_writes

    def fail_after_apply(plan):
        original_apply(plan)
        raise RuntimeError("authority_write_injected_failure")

    monkeypatch.setattr(store, "_apply_candidate_fact_resource_writes", fail_after_apply)
    with pytest.raises(RuntimeError, match="authority_write_injected_failure"):
        store.confirm_candidate(candidate.candidate_id)
    assert store.candidate_store.get(candidate.candidate_id).status == "pending"
    assert json.dumps(store.persisted_state(), ensure_ascii=False, sort_keys=True) == before_state
    assert not (store.story_system_dir / "chapters" / "0011.json").exists()
    monkeypatch.undo()
    store.confirm_candidate(candidate.candidate_id)
    history = store.persisted_state()["progression_ledger"]["protagonist"]["history"]
    assert len([item for item in history if item.get("chapter") == 11]) == 1
