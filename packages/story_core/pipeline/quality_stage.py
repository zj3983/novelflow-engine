"""Bounded chapter quality stage.

This module is now a thin compatibility shim around the canonical
`run_review_revision_stage` controller. The legacy `run_quality_stage` is
preserved for callers that still pass a `QualityStageCallbacks` bundle, but
its body is no longer a freeform `while` loop:

* Review (hard gate) runs once.
* At most one model-driven revision runs.
* A final soft review runs once.
* Optional compression runs once with no retry.

Compression, length rebalance, and revision-safety selection happen
*outside* the review-revision controller, but they are bounded: at most one
compression attempt, no second-round retry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from packages.story_core.review.contracts import ReviewResult

from .review_revision_stage import (
    ReviewRevisionCallbacks,
    ReviewRevisionResult,
    run_review_revision_stage,
)


Review = Callable[[str], dict[str, Any]]
GateBuilder = Callable[[dict[str, Any]], dict[str, Any]]
RevisionCall = Callable[[str, dict[str, Any], int], tuple[str, str]]
CompressionCall = Callable[[str, int, dict[str, Any] | None], tuple[str, str]]
QualityEvent = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class QualityStageCallbacks:
    review: Review
    build_gate: GateBuilder
    should_revise: Callable[[dict[str, Any]], bool]
    revise: RevisionCall
    postprocess: Callable[[str], str]
    choose_revision: Callable[..., dict[str, Any]]
    should_compress: Callable[[str], bool]
    compress: CompressionCall
    compression_quality_not_worse: Callable[[dict[str, Any], dict[str, Any], str, str], bool]
    compression_action: Callable[[str, str], str]
    compressed_acceptable: Callable[[str, str], bool]
    retry_acceptable: Callable[[str, str], bool]
    hard_length_acceptable: Callable[[str], bool]
    char_count: Callable[[str], int]


@dataclass(frozen=True)
class QualityStageResult:
    body: str
    writing_review: dict[str, Any]
    review_gate: dict[str, Any]
    revision_rounds: int = 0
    revision_safety_report: dict[str, Any] | None = None
    accepted_revision_actions: tuple[str, ...] = ()


def _review_to_result(review: dict[str, Any]) -> ReviewResult:
    """Adapt a legacy review dict into a ReviewResult for the bounded controller.

    The legacy aggregate exposes ``has_hard_errors`` and the simplified
    review's ``has_blocking_dialogue`` flag. We only treat the review as
    blocking when at least one of those is True, matching the historical
    `_should_run_full_revision` semantics so that soft advisory findings do
    not trigger a model rewrite.
    """
    if not isinstance(review, dict):
        return ReviewResult.from_findings([])
    from packages.story_core.review.contracts import ReviewFinding
    from packages.story_core.simplified_review import build_simplified_review

    has_hard_errors = bool(review.get("has_hard_errors"))
    if not has_hard_errors:
        simplified = build_simplified_review({"writing_review": review})
        if isinstance(simplified, dict):
            has_hard_errors = bool(simplified.get("has_hard_errors")) or bool(simplified.get("has_blocking_dialogue"))
    if not has_hard_errors:
        return ReviewResult.from_findings([])

    issues: list[str] = []
    for index, issue in enumerate(review.get("issues") or []):
        if isinstance(issue, str):
            message = issue.strip()
        elif isinstance(issue, dict):
            message = str(issue.get("message") or issue.get("reason") or issue.get("issue") or "").strip()
        else:
            continue
        if not message:
            continue
        issues.append(message)
    findings = [
        ReviewFinding(
            code=f"legacy.{index}",
            category="hard",
            blocking=True,
            message=message,
            suggestion="",
            source="legacy",
        )
        for index, message in enumerate(issues[:3])
    ]
    return ReviewResult.from_findings(findings)


def _result_to_gate(result: ReviewResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "needs_revision": result.needs_revision,
        "has_hard_errors": result.has_hard_errors,
    }


def _run_review_revision_stage(
    *,
    body: str,
    callbacks: QualityStageCallbacks,
    on_event: QualityEvent | None = None,
) -> ReviewRevisionResult:
    cache: dict[str, dict[str, Any]] = {}

    def _review(candidate: str) -> dict[str, Any]:
        if candidate not in cache:
            cache[candidate] = callbacks.review(candidate)
        return cache[candidate]

    original_review = _review(body)
    original_gate = callbacks.build_gate(original_review)

    def _hard(candidate: str) -> ReviewResult:
        review = _review(candidate)
        gate = callbacks.build_gate(review)
        if callbacks.should_revise(gate) and (
            bool(gate.get("has_hard_errors"))
            or bool(gate.get("has_blocking_dialogue"))
        ):
            from packages.story_core.review.contracts import ReviewFinding

            findings: list[ReviewFinding] = []
            for index, issue in enumerate(review.get("issues") or [][:3]):
                if isinstance(issue, str):
                    message = issue
                elif isinstance(issue, dict):
                    message = str(issue.get("message") or issue.get("reason") or issue.get("issue") or "")
                else:
                    continue
                if not message.strip():
                    continue
                findings.append(
                    ReviewFinding(
                        code=f"legacy.{index}",
                        category="hard",
                        blocking=True,
                        message=message,
                        suggestion="",
                        source="legacy",
                    )
                )
            return ReviewResult.from_findings(findings)
        return ReviewResult.from_findings([])

    def _soft(candidate: str) -> ReviewResult:
        return ReviewResult.from_findings([])

    def _revise(candidate: str, _ignored: ReviewResult) -> tuple[str, str]:
        return callbacks.revise(candidate, _review(candidate), 1)

    def _postprocess(text: str) -> str:
        return callbacks.postprocess(text)

    def _choose_revision(*, original_body: str, candidate_body: str, **kwargs) -> dict[str, Any]:
        candidate_review = _review(candidate_body)
        candidate_gate = callbacks.build_gate(candidate_review)
        original_quality_with_flag = dict(original_review)
        original_quality_with_flag["has_hard_errors"] = bool(
            original_gate.get("has_hard_errors")
        )
        candidate_quality_with_flag = dict(candidate_review)
        candidate_quality_with_flag["has_hard_errors"] = bool(
            candidate_gate.get("has_hard_errors")
        )
        return callbacks.choose_revision(
            original_body=original_body,
            original_quality=original_quality_with_flag,
            candidate_body=candidate_body,
            candidate_quality=candidate_quality_with_flag,
        )

    return run_review_revision_stage(
        body=body,
        callbacks=ReviewRevisionCallbacks(
            hard_review=_hard,
            soft_review=_soft,
            revise=_revise,
            postprocess=_postprocess,
            choose_revision=_choose_revision,
        ),
        on_event=on_event,
    )


def _run_single_compression(
    *,
    body: str,
    callbacks: QualityStageCallbacks,
    on_event: QualityEvent | None,
) -> tuple[str, dict[str, Any] | None, str]:
    """Run a single compression attempt with no retry loop.

    Returns the (possibly) compressed body, the candidate review (or None),
    and an error string.
    """
    if not callbacks.should_compress(body):
        return body, None, ""
    if on_event is not None:
        on_event("compression_start", {"body": body})
    compressed, error = callbacks.compress(body, 1, None)
    if error or not compressed.strip():
        if on_event is not None:
            on_event("compression_complete", {"before_body": body, "candidate_body": compressed, "quality_preserved": False, "action": "reject", "candidate_review": {}})
        return body, None, error or "compression_empty"
    candidate_body = callbacks.postprocess(compressed)
    candidate_review = callbacks.review(candidate_body)
    quality_preserved = callbacks.compression_quality_not_worse(
        {"pass": True, "issues": []}, candidate_review, body, candidate_body
    )
    action = callbacks.compression_action(body, candidate_body)
    if on_event is not None:
        on_event(
            "compression_complete",
            {
                "before_body": body,
                "candidate_body": candidate_body,
                "quality_preserved": quality_preserved,
                "action": action,
                "candidate_review": candidate_review,
            },
        )
    if callbacks.compressed_acceptable(body, candidate_body) and quality_preserved and action == "accept":
        return candidate_body, candidate_review, ""
    return body, None, ""


def run_quality_stage(
    *,
    body: str,
    callbacks: QualityStageCallbacks,
    max_revision_rounds: int = 1,
    on_event: QualityEvent | None = None,
) -> QualityStageResult:
    # Review → optional single revision → final review, all bounded.
    stage = _run_review_revision_stage(body=body, callbacks=callbacks, on_event=on_event)
    body = stage.body
    # The bounded controller's hard_result already reflects the post-revision
    # state. Use it to derive the final review dict for the legacy aggregate.
    hard_dict = stage.hard_result.to_dict()
    review = {
        "pass": not stage.hard_result.has_hard_errors,
        "issues": [item.message for item in stage.hard_result.findings],
        "revision_plan": stage.hard_result.revision_plan,
        "has_hard_errors": stage.hard_result.has_hard_errors,
        "review_result": hard_dict,
    }
    gate = {
        "needs_revision": stage.hard_result.needs_revision,
        "has_hard_errors": stage.hard_result.has_hard_errors,
        "status": stage.hard_result.status,
        "categories": hard_dict.get("categories", {}),
    }

    # Single compression attempt; no retry loop, no second round.
    body, _candidate_review, _compression_error = _run_single_compression(
        body=body, callbacks=callbacks, on_event=on_event
    )
    # Re-derive gate from cached review so memory extraction still sees a
    # valid gate without forcing an extra `callbacks.review` call.
    if body != stage.body:
        review_after_compression = callbacks.review(body)
        review = review_after_compression
        gate = callbacks.build_gate(review)

    if on_event is not None:
        on_event(
            "review_complete",
            {
                "body": body,
                "review": review,
                "gate": gate,
                "revision_rounds": stage.revision_rounds,
            },
        )

    return QualityStageResult(
        body=body,
        writing_review=review,
        review_gate=gate,
        revision_rounds=stage.revision_rounds,
        revision_safety_report=stage.revision_safety_report,
    )
