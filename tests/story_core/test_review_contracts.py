from packages.story_core.review.contracts import ReviewFinding, ReviewResult


def test_review_result_is_blocked_only_by_blocking_findings():
    result = ReviewResult.from_findings(
        [
            ReviewFinding(
                code="continuity.timeline_conflict",
                category="hard",
                blocking=True,
                message="时间线与上一章冲突。",
                suggestion="把事件时间改回次日早晨。",
                source="continuity",
            ),
            ReviewFinding(
                code="style.ai_flavor",
                category="ai_flavor",
                blocking=False,
                message="存在报告腔。",
                suggestion="改成动作和现场结果。",
                source="ai_flavor",
            ),
        ]
    )

    assert result.status == "blocked"
    assert result.has_hard_errors is True
    assert result.needs_revision is True
    assert result.revision_plan == ["把事件时间改回次日早晨。"]
    assert result.to_dict()["issues"][0]["code"] == "continuity.timeline_conflict"


def test_review_result_uses_warning_for_advisory_findings():
    result = ReviewResult.from_findings(
        [
            ReviewFinding(
                code="dialogue.unnatural",
                category="dialogue",
                blocking=False,
                message="对白不够自然。",
                suggestion="只重写对应对话。",
                source="dialogue",
            )
        ]
    )

    assert result.status == "warning"
    assert result.has_hard_errors is False
    assert result.needs_revision is False
    assert result.revision_plan == []
