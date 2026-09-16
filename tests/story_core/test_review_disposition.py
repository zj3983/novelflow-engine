from packages.story_core.review.service import _adapt_critical_report, _adapt_genre_report


def test_critical_adapter_preserves_hard_soft_split():
    report = {
        "pass": False,
        "requires_revision": True,
        "issues": ["后台术语泄漏", "段首主语单调"],
        "hard_issues": ["后台术语泄漏"],
        "soft_issues": ["段首主语单调"],
        "revision_plan": ["删除后台术语", "调整部分段首"],
        "scores": {"diagnostic_terms": 5, "paragraph_opener_variety": 5},
    }

    result = _adapt_critical_report(report)

    assert result.status == "blocked"
    assert [finding.blocking for finding in result.findings] == [True, False]
    assert [finding.category for finding in result.findings] == ["hard", "prose"]
    assert [finding.suggestion for finding in result.findings] == ["删除后台术语", "调整部分段首"]


def test_critical_adapter_keeps_legacy_reports_blocking_without_classification():
    result = _adapt_critical_report(
        {
            "pass": False,
            "issues": ["旧版关键规则失败"],
            "revision_plan": ["修复旧版关键规则"],
        }
    )

    assert result.status == "blocked"
    assert len(result.findings) == 1
    assert result.findings[0].blocking is True


def test_genre_failure_is_advisory_by_default():
    result = _adapt_genre_report(
        {
            "pass": False,
            "issues": ["本章爽点兑现偏弱"],
            "revision_plan": ["可以加强可见回报，但不要为了过审强改剧情"],
        }
    )

    assert result.status == "passed"
    assert len(result.findings) == 1
    assert result.findings[0].blocking is False
    assert result.findings[0].category == "prose"


def test_genre_issue_can_explicitly_opt_into_blocking():
    result = _adapt_genre_report(
        {
            "pass": False,
            "issues": [
                {
                    "message": "类型插件确认了不可接受的事实冲突",
                    "blocking": True,
                    "suggestion": "修复事实冲突",
                }
            ],
        }
    )

    assert result.status == "blocked"
    assert len(result.findings) == 1
    assert result.findings[0].blocking is True
    assert result.findings[0].category == "hard"
