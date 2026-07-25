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
_OUTPUT_NEGATION_PREFIX_PATTERN = r"(?:不要|禁止|无需|不需要|不能|请勿|不得)"
_OUTPUT_REQUIREMENT_TARGET_PATTERN = (
    r"(?:最后\s*输出\s*分析报告|输出\s*(?:分析报告|分析|报告|解释))"
)
_NEGATED_OUTPUT_REQUIREMENT_RE = re.compile(
    rf"{_OUTPUT_NEGATION_PREFIX_PATTERN}\s*{_OUTPUT_REQUIREMENT_TARGET_PATTERN}"
)
_POSITIVE_OUTPUT_REQUIREMENT_RE = re.compile(
    r"(?:最后输出分析报告|输出分析|输出报告|输出解释)"
)
_NEGATED_VIEWPOINT_RE = re.compile(
    rf"{_OUTPUT_NEGATION_PREFIX_PATTERN}\s*(?:使用|采用)?\s*(?:第一人称|第三人称)"
)
_VIEWPOINT_ALTERNATIVE_RE = re.compile(
    r"(?:第一人称\s*或\s*第三人称|第三人称\s*或\s*第一人称)(?:\s*(?:均可|任选))?"
    r"|(?:第一人称\s*(?:、|和)\s*第三人称|第三人称\s*(?:、|和)\s*第一人称)"
    r"\s*(?:均可|任选)"
)
_WORD_COUNT_SEGMENT_RE = re.compile(r"[^，,。.；;\r\n]+")
_WORD_COUNT_STAGE_RE = re.compile(r"初稿|终稿")


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


def _word_count_stage(segment: str) -> str | None:
    match = _WORD_COUNT_STAGE_RE.search(segment)
    return match.group(0) if match else None


def _word_count_ranges_in_segment(
    segment: str,
) -> tuple[list[tuple[int, int, str, str | None]], bool]:
    matches = list(_WORD_COUNT_RANGE_RE.finditer(segment))
    stage = _word_count_stage(segment)
    ranges = [
        (
            min(int(match.group(1)), int(match.group(2))),
            max(int(match.group(1)), int(match.group(2))),
            match.group(0),
            stage,
        )
        for match in matches
    ]
    qualifier_present = "任选" in segment or "均可" in segment
    or_after_first_range = bool(matches) and segment.find("或", matches[0].end()) >= 0
    return ranges, len(matches) >= 2 and qualifier_present and or_after_first_range


def _first_disjoint_word_count_pair(
    content: str,
) -> tuple[tuple[int, int, str, str | None], tuple[int, int, str, str | None]] | None:
    min_high_by_stage: dict[str | None, tuple[int, int, str, str | None]] = {}
    max_low_by_stage: dict[str | None, tuple[int, int, str, str | None]] = {}

    def compare_with_previous(
        current: tuple[int, int, str, str | None],
    ) -> tuple[tuple[int, int, str, str | None], tuple[int, int, str, str | None]] | None:
        stage = current[3]
        compatible_stages = (
            (None, "初稿")
            if stage == "初稿"
            else (None, "终稿")
            if stage == "终稿"
            else (None, "初稿", "终稿")
        )
        previous_min_high = min(
            (
                min_high_by_stage[compatible_stage]
                for compatible_stage in compatible_stages
                if compatible_stage in min_high_by_stage
            ),
            key=lambda item: item[1],
            default=None,
        )
        if previous_min_high is not None and current[0] > previous_min_high[1]:
            return previous_min_high, current

        previous_max_low = max(
            (
                max_low_by_stage[compatible_stage]
                for compatible_stage in compatible_stages
                if compatible_stage in max_low_by_stage
            ),
            key=lambda item: item[0],
            default=None,
        )
        if previous_max_low is not None and current[1] < previous_max_low[0]:
            return previous_max_low, current

        return None

    def update_extrema(current: tuple[int, int, str, str | None]) -> None:
        stage = current[3]
        if stage not in min_high_by_stage or current[1] < min_high_by_stage[stage][1]:
            min_high_by_stage[stage] = current
        if stage not in max_low_by_stage or current[0] > max_low_by_stage[stage][0]:
            max_low_by_stage[stage] = current

    for segment_match in _WORD_COUNT_SEGMENT_RE.finditer(content):
        ranges, are_alternatives = _word_count_ranges_in_segment(segment_match.group(0))
        if are_alternatives:
            continue
        for current in ranges:
            disjoint_pair = compare_with_previous(current)
            if disjoint_pair is not None:
                return disjoint_pair
            update_extrema(current)

    return None


def _conflict_issues(content: str) -> list[PromptAuditIssue]:
    issues: list[PromptAuditIssue] = []
    output_body_only = re.search(r"只输出(?:小说)?正文", content)
    without_negated_output = _NEGATED_OUTPUT_REQUIREMENT_RE.sub("", content)
    positive_extra_output = _POSITIVE_OUTPUT_REQUIREMENT_RE.search(
        without_negated_output
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

    viewpoint_content = _NEGATED_VIEWPOINT_RE.sub("", content)
    has_viewpoint_alternative = _VIEWPOINT_ALTERNATIVE_RE.search(viewpoint_content)
    if (
        "第一人称" in viewpoint_content
        and "第三人称" in viewpoint_content
        and not has_viewpoint_alternative
    ):
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

    disjoint_pair = _first_disjoint_word_count_pair(content)
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
