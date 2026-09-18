from packages.story_core.agents.consistency.agent import (
    ConsistencyFinding,
    FocusedConsistencyAgent,
)
from packages.story_core.agents.contracts import DirectorArtifact
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


def test_critical_adapter_normalizes_structured_hard_classification():
    message = "后台术语泄漏"
    result = _adapt_critical_report(
        {
            "pass": False,
            "issues": [{"message": message}],
            "hard_issues": [{"message": message}],
            "soft_issues": [],
        }
    )

    assert result.status == "blocked"
    assert len(result.findings) == 1
    assert result.findings[0].message == message
    assert result.findings[0].blocking is True
    assert result.findings[0].category == "hard"


def test_critical_adapter_fails_closed_for_unclassified_layered_issue():
    result = _adapt_critical_report(
        {
            "pass": False,
            "issues": ["段首主语单调", "漏分类关键问题"],
            "hard_issues": [],
            "soft_issues": ["段首主语单调"],
        }
    )

    assert result.status == "blocked"
    by_message = {finding.message: finding for finding in result.findings}
    assert by_message["段首主语单调"].blocking is False
    assert by_message["段首主语单调"].category == "prose"
    assert by_message["漏分类关键问题"].blocking is True
    assert by_message["漏分类关键问题"].category == "hard"


def test_genre_failure_is_advisory_by_default():
    result = _adapt_genre_report(
        {
            "pass": False,
            "issues": ["本章爽点兑现偏弱"],
            "revision_plan": ["可以加强可见回报，但不要为了过审强改剧情"],
        }
    )

    assert result.status == "warning"
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


def test_legacy_game_progression_conflict_remains_blocking():
    result = _adapt_genre_report(
        {
            "pass": False,
            "issues": [
                "Lv.1越级：第二章仍是新手村阶段，不能接取或开始转职任务、职业试炼。",
                "第一章节奏过载：登录、金手指、刷怪和追查被压进同一章。",
            ],
            "revision_plan": ["退回新手村阶段。", "拆分开篇节奏。"],
        }
    )

    assert result.status == "blocked"
    assert [finding.blocking for finding in result.findings] == [True, False]
    assert [finding.category for finding in result.findings] == ["hard", "prose"]


def test_numeric_genre_subreview_remains_blocking():
    issue = "净到账计算错误：兑换总额10.00元扣除手续费1.00元后，应到账9.00元。"
    result = _adapt_genre_report(
        {
            "pass": False,
            "issues": [issue, "本章爽点兑现偏弱"],
            "revision_plan": ["重算到账金额。", "增强可见回报。"],
            "active_genre_reviews": {
                "numeric_consistency_review": {
                    "pass": False,
                    "issues": [issue],
                    "revision_plan": ["重算到账金额。"],
                }
            },
        }
    )

    assert result.status == "blocked"
    assert [finding.blocking for finding in result.findings] == [True, False]


def _director_artifact() -> DirectorArtifact:
    return DirectorArtifact(
        chapter_number=7,
        chapter_goal="推进本章事件",
        opening_state="承接上一章",
        scene_beats=[],
        ending_state="形成新的已发生状态",
    )


def test_consistency_finding_never_blocks_style_even_if_caller_marks_it_blocking():
    finding = ConsistencyFinding(
        code="style.simile_stacking",
        message="显式比喻密度偏高",
        source="deterministic",
        blocking=True,
    )

    assert finding.blocking is False


def test_consistency_finding_never_blocks_unavailable_even_if_outer_fallback_marks_it_blocking():
    finding = ConsistencyFinding(
        code="consistency.unavailable",
        message="事实审稿 pipeline 异常；本次未完成核验。",
        source="consistency",
        blocking=True,
    )

    assert finding.blocking is False


def test_consistency_runtime_failure_is_unverified_not_blocking():
    class RaisingRuntime:
        def complete(self, request):
            raise RuntimeError("temporary outage")

    findings = FocusedConsistencyAgent(RaisingRuntime()).review(
        body="正文仍然可以继续进入后续流程。",
        director_artifact=_director_artifact(),
        active_facts=[],
    )

    assert len(findings) == 1
    assert findings[0].code == "consistency.unavailable"
    assert findings[0].blocking is False


def test_consistency_invalid_response_is_unverified_not_blocking():
    class InvalidRuntime:
        def complete(self, request):
            return {"unexpected": "shape"}

    findings = FocusedConsistencyAgent(InvalidRuntime()).review(
        body="正文仍然可以继续进入后续流程。",
        director_artifact=_director_artifact(),
        active_facts=[],
    )

    assert len(findings) == 1
    assert findings[0].code == "consistency.invalid_response"
    assert findings[0].blocking is False


def test_actual_canon_conflict_remains_blocking():
    class ConflictRuntime:
        def complete(self, request):
            return {
                "issues": [
                    {
                        "code": "canon.location_conflict",
                        "message": "角色已离开现场却无返场过程直接出现。",
                        "source": "canon",
                        "blocking": True,
                    }
                ]
            }

    findings = FocusedConsistencyAgent(ConflictRuntime()).review(
        body="角色突然再次出现在现场。",
        director_artifact=_director_artifact(),
        active_facts=[{"subject": "角色", "field": "location", "value": "已离开"}],
    )

    assert len(findings) == 1
    assert findings[0].code == "canon.location_conflict"
    assert findings[0].blocking is True
