"""Bounded review-revision controller for one chapter.

`run_review_revision_stage` runs a hard gate once, optionally one model-driven
revision, re-runs the hard gate, then a single soft review. Compression and
ad-hoc loops live elsewhere; this module only owns the review → revise →
re-review → soft-review sequence and is the only piece allowed to call the
model rewrite during chapter generation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from packages.story_core.review.contracts import ReviewResult


HardReview = Callable[[str], ReviewResult]
SoftReview = Callable[[str], ReviewResult]
Revise = Callable[[str, ReviewResult], tuple[str, str]]
Postprocess = Callable[[str], str]
ChooseRevision = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ReviewRevisionCallbacks:
    hard_review: HardReview
    soft_review: SoftReview
    revise: Revise
    postprocess: Postprocess
    choose_revision: ChooseRevision


@dataclass(frozen=True)
class ReviewRevisionResult:
    body: str
    review_result: ReviewResult
    hard_result: ReviewResult
    soft_result: ReviewResult
    revision_rounds: int
    revision_safety_report: dict[str, Any] | None = None


def run_review_revision_stage(
    *,
    body: str,
    callbacks: ReviewRevisionCallbacks,
) -> ReviewRevisionResult:
    """Run hard-gate → optional one-shot revision → hard-gate → soft-review.

    The algorithm is intentionally linear (no `while`): the hard gate runs
    at most twice, the model rewrite runs at most once, and the soft review
    runs exactly once. Compression retries are the caller's responsibility
    and must not live inside this stage.
    """

    current_body = body
    hard = callbacks.hard_review(current_body)
    revision_rounds = 0
    revision_safety_report: Optional[dict[str, Any]] = None

    if hard.status == "blocked":
        candidate_body, revision_error = callbacks.revise(current_body, hard)
        if not revision_error and candidate_body.strip():
            postprocessed = callbacks.postprocess(candidate_body)
            if postprocessed.strip():
                candidate_hard = callbacks.hard_review(postprocessed)
                safety = callbacks.choose_revision(
                    original_body=current_body,
                    candidate_body=postprocessed,
                    original_hard=hard,
                    candidate_hard=candidate_hard,
                )
                if isinstance(safety, dict) and safety.get("accepted"):
                    current_body = str(safety.get("body") or postprocessed)
                    hard = candidate_hard
                    revision_rounds = 1
                    revision_safety_report = safety.get("report") if isinstance(safety.get("report"), dict) else None

    soft = callbacks.soft_review(current_body)
    combined = ReviewResult.from_findings(
        [*hard.findings, *soft.findings],
        diagnostics={**hard.diagnostics, **soft.diagnostics},
    )

    return ReviewRevisionResult(
        body=current_body,
        review_result=combined,
        hard_result=hard,
        soft_result=soft,
        revision_rounds=revision_rounds,
        revision_safety_report=revision_safety_report,
    )
