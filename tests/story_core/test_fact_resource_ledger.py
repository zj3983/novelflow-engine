from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from packages.story_core.fact_resource_ledger import (
    FactResourceEntry,
    FactResourceExtraction,
    FactResourceLedger,
    FactResourceSnapshot,
    extract_fact_resource_changes,
    render_fact_resource_context,
    stable_fact_id,
    validate_fact_resource_extraction,
)
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.generation_progress import generation_progress


def _snapshot(*, crystal: int = 20) -> FactResourceSnapshot:
    return FactResourceSnapshot(
        known=True,
        as_of_chapter=0,
        entries=[
            FactResourceEntry(
                category="inventory",
                resource_key="记录水晶",
                value=crystal,
                unit="枚",
            )
        ],
    )


def test_fact_ids_are_stable_but_exact_names_do_not_fuzzy_merge() -> None:
    assert stable_fact_id("inventory", "", "记录水晶") == stable_fact_id(
        "inventory", "", "记录水晶"
    )
    assert stable_fact_id("inventory", "", "记录水晶") != stable_fact_id(
        "inventory", "", "记录水晶碎片"
    )


def test_golden_record_remaining_assertion_replays_without_mismatch() -> None:
    extraction = extract_fact_resource_changes(
        "他消耗5枚记录水晶，还剩15枚记录水晶。",
        1,
        _snapshot(),
    )
    result = validate_fact_resource_extraction(_snapshot(), extraction)
    assert result.ok is True
    assert result.proposed_snapshot.value_for("inventory", "记录水晶") == 15
    assert any(item.expected_value == 15 for item in extraction.assertions)


def test_resource_mismatch_is_blocking_and_category_specific() -> None:
    extraction = extract_fact_resource_changes(
        "他消耗5枚记录水晶，还剩14枚记录水晶。",
        1,
        _snapshot(),
    )
    result = validate_fact_resource_extraction(_snapshot(), extraction)
    assert result.ok is False
    assert "INVENTORY_QUANTITY_MISMATCH" in {
        item.code for item in result.blocking_findings
    }


def test_unknown_arithmetic_stays_unknown_and_is_only_a_warning() -> None:
    extraction = extract_fact_resource_changes("获得5枚记录水晶。", 1)
    result = validate_fact_resource_extraction(
        FactResourceSnapshot(known=False),
        extraction,
    )
    assert result.ok is True
    assert result.proposed_snapshot.entries == []
    assert any(item.severity == "warning" for item in result.findings)


def test_unknown_explicit_set_can_initialize_a_value_without_backdating() -> None:
    extraction = extract_fact_resource_changes("现在有8个记录水晶。", 1)
    result = validate_fact_resource_extraction(
        FactResourceSnapshot(known=False),
        extraction,
    )
    assert result.ok is True
    assert result.proposed_snapshot.value_for("inventory", "记录水晶") == 8


def test_owner_assertion_and_level_assertion_use_required_codes() -> None:
    owner_entry = FactResourceEntry(
        category="equipment_owner", resource_key="寒霜剑", owner="林渊"
    )
    level_entry = FactResourceEntry(category="level", resource_key="level", value=27)
    start = FactResourceSnapshot(known=True, entries=[owner_entry, level_entry])
    extraction = extract_fact_resource_changes(
        "顾闻舟一直持有寒霜剑，当前等级30级。", 61, start
    )
    result = validate_fact_resource_extraction(start, extraction)
    assert "EQUIPMENT_OWNER_MISMATCH" in {item.code for item in result.findings}
    assert "LEVEL_MISMATCH" in {item.code for item in result.findings}


def test_explicit_relationship_delta_is_arithmetic_not_semantic_inference() -> None:
    start = FactResourceSnapshot(
        known=True,
        entries=[
            FactResourceEntry(
                category="relationship_numeric",
                subject="王铁匠",
                resource_key="好感度",
                value=42,
            )
        ],
    )
    extraction = extract_fact_resource_changes("王铁匠好感度+5。", 1, start)
    result = validate_fact_resource_extraction(start, extraction)
    assert result.ok is True
    assert result.proposed_snapshot.value_for(
        "relationship_numeric", "好感度", subject="王铁匠"
    ) == 47


def test_equipping_with_a_different_owner_is_blocked() -> None:
    start = FactResourceSnapshot(
        known=True,
        entries=[
            FactResourceEntry(
                category="equipment_state",
                resource_key="寒霜剑",
                owner="林渊",
            )
        ],
    )
    extraction = FactResourceExtraction(
        chapter_number=1,
        deltas=[
            {
                "category": "equipment_state",
                "resource_key": "寒霜剑",
                "operation": "EQUIP",
                "owner": "顾闻舟",
                "sequence": 0,
            }
        ],
    )
    result = validate_fact_resource_extraction(start, extraction)
    assert result.ok is False
    assert "EQUIPMENT_OWNER_MISMATCH" in {item.code for item in result.errors}


def test_ledger_replay_orders_history_and_refuses_negative_balance() -> None:
    ledger = FactResourceLedger(
        baseline={
            "chapter": 0,
            "entries": [_snapshot().entries[0].model_dump(mode="json")],
        }
    )
    first = extract_fact_resource_changes("消耗5枚记录水晶，还剩15枚记录水晶。", 1, _snapshot())
    ledger.append(first, candidate_id="cd-1")
    assert ledger.replay(as_of_chapter=0).value_for("inventory", "记录水晶") == 20
    assert ledger.replay(as_of_chapter=1).value_for("inventory", "记录水晶") == 15
    assert ledger.confirmed_candidates == ["cd-1"]


def test_fact_resource_context_is_compact_and_warns_against_inference() -> None:
    rendered = render_fact_resource_context(_snapshot())
    assert "记录水晶" in rendered
    assert "不从" in rendered


def _long_body_with_resource_event() -> str:
    return "消耗5枚记录水晶，还剩15枚记录水晶。" + ("他把现场痕迹逐一记下。" * 400)


def _seed_explicit_ledger(store: FileProjectStore) -> None:
    path = store.fact_resource_ledger_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            FactResourceLedger(
                baseline={
                    "chapter": 0,
                    "entries": [_snapshot().entries[0].model_dump(mode="json")],
                }
            ).to_dict(),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_candidate_resource_events_are_pending_until_confirmation(tmp_path) -> None:
    store = FileProjectStore(tmp_path)
    _seed_explicit_ledger(store)
    candidate = store._save_candidate_from_bundle(
        SimpleNamespace(
            chapter_number=1,
            chapter_title="资源核对",
            body=_long_body_with_resource_event(),
            quality_report={"ok": True},
        ),
        project_id=tmp_path.name,
    )
    before = FactResourceLedger.load(store.fact_resource_ledger_path)
    assert before is not None
    assert before.history == []
    assert candidate.fact_resource_extraction is not None
    assert candidate.fact_resource_review["ok"] is True

    store.confirm_candidate(candidate.candidate_id)
    after = FactResourceLedger.load(store.fact_resource_ledger_path)
    assert after is not None
    assert len(after.history) == 1
    assert after.replay(as_of_chapter=1).value_for("inventory", "记录水晶") == 15
    store.confirm_candidate(candidate.candidate_id)
    retried = FactResourceLedger.load(store.fact_resource_ledger_path)
    assert retried is not None
    assert len(retried.history) == 1
    assert retried.replay(as_of_chapter=1).value_for("inventory", "记录水晶") == 15


def test_fact_resource_historical_rewrite_is_rejected_before_chapter_mutation(tmp_path) -> None:
    store = FileProjectStore(tmp_path)
    _seed_explicit_ledger(store)
    first = store._save_candidate_from_bundle(
        SimpleNamespace(
            chapter_number=1,
            chapter_title="第一章",
            body=_long_body_with_resource_event(),
            quality_report={"ok": True},
        ),
        project_id=tmp_path.name,
    )
    store.confirm_candidate(first.candidate_id)
    rewrite = store._save_candidate_from_bundle(
        SimpleNamespace(
            chapter_number=1,
            chapter_title="第一章重写",
            body=_long_body_with_resource_event(),
            quality_report={"ok": True},
        ),
        project_id=tmp_path.name,
        operation="regenerate",
    )
    with pytest.raises(ValueError, match="historical_rewrite_requires_reconciliation"):
        store.confirm_candidate(rewrite.candidate_id)
    assert store.candidate_store.get(rewrite.candidate_id).status == "pending"
    ledger = FactResourceLedger.load(store.fact_resource_ledger_path)
    assert ledger is not None
    assert len(ledger.history) == 1
