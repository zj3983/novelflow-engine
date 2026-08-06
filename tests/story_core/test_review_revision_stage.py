from typing import Any

import pytest

from packages.story_core.pipeline.review_revision_stage import (
    ReviewRevisionCallbacks,
    ReviewRevisionResult,
    run_review_revision_stage,
)
from packages.story_core.review.contracts import ReviewFinding, ReviewResult


def _passing() -> ReviewResult:
    return ReviewResult.from_findings([])


def _blocked(code: str = "continuity.timeline") -> ReviewResult:
    return ReviewResult.from_findings(
        [
            ReviewFinding(
                code=code,
                category="hard",
                blocking=True,
                message="需要修复的硬伤。",
                suggestion="按要求修复。",
                source="continuity",
            )
        ]
    )


def _warning() -> ReviewResult:
    return ReviewResult.from_findings(
        [
            ReviewFinding(
                code="style.advisory",
                category="ai_flavor",
                blocking=False,
                message="存在轻微报告腔。",
                suggestion="改成动作。",
                source="ai_flavor",
            )
        ]
    )


def _revision_reviewer(body_to_review_result: dict[str, ReviewResult]):
    calls: list[str] = []

    def _hard(body: str) -> ReviewResult:
        calls.append("hard")
        return body_to_review_result.get(body, _passing())

    def _soft(body: str) -> ReviewResult:
        calls.append("soft")
        return _warning()

    def _revise(body: str, _review: ReviewResult) -> tuple[str, str]:
        calls.append("revise")
        return "revised", ""

    def _postprocess(body: str) -> str:
        return body.strip()

    def _choose_revision(*, original_body: str, candidate_body: str, **_kwargs) -> dict[str, Any]:
        return {
            "body": candidate_body,
            "quality": {"pass": True, "issues": []},
            "report": {"accepted": True},
            "accepted": True,
        }

    return calls, ReviewRevisionCallbacks(
        hard_review=_hard,
        soft_review=_soft,
        revise=_revise,
        postprocess=_postprocess,
        choose_revision=_choose_revision,
    )


def test_passed_draft_runs_one_hard_gate_and_one_soft_review():
    calls, callbacks = _revision_reviewer({"clean": _passing()})

    result = run_review_revision_stage(body="clean", callbacks=callbacks)

    assert isinstance(result, ReviewRevisionResult)
    assert result.body == "clean"
    assert result.revision_rounds == 0
    assert result.hard_result.status == "passed"
    assert result.soft_result.status == "warning"
    assert result.review_result.status == "warning"
    assert calls == ["hard", "soft"]


def test_blocked_draft_revises_once_then_rechecks_hard_gate():
    calls, callbacks = _revision_reviewer(
        {
            "blocked": _blocked(),
            "revised": _passing(),
        }
    )

    result = run_review_revision_stage(body="blocked", callbacks=callbacks)

    assert result.body == "revised"
    assert result.revision_rounds == 1
    assert result.hard_result.status == "passed"
    assert result.soft_result.status == "warning"
    assert calls == ["hard", "revise", "hard", "soft"]


def test_failed_revision_is_not_retried():
    calls = []

    def _hard(body: str) -> ReviewResult:
        calls.append("hard")
        return _blocked()

    def _soft(body: str) -> ReviewResult:
        calls.append("soft")
        return _passing()

    def _revise(body: str, _review: ReviewResult) -> tuple[str, str]:
        calls.append("revise")
        return "", "model_failed"

    def _postprocess(body: str) -> str:
        return body.strip()

    def _choose_revision(*, original_body: str, candidate_body: str, **_kwargs) -> dict[str, Any]:
        return {
            "body": original_body,
            "quality": {"pass": True, "issues": []},
            "report": {"accepted": False},
            "accepted": False,
        }

    callbacks = ReviewRevisionCallbacks(
        hard_review=_hard,
        soft_review=_soft,
        revise=_revise,
        postprocess=_postprocess,
        choose_revision=_choose_revision,
    )

    result = run_review_revision_stage(body="blocked", callbacks=callbacks)

    assert result.revision_rounds == 0
    assert result.body == "blocked"
    assert result.hard_result.status == "blocked"
    assert calls == ["hard", "revise", "soft"]


def test_soft_warning_never_triggers_revision():
    calls = []

    def _hard(body: str) -> ReviewResult:
        calls.append("hard")
        return _passing()

    def _soft(body: str) -> ReviewResult:
        calls.append("soft")
        return _warning()

    callbacks = ReviewRevisionCallbacks(
        hard_review=_hard,
        soft_review=_soft,
        revise=lambda *_a, **_k: ("", "should_not_call"),
        postprocess=lambda b: b,
        choose_revision=lambda **_k: {"body": "", "quality": {}, "report": {}, "accepted": False},
    )

    result = run_review_revision_stage(body="clean", callbacks=callbacks)

    assert result.revision_rounds == 0
    assert "revise" not in calls
    assert calls == ["hard", "soft"]
