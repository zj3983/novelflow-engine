"""Manual, non-mutating commercial-shuangwen chapter review."""

from __future__ import annotations

from hashlib import sha256
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from packages.story_core.model_gateway import ModelRequest, ModelResponse, RuntimeModelGateway


SKILL_ID = "commercial-shuangwen"
CHECK_KEYS = (
    "goal",
    "pressure",
    "information_gap",
    "counterattack",
    "payoff",
    "reaction",
    "ending_hook",
    "cliches",
)
PAYOFF_FIELDS = ("need", "pressure", "hidden_advantage", "concrete_reward")
SOP_FIELDS = ("opening_carry", "mid_feedback", "turn", "ending_hook")
MAX_SUMMARY_CHARS = 1000
MAX_FINDING_CHARS = 2000
MAX_FINDINGS_PER_CHECK = 20
MAX_ISSUES = 50

SummaryText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_SUMMARY_CHARS,
    ),
]
FindingText = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_FINDING_CHARS,
    ),
]


class ShuangwenReviewPreconditionError(ValueError):
    """Local chapter state does not permit a reviewer call."""


class ShuangwenReviewError(RuntimeError):
    """Stable public error raised by the manual review boundary."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ShuangwenChecks(_StrictModel):
    goal: list[FindingText] = Field(max_length=MAX_FINDINGS_PER_CHECK)
    pressure: list[FindingText] = Field(max_length=MAX_FINDINGS_PER_CHECK)
    information_gap: list[FindingText] = Field(max_length=MAX_FINDINGS_PER_CHECK)
    counterattack: list[FindingText] = Field(max_length=MAX_FINDINGS_PER_CHECK)
    payoff: list[FindingText] = Field(max_length=MAX_FINDINGS_PER_CHECK)
    reaction: list[FindingText] = Field(max_length=MAX_FINDINGS_PER_CHECK)
    ending_hook: list[FindingText] = Field(max_length=MAX_FINDINGS_PER_CHECK)
    cliches: list[FindingText] = Field(max_length=MAX_FINDINGS_PER_CHECK)


class ShuangwenReviewResult(_StrictModel):
    schema_version: Literal["skill-review/v1"]
    skill_id: Literal["commercial-shuangwen"]
    executed: Literal[True]
    status: Literal["passed", "warning"]
    summary: SummaryText
    checks: ShuangwenChecks
    issues: list[FindingText] = Field(max_length=MAX_ISSUES)

    @model_validator(mode="after")
    def validate_status_matches_findings(self) -> "ShuangwenReviewResult":
        has_findings = bool(self.issues) or any(
            getattr(self.checks, key) for key in CHECK_KEYS
        )
        if self.status == "passed" and has_findings:
            raise ValueError("passed_review_has_findings")
        if self.status == "warning" and not has_findings:
            raise ValueError("warning_review_has_no_findings")
        return self


def _text_fields(value: Any, fields: tuple[str, ...]) -> dict[str, str]:
    source = value if isinstance(value, Mapping) else {}
    return {field: str(source.get(field) or "").strip() for field in fields}


def _reviewer_context(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    compact: list[dict[str, Any]] = []
    for raw_pack in value:
        if not isinstance(raw_pack, Mapping) or str(raw_pack.get("skill_id") or "") != SKILL_ID:
            continue
        modules: list[dict[str, str]] = []
        for raw_module in raw_pack.get("modules") or []:
            if not isinstance(raw_module, Mapping):
                continue
            module_id = str(raw_module.get("module_id") or "").strip()
            instructions = str(raw_module.get("instructions") or "").strip()
            if module_id and instructions:
                modules.append({"module_id": module_id, "instructions": instructions})
        compact.append({"skill_id": SKILL_ID, "modules": modules})
    return compact


def build_shuangwen_review_prompt(
    *,
    body: str,
    chapter_plan: Mapping[str, Any] | None,
    skill_context: Any,
) -> str:
    """Serialize the allowlisted review input and no project-wide state."""

    plan = chapter_plan if isinstance(chapter_plan, Mapping) else {}
    payload = {
        "task": "Review the confirmed chapter without rewriting it. Return JSON only.",
        "input": {
            "confirmed_chapter_body": body,
            "payoff_contract": _text_fields(plan.get("payoff_contract"), PAYOFF_FIELDS),
            "chapter_sop": _text_fields(plan.get("chapter_sop"), SOP_FIELDS),
            "skill_context": _reviewer_context(skill_context),
        },
        "required_schema": {
            "schema_version": "skill-review/v1",
            "skill_id": SKILL_ID,
            "executed": True,
            "status": "passed only with zero findings; otherwise warning",
            "summary": f"non-empty string, max {MAX_SUMMARY_CHARS} characters",
            "checks": {
                key: (
                    f"array of at most {MAX_FINDINGS_PER_CHECK} non-empty finding strings; "
                    f"max {MAX_FINDING_CHARS} characters each"
                )
                for key in CHECK_KEYS
            },
            "issues": (
                f"array of at most {MAX_ISSUES} non-empty actionable issue strings; "
                f"max {MAX_FINDING_CHARS} characters each"
            ),
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _payload_from_response(response: Any) -> tuple[dict[str, Any], dict[str, str]]:
    metadata = {"runtime": "", "model": "", "trace_id": ""}
    if isinstance(response, ModelResponse):
        if not response.ok:
            raise ShuangwenReviewError("shuangwen_review_runtime_failed")
        raw = response.text
        metadata = {
            "runtime": str(response.provider or ""),
            "model": str(response.model or ""),
            "trace_id": str(response.request_id or ""),
        }
    elif isinstance(response, Mapping):
        raw = response
    else:
        raw = getattr(response, "text", "")
    if isinstance(raw, Mapping):
        return dict(raw), metadata
    try:
        parsed = json.loads(str(raw or ""))
    except (TypeError, ValueError) as exc:
        raise ShuangwenReviewError("shuangwen_review_invalid_response") from exc
    if not isinstance(parsed, dict):
        raise ShuangwenReviewError("shuangwen_review_invalid_response")
    return parsed, metadata


def review_shuangwen_chapter(
    *,
    body: str,
    chapter_plan: Mapping[str, Any] | None,
    skill_context: Any,
    model_gateway: Any | None = None,
) -> dict[str, Any]:
    """Run one manual review call and return a validated report."""

    if not isinstance(body, str) or not body.strip():
        raise ShuangwenReviewPreconditionError(
            "shuangwen_review_confirmed_body_required"
        )
    before_hash = sha256(body.encode("utf-8")).hexdigest()
    prompt = build_shuangwen_review_prompt(
        body=body,
        chapter_plan=chapter_plan,
        skill_context=skill_context,
    )
    gateway = model_gateway or RuntimeModelGateway()
    request = ModelRequest(
        prompt=prompt,
        system_prompt="You are a Chinese commercial webnovel reviewer. Never rewrite the chapter. Return strict JSON only.",
        provider="",
        model="",
        operation="commercial-shuangwen-review",
        temperature=0.0,
        json_mode=True,
        metadata={"skill_id": SKILL_ID, "purpose": "reviewer"},
    )
    try:
        response = gateway.complete_stage("consistency", request)
    except Exception as exc:
        raise ShuangwenReviewError("shuangwen_review_runtime_failed") from exc
    if sha256(body.encode("utf-8")).hexdigest() != before_hash:
        raise ShuangwenReviewError("shuangwen_review_body_mutated")

    payload, metadata = _payload_from_response(response)
    try:
        result = ShuangwenReviewResult.model_validate(payload).model_dump(mode="json")
    except ValidationError as exc:
        raise ShuangwenReviewError("shuangwen_review_invalid_response") from exc
    result.update({key: value for key, value in metadata.items() if value})
    return result


__all__ = [
    "CHECK_KEYS",
    "MAX_FINDING_CHARS",
    "MAX_FINDINGS_PER_CHECK",
    "MAX_ISSUES",
    "MAX_SUMMARY_CHARS",
    "SKILL_ID",
    "ShuangwenReviewError",
    "ShuangwenReviewPreconditionError",
    "ShuangwenReviewResult",
    "build_shuangwen_review_prompt",
    "review_shuangwen_chapter",
]
