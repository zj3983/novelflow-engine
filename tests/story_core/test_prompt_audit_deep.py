import json
from hashlib import sha256

import pytest

import packages.story_core.prompt_audit as prompt_audit
import packages.story_core.prompt_audit_deep as prompt_audit_deep
from packages.story_core.prompt_audit import (
    PromptAuditIssue,
    PromptAuditResult,
    PromptAuditSummary,
    audit_prompt,
)
from packages.story_core.prompt_audit_deep import (
    DEEP_CONTENT_LIMIT,
    DeepPromptAuditor,
)
from packages.story_core.runtime_config import StageRuntimeSettings


CONTENT = "请保持角色动机一致，并让结尾形成悬念。"


def runtime(*, provider="openai", api_key="secret", model="planner-model") -> StageRuntimeSettings:
    return StageRuntimeSettings(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url="https://llm.example/v1",
        codex_command="codex-test",
        temperature=0.25,
    )


def local_result(content=CONTENT) -> PromptAuditResult:
    return audit_prompt(mode="final_call", content=content)


def response(issues, *, fenced=False):
    content = json.dumps({"issues": issues}, ensure_ascii=False)
    if fenced:
        content = f"```json\n{content}\n```"
    return {"choices": [{"message": {"content": content}}]}


def issue(
    *,
    severity="suggestion",
    code="semantic_duplicate",
    title="语义重复",
    evidence="角色动机一致",
    location="第1段",
    suggestion="合并重复要求。",
    estimated_reduction_characters=8,
):
    return {
        "severity": severity,
        "code": code,
        "title": title,
        "evidence": evidence,
        "location": location,
        "suggestion": suggestion,
        "estimated_reduction_characters": estimated_reduction_characters,
    }


def test_openai_runtime_calls_model_once_with_expected_payload_and_merges_runtime():
    calls = []
    stages = []
    clock_values = iter([10.0, 10.1236])

    def fake_post(base_url, path, payload, api_key, **kwargs):
        calls.append((base_url, path, payload, api_key, kwargs))
        return response([issue()])

    auditor = DeepPromptAuditor(
        post_json=fake_post,
        runtime_resolver=lambda stage: stages.append(stage) or runtime(),
        clock=lambda: next(clock_values),
    )
    result = auditor.analyze(content=CONTENT, local_result=local_result())

    assert stages == ["planner"]
    assert len(calls) == 1
    base_url, path, payload, api_key, kwargs = calls[0]
    assert (base_url, path, api_key) == (
        "https://llm.example/v1",
        "/chat/completions",
        "secret",
    )
    assert kwargs == {"provider": "openai", "codex_command": "codex-test"}
    assert payload["model"] == "planner-model"
    assert payload["temperature"] == 0.25
    assert payload["response_format"] == {"type": "json_object"}
    assert [message["role"] for message in payload["messages"]] == ["system", "user"]
    system = payload["messages"][0]["content"]
    assert all(
        phrase in system
        for phrase in (
            "语义重复",
            "语义冲突",
            "不得重新统计字符",
            "不得改写提示词",
            "不得输出长报告",
            "只返回JSON",
        )
    )
    user_content = payload["messages"][1]["content"]
    assert "请保持角色动机一致" in user_content
    assert "\\u8bf7" not in user_content
    assert json.loads(user_content) == {
        "content": CONTENT,
        "local_result": local_result().model_dump(),
    }
    assert [item.code for item in result.suggestions] == ["semantic_duplicate"]
    assert result.suggestions[0].suggestion == "合并重复要求。"
    assert result.runtime.model_dump() == {
        "provider": "openai",
        "model": "planner-model",
        "elapsed_seconds": 0.124,
        "prompt_characters": len(CONTENT),
    }


def test_codexcli_without_api_key_is_available():
    calls = []
    auditor = DeepPromptAuditor(
        runtime_resolver=lambda stage: runtime(provider="codexcli", api_key=""),
        post_json=lambda *args, **kwargs: calls.append((args, kwargs)) or response([]),
        clock=lambda: 3.0,
    )

    result = auditor.analyze(content=CONTENT, local_result=local_result())

    assert result.runtime.provider == "codexcli"
    assert len(calls) == 1
    assert calls[0][1] == {"provider": "codexcli", "codex_command": "codex-test"}


@pytest.mark.parametrize(
    ("content_factory", "local_factory", "expected_error", "expected_resolver_calls"),
    [
        (lambda: " \n\t", lambda content: local_result(), "content_required", 0),
        (
            lambda: "x" * (DEEP_CONTENT_LIMIT + 1),
            lambda content: PromptAuditResult(
                mode="final_call",
                content_sha256=sha256(content.encode("utf-8")).hexdigest(),
                summary=PromptAuditSummary(characters=len(content), lines=1),
            ),
            "prompt_audit_deep_content_too_long",
            0,
        ),
        (
            lambda: CONTENT,
            lambda content: local_result("different"),
            "prompt_audit_local_result_mismatch",
            0,
        ),
        (
            lambda: CONTENT,
            lambda content: local_result(content),
            "runtime_unavailable",
            1,
        ),
    ],
)
def test_preflight_errors_never_call_model(
    content_factory, local_factory, expected_error, expected_resolver_calls
):
    posts = []
    resolver_calls = []
    content = content_factory()
    auditor = DeepPromptAuditor(
        runtime_resolver=lambda stage: resolver_calls.append(stage)
        or runtime(provider="openai", api_key=""),
        post_json=lambda *args, **kwargs: posts.append((args, kwargs)),
    )

    with pytest.raises(ValueError, match=f"^{expected_error}$"):
        auditor.analyze(content=content, local_result=local_factory(content))

    assert posts == []
    assert len(resolver_calls) == expected_resolver_calls


def test_post_exception_maps_to_stable_error():
    def failing_post(*args, **kwargs):
        raise OSError("network detail must not leak")

    with pytest.raises(ValueError, match="^prompt_audit_deep_failed$"):
        DeepPromptAuditor(post_json=failing_post, runtime_resolver=lambda stage: runtime()).analyze(
            content=CONTENT, local_result=local_result()
        )


@pytest.mark.parametrize(
    "model_response",
    [
        {"choices": [{"message": {"content": "not json"}}]},
        {"choices": [{"message": 1}]},
        response([issue(severity="warning")]),
        response([issue(code="other")]),
        response([issue()] * 21),
    ],
)
def test_invalid_provider_outputs_map_to_stable_error(model_response):
    with pytest.raises(ValueError, match="^prompt_audit_deep_invalid_response$"):
        DeepPromptAuditor(
            post_json=lambda *args, **kwargs: model_response,
            runtime_resolver=lambda stage: runtime(),
        ).analyze(content=CONTENT, local_result=local_result())


def test_merge_deduplicates_sorts_cleans_passed_checks_and_does_not_mutate_local_result():
    local = local_result()
    local.suggestions.append(
        PromptAuditIssue(
            code="semantic_duplicate",
            title="existing",
            evidence="same evidence",
            location="same location",
            suggestion="existing suggestion",
            estimated_reduction_characters=3,
        )
    )
    before = local.model_dump()
    findings = [
        issue(
            severity="suggestion",
            code="semantic_duplicate",
            evidence="same evidence",
            location="same location",
            estimated_reduction_characters=99,
        ),
        issue(
            severity="suggestion",
            code="semantic_duplicate",
            title="larger",
            evidence="other duplicate",
            location="末段",
            estimated_reduction_characters=20,
        ),
        issue(
            severity="must_fix",
            code="semantic_conflict",
            title="conflict b",
            evidence="conflict b",
            location="第2段",
            estimated_reduction_characters=0,
        ),
        issue(
            severity="must_fix",
            code="semantic_conflict",
            title="conflict a",
            evidence="conflict a",
            location="第1段",
            estimated_reduction_characters=0,
        ),
    ]
    auditor = DeepPromptAuditor(
        post_json=lambda *args, **kwargs: response(findings),
        runtime_resolver=lambda stage: runtime(),
        clock=lambda: 1.0,
    )

    result = auditor.analyze(content=CONTENT, local_result=local)

    assert local.model_dump() == before
    assert result.summary == local.summary
    assert result.mode == local.mode
    assert result.content_sha256 == local.content_sha256
    assert [item.title for item in result.suggestions] == ["larger", "existing"]
    assert [item.title for item in result.must_fix] == ["conflict a", "conflict b"]
    assert "没有发现明确重复行" not in result.passed_checks
    assert "没有发现明确冲突" not in result.passed_checks
    assert result.summary.estimated_redundant_characters == local.summary.estimated_redundant_characters


def test_semantic_issue_severity_is_forced_by_code():
    findings = [
        issue(
            severity="suggestion",
            code="semantic_conflict",
            title="conflict",
            evidence="conflicting requirements",
        ),
        issue(
            severity="must_fix",
            code="semantic_duplicate",
            title="duplicate",
            evidence="duplicate requirement",
        ),
    ]

    result = DeepPromptAuditor(
        post_json=lambda *args, **kwargs: response(findings),
        runtime_resolver=lambda stage: runtime(),
        clock=lambda: 1.0,
    ).analyze(content=CONTENT, local_result=local_result())

    assert [item.code for item in result.must_fix] == ["semantic_conflict"]
    assert [item.code for item in result.suggestions] == ["semantic_duplicate"]


def test_deep_merge_preserves_global_issue_limit_and_reports_truncation():
    lines = [f"第{index:03d}条规则要求人物行为始终符合当前动机。" for index in range(90)]
    content = "\n".join([*lines, *lines])
    findings = [
        issue(
            evidence=f"semantic duplicate {index}",
            location=f"第{index}段",
        )
        for index in range(20)
    ]

    result = DeepPromptAuditor(
        post_json=lambda *args, **kwargs: response(findings),
        runtime_resolver=lambda stage: runtime(),
        clock=lambda: 1.0,
    ).analyze(content=content, local_result=local_result(content))

    issues = [*result.must_fix, *result.suggestions]
    assert len(issues) == 100
    assert sum(item.code == "issues_truncated" for item in issues) == 1


def test_markdown_fenced_json_uses_shared_parser():
    result = DeepPromptAuditor(
        post_json=lambda *args, **kwargs: response([issue()], fenced=True),
        runtime_resolver=lambda stage: runtime(),
        clock=lambda: 0.0,
    ).analyze(content=CONTENT, local_result=local_result())

    assert [item.code for item in result.suggestions] == ["semantic_duplicate"]


def test_elapsed_time_is_never_negative():
    values = iter([5.0, 4.0])
    result = DeepPromptAuditor(
        post_json=lambda *args, **kwargs: response([]),
        runtime_resolver=lambda stage: runtime(),
        clock=lambda: next(values),
    ).analyze(content=CONTENT, local_result=local_result())

    assert result.runtime.elapsed_seconds == 0.0


def test_mutated_invalid_local_result_is_rejected_before_runtime_or_model():
    local = local_result()
    local.summary.characters = -1
    resolver_calls = []
    post_calls = []
    auditor = DeepPromptAuditor(
        runtime_resolver=lambda stage: resolver_calls.append(stage) or runtime(),
        post_json=lambda *args, **kwargs: post_calls.append((args, kwargs)),
    )

    with pytest.raises(ValueError, match="^prompt_audit_local_result_invalid$"):
        auditor.analyze(content=CONTENT, local_result=local)

    assert resolver_calls == []
    assert post_calls == []


def test_oversized_complete_user_payload_is_rejected_without_model_call():
    local = local_result()
    local.passed_checks = ["x" * prompt_audit_deep.DEEP_PAYLOAD_LIMIT]
    resolver_calls = []
    post_calls = []
    auditor = DeepPromptAuditor(
        runtime_resolver=lambda stage: resolver_calls.append(stage) or runtime(),
        post_json=lambda *args, **kwargs: post_calls.append((args, kwargs)),
    )

    with pytest.raises(ValueError, match="^prompt_audit_deep_payload_too_long$"):
        auditor.analyze(content=CONTENT, local_result=local)

    assert resolver_calls == []
    assert post_calls == []


def test_runtime_model_name_longer_than_500_characters_is_preserved():
    model = "m" * 501
    result = DeepPromptAuditor(
        runtime_resolver=lambda stage: runtime(model=model),
        post_json=lambda *args, **kwargs: response([]),
        clock=lambda: 1.0,
    ).analyze(content=CONTENT, local_result=local_result())

    assert result.runtime.model == model


def test_final_result_validation_error_maps_to_invalid_response():
    with pytest.raises(ValueError, match="^prompt_audit_deep_invalid_response$"):
        DeepPromptAuditor(
            runtime_resolver=lambda stage: runtime(model=""),
            post_json=lambda *args, **kwargs: response([]),
            clock=lambda: 1.0,
        ).analyze(content=CONTENT, local_result=local_result())


def test_prompt_audit_exposes_shared_issue_sort_key():
    low = PromptAuditIssue(
        code="z",
        title="low",
        evidence="low",
        location="later",
        suggestion="low",
        estimated_reduction_characters=1,
    )
    high = low.model_copy(
        update={"code": "a", "title": "high", "estimated_reduction_characters": 2}
    )

    assert sorted([low, high], key=prompt_audit.prompt_audit_issue_sort_key) == [high, low]
