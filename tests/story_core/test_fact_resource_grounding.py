from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.fact_resource_ledger import (
    FactResourceEntry,
    FactResourceSnapshot,
    extract_fact_resource_changes,
)
from packages.story_core.generation_progress import generation_progress


def _snapshot(*entries: FactResourceEntry) -> FactResourceSnapshot:
    return FactResourceSnapshot(known=True, entries=list(entries))


def _delta_pairs(extraction):
    return [
        (item.category, item.resource_key, item.operation, item.change)
        for item in extraction.deltas
    ]


def test_real_chapter_62_backpack_action_is_not_a_resource_delta() -> None:
    extraction = extract_fact_resource_changes(
        "周行沉默了两秒，把背包卸下来，取出那三块演示水晶。",
        62,
    )

    assert extraction.deltas == []
    assert {item.code for item in extraction.findings} == {
        "FACT_RESOURCE_ENTITY_UNRESOLVED"
    }
    assert all(item.severity == "warning" for item in extraction.findings)


def test_real_chapter_64_inventory_phrase_remains_grounded() -> None:
    extraction = extract_fact_resource_changes(
        "我那儿有两件装备要修，是不是也能挂？",
        64,
    )

    assert _delta_pairs(extraction) == [("inventory", "装备要修", "SET", 2)]
    assert extraction.deltas[0].metadata["grounding"]["status"] == "GROUNDED"


def test_real_chapter_65_quest_phrase_remains_grounded() -> None:
    extraction = extract_fact_resource_changes(
        "还有两个想直接把货寄存到任务站代卖。",
        65,
    )

    assert _delta_pairs(extraction) == [
        ("quest", "想直接把货寄存到任务站代卖", "SET", 2)
    ]
    assert extraction.deltas[0].metadata["grounding"]["status"] == "GROUNDED"


def test_known_equipment_can_be_unequipped_with_exact_evidence() -> None:
    start = _snapshot(
        FactResourceEntry(
            category="equipment_state",
            resource_key="寒霜剑",
            value=True,
            metadata={"equipped": True, "lookup_keys": ["寒霜剑", "frost-sword"]},
        )
    )

    extraction = extract_fact_resource_changes("他卸下寒霜剑。", 1, start)

    assert _delta_pairs(extraction) == [
        ("equipment_state", "寒霜剑", "UNEQUIP", None)
    ]
    grounding = extraction.deltas[0].metadata["grounding"]
    assert grounding["status"] == "GROUNDED"
    assert grounding["source"] == "equipment_authority"
    assert grounding["evidence"] == "寒霜剑"


def test_unknown_equipment_object_stays_unresolved() -> None:
    extraction = extract_fact_resource_changes("他把背包卸下来。", 1)

    assert extraction.deltas == []
    assert any(
        item.code == "FACT_RESOURCE_ENTITY_UNRESOLVED"
        and item.resource_key == "来"
        for item in extraction.findings
    )


def test_known_equipment_transfer_supports_ba_construction() -> None:
    start = _snapshot(
        FactResourceEntry(
            category="equipment_owner",
            resource_key="寒霜剑",
            owner="林远",
            metadata={"lookup_keys": ["寒霜剑"]},
        )
    )

    extraction = extract_fact_resource_changes("他把寒霜剑交给林远。", 1, start)

    assert _delta_pairs(extraction) == [
        ("equipment_owner", "寒霜剑", "TRANSFER", None)
    ]


def test_structured_writer_claim_uses_the_same_grounding_gate() -> None:
    extraction = extract_fact_resource_changes(
        "把背包卸下来。",
        1,
        candidate_claims=[
            {
                "explicit": True,
                "confidence": 0.99,
                "category": "equipment_state",
                "resource_key": "来",
                "operation": "UNEQUIP",
                "evidence": "把背包卸下来。",
            }
        ],
    )

    assert extraction.deltas == []
    assert any(item.code == "FACT_RESOURCE_ENTITY_UNRESOLVED" for item in extraction.findings)


def test_structured_writer_claim_without_evidence_is_invalid() -> None:
    extraction = extract_fact_resource_changes(
        "任务记录更新。",
        1,
        candidate_claims=[
            {
                "explicit": True,
                "confidence": 0.99,
                "category": "quest",
                "resource_key": "采集",
                "operation": "PROGRESS_ADD",
                "change": 2,
                "evidence": "",
            }
        ],
    )

    assert extraction.deltas == []
    assert any(
        item.code == "FACT_RESOURCE_EVIDENCE_UNGROUNDED"
        and (item.observed or {}).get("grounding_status") == "INVALID"
        for item in extraction.findings
    )


def test_structured_writer_claim_can_preserve_grounded_equipment() -> None:
    start = _snapshot(
        FactResourceEntry(
            category="equipment_state",
            resource_key="寒霜剑",
            value=True,
            metadata={"equipped": True},
        )
    )
    extraction = extract_fact_resource_changes(
        "他卸下寒霜剑。",
        1,
        start,
        candidate_claims=[
            {
                "explicit": True,
                "confidence": 0.99,
                "category": "equipment_state",
                "resource_key": "寒霜剑",
                "operation": "UNEQUIP",
                "evidence": "他卸下寒霜剑。",
            }
        ],
    )

    assert len(extraction.deltas) == 1
    assert extraction.deltas[0].resource_key == "寒霜剑"
    assert extraction.deltas[0].metadata["grounding"]["status"] == "GROUNDED"


def test_unresolved_candidate_can_confirm_without_resource_ledger_mutation(tmp_path) -> None:
    store = FileProjectStore(tmp_path)
    body = ("周行把背包卸下来，取出水晶。" + "他继续记录现场变化。" * 600)[:5000]
    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="候选章节",
        title="候选章节",
        body=body,
        quality_report={"ok": True},
        context_snapshot_id="ctx-grounding",
    )

    with generation_progress(lambda *_: None):
        candidate = store._save_candidate_from_bundle(bundle, project_id=store.root.name)

    assert candidate.status == "pending"
    assert candidate.fact_resource_extraction is not None
    assert candidate.fact_resource_extraction.deltas == []
    assert any(
        item.code == "FACT_RESOURCE_ENTITY_UNRESOLVED"
        for item in candidate.fact_resource_extraction.findings
    )

    result = store.confirm_candidate(candidate.candidate_id)

    assert result["candidate"]["status"] == "confirmed"
    assert not store.fact_resource_ledger_path.exists()


@pytest.mark.parametrize(
    "body",
    [
        "如果有10枚金币，我就买下它。",
        "完成任务可获得500经验。",
        "明天再买三瓶药。",
        "奖励500经验。",
        "昨天花费100金币。",
        "没有花费100金币。",
        "并未卸下寒霜剑。",
        "如果好感再加5点……",
        "任务要求卖出10件。",
    ],
)
def test_non_factual_or_negated_resource_language_produces_no_delta(body: str) -> None:
    start = _snapshot(
        FactResourceEntry(
            category="equipment_state",
            resource_key="寒霜剑",
            value=True,
            metadata={"equipped": True},
        )
    )

    extraction = extract_fact_resource_changes(body, 1, start)

    assert extraction.deltas == []
    assert all(
        item.code in {
            "FACT_RESOURCE_NON_FACTUAL",
            "FACT_RESOURCE_TEMPORAL_AMBIGUITY",
            "FACT_RESOURCE_ENTITY_UNRESOLVED",
        }
        for item in extraction.findings
    )


def test_explicit_mutations_remain_available() -> None:
    extraction = extract_fact_resource_changes(
        "获得100金币，获得3瓶药，花100金币。",
        1,
    )

    assert _delta_pairs(extraction) == [
        ("currency", "金币", "ADD", 100),
        ("inventory", "药", "ADD", 3),
        ("currency", "金币", "SUBTRACT", 100),
    ]


def test_purchase_can_emit_two_independently_grounded_deltas() -> None:
    extraction = extract_fact_resource_changes("他花100金币买了3瓶药。", 1)

    assert _delta_pairs(extraction) == [
        ("currency", "金币", "SUBTRACT", 100),
        ("inventory", "药", "ADD", 3),
    ]
    assert len({item.delta_id for item in extraction.deltas}) == 2


def test_relationship_numeric_requires_a_grounded_existing_metric() -> None:
    start = _snapshot(
        FactResourceEntry(
            category="relationship_numeric",
            subject="林远",
            resource_key="好感度",
            value=10,
        )
    )

    extraction = extract_fact_resource_changes("林远对他的好感度增加5点。", 1, start)

    assert _delta_pairs(extraction) == [
        ("relationship_numeric", "好感度", "ADD", 5)
    ]
    assert extraction.deltas[0].subject == "林远"


def test_quest_target_is_not_current_progress() -> None:
    extraction = extract_fact_resource_changes("任务要求卖出10件。", 1)

    assert extraction.deltas == []


def test_known_quest_progress_can_be_grounded() -> None:
    start = _snapshot(
        FactResourceEntry(
            category="quest",
            resource_key="代卖任务",
            value=0,
            metadata={"target": 10},
        )
    )

    extraction = extract_fact_resource_changes("代卖任务完成2件。", 1, start)

    assert _delta_pairs(extraction) == [("quest", "代卖任务", "PROGRESS_ADD", 2)]
