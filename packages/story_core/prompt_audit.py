"""Deterministic, local-only prompt diagnostics."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.story_core.prompt_templates import (
    template_variable_occurrences,
    template_variables,
)


PromptAuditMode = Literal["template", "final_call"]

LOCAL_CONTENT_LIMIT = 200_000
LONG_PROMPT_WARNING = 40_000


class _StrictPromptAuditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PromptAuditSection(_StrictPromptAuditModel):
    title: str
    characters: int = Field(ge=0)
    lines: int = Field(ge=0)


class PromptAuditSummary(_StrictPromptAuditModel):
    characters: int = Field(ge=0)
    lines: int = Field(ge=0)
    duplicate_characters: int = Field(default=0, ge=0)
    duplicate_percentage: float = Field(default=0.0, ge=0, le=100)
    sections: list[PromptAuditSection] = Field(default_factory=list)


class PromptAuditIssue(_StrictPromptAuditModel):
    code: str
    title: str
    evidence: str
    location: str
    suggestion: str
    estimated_reduction_characters: int = Field(ge=0)


class PromptAuditResult(_StrictPromptAuditModel):
    schema_version: Literal["prompt-audit/v1"] = "prompt-audit/v1"
    mode: PromptAuditMode
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: PromptAuditSummary
    must_fix: list[PromptAuditIssue] = Field(default_factory=list)
    suggestions: list[PromptAuditIssue] = Field(default_factory=list)
    passed_checks: list[str] = Field(default_factory=list)


def _issue_sort_key(issue: PromptAuditIssue) -> tuple[int, str, str]:
    return (-issue.estimated_reduction_characters, issue.code, issue.location)


def _variable_issue(
    *,
    code: str,
    title: str,
    variable: str,
    template_key: str,
    suggestion: str,
) -> PromptAuditIssue:
    placeholder = "{{" + variable + "}}"
    location_prefix = template_key or "prompt"
    return PromptAuditIssue(
        code=code,
        title=title,
        evidence=placeholder,
        location=f"{location_prefix}:{placeholder}",
        suggestion=suggestion,
        estimated_reduction_characters=0,
    )


def audit_prompt(
    *,
    mode: str,
    content: str,
    template_key: str = "",
    required_variables: list[str] | tuple[str, ...] = (),
) -> PromptAuditResult:
    if mode not in ("template", "final_call"):
        raise ValueError("invalid_prompt_audit_mode")
    if not content.strip():
        raise ValueError("content_required")
    if len(content) > LOCAL_CONTENT_LIMIT:
        raise ValueError("prompt_audit_content_too_long")

    must_fix: list[PromptAuditIssue] = []
    suggestions: list[PromptAuditIssue] = []
    passed_checks: list[str] = []

    if mode == "template":
        occurrences = template_variable_occurrences(content)
        variables = template_variables(content)
        variable_set = set(variables)
        required_set = set(required_variables)

        for variable in required_set - variable_set:
            must_fix.append(
                _variable_issue(
                    code="missing_required_variable",
                    title="Missing required variable",
                    variable=variable,
                    template_key=template_key,
                    suggestion="Add the required placeholder to the template.",
                )
            )
        for variable in variable_set - required_set:
            must_fix.append(
                _variable_issue(
                    code="unknown_template_variable",
                    title="Unknown template variable",
                    variable=variable,
                    template_key=template_key,
                    suggestion="Remove the placeholder or declare it as required.",
                )
            )
        for variable, count in Counter(occurrences).items():
            if count > 1:
                suggestions.append(
                    _variable_issue(
                        code="repeated_template_variable",
                        title="Repeated template variable",
                        variable=variable,
                        template_key=template_key,
                        suggestion="Confirm that each repeated placeholder is intentional.",
                    )
                )

        if not must_fix:
            passed_checks.append("模板变量完整且没有未知变量")

    if len(content) > LONG_PROMPT_WARNING:
        suggestions.append(
            PromptAuditIssue(
                code="oversized_prompt",
                title="Prompt exceeds the recommended length",
                evidence=f"{len(content)} characters",
                location=template_key or "prompt",
                suggestion=f"Reduce the prompt to {LONG_PROMPT_WARNING} characters or fewer.",
                estimated_reduction_characters=len(content) - LONG_PROMPT_WARNING,
            )
        )

    return PromptAuditResult(
        mode=mode,
        content_sha256=sha256(content.encode("utf-8")).hexdigest(),
        summary=PromptAuditSummary(
            characters=len(content),
            lines=sum(1 for line in content.splitlines() if line.strip()),
        ),
        must_fix=sorted(must_fix, key=_issue_sort_key),
        suggestions=sorted(suggestions, key=_issue_sort_key),
        passed_checks=passed_checks,
    )
