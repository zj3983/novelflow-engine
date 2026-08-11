import pytest

from packages.story_core.model_gateway import ModelResponse

from packages.story_core.review.contracts import ReviewResult
from packages.story_core.review.service import ReviewService


SHUANGWEN_CHECKS = {
    "goal": [],
    "pressure": ["限时压力在拒绝函中形成了实际阻碍。"],
    "information_gap": [],
    "counterattack": [],
    "payoff": ["订单是否到账仍未落地。"],
    "reaction": [],
    "ending_hook": [],
    "cliches": [],
}


class _ShuangwenGateway:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = []

    def complete_stage(self, stage, request):
        import json

        self.calls.append((stage, request))
        return ModelResponse(
            ok=True,
            text=json.dumps(self.payload, ensure_ascii=False),
            provider="test",
            model="test",
            operation=request.operation,
            request_id="trace-review-7",
        )


def _shuangwen_payload(**overrides):
    payload = {
        "schema_version": "skill-review/v1",
        "skill_id": "commercial-shuangwen",
        "executed": True,
        "status": "warning",
        "summary": "反击成立，但具体回报尚未兑现。",
        "checks": SHUANGWEN_CHECKS,
        "issues": ["补充财务核款或订单到账这一可观察结果。"],
    }
    payload.update(overrides)
    return payload


def test_shuangwen_review_returns_strict_schema_and_runtime_metadata():
    from packages.story_core.shuangwen_review import review_shuangwen_chapter

    gateway = _ShuangwenGateway(_shuangwen_payload())
    body = "林修亮出备案回执，负责人当场撤回拒绝函。"

    result = review_shuangwen_chapter(
        body=body,
        chapter_plan={
            "payoff_contract": {
                "need": "林修必须拿到替换镜芯",
                "pressure": "买家只给他一夜验货",
                "hidden_advantage": "他能恢复物品上次完整运行状态",
                "concrete_reward": "修复订单并获得父亲失踪线索",
            },
            "chapter_sop": {
                "opening_carry": "接上铜镜第一次亮起",
                "mid_feedback": "镜面恢复一段旧影像",
                "turn": "影像中的人认出了林修",
                "ending_hook": "镜中人叫出林修父亲的名字",
            },
        },
        skill_context=[{"skill_id": "commercial-shuangwen", "modules": []}],
        model_gateway=gateway,
    )

    assert result == {
        **_shuangwen_payload(),
        "runtime": "test",
        "model": "test",
        "trace_id": "trace-review-7",
    }
    assert gateway.calls[0][0] == "consistency"
    assert len(gateway.calls) == 1
    assert "body" not in result


def test_shuangwen_review_prompt_contains_only_confirmed_body_contracts_and_reviewer_skill_context():
    from hashlib import sha256

    from packages.story_core.shuangwen_review import review_shuangwen_chapter

    gateway = _ShuangwenGateway(_shuangwen_payload(status="passed", summary="检查通过", issues=[]))
    body = "林修用旧回执证明验收记录被人篡改。"
    before_hash = sha256(body.encode("utf-8")).hexdigest()
    chapter_plan = {
        "payoff_contract": {
            "need": "拿到替换镜芯",
            "pressure": "一夜内完成验货",
            "hidden_advantage": "恢复旧运行状态",
            "concrete_reward": "获得订单与线索",
        },
        "chapter_sop": {
            "opening_carry": "铜镜亮起",
            "mid_feedback": "旧影像恢复",
            "turn": "镜中人认出林修",
            "ending_hook": "父亲的名字出现",
        },
        "unrelated_project_dump": "FORBIDDEN_PROJECT_SENTINEL",
    }
    skill_context = [
        {
            "skill_id": "commercial-shuangwen",
            "modules": [
                {"module_id": "review-checklist", "instructions": "REVIEWER_CONTEXT_SENTINEL"}
            ],
        }
    ]

    review_shuangwen_chapter(
        body=body,
        chapter_plan=chapter_plan,
        skill_context=skill_context,
        model_gateway=gateway,
    )

    prompt = gateway.calls[0][1].prompt
    assert body in prompt
    assert "拿到替换镜芯" in prompt
    assert "父亲的名字出现" in prompt
    assert "REVIEWER_CONTEXT_SENTINEL" in prompt
    assert "FORBIDDEN_PROJECT_SENTINEL" not in prompt
    assert sha256(body.encode("utf-8")).hexdigest() == before_hash


@pytest.mark.parametrize(
    "payload",
    [
        _shuangwen_payload(executed=False),
        _shuangwen_payload(status="blocked"),
        _shuangwen_payload(checks={"goal": []}),
        _shuangwen_payload(unexpected="not allowed"),
    ],
)
def test_shuangwen_review_rejects_non_contract_runtime_results(payload):
    from packages.story_core.shuangwen_review import ShuangwenReviewError, review_shuangwen_chapter

    with pytest.raises(ShuangwenReviewError, match="shuangwen_review_invalid_response"):
        review_shuangwen_chapter(
            body="确认正文",
            chapter_plan={"payoff_contract": {}, "chapter_sop": {}},
            skill_context=[],
            model_gateway=_ShuangwenGateway(payload),
        )


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
