"""Deterministic, local-only prompt diagnostics."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.story_core.prompt_templates import (
    template_variable_occurrences,
    template_variables,
)


PromptAuditMode = Literal["template", "final_call"]

LOCAL_CONTENT_LIMIT = 200_000
LONG_PROMPT_WARNING = 40_000
SECTION_CHARACTER_LIMIT = 12_000
SECTION_PERCENT_LIMIT = 45
PROMPT_AUDIT_ISSUE_LIMIT = 100
PROMPT_AUDIT_SECTION_LIMIT = 100
PROMPT_AUDIT_SECTION_TITLE_LIMIT = 200
_WORD_COUNT_UPPER_BOUND = 1_000_000

_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_LIST_PREFIX_RE = re.compile(
    r"^(?:(?:[-*+])|(?:\d+[.)、])|(?:(?:十|[一二三四五六七八九])[、.]))\s*"
)
_WORD_COUNT_RE = re.compile(
    r"(?:(\d{2,6})\s*[-—~到至]\s*(\d{2,6})|(\d{2,6}))\s*字"
)
_WORD_COUNT_CONTEXT_RE = re.compile(
    r"(?:全文|全篇|本章|正文|篇幅|目标字数|字数|控制在|限定在|保持在|"
    r"不少于|不低于|至少|不超过|不高于|至多|最多|初稿|终稿)"
    r"(?:\s*(?:字数|篇幅|长度|为|是|要求|需|应|应为|约|大约|可在|"
    r"控制在|限定在|保持在|不少于|不低于|至少|不超过|不高于|至多|最多))*\s*$"
)
_WORD_COUNT_LOWER_BOUND_RE = re.compile(r"(?:不少于|不低于|至少)\s*$")
_WORD_COUNT_UPPER_BOUND_RE = re.compile(r"(?:不超过|不高于|至多|最多)\s*$")
_CHINESE_SENTENCE_END_RE = re.compile(r"([。！？](?:[”’」』》】])?)")
_CHINESE_QUOTE_CHARACTERS = "“”‘’「」『』《》【】"
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
    title: str = Field(max_length=PROMPT_AUDIT_SECTION_TITLE_LIMIT)
    characters: int = Field(ge=0)
    percent: float = Field(ge=0, le=100)


class PromptAuditSummary(_StrictPromptAuditModel):
    characters: int = Field(ge=0)
    lines: int = Field(ge=0)
    estimated_redundant_characters: int = Field(default=0, ge=0)
    estimated_reduction_percent: float = Field(default=0.0, ge=0, le=100)
    sections: list[PromptAuditSection] = Field(
        default_factory=list,
        max_length=PROMPT_AUDIT_SECTION_LIMIT,
    )
    total_sections: int = Field(default=0, ge=0)
    sections_truncated: bool = False


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

    @model_validator(mode="after")
    def validate_global_issue_limit(self) -> "PromptAuditResult":
        if len(self.must_fix) + len(self.suggestions) > PROMPT_AUDIT_ISSUE_LIMIT:
            raise ValueError("prompt_audit_issue_limit_exceeded")
        return self


def prompt_audit_issue_sort_key(issue: PromptAuditIssue) -> tuple[int, str, str]:
    return (-issue.estimated_reduction_characters, issue.code, issue.location)


def limit_prompt_audit_issues(
    must_fix: list[PromptAuditIssue],
    suggestions: list[PromptAuditIssue],
    *,
    total_issues: int | None = None,
) -> tuple[list[PromptAuditIssue], list[PromptAuditIssue]]:
    existing_truncation = any(
        issue.code == "issues_truncated" for issue in [*must_fix, *suggestions]
    )
    must_fix = [issue for issue in must_fix if issue.code != "issues_truncated"]
    suggestions = [issue for issue in suggestions if issue.code != "issues_truncated"]
    known_total = total_issues if total_issues is not None else len(must_fix) + len(suggestions)
    if not existing_truncation and known_total <= PROMPT_AUDIT_ISSUE_LIMIT:
        return (
            sorted(must_fix, key=prompt_audit_issue_sort_key),
            sorted(suggestions, key=prompt_audit_issue_sort_key),
        )

    regular_limit = PROMPT_AUDIT_ISSUE_LIMIT - 1
    limited_must_fix = sorted(must_fix, key=prompt_audit_issue_sort_key)[:regular_limit]
    suggestion_slots = regular_limit - len(limited_must_fix)
    limited_suggestions = sorted(suggestions, key=prompt_audit_issue_sort_key)[
        :suggestion_slots
    ]
    evidence = (
        f"共发现 {known_total} 项，已汇总返回 {PROMPT_AUDIT_ISSUE_LIMIT} 项（含本提示）。"
        if not existing_truncation
        else f"发现的问题超过 {PROMPT_AUDIT_ISSUE_LIMIT} 项，结果已汇总（含本提示）。"
    )
    limited_suggestions.append(
        PromptAuditIssue(
            code="issues_truncated",
            title="审计结果已截断",
            evidence=evidence,
            location="审计结果",
            suggestion="优先处理已返回问题，精简提示词后重新审计。",
            estimated_reduction_characters=0,
        )
    )
    limited_suggestions.sort(key=prompt_audit_issue_sort_key)
    return limited_must_fix, limited_suggestions


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


def _duplicate_sentence_issues(content: str) -> list[PromptAuditIssue]:
    issues: list[PromptAuditIssue] = []
    seen_lines: set[str] = set()
    for line_number, line in enumerate(content.splitlines(), start=1):
        normalized_line = normalize_audit_line(line)
        if not normalized_line or normalized_line in seen_lines:
            continue
        seen_lines.add(normalized_line)
        seen_sentences: set[str] = set()
        sentence_parts = _CHINESE_SENTENCE_END_RE.split(line)
        for index in range(0, len(sentence_parts) - 1, 2):
            raw_sentence = sentence_parts[index] + sentence_parts[index + 1]
            sentence = " ".join(raw_sentence.strip().split())
            chinese_characters = sum("\u4e00" <= char <= "\u9fff" for char in sentence)
            if chinese_characters < 6:
                continue
            normalized_sentence = sentence.strip(_CHINESE_QUOTE_CHARACTERS)
            if normalized_sentence in seen_sentences:
                issues.append(
                    PromptAuditIssue(
                        code="duplicate_sentence",
                        title="发现同一行内重复完整句",
                        evidence=sentence,
                        location=f"第{line_number}行",
                        suggestion="删除或合并这句重复内容。",
                        estimated_reduction_characters=len(sentence),
                    )
                )
            else:
                seen_sentences.add(normalized_sentence)
    return issues


def _markdown_sections(content: str) -> list[PromptAuditSection]:
    sections: list[PromptAuditSection] = []
    chunks: list[str] = []
    current_title: str | None = None
    found_heading = False

    def append_section(title: str, body: str) -> None:
        characters = len(body)
        if len(title) > PROMPT_AUDIT_SECTION_TITLE_LIMIT:
            title = title[: PROMPT_AUDIT_SECTION_TITLE_LIMIT - 3] + "..."
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
    qualifier_suffix: str = "",
) -> tuple[list[tuple[int, int, str, str | None]], bool]:
    matches = list(_WORD_COUNT_RE.finditer(segment))
    stage = _word_count_stage(segment)
    ranges = []
    first_included_match: re.Match[str] | None = None
    previous_included_match: re.Match[str] | None = None
    for match in matches:
        context = segment[max(0, match.start() - 24) : match.start()]
        continues_alternative = (
            previous_included_match is not None
            and "或" in segment[previous_included_match.end() : match.start()]
        )
        if not _WORD_COUNT_CONTEXT_RE.search(context) and not continues_alternative:
            continue
        if match.group(3) is not None:
            value = int(match.group(3))
            if _WORD_COUNT_LOWER_BOUND_RE.search(context):
                low, high = value, _WORD_COUNT_UPPER_BOUND
            elif _WORD_COUNT_UPPER_BOUND_RE.search(context):
                low, high = 0, value
            else:
                low = high = value
        else:
            low = min(int(match.group(1)), int(match.group(2)))
            high = max(int(match.group(1)), int(match.group(2)))
        ranges.append((low, high, match.group(0), stage))
        if first_included_match is None:
            first_included_match = match
        previous_included_match = match
    qualifier_text = segment + qualifier_suffix
    qualifier_present = "任选" in qualifier_text or "均可" in qualifier_text
    or_after_first_range = (
        first_included_match is not None
        and len(ranges) >= 2
        and segment.find("或", first_included_match.end()) >= 0
    )
    return ranges, len(ranges) >= 2 and qualifier_present and or_after_first_range


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
        ranges, are_alternatives = _word_count_ranges_in_segment(
            segment_match.group(0),
            content[segment_match.end() : segment_match.end() + 8],
        )
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

    duplicate_issues = [
        *_duplicate_line_issues(content),
        *_duplicate_sentence_issues(content),
    ]
    suggestions.extend(duplicate_issues)
    if not duplicate_issues:
        passed_checks.append("没有发现明确重复行")

    all_sections = _markdown_sections(content)
    total_sections = len(all_sections)
    sections = all_sections[:PROMPT_AUDIT_SECTION_LIMIT]
    oversized_section_issues = _oversized_section_issues(all_sections, len(content))
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

    limited_must_fix, limited_suggestions = limit_prompt_audit_issues(
        must_fix,
        suggestions,
        total_issues=len(must_fix) + len(suggestions),
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
            total_sections=total_sections,
            sections_truncated=total_sections > len(sections),
        ),
        must_fix=limited_must_fix,
        suggestions=limited_suggestions,
        passed_checks=passed_checks,
    )
