"""Deterministic, local-only prompt diagnostics."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.story_core.prompt_templates import (
    template_variable_occurrences,
    template_variables,
)


PromptAuditMode = Literal["template", "final_call"]

LOCAL_CONTENT_LIMIT = 200_000
LONG_PROMPT_WARNING = 40_000
SECTION_CHARACTER_LIMIT = 12_000
SECTION_PERCENT_LIMIT = 45

_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_LIST_PREFIX_RE = re.compile(
    r"^(?:(?:[-*+])|(?:\d+[.)、])|(?:(?:十|[一二三四五六七八九])[、.]))\s*"
)
_WORD_COUNT_RANGE_RE = re.compile(r"(\d{2,6})\s*[-—~到至]\s*(\d{2,6})\s*字")


class _StrictPromptAuditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PromptAuditSection(_StrictPromptAuditModel):
    title: str
    characters: int = Field(ge=0)
    percent: float = Field(ge=0, le=100)


class PromptAuditSummary(_StrictPromptAuditModel):
    characters: int = Field(ge=0)
    lines: int = Field(ge=0)
    estimated_redundant_characters: int = Field(default=0, ge=0)
    estimated_reduction_percent: float = Field(default=0.0, ge=0, le=100)
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


def normalize_audit_line(line: str) -> str:
    normalized = line.strip()
    normalized = _LIST_PREFIX_RE.sub("", normalized, count=1)
    return " ".join(normalized.split())


def _duplicate_line_issues(content: str) -> list[PromptAuditIssue]:
    seen: set[str] = set()
    issues: list[PromptAuditIssue] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if _MARKDOWN_HEADING_RE.fullmatch(line):
            continue
        normalized = normalize_audit_line(line)
        if not normalized or len(normalized) < 12:
            continue
        if normalized in seen:
            evidence = " ".join(line.strip().split())
            issues.append(
                PromptAuditIssue(
                    code="duplicate_line",
                    title="发现明确重复行",
                    evidence=evidence,
                    location=f"第{line_number}行",
                    suggestion="删除或合并这条重复内容。",
                    estimated_reduction_characters=len(line),
                )
            )
        else:
            seen.add(normalized)
    return issues


def _markdown_sections(content: str) -> list[PromptAuditSection]:
    sections: list[PromptAuditSection] = []
    chunks: list[str] = []
    current_title: str | None = None
    found_heading = False

    def append_section(title: str, body: str) -> None:
        characters = len(body)
        sections.append(
            PromptAuditSection(
                title=title,
                characters=characters,
                percent=round(characters * 100 / len(content), 1),
            )
        )

    for raw_line in content.splitlines(keepends=True):
        heading = _MARKDOWN_HEADING_RE.fullmatch(raw_line.rstrip("\r\n"))
        if heading is None:
            chunks.append(raw_line)
            continue

        body = "".join(chunks)
        if current_title is not None:
            append_section(current_title, body)
        elif body.strip():
            append_section("开头", body)
        chunks = []
        current_title = heading.group(1)
        found_heading = True

    if not found_heading:
        return []
    append_section(current_title or "", "".join(chunks))
    return sections


def _oversized_section_issues(
    sections: list[PromptAuditSection], content_length: int
) -> list[PromptAuditIssue]:
    issues: list[PromptAuditIssue] = []
    for section in sections:
        too_many_characters = section.characters > SECTION_CHARACTER_LIMIT
        too_large_a_share = section.characters * 100 > content_length * SECTION_PERCENT_LIMIT
        if not (too_many_characters or too_large_a_share):
            continue
        reduction = max(
            section.characters - SECTION_CHARACTER_LIMIT,
            section.characters - int(content_length * SECTION_PERCENT_LIMIT / 100),
        )
        issues.append(
            PromptAuditIssue(
                code="oversized_section",
                title="Markdown区块过大",
                evidence=f"{section.characters} 个字符，占 {section.percent}%",
                location=section.title,
                suggestion="拆分或精简这个区块，降低单一区块占比。",
                estimated_reduction_characters=max(0, reduction),
            )
        )
    return issues


def _conflict_issues(content: str) -> list[PromptAuditIssue]:
    issues: list[PromptAuditIssue] = []
    output_body_only = re.search(r"只输出(?:小说)?正文", content)
    without_negated_output = re.sub(
        r"(?:不要|禁止|无需|不需要)\s*输出\s*(?:分析报告|分析|报告|解释)",
        "",
        content,
    )
    positive_extra_output = re.search(
        r"(?:最后输出分析报告|输出分析|输出报告|输出解释)",
        without_negated_output,
    )
    if output_body_only and positive_extra_output:
        issues.append(
            PromptAuditIssue(
                code="conflicting_output_format",
                title="输出格式要求冲突",
                evidence=f"{output_body_only.group(0)} / {positive_extra_output.group(0)}",
                location="输出格式",
                suggestion="保留一种明确且一致的输出格式要求。",
                estimated_reduction_characters=0,
            )
        )

    if "第一人称" in content and "第三人称" in content:
        issues.append(
            PromptAuditIssue(
                code="conflicting_viewpoint",
                title="叙事视角要求冲突",
                evidence="第一人称 / 第三人称",
                location="叙事视角",
                suggestion="明确保留第一人称或第三人称中的一种。",
                estimated_reduction_characters=0,
            )
        )

    ranges = [
        (min(int(match.group(1)), int(match.group(2))),
         max(int(match.group(1)), int(match.group(2))),
         match.group(0))
        for match in _WORD_COUNT_RANGE_RE.finditer(content)
    ]
    disjoint_pair = next(
        (
            (left, right)
            for index, left in enumerate(ranges)
            for right in ranges[index + 1 :]
            if left[1] < right[0] or right[1] < left[0]
        ),
        None,
    )
    if disjoint_pair is not None:
        left, right = disjoint_pair
        issues.append(
            PromptAuditIssue(
                code="conflicting_word_count",
                title="字数范围要求冲突",
                evidence=f"{left[2]} / {right[2]}",
                location="字数要求",
                suggestion="合并为一个边界一致的字数范围。",
                estimated_reduction_characters=0,
            )
        )
    return issues


def _variable_issue(
    *,
    code: str,
    title: str,
    variable: str,
    template_key: str,
    suggestion: str,
) -> PromptAuditIssue:
    placeholder = "{{" + variable + "}}"
    location_prefix = template_key or "提示词"
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
                    title="缺少必需变量",
                    variable=variable,
                    template_key=template_key,
                    suggestion="在模板中补充必需占位符。",
                )
            )
        for variable in variable_set - required_set:
            must_fix.append(
                _variable_issue(
                    code="unknown_template_variable",
                    title="未知模板变量",
                    variable=variable,
                    template_key=template_key,
                    suggestion="移除该占位符，或将其声明为必需变量。",
                )
            )
        for variable, count in Counter(occurrences).items():
            if count > 1:
                suggestions.append(
                    _variable_issue(
                        code="repeated_template_variable",
                        title="模板变量重复",
                        variable=variable,
                        template_key=template_key,
                        suggestion="确认重复出现的占位符是否为有意设置。",
                    )
                )

        if not must_fix:
            passed_checks.append("模板变量完整且没有未知变量")

    if len(content) > LONG_PROMPT_WARNING:
        suggestions.append(
            PromptAuditIssue(
                code="oversized_prompt",
                title="提示词整体过长",
                evidence=f"{len(content)} 个字符",
                location=template_key or "提示词",
                suggestion=f"将提示词缩减至 {LONG_PROMPT_WARNING} 个字符以内。",
                estimated_reduction_characters=len(content) - LONG_PROMPT_WARNING,
            )
        )

    duplicate_issues = _duplicate_line_issues(content)
    suggestions.extend(duplicate_issues)
    if not duplicate_issues:
        passed_checks.append("没有发现明确重复行")

    sections = _markdown_sections(content)
    oversized_section_issues = _oversized_section_issues(sections, len(content))
    suggestions.extend(oversized_section_issues)
    if not oversized_section_issues:
        passed_checks.append("没有发现过大区块")

    conflict_issues = _conflict_issues(content)
    must_fix.extend(conflict_issues)
    if not conflict_issues:
        passed_checks.append("没有发现明确冲突")

    redundant_characters = min(
        len(content),
        sum(issue.estimated_reduction_characters for issue in duplicate_issues),
    )

    return PromptAuditResult(
        mode=mode,
        content_sha256=sha256(content.encode("utf-8")).hexdigest(),
        summary=PromptAuditSummary(
            characters=len(content),
            lines=sum(1 for line in content.splitlines() if line.strip()),
            estimated_redundant_characters=redundant_characters,
            estimated_reduction_percent=round(
                redundant_characters * 100 / len(content), 1
            ),
            sections=sections,
        ),
        must_fix=sorted(must_fix, key=_issue_sort_key),
        suggestions=sorted(suggestions, key=_issue_sort_key),
        passed_checks=passed_checks,
    )
