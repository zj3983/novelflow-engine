from dataclasses import replace

from packages.story_core.pipeline.quality_stage import QualityStageCallbacks, run_quality_stage


def _review(body: str) -> dict:
    if body == "draft":
        return {"pass": False, "issues": ["hard"]}
    if body == "worse":
        return {"pass": False, "issues": ["hard", "new"]}
    return {"pass": True, "issues": []}


def _callbacks(*, revise=None, compress=None) -> QualityStageCallbacks:
    return QualityStageCallbacks(
        review=_review,
        build_gate=lambda review: {
            "needs_revision": bool(review["issues"]),
            "has_hard_errors": bool(review["issues"]),
            "categories": {},
        },
        should_revise=lambda gate: bool(gate["needs_revision"]),
        revise=revise or (lambda _body, _review, _round: ("draft", "")),
        postprocess=lambda body: body.strip(),
        choose_revision=lambda original_body, original_quality, candidate_body, candidate_quality: {
            "body": candidate_body if len(candidate_quality["issues"]) < len(original_quality["issues"]) else original_body,
            "quality": candidate_quality if len(candidate_quality["issues"]) < len(original_quality["issues"]) else original_quality,
            "accepted": len(candidate_quality["issues"]) < len(original_quality["issues"]),
            "report": {"accepted": len(candidate_quality["issues"]) < len(original_quality["issues"])},
        },
        should_compress=lambda body: len(body) > 10,
        compress=compress or (lambda _body, _round, _feedback: ("short", "")),
        compression_quality_not_worse=lambda before, candidate, _before_body, _candidate_body: len(candidate["issues"]) <= len(before["issues"]),
        compression_action=lambda _before, candidate: "retry" if candidate == "short" else "accept",
        compressed_acceptable=lambda before, candidate: len(candidate) < len(before) and len(candidate) >= 5,
        retry_acceptable=lambda before, candidate: len(candidate) < len(before) and len(candidate) >= 5,
        hard_length_acceptable=lambda body: 5 <= len(body) <= 10,
        char_count=len,
    )


def test_quality_stage_runs_at_most_one_full_revision_and_keeps_accepted_candidate():
    """The bounded controller keeps the accepted candidate and records the
    safety report when the rewrite was accepted."""
    calls = []

    def revise(body, review, round_number):
        calls.append((body, review, round_number))
        return "fixed", ""

    result = run_quality_stage(body="draft", callbacks=_callbacks(revise=revise))

    assert result.body == "fixed"
    assert result.writing_review["pass"] is True
    assert result.revision_rounds == 1
    assert result.revision_safety_report == {"accepted": True}
    assert calls == [("draft", {"pass": False, "issues": ["hard"]}, 1)]


def test_quality_stage_runs_at_most_one_compression_attempt():
    """Compression never retries under the new bounded flow."""
    calls = []

    def compress(body, round_number, feedback):
        calls.append((body, round_number, feedback))
        return ("normal", "")

    result = run_quality_stage(body="long original", callbacks=_callbacks(compress=compress))

    assert calls == [("long original", 1, None)]
    # The bounded flow runs a single compression; the candidate replaces the body
    # when the action returns "accept".
    assert result.body == "normal"


def test_quality_stage_does_not_retry_compression_when_candidate_expands():
    """The bounded flow does NOT issue a second compression attempt even if
    the first candidate expanded past the original body."""
    calls = []

    def compress(body, round_number, feedback):
        calls.append((body, round_number, feedback))
        return ("expanded beyond original", "")

    callbacks = replace(
        _callbacks(compress=compress),
        compression_action=lambda before, candidate: (
            "reject" if len(candidate) >= len(before) else "accept"
        ),
    )

    result = run_quality_stage(body="long original", callbacks=callbacks)

    assert result.body == "long original"
    assert len(calls) == 1


def test_quality_stage_rejects_compression_that_makes_review_worse():
    """When compression quality is preserved and the action is not accept, the
    original body is kept. No retry is attempted under the new bounded flow."""
    callbacks = _callbacks(compress=lambda _body, _round, _feedback: ("worse", ""))

    result = run_quality_stage(body="long original", callbacks=callbacks)

    assert result.body == "long original"
    assert result.writing_review["pass"] is True
