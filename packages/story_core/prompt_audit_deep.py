"""Optional model-assisted semantic diagnostics for prompt audits."""

from __future__ import annotations

from hashlib import sha256
import json
from time import perf_counter
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.story_core.agent_base import parse_json_message_content
from packages.story_core.http_retry import post_json_with_retry
from packages.story_core.prompt_audit import (
    PromptAuditIssue,
    PromptAuditResult,
    prompt_audit_issue_sort_key,
)
from packages.story_core.runtime_config import (
    StageRuntimeSettings,
    resolve_stage_runtime,
)


DEEP_CONTENT_LIMIT = 80_000
DEEP_PAYLOAD_LIMIT = 120_000

_NO_EXPLICIT_DUPLICATE = "没有发现明确重复行"
_NO_EXPLICIT_CONFLICT = "没有发现明确冲突"

_SYSTEM_PROMPT = (
    "你是提示词深度语义诊断器。只补充语义重复和语义冲突两类发现；"
    "不得重新统计字符、变量或区块，不得改写提示词，不得输出长报告，只返回JSON。"
    "返回对象只能包含issues数组；每项必须包含severity、code、title、evidence、location、"
    "suggestion、estimated_reduction_characters。severity只能是must_fix或suggestion，"
    "code只能是semantic_duplicate或semantic_conflict，最多返回20项。"
)


class _StrictDeepAuditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SemanticIssue(_StrictDeepAuditModel):
    severity: Literal["must_fix", "suggestion"]
    code: Literal["semantic_duplicate", "semantic_conflict"]
    title: str = Field(min_length=1, max_length=120)
    evidence: str = Field(min_length=1, max_length=2_000)
    location: str = Field(min_length=1, max_length=500)
    suggestion: str = Field(min_length=1, max_length=1_000)
    estimated_reduction_characters: int = Field(ge=0, le=DEEP_CONTENT_LIMIT)


class _SemanticResponse(_StrictDeepAuditModel):
    issues: list[SemanticIssue] = Field(max_length=20)


class DeepAuditRuntime(_StrictDeepAuditModel):
    provider: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1)
    elapsed_seconds: float = Field(ge=0)
    prompt_characters: int = Field(ge=0, le=DEEP_CONTENT_LIMIT)


class DeepPromptAuditResult(PromptAuditResult):
    runtime: DeepAuditRuntime


class DeepPromptAuditor:
    def __init__(
        self,
        *,
        post_json: Callable[..., dict[str, Any]] = post_json_with_retry,
        runtime_resolver: Callable[[str], StageRuntimeSettings] = resolve_stage_runtime,
        clock: Callable[[], float] = perf_counter,
    ) -> None:
        self._post_json = post_json
        self._runtime_resolver = runtime_resolver
        self._clock = clock

    def analyze(
        self,
        *,
        content: str,
        local_result: PromptAuditResult,
    ) -> DeepPromptAuditResult:
        try:
            validated_local_result = PromptAuditResult.model_validate(
                local_result.model_dump()
            )
        except ValidationError as exc:
            raise ValueError("prompt_audit_local_result_invalid") from exc
        if not content.strip():
            raise ValueError("content_required")
        if len(content) > DEEP_CONTENT_LIMIT:
            raise ValueError("prompt_audit_deep_content_too_long")
        content_hash = sha256(content.encode("utf-8")).hexdigest()
        if content_hash != validated_local_result.content_sha256:
            raise ValueError("prompt_audit_local_result_mismatch")

        user_content = json.dumps(
            {
                "content": content,
                "local_result": validated_local_result.model_dump(),
            },
            ensure_ascii=False,
        )
        if len(user_content) > DEEP_PAYLOAD_LIMIT:
            raise ValueError("prompt_audit_deep_payload_too_long")

        try:
            runtime = self._runtime_resolver("planner")
        except Exception as exc:
            raise ValueError("prompt_audit_deep_failed") from exc
        if runtime.provider != "codexcli" and not runtime.api_key:
            raise ValueError("runtime_unavailable")

        payload = {
            "model": runtime.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": runtime.temperature,
        }
        started_at = self._clock()
        try:
            response = self._post_json(
                runtime.base_url,
                "/chat/completions",
                payload,
                runtime.api_key,
                provider=runtime.provider,
                codex_command=runtime.codex_command,
            )
        except Exception as exc:
            raise ValueError("prompt_audit_deep_failed") from exc
        finished_at = self._clock()

        try:
            parsed = parse_json_message_content(response)
        except Exception as exc:
            raise ValueError("prompt_audit_deep_invalid_response") from exc
        if parsed is None:
            raise ValueError("prompt_audit_deep_invalid_response")
        try:
            semantic_response = _SemanticResponse.model_validate(parsed)
        except ValidationError as exc:
            raise ValueError("prompt_audit_deep_invalid_response") from exc

        merged = validated_local_result.model_copy(deep=True)
        seen = {
            (item.code, item.evidence, item.location)
            for item in [*merged.must_fix, *merged.suggestions]
        }
        for finding in semantic_response.issues:
            identity = (finding.code, finding.evidence, finding.location)
            if identity in seen:
                continue
            seen.add(identity)
            converted = PromptAuditIssue(
                code=finding.code,
                title=finding.title,
                evidence=finding.evidence,
                location=finding.location,
                suggestion=finding.suggestion,
                estimated_reduction_characters=finding.estimated_reduction_characters,
            )
            if finding.severity == "must_fix":
                merged.must_fix.append(converted)
            else:
                merged.suggestions.append(converted)

        merged.must_fix.sort(key=prompt_audit_issue_sort_key)
        merged.suggestions.sort(key=prompt_audit_issue_sort_key)
        merged_codes = {item.code for item in [*merged.must_fix, *merged.suggestions]}
        if "semantic_duplicate" in merged_codes:
            merged.passed_checks = [
                check for check in merged.passed_checks if check != _NO_EXPLICIT_DUPLICATE
            ]
        if "semantic_conflict" in merged_codes:
            merged.passed_checks = [
                check for check in merged.passed_checks if check != _NO_EXPLICIT_CONFLICT
            ]

        try:
            return DeepPromptAuditResult.model_validate(
                {
                    **merged.model_dump(),
                    "runtime": {
                        "provider": runtime.provider,
                        "model": runtime.model,
                        "elapsed_seconds": round(max(0.0, finished_at - started_at), 3),
                        "prompt_characters": len(content),
                    },
                }
            )
        except ValidationError as exc:
            raise ValueError("prompt_audit_deep_invalid_response") from exc
