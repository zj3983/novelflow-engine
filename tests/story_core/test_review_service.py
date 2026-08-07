import pytest

from packages.story_core.review.contracts import ReviewResult
from packages.story_core.review.service import ReviewService


class _RecordingService(ReviewService):
    """Test double that records reviewer source names and returns canned results."""

    def __init__(self):
        self.calls: list[str] = []

    def run_hard_gate(self, *, body: str, context: dict) -> ReviewResult:
        self.calls.extend(["continuity", "fragments", "consistency", "critical", "genre"])
        findings = []
        if body.startswith("short"):
            findings.append(
                self._finding(
                    code="length.out_of_range",
                    category="hard",
                    blocking=True,
                    message="章节字数偏少。",
                    suggestion="扩写到目标字数。",
                )
            )
        return ReviewResult.from_findings(findings)

    def run_soft_review(self, *, body: str, context: dict) -> ReviewResult:
        self.calls.extend(
            ["style", "prose_quality", "adversarial_cut", "ai_flavor", "reader_feel", "cold_reader", "plot_spine"]
        )
        return ReviewResult.from_findings(
            [
                self._finding(
                    code="style.advisory",
                    category="ai_flavor",
                    blocking=False,
                    message="存在轻微报告腔。",
                    suggestion="改成动作和现场结果。",
                )
            ]
        )

    @staticmethod
    def _finding(*, code: str, category: str, blocking: bool, message: str, suggestion: str):
        from packages.story_core.review.contracts import ReviewFinding

        return ReviewFinding(
            code=code,
            category=category,
            blocking=blocking,
            message=message,
            suggestion=suggestion,
            source=code.split(".")[0],
        )


@pytest.fixture
def review_service() -> _RecordingService:
    return _RecordingService()


def test_hard_gate_does_not_run_soft_reviewers(review_service):
    result = review_service.run_hard_gate(body="正文", context={})

    assert result.status in {"passed", "blocked"}
    assert review_service.calls == ["continuity", "fragments", "consistency", "critical", "genre"]


def test_soft_review_never_returns_blocking_findings(review_service):
    result = review_service.run_soft_review(body="正文", context={})

    assert review_service.calls == [
        "style",
        "prose_quality",
        "adversarial_cut",
        "ai_flavor",
        "reader_feel",
        "cold_reader",
        "plot_spine",
    ]
    assert all(finding.blocking is False for finding in result.findings)


def test_adapt_report_pairs_revision_plan_with_issues_by_position():
    """The ``_adapt_report`` adapter must pair ``revision_plan[i]`` with
    ``issues[i]`` by position so legacy reviewers can surface concrete
    fix instructions alongside each issue. Items without a paired plan
    keep the issue's own suggestion.
    """
    from packages.story_core.review.service import _adapt_report

    report = {
        "issues": ["时间线冲突", "对白过长", "无配图问题"],
        "revision_plan": ["修复时间线顺序", "缩短对白"],
    }

    result = _adapt_report(report, source="legacy", default_blocking=True)

    suggestions = [finding.suggestion for finding in result.findings]
    assert suggestions == ["修复时间线顺序", "缩短对白", ""]
    # The first two findings get their paired action; the third one had
    # no plan and therefore an empty suggestion.
    assert [finding.message for finding in result.findings] == [
        "时间线冲突",
        "对白过长",
        "无配图问题",
    ]
    # All three stay blocking because the source defaults to True.
    assert all(finding.blocking for finding in result.findings)


def test_adapt_report_keeps_issue_dict_suggestion_when_plan_does_not_override():
    from packages.story_core.review.service import _adapt_report

    report = {
        "issues": [
            {"message": "问题1", "suggestion": "自带建议"},
            "裸字符串问题",
        ],
        "revision_plan": ["覆盖建议"],
    }

    result = _adapt_report(report, source="legacy", default_blocking=False)

    assert [finding.suggestion for finding in result.findings] == ["覆盖建议", ""]
    # The first issue had its own suggestion in the dict, but the
    # paired revision_plan[0] wins. The second issue has no plan so its
    # suggestion stays empty (the dict's suggestion was the implicit "").
    assert result.findings[0].message == "问题1"
    assert result.findings[1].message == "裸字符串问题"
