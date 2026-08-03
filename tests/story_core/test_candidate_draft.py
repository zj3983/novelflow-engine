import pytest

from packages.story_core.candidate_draft import CandidateDraft


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
