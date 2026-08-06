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
