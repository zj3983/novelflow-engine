"""Review, bounded revision, compression, and final review for one chapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


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


def _quality(review: dict[str, Any], gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(review.get("pass")),
        "issues": review.get("issues", []),
        "writing_review": review,
        "has_hard_errors": bool(gate.get("has_hard_errors")),
    }


def _resolved_revision_actions(
    before_gate: dict[str, Any],
    after_gate: dict[str, Any],
) -> list[str]:
    unresolved = {
        category
        for category in ("hard", "dialogue", "ai_flavor")
        if int(after_gate.get("categories", {}).get(category, {}).get("count") or 0) > 0
    }
    return [
        str(item.get("suggestion") or "").strip()
        for item in before_gate.get("issues", [])
        if isinstance(item, dict)
        and item.get("category") in {"hard", "dialogue", "ai_flavor"}
        and item.get("category") not in unresolved
        and str(item.get("suggestion") or "").strip()
    ]


def run_quality_stage(
    *,
    body: str,
    callbacks: QualityStageCallbacks,
    max_revision_rounds: int = 1,
    on_event: QualityEvent | None = None,
) -> QualityStageResult:
    review = callbacks.review(body)
    gate = callbacks.build_gate(review)
    revision_rounds = 0
    revision_safety_report = None
    accepted_revision_actions: list[str] = []

    while callbacks.should_revise(gate) and revision_rounds < max_revision_rounds:
        revision_rounds += 1
        if on_event:
            on_event("revision_start", {"round": revision_rounds, "review": review, "gate": gate})
        before_body = body
        before_review = review
        before_gate = gate
        revised_text, revision_error = callbacks.revise(body, review, revision_rounds)
        if not revision_error and revised_text.strip():
            candidate_body = callbacks.postprocess(revised_text)
            candidate_review = callbacks.review(candidate_body)
            candidate_gate = callbacks.build_gate(candidate_review)
            safety = callbacks.choose_revision(
                original_body=before_body,
                original_quality=_quality(before_review, before_gate),
                candidate_body=candidate_body,
                candidate_quality=_quality(candidate_review, candidate_gate),
            )
            body = str(safety["body"])
            selected_quality = safety.get("quality") if isinstance(safety.get("quality"), dict) else _quality(before_review, before_gate)
            review = selected_quality.get("writing_review") if isinstance(selected_quality.get("writing_review"), dict) else before_review
            revision_safety_report = safety.get("report") if isinstance(safety.get("report"), dict) else None
            if safety.get("accepted"):
                accepted_revision_actions.extend(_resolved_revision_actions(before_gate, candidate_gate))
        gate = callbacks.build_gate(review)
        if on_event:
            on_event(
                "revision_complete",
                {
                    "round": revision_rounds,
                    "review": review,
                    "gate": gate,
                    "safety_report": revision_safety_report,
                    "error": revision_error,
                },
            )

    if callbacks.should_compress(body):
        if on_event:
            on_event("compression_start", {"body": body})
        best_acceptable_body = ""
        best_acceptable_review: dict[str, Any] | None = None
        before_body = body
        compressed_text, compression_error = callbacks.compress(before_body, 1, None)
        if not compression_error and compressed_text.strip():
            candidate_body = callbacks.postprocess(compressed_text)
            candidate_review = callbacks.review(candidate_body)
            quality_preserved = callbacks.compression_quality_not_worse(
                review, candidate_review, before_body, candidate_body
            )
            action = callbacks.compression_action(before_body, candidate_body)
            candidate_chars = callbacks.char_count(candidate_body)
            before_chars = callbacks.char_count(before_body)
            retry_reason = (
                "too_short"
                if action == "retry"
                else "expanded"
                if action == "reject" and candidate_chars >= before_chars
                else ""
            )
            if retry_reason:
                retry_feedback = {
                    "previous_chars": candidate_chars,
                    "reason": retry_reason,
                }
                if on_event:
                    on_event(
                        "compression_retry_start",
                        {"before_body": before_body, "candidate_body": candidate_body, **retry_feedback},
                    )
                retry_text, retry_error = callbacks.compress(before_body, 1, retry_feedback)
                retry_accepted = False
                if not retry_error and retry_text.strip():
                    retry_body = callbacks.postprocess(retry_text)
                    retry_review = callbacks.review(retry_body)
                    retry_quality_preserved = callbacks.compression_quality_not_worse(
                        review, retry_review, before_body, retry_body
                    )
                    retry_accepted = (
                        callbacks.retry_acceptable(before_body, retry_body)
                        and retry_quality_preserved
                    )
                    if retry_accepted:
                        candidate_body = retry_body
                        candidate_review = retry_review
                        quality_preserved = True
                        action = callbacks.compression_action(before_body, retry_body)
                if on_event:
                    on_event(
                        "compression_retry_complete",
                        {
                            "before_body": before_body,
                            "candidate_body": candidate_body,
                            "candidate_review": candidate_review,
                            "previous_chars": retry_feedback["previous_chars"],
                            "accepted": retry_accepted,
                            "error": retry_error,
                        },
                    )
            if callbacks.compressed_acceptable(before_body, candidate_body) and quality_preserved:
                best_acceptable_body = candidate_body
                best_acceptable_review = candidate_review
            if on_event:
                on_event(
                    "compression_complete",
                    {
                        "before_body": before_body,
                        "candidate_body": candidate_body,
                        "quality_preserved": quality_preserved,
                        "action": action,
                        "candidate_review": candidate_review,
                    },
                )
            if quality_preserved and action == "accept":
                body = candidate_body
                review = candidate_review
        if not callbacks.hard_length_acceptable(body) and best_acceptable_body:
            body = best_acceptable_body
            review = best_acceptable_review or review
        review = callbacks.review(body)
        gate = callbacks.build_gate(review)

    if on_event:
        on_event(
            "review_complete",
            {"body": body, "review": review, "gate": gate, "revision_rounds": revision_rounds},
        )
    return QualityStageResult(
        body=body,
        writing_review=review,
        review_gate=gate,
        revision_rounds=revision_rounds,
        revision_safety_report=revision_safety_report,
        accepted_revision_actions=tuple(accepted_revision_actions),
    )
