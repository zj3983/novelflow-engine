from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _bool_score(value: Any, *, yes: float, no: float) -> float:
    return yes if bool(value) else no


def score_quality_report(quality: dict[str, Any]) -> float:
    """Return a compact safety score for comparing before/after drafts.

    The score is intentionally simple and conservative. It favors drafts that
    pass existing reviewers, keeps average rubric scores meaningful, and heavily
    penalizes new issue lists or adversarial cut pressure.
    """

    quality = _as_dict(quality)
    writing_review = _as_dict(quality.get("writing_review"))
    scores = _as_dict(writing_review.get("scores"))
    numeric_scores = [float(value) for value in scores.values() if isinstance(value, (int, float))]
    rubric_score = (sum(numeric_scores) / len(numeric_scores) * 10.0) if numeric_scores else 0.0

    prose_review = _as_dict(writing_review.get("prose_quality_review"))
    prose_score = float(prose_review.get("overall") or 0)

    cut_review = _as_dict(writing_review.get("adversarial_cut_review"))
    cut_pressure = float(cut_review.get("cut_pressure") or 0)
    world_state_review = _as_dict(writing_review.get("world_state_review"))

    issue_count = len(_as_list(quality.get("issues"))) + len(_as_list(writing_review.get("issues")))
    issue_count += len(_as_list(prose_review.get("issues"))) + len(_as_list(world_state_review.get("issues")))
    issue_count += len(_as_list(cut_review.get("cuts")))

    score = 0.0
    score += _bool_score(quality.get("ok"), yes=20.0, no=-10.0)
    score += _bool_score(writing_review.get("pass"), yes=25.0, no=-15.0)
    score += _bool_score(prose_review.get("pass", True), yes=8.0, no=-8.0)
    score += _bool_score(world_state_review.get("pass", True), yes=8.0, no=-12.0)
    score += _bool_score(cut_review.get("pass", True), yes=8.0, no=-12.0)
    score += rubric_score
    score += prose_score * 0.3
    score -= issue_count * 4.0
    score -= cut_pressure * 6.0
    return round(score, 2)


def choose_best_revision(
    *,
    original_body: str,
    original_quality: dict[str, Any],
    candidate_body: str,
    candidate_quality: dict[str, Any],
    min_delta: float = 0.0,
) -> dict[str, Any]:
    original_score = score_quality_report(original_quality)
    candidate_score = score_quality_report(candidate_quality)
    original_chars = len("".join(str(original_body or "").split()))
    candidate_chars = len("".join(str(candidate_body or "").split()))
    forced_reject_reason = ""
    if original_chars >= 1000 and candidate_chars < original_chars * 0.65:
        forced_reject_reason = "candidate_severely_shorter"
        candidate_score -= 80.0
    elif original_chars >= 3900 and candidate_chars < 3900:
        forced_reject_reason = "candidate_below_chapter_minimum"
        candidate_score -= 120.0
    elif original_chars >= 3900 and candidate_chars < original_chars * 0.75:
        forced_reject_reason = "candidate_shrank_too_much"
        candidate_score -= 80.0
    accepted = not forced_reject_reason and candidate_score >= original_score + min_delta
    report = {
        "reviewer": "revision_safety/v1",
        "accepted": accepted,
        "selected": "candidate" if accepted else "original",
        "reason": "candidate_not_worse" if accepted else (forced_reject_reason or "candidate_worse_than_original"),
        "original_score": original_score,
        "candidate_score": round(candidate_score, 2),
        "min_delta": min_delta,
        "original_chars": original_chars,
        "candidate_chars": candidate_chars,
    }
    if accepted:
        return {
            "accepted": True,
            "selected": "candidate",
            "body": candidate_body,
            "quality": candidate_quality,
            "report": report,
        }
    return {
        "accepted": False,
        "selected": "original",
        "body": original_body,
        "quality": original_quality,
        "report": report,
    }


def score_segment_review(review: dict[str, Any]) -> float:
    review = _as_dict(review)
    scores = _as_dict(review.get("scores"))
    numeric_scores = [float(value) for value in scores.values() if isinstance(value, (int, float))]
    rubric_score = (sum(numeric_scores) / len(numeric_scores) * 10.0) if numeric_scores else 0.0
    issue_count = len(_as_list(review.get("issues")))
    score = 0.0
    score += _bool_score(review.get("pass"), yes=30.0, no=-12.0)
    score += rubric_score
    score -= issue_count * 6.0
    return round(score, 2)


def choose_best_segment_revision(
    *,
    original_text: str,
    original_review: dict[str, Any],
    candidate_text: str,
    candidate_review: dict[str, Any],
    min_delta: float = 0.0,
) -> dict[str, Any]:
    original_score = score_segment_review(original_review)
    candidate_score = score_segment_review(candidate_review)
    original_chars = len("".join(str(original_text or "").split()))
    candidate_chars = len("".join(str(candidate_text or "").split()))
    if original_chars >= 360 and candidate_chars < original_chars * 0.65:
        candidate_score -= 50.0
    accepted = candidate_score >= original_score + min_delta
    report = {
        "reviewer": "segment_revision_safety/v1",
        "accepted": accepted,
        "selected": "candidate" if accepted else "original",
        "reason": "candidate_not_worse" if accepted else "candidate_worse_than_original",
        "original_score": original_score,
        "candidate_score": round(candidate_score, 2),
        "min_delta": min_delta,
        "original_chars": original_chars,
        "candidate_chars": candidate_chars,
    }
    if accepted:
        return {
            "accepted": True,
            "selected": "candidate",
            "text": candidate_text,
            "review": candidate_review,
            "report": report,
        }
    return {
        "accepted": False,
        "selected": "original",
        "text": original_text,
        "review": original_review,
        "report": report,
    }
