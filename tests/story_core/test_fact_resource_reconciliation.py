from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import packages.story_core.file_project_store as file_project_store_module
from packages.story_core.fact_resource_ledger import (
    FactResourceLedger,
    get_fact_resource_snapshot,
)
from packages.story_core.file_project_store import FileProjectStore


def _body(sentence: str) -> str:
    return sentence + ("他把现场痕迹逐一记下，确认每一个细节都没有被遗漏。" * 180)


def _claims(
    *,
    evidence: str,
    before: int,
    change: int,
    after: int,
    operation: str,
) -> list[dict[str, object]]:
    return [
        {
            "explicit": True,
            "category": "resource",
            "resource_key": "记录水晶",
            "operation": operation,
            "before": before,
            "change": change,
            "after": after,
            "evidence": evidence,
            "confidence": 0.99,
        }
    ]


def _store(tmp_path: Path) -> FileProjectStore:
    store = FileProjectStore(tmp_path)
    store.webnovel_dir.mkdir(parents=True, exist_ok=True)
    store._write_json(
        store.webnovel_dir / "state.json",
        {
            "story_id": tmp_path.name,
            "current_chapter": 9,
            "characters": [],
        },
    )
    store._write_json(
        store.webnovel_dir / "project.json",
        {"project_id": tmp_path.name, "title": "历史资源重建测试"},
    )
    store._write_json(
        store.fact_resource_ledger_path,
        FactResourceLedger(
            baseline={
                "entries": [
                    {
                        "category": "resource",
                        "resource_key": "记录水晶",
                        "value": 0,
                    }
                ]
            }
        ).to_dict(),
    )
    return store


def _authority_store(tmp_path: Path) -> FileProjectStore:
    store = FileProjectStore(tmp_path)
    store.webnovel_dir.mkdir(parents=True, exist_ok=True)
    store._write_json(
        store.webnovel_dir / "state.json",
        {
            "story_id": tmp_path.name,
            "current_chapter": 9,
            "progression_ledger": {
                "protagonist": {
                    "inventory": {"记录水晶": 0},
                    "history": [
                        {"chapter": 9, "current": {"inventory": {"记录水晶": 0}}}
                    ],
                }
            },
            "characters": [],
        },
    )
    store._write_json(
        store.webnovel_dir / "project.json",
        {"project_id": tmp_path.name, "title": "authority reconciliation"},
    )
    return store


def _mixed_store(tmp_path: Path) -> FileProjectStore:
    store = _authority_store(tmp_path)
    store._write_json(
        store.fact_resource_ledger_path,
        FactResourceLedger(
            baseline={
                "entries": [
                    {
                        "category": "resource",
                        "resource_key": "灵草",
                        "value": 0,
                    }
                ]
            }
        ).to_dict(),
    )
    return store


def _equipment_store(tmp_path: Path) -> FileProjectStore:
    store = FileProjectStore(tmp_path)
    store.webnovel_dir.mkdir(parents=True, exist_ok=True)
    store._write_json(
        store.webnovel_dir / "state.json",
        {
            "story_id": tmp_path.name,
            "current_chapter": 9,
            "equipment_cards": [
                {
                    "id": "frost-sword",
                    "name": "寒霜剑",
                    "aliases": ["霜剑"],
                    "first_appearance_chapter": 9,
                    "current_owner": "林远",
                    "history": [
                        {"chapter": 9, "current_owner": "林远", "status": "未装备"}
                    ],
                }
            ],
            "characters": [],
        },
    )
    store._write_json(
        store.webnovel_dir / "project.json",
        {"project_id": tmp_path.name, "title": "equipment reconciliation"},
    )
    return store


def _relationship_store(tmp_path: Path) -> FileProjectStore:
    store = FileProjectStore(tmp_path)
    store.webnovel_dir.mkdir(parents=True, exist_ok=True)
    store._write_json(
        store.webnovel_dir / "state.json",
        {
            "story_id": tmp_path.name,
            "current_chapter": 9,
            "characters": [{"name": "林照", "role": "protagonist"}],
        },
    )
    store._write_json(
        store.webnovel_dir / "project.json",
        {
            "project_id": tmp_path.name,
            "title": "relationship reconciliation",
            "relationship_graph": [
                {
                    "id": "rel-lin-wang",
                    "source": "林照",
                    "target": "王铁匠",
                    "first_chapter": 9,
                    "changes": [{"chapter_number": 9, "trust": 42}],
                    "trust": 42,
                }
            ],
        },
    )
    return store


def _candidate(
    store: FileProjectStore,
    *,
    chapter: int,
    sentence: str,
    claims: list[dict[str, object]],
    operation: str = "generate",
):
    body = _body(sentence)
    return store._save_candidate_from_bundle(
        SimpleNamespace(
            chapter_number=chapter,
            chapter_title=f"第{chapter}章",
            body=body,
            quality_report={"ok": True},
            fact_resource_claims=claims,
        ),
        project_id=store.root.name,
        operation=operation,
    )


def test_rewrite_rebuilds_generic_history_from_n_minus_one(tmp_path: Path) -> None:
    store = _store(tmp_path)
    chapter10 = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动20。",
        claims=_claims(
            evidence="记录水晶数量变动20",
            before=0,
            change=20,
            after=20,
            operation="ADD",
        ),
    )
    store.confirm_candidate(chapter10.candidate_id)
    chapter11 = _candidate(
        store,
        chapter=11,
        sentence="记录水晶数量变动5。",
        claims=_claims(
            evidence="记录水晶数量变动5",
            before=20,
            change=5,
            after=15,
            operation="SUBTRACT",
        ),
    )
    store.confirm_candidate(chapter11.candidate_id)

    rewrite = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动10。",
        claims=_claims(
            evidence="记录水晶数量变动10",
            before=0,
            change=10,
            after=10,
            operation="ADD",
        ),
        operation="regenerate",
    )

    result = store.confirm_candidate(rewrite.candidate_id)
    assert result["candidate"]["status"] == "confirmed"
    ledger = FactResourceLedger.load(store.fact_resource_ledger_path)
    assert ledger is not None
    assert ledger.replay(as_of_chapter=10).value_for("resource", "记录水晶") == 10
    assert ledger.replay(as_of_chapter=11).value_for("resource", "记录水晶") == 5
    history_before_retry = [item.delta_id for item in ledger.history]
    audit_before_retry = list(ledger.audit)
    store.confirm_candidate(rewrite.candidate_id)
    retried = FactResourceLedger.load(store.fact_resource_ledger_path)
    assert retried is not None
    assert [item.delta_id for item in retried.history] == history_before_retry
    assert retried.audit == audit_before_retry


def test_latest_rewrite_replaces_history_without_downstream(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动20。",
        claims=_claims(
            evidence="记录水晶数量变动20",
            before=0,
            change=20,
            after=20,
            operation="ADD",
        ),
    )
    store.confirm_candidate(original.candidate_id)
    rewrite = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动7。",
        claims=_claims(
            evidence="记录水晶数量变动7",
            before=0,
            change=7,
            after=7,
            operation="ADD",
        ),
        operation="regenerate",
    )

    result = store.confirm_candidate(rewrite.candidate_id)
    assert result["candidate"]["status"] == "confirmed"
    reconciliation = result["candidate"]["fact_resource_review"]["reconciliation"]
    assert reconciliation["status"] == "CLEAR"
    assert reconciliation["replayed_through_chapter"] == 10
    ledger = FactResourceLedger.load(store.fact_resource_ledger_path)
    assert ledger is not None
    assert ledger.replay(as_of_chapter=10).value_for("resource", "记录水晶") == 7


def test_reconciliation_never_reextracts_confirmed_downstream_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    first = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动20。",
        claims=_claims(
            evidence="记录水晶数量变动20",
            before=0,
            change=20,
            after=20,
            operation="ADD",
        ),
    )
    store.confirm_candidate(first.candidate_id)
    downstream = _candidate(
        store,
        chapter=11,
        sentence="记录水晶数量变动5。",
        claims=_claims(
            evidence="记录水晶数量变动5",
            before=20,
            change=5,
            after=15,
            operation="SUBTRACT",
        ),
    )
    store.confirm_candidate(downstream.candidate_id)
    rewrite = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动10。",
        claims=_claims(
            evidence="记录水晶数量变动10",
            before=0,
            change=10,
            after=10,
            operation="ADD",
        ),
        operation="regenerate",
    )

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("downstream prose must not be re-extracted")

    monkeypatch.setattr(file_project_store_module, "extract_fact_resource_changes", fail_if_called)
    result = store.confirm_candidate(rewrite.candidate_id)

    assert result["candidate"]["status"] == "confirmed"
    ledger = FactResourceLedger.load(store.fact_resource_ledger_path)
    assert ledger is not None
    assert ledger.replay(as_of_chapter=11).value_for("resource", "记录水晶") == 5


def test_downstream_conflict_is_first_and_leaves_candidate_pending(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动20。",
        claims=_claims(
            evidence="记录水晶数量变动20",
            before=0,
            change=20,
            after=20,
            operation="ADD",
        ),
    )
    store.confirm_candidate(first.candidate_id)
    downstream = _candidate(
        store,
        chapter=11,
        sentence="记录水晶数量变动15。",
        claims=_claims(
            evidence="记录水晶数量变动15",
            before=20,
            change=15,
            after=5,
            operation="SUBTRACT",
        ),
    )
    store.confirm_candidate(downstream.candidate_id)
    rewrite = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动10。",
        claims=_claims(
            evidence="记录水晶数量变动10",
            before=0,
            change=10,
            after=10,
            operation="ADD",
        ),
        operation="regenerate",
    )

    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and ".pytest_cache" not in path.parts
    }
    result = store.confirm_candidate(rewrite.candidate_id)
    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and ".pytest_cache" not in path.parts
    }

    assert result["candidate"]["status"] == "pending"
    reconciliation = result["fact_resource_reconciliation"]
    assert reconciliation["status"] == "CONFLICT"
    assert reconciliation["first_conflict_chapter"] == 11
    assert reconciliation["first_conflict"]["code"] == "NEGATIVE_RESOURCE_BALANCE"
    assert before == after


def test_reconciliation_transaction_rolls_back_generic_after_authority_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    first = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动20。",
        claims=_claims(
            evidence="记录水晶数量变动20",
            before=0,
            change=20,
            after=20,
            operation="ADD",
        ),
    )
    store.confirm_candidate(first.candidate_id)
    downstream = _candidate(
        store,
        chapter=11,
        sentence="记录水晶数量变动5。",
        claims=_claims(
            evidence="记录水晶数量变动5",
            before=20,
            change=5,
            after=15,
            operation="SUBTRACT",
        ),
    )
    store.confirm_candidate(downstream.candidate_id)
    rewrite = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动10。",
        claims=_claims(
            evidence="记录水晶数量变动10",
            before=0,
            change=10,
            after=10,
            operation="ADD",
        ),
        operation="regenerate",
    )
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and ".pytest_cache" not in path.parts
    }
    original_write = store._write_json_atomic

    def fail_after_ledger_write(path: Path, payload: object) -> None:
        original_write(path, payload)
        if path == store.fact_resource_ledger_path:
            raise RuntimeError("reconciliation_ledger_write_injected_failure")

    monkeypatch.setattr(store, "_write_json_atomic", fail_after_ledger_write)
    with pytest.raises(RuntimeError, match="reconciliation_ledger_write_injected_failure"):
        store.confirm_candidate(rewrite.candidate_id)

    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and ".pytest_cache" not in path.parts
    }
    assert before == after
    assert store.candidate_store.get(rewrite.candidate_id).status == "pending"


def test_authority_history_is_rebuilt_from_end_n_minus_one(tmp_path: Path) -> None:
    store = _authority_store(tmp_path)
    chapter10 = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动20。",
        claims=[
            {
                "explicit": True,
                "category": "inventory",
                "resource_key": "记录水晶",
                "operation": "ADD",
                "before": 0,
                "change": 20,
                "after": 20,
                "evidence": "记录水晶数量变动20",
                "confidence": 0.99,
            }
        ],
    )
    store.confirm_candidate(chapter10.candidate_id)
    chapter11 = _candidate(
        store,
        chapter=11,
        sentence="记录水晶数量变动5。",
        claims=[
            {
                "explicit": True,
                "category": "inventory",
                "resource_key": "记录水晶",
                "operation": "SUBTRACT",
                "before": 20,
                "change": 5,
                "after": 15,
                "evidence": "记录水晶数量变动5",
                "confidence": 0.99,
            }
        ],
    )
    store.confirm_candidate(chapter11.candidate_id)
    rewrite = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动10。",
        claims=[
            {
                "explicit": True,
                "category": "inventory",
                "resource_key": "记录水晶",
                "operation": "ADD",
                "before": 0,
                "change": 10,
                "after": 10,
                "evidence": "记录水晶数量变动10",
                "confidence": 0.99,
            }
        ],
        operation="regenerate",
    )

    result = store.confirm_candidate(rewrite.candidate_id)
    assert result["candidate"]["status"] == "confirmed", result
    state = store.persisted_state()
    progression = state["progression_ledger"]["protagonist"]
    assert progression["inventory"]["记录水晶"] == 5
    history = progression["history"]
    assert [item["chapter"] for item in history if item.get("fact_resource_delta_id")] == [10, 11]
    assert get_fact_resource_snapshot(tmp_path, as_of_chapter=10).value_for("inventory", "记录水晶") == 10
    assert get_fact_resource_snapshot(tmp_path, as_of_chapter=11).value_for("inventory", "记录水晶") == 5


def test_mixed_authority_and_generic_reconciliation_commits_together(tmp_path: Path) -> None:
    store = _mixed_store(tmp_path)

    def claims(inventory_change: int, inventory_after: int, herb_change: int, herb_after: int) -> list[dict[str, object]]:
        return [
            {
                "explicit": True,
                "category": "inventory",
                "resource_key": "记录水晶",
                "operation": "ADD" if inventory_change >= 0 else "SUBTRACT",
                "before": inventory_after - inventory_change,
                "change": abs(inventory_change),
                "after": inventory_after,
                "evidence": f"记录水晶数量变动{abs(inventory_change)}",
                "confidence": 0.99,
            },
            {
                "explicit": True,
                "category": "resource",
                "resource_key": "灵草",
                "operation": "ADD" if herb_change >= 0 else "SUBTRACT",
                "before": herb_after - herb_change,
                "change": abs(herb_change),
                "after": herb_after,
                "evidence": f"灵草数量变动{abs(herb_change)}",
                "confidence": 0.99,
            },
        ]

    original = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动20。灵草数量变动6。",
        claims=claims(20, 20, 6, 6),
    )
    store.confirm_candidate(original.candidate_id)
    downstream = _candidate(
        store,
        chapter=11,
        sentence="记录水晶数量变动5。灵草数量变动2。",
        claims=claims(-5, 15, -2, 4),
    )
    store.confirm_candidate(downstream.candidate_id)
    rewrite = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动10。灵草数量变动4。",
        claims=claims(10, 10, 4, 4),
        operation="regenerate",
    )

    result = store.confirm_candidate(rewrite.candidate_id)
    assert result["candidate"]["status"] == "confirmed"
    state = store.persisted_state()
    assert state["progression_ledger"]["protagonist"]["inventory"]["记录水晶"] == 5
    ledger = FactResourceLedger.load(store.fact_resource_ledger_path)
    assert ledger is not None
    assert ledger.replay(as_of_chapter=11).value_for("resource", "灵草") == 2


def test_ambiguous_legacy_authority_history_is_unsupported_and_read_only(tmp_path: Path) -> None:
    store = _authority_store(tmp_path)
    initial = _candidate(
        store,
        chapter=10,
        sentence="本章没有资源变化。",
        claims=[],
    )
    store.confirm_candidate(initial.candidate_id)
    state = store.persisted_state()
    progression = state["progression_ledger"]["protagonist"]
    progression["history"] = [
        {"chapter": 9, "current": {"inventory": {"记录水晶": 0}}},
        {"chapter": 10, "current": {"inventory": {"记录水晶": 20}}},
    ]
    progression["inventory"] = {"记录水晶": 20}
    store._write_json(store.webnovel_dir / "state.json", state)
    rewrite = _candidate(
        store,
        chapter=10,
        sentence="记录水晶数量变动10。",
        claims=[
            {
                "explicit": True,
                "category": "inventory",
                "resource_key": "记录水晶",
                "operation": "SET",
                "before": 0,
                "change": 10,
                "after": 10,
                "evidence": "记录水晶数量变动10",
                "confidence": 0.99,
            }
        ],
        operation="regenerate",
    )
    before = store.persisted_state()
    result = store.confirm_candidate(rewrite.candidate_id)

    assert result["candidate"]["status"] == "pending"
    assert result["fact_resource_reconciliation"]["status"] == "UNSUPPORTED"
    assert any(
        item["code"] == "FACT_RESOURCE_RECONCILIATION_UNSUPPORTED_HISTORY"
        for item in result["fact_resource_reconciliation"]["findings"]
    )
    assert store.persisted_state() == before


def _equipment_claim(*, operation: str, before_owner: str, owner: str, evidence: str) -> list[dict[str, object]]:
    return [
        {
            "explicit": True,
            "category": "equipment_owner",
            "resource_key": "寒霜剑",
            "operation": operation,
            "before": before_owner,
            "owner": owner,
            "from_owner": before_owner,
            "to_owner": owner,
            "evidence": evidence,
            "confidence": 0.99,
        }
    ]


def test_equipment_reconciliation_replays_owner_transition(tmp_path: Path) -> None:
    store = _equipment_store(tmp_path)
    first = _candidate(
        store,
        chapter=10,
        sentence="把寒霜剑交给林山。",
        claims=_equipment_claim(
            operation="TRANSFER",
            before_owner="林远",
            owner="林山",
            evidence="把寒霜剑交给林山",
        ),
    )
    store.confirm_candidate(first.candidate_id)
    downstream = _candidate(
        store,
        chapter=11,
        sentence="把寒霜剑交给林河。",
        claims=_equipment_claim(
            operation="TRANSFER",
            before_owner="林山",
            owner="林河",
            evidence="把寒霜剑交给林河",
        ),
    )
    store.confirm_candidate(downstream.candidate_id)
    rewrite = _candidate(
        store,
        chapter=10,
        sentence="把寒霜剑交给林山。",
        claims=_equipment_claim(
            operation="TRANSFER",
            before_owner="林远",
            owner="林山",
            evidence="把寒霜剑交给林山",
        ),
        operation="regenerate",
    )

    result = store.confirm_candidate(rewrite.candidate_id)
    assert result["candidate"]["status"] == "confirmed"
    card = store.persisted_state()["equipment_cards"][0]
    assert card["current_owner"] == "林河"
    assert [item["chapter"] for item in card["history"] if item.get("fact_resource_delta_id")] == [10, 11]


def test_equipment_reconciliation_reports_owner_conflict_without_mutation(tmp_path: Path) -> None:
    store = _equipment_store(tmp_path)
    first = _candidate(
        store,
        chapter=10,
        sentence="把寒霜剑交给林山。",
        claims=_equipment_claim(
            operation="TRANSFER",
            before_owner="林远",
            owner="林山",
            evidence="把寒霜剑交给林山",
        ),
    )
    store.confirm_candidate(first.candidate_id)
    downstream = _candidate(
        store,
        chapter=11,
        sentence="把寒霜剑交给林河。",
        claims=_equipment_claim(
            operation="TRANSFER",
            before_owner="林山",
            owner="林河",
            evidence="把寒霜剑交给林河",
        ),
    )
    store.confirm_candidate(downstream.candidate_id)
    rewrite = _candidate(
        store,
        chapter=10,
        sentence="把寒霜剑交给顾闻舟。",
        claims=_equipment_claim(
            operation="TRANSFER",
            before_owner="林远",
            owner="顾闻舟",
            evidence="把寒霜剑交给顾闻舟",
        ),
        operation="regenerate",
    )
    before = store.persisted_state()
    result = store.confirm_candidate(rewrite.candidate_id)

    assert result["candidate"]["status"] == "pending"
    reconciliation = result["fact_resource_reconciliation"]
    assert reconciliation["status"] == "CONFLICT"
    assert reconciliation["first_conflict_chapter"] == 11
    assert reconciliation["first_conflict"]["code"] == "EQUIPMENT_OWNER_MISMATCH"
    assert store.persisted_state() == before


def _relationship_claim(*, operation: str, before: int, change: int, after: int, evidence: str) -> list[dict[str, object]]:
    return [
        {
            "explicit": True,
            "category": "relationship_numeric",
            "subject": "王铁匠",
            "resource_key": "trust",
            "operation": operation,
            "before": before,
            "change": change,
            "after": after,
            "evidence": evidence,
            "confidence": 0.99,
        }
    ]


def test_relationship_numeric_reconciliation_replays_from_end_n_minus_one(tmp_path: Path) -> None:
    store = _relationship_store(tmp_path)
    first = _candidate(
        store,
        chapter=10,
        sentence="王铁匠的信任发生变化5。",
        claims=_relationship_claim(
            operation="ADD",
            before=42,
            change=5,
            after=47,
            evidence="王铁匠的信任发生变化5",
        ),
    )
    store.confirm_candidate(first.candidate_id)
    downstream = _candidate(
        store,
        chapter=11,
        sentence="王铁匠的信任发生变化2。",
        claims=_relationship_claim(
            operation="SUBTRACT",
            before=47,
            change=2,
            after=45,
            evidence="王铁匠的信任发生变化2",
        ),
    )
    store.confirm_candidate(downstream.candidate_id)
    rewrite = _candidate(
        store,
        chapter=10,
        sentence="王铁匠的信任发生变化1。",
        claims=_relationship_claim(
            operation="ADD",
            before=42,
            change=1,
            after=43,
            evidence="王铁匠的信任发生变化1",
        ),
        operation="regenerate",
    )

    result = store.confirm_candidate(rewrite.candidate_id)
    assert result["candidate"]["status"] == "confirmed"
    graph = store._read_json(store.webnovel_dir / "project.json", {})["relationship_graph"]
    assert graph[0]["trust"] == 41
    assert get_fact_resource_snapshot(tmp_path, as_of_chapter=11).value_for(
        "relationship_numeric", "trust", subject="王铁匠"
    ) == 41
