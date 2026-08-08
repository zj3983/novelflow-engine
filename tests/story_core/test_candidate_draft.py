import pytest

from packages.story_core.candidate_draft import CandidateDraft
from packages.story_core.continuity.delta import ContinuityDelta, InventoryChange


def test_candidate_draft_stays_pending_until_explicit_confirmation():
    draft = CandidateDraft.create(
        project_id="p-1",
        chapter_number=4,
        chapter_title="第四章",
        body="候选正文",
        context_snapshot_id="ctx-1",
        quality_report={"ok": True},
    )

    assert draft.status == "pending"
    assert draft.current_chapter_after_confirm == 4
    assert draft.to_dict()["status"] == "pending"

    confirmed = draft.confirm()
    assert confirmed.status == "confirmed"
    assert confirmed.confirmed_at


def test_candidate_confirmation_is_idempotent_but_other_transitions_are_guarded():
    draft = CandidateDraft.create(project_id="p-1", chapter_number=1, body="正文")
    confirmed = draft.confirm()

    assert confirmed.confirm() == confirmed
    with pytest.raises(ValueError, match="candidate_not_pending"):
        confirmed.discard()


def test_candidate_draft_round_trips_without_losing_context_or_review():
    draft = CandidateDraft.create(
        project_id="p-1",
        chapter_number=2,
        body="正文",
        context_snapshot_id="ctx-2",
        quality_report={"issues": ["dialogue"]},
        revision_history=[{"round": 1, "accepted": False}],
        submission_payload={"updated_story": {"current_chapter": 2}},
    )

    restored = CandidateDraft.from_dict(draft.to_dict())

    assert restored == draft
    assert restored.quality_report["issues"] == ["dialogue"]
    assert restored.revision_history[0]["round"] == 1
    assert restored.submission_payload["updated_story"]["current_chapter"] == 2


def test_candidate_draft_round_trips_submission_operation():
    draft = CandidateDraft.create(
        project_id="p-1",
        chapter_number=2,
        body="重写正文",
        operation="regenerate",
    )

    restored = CandidateDraft.from_dict(draft.to_dict())

    assert restored.operation == "regenerate"


def test_candidate_draft_v1_payload_still_loads_after_v2_introduction():
    legacy_v1 = {
        "schema_version": "candidate-draft/v1",
        "candidate_id": "cd-legacy",
        "project_id": "p-1",
        "chapter_number": 3,
        "chapter_title": "第三章",
        "body": "候选正文",
        "context_snapshot_id": "ctx-1",
        "quality_report": {"ok": True},
        "revision_history": [],
        "submission_payload": {"chapter_number": 3},
        "operation": "generate",
        "status": "pending",
        "created_at": "2026-01-01T00:00:00+00:00",
        "confirmed_at": "",
    }

    restored = CandidateDraft.from_dict(legacy_v1)

    assert restored.candidate_id == "cd-legacy"
    assert restored.continuity_delta is None
    assert restored.context_trace_ids == []


def test_candidate_draft_v2_carries_continuity_delta_and_trace_ids():
    delta = ContinuityDelta(
        chapter_number=4,
        inventory_changes=[
            InventoryChange(
                chapter_number=4,
                source_sentence="林昭收下了三枚金币",
                confidence=1.0,
                entity_id="char-linzhao",
                item="金币",
                delta=3,
            )
        ],
    )

    draft = CandidateDraft.create(
        project_id="p-1",
        chapter_number=4,
        body="正文",
        continuity_delta=delta,
        context_trace_ids=["trace-director-1", "trace-writer-1"],
    )

    payload = draft.to_dict()
    assert payload["schema_version"] == "candidate-draft/v2"
    assert payload["continuity_delta"]["inventory_changes"][0]["item"] == "金币"
    assert payload["context_trace_ids"] == ["trace-director-1", "trace-writer-1"]

    restored = CandidateDraft.from_dict(payload)
    assert restored.continuity_delta is not None
    assert restored.continuity_delta.inventory_changes[0].delta == 3
    assert restored.context_trace_ids == ["trace-director-1", "trace-writer-1"]


def test_candidate_draft_stays_v1_when_no_new_fields_are_set():
    draft = CandidateDraft.create(
        project_id="p-1",
        chapter_number=5,
        body="旧式候选稿",
    )

    payload = draft.to_dict()

    assert payload["schema_version"] == "candidate-draft/v1"
    assert "continuity_delta" not in payload
    assert "context_trace_ids" not in payload
