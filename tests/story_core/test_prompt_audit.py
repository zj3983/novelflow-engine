from hashlib import sha256
from time import perf_counter

import pytest
from pydantic import ValidationError

import packages.story_core.prompt_audit as prompt_audit
from packages.story_core.prompt_audit import (
    LONG_PROMPT_WARNING,
    PromptAuditIssue,
    PromptAuditSection,
    audit_prompt,
)


def test_template_audit_reports_missing_unknown_and_repeated_variables_in_stable_order():
    result = audit_prompt(
        mode="template",
        content="{{output_section}}\n{{unexpected}}\n{{output_section}}",
        template_key="writer",
        required_variables=("output_section", "chapter_direction"),
    )

    assert [issue.code for issue in result.must_fix] == [
        "missing_required_variable",
        "unknown_template_variable",
    ]
    assert [issue.code for issue in result.suggestions] == [
        "duplicate_line",
        "repeated_template_variable",
    ]
    assert [issue.evidence for issue in result.must_fix] == [
        "{{chapter_direction}}",
        "{{unexpected}}",
    ]
    assert [issue.title for issue in result.must_fix] == [
        "缺少必需变量",
        "未知模板变量",
    ]
    assert [issue.suggestion for issue in result.must_fix] == [
        "在模板中补充必需占位符。",
        "移除该占位符，或将其声明为必需变量。",
    ]
    repeated_variable = next(
        issue for issue in result.suggestions if issue.code == "repeated_template_variable"
    )
    assert repeated_variable.title == "模板变量重复"
    assert repeated_variable.suggestion == "确认重复出现的占位符是否为有意设置。"
    assert repeated_variable.evidence == "{{output_section}}"
    assert result.summary.characters == len("{{output_section}}\n{{unexpected}}\n{{output_section}}")
    assert result.summary.lines == 3
    assert result.summary.estimated_redundant_characters == len("{{output_section}}")
    assert result.summary.estimated_reduction_percent == round(
        len("{{output_section}}") * 100 / len("{{output_section}}\n{{unexpected}}\n{{output_section}}"),
        1,
    )
    assert result.summary.sections == []
    assert "模板变量完整且没有未知变量" not in result.passed_checks


def test_same_input_produces_identical_dump():
    arguments = {
        "mode": "template",
        "content": "{{chapter}}\n\ntext",
        "template_key": "writer",
        "required_variables": ["chapter"],
    }

    assert audit_prompt(**arguments).model_dump() == audit_prompt(**arguments).model_dump()


def test_long_prompt_produces_oversized_suggestion():
    result = audit_prompt(mode="final_call", content="x" * (LONG_PROMPT_WARNING + 1))

    assert [issue.code for issue in result.suggestions] == ["oversized_prompt"]
    issue = result.suggestions[0]
    assert issue.title == "提示词整体过长"
    assert issue.evidence == "40001 个字符"
    assert issue.location == "提示词"
    assert issue.suggestion == "将提示词缩减至 40000 个字符以内。"
    assert issue.estimated_reduction_characters == 1


def test_default_variable_location_is_localized_but_template_key_is_preserved():
    default_location = audit_prompt(
        mode="template",
        content="{{unexpected}}",
    ).must_fix[0].location
    keyed_location = audit_prompt(
        mode="template",
        content="{{unexpected}}",
        template_key="writer",
    ).must_fix[0].location

    assert default_location == "提示词:{{unexpected}}"
    assert keyed_location == "writer:{{unexpected}}"


def test_warning_and_hard_limits_are_exclusive():
    warning_boundary = audit_prompt(mode="final_call", content="x" * LONG_PROMPT_WARNING)
    hard_boundary = audit_prompt(mode="final_call", content="x" * 200_000)

    assert all(issue.code != "oversized_prompt" for issue in warning_boundary.suggestions)
    assert hard_boundary.summary.characters == 200_000


def test_summary_dump_uses_contract_field_names_only():
    summary = audit_prompt(mode="final_call", content="text").model_dump()["summary"]

    assert summary == {
        "characters": 4,
        "lines": 1,
        "estimated_redundant_characters": 0,
        "estimated_reduction_percent": 0.0,
        "sections": [],
    }
    assert "duplicate_characters" not in summary
    assert "duplicate_percentage" not in summary


def test_section_contract_uses_percent_instead_of_lines():
    section = PromptAuditSection(title="Instructions", characters=20, percent=50.0)

    assert section.model_dump() == {
        "title": "Instructions",
        "characters": 20,
        "percent": 50.0,
    }


def test_issues_sort_by_reduction_then_code_and_location():
    prefix = "{{z_unknown}} {{a_unknown}} {{output}} {{output}}"
    content = prefix + "x" * (LONG_PROMPT_WARNING + 1 - len(prefix))

    result = audit_prompt(
        mode="template",
        content=content,
        template_key="writer",
        required_variables=("output",),
    )

    assert [issue.code for issue in result.suggestions] == [
        "oversized_prompt",
        "repeated_template_variable",
    ]
    assert [issue.evidence for issue in result.must_fix] == [
        "{{a_unknown}}",
        "{{z_unknown}}",
    ]


@pytest.mark.parametrize(
    ("arguments", "error_code"),
    [
        ({"mode": "template", "content": " \n\t"}, "content_required"),
        ({"mode": "other", "content": "text"}, "invalid_prompt_audit_mode"),
        ({"mode": "final_call", "content": "x" * 200_001}, "prompt_audit_content_too_long"),
    ],
)
def test_invalid_audit_inputs_raise_stable_error_codes(arguments, error_code):
    with pytest.raises(ValueError, match=f"^{error_code}$"):
        audit_prompt(**arguments)


def test_hash_uses_original_utf8_content_and_final_call_skips_template_checks():
    content = " 正文 {{unexpected}} \n"

    result = audit_prompt(
        mode="final_call",
        content=content,
        required_variables=("chapter_direction",),
    )

    assert result.content_sha256 == sha256(content.encode("utf-8")).hexdigest()
    assert result.must_fix == []
    assert all(issue.code != "unknown_template_variable" for issue in result.suggestions)
    assert "模板变量完整且没有未知变量" not in result.passed_checks


def test_clean_template_records_variable_check_as_passed():
    result = audit_prompt(
        mode="template",
        content="{{chapter_direction}}",
        required_variables=("chapter_direction",),
    )

    assert result.passed_checks == [
        "模板变量完整且没有未知变量",
        "没有发现明确重复行",
        "没有发现过大区块",
        "没有发现明确冲突",
    ]


def test_prompt_audit_models_are_strict():
    with pytest.raises(ValidationError):
        PromptAuditIssue(
            code="example",
            title="Example",
            evidence="evidence",
            location="prompt",
            suggestion="suggestion",
            estimated_reduction_characters=0,
            extra_field=True,
        )


@pytest.mark.parametrize(
    "arguments",
    [
        {"title": "Instructions", "characters": "20", "percent": 50.0},
        {"title": "Instructions", "characters": 20, "percent": "50.0"},
    ],
)
def test_prompt_audit_section_rejects_string_numbers(arguments):
    with pytest.raises(ValidationError):
        PromptAuditSection(**arguments)


@pytest.mark.parametrize(
    ("line", "normalized"),
    [
        ("  -  对话必须   符合人物关系。 ", "对话必须 符合人物关系。"),
        ("2) 对话必须符合人物关系。", "对话必须符合人物关系。"),
        ("三、 对话必须符合人物关系。", "对话必须符合人物关系。"),
        ("十. 对话必须符合人物关系。", "对话必须符合人物关系。"),
    ],
)
def test_normalize_audit_line_removes_only_deterministic_list_syntax(line, normalized):
    assert prompt_audit.normalize_audit_line(line) == normalized


def test_duplicate_lines_report_only_later_exact_normalized_occurrences():
    content = "\n".join(
        [
            "1. 对话必须始终符合人物关系。",
            "2. 对话必须始终符合人物关系。",
            "对话要符合当前场面的关系。",
        ]
    )

    result = audit_prompt(mode="final_call", content=content)

    duplicates = [issue for issue in result.suggestions if issue.code == "duplicate_line"]
    assert len(duplicates) == 1
    assert duplicates[0].location == "第2行"
    assert duplicates[0].evidence == "2. 对话必须始终符合人物关系。"
    assert duplicates[0].title == "发现明确重复行"
    assert duplicates[0].suggestion == "删除或合并这条重复内容。"
    assert duplicates[0].estimated_reduction_characters == len(
        "2. 对话必须始终符合人物关系。"
    )


def test_duplicate_line_length_boundary_uses_normalized_characters():
    eleven_characters = "一二三四五六七八九十。"
    twelve_characters = "一二三四五六七八九十甲。"
    content = "\n".join(
        [
            eleven_characters,
            eleven_characters,
            twelve_characters,
            twelve_characters,
        ]
    )

    result = audit_prompt(mode="final_call", content=content)

    duplicates = [issue for issue in result.suggestions if issue.code == "duplicate_line"]
    assert [issue.location for issue in duplicates] == ["第4行"]
    assert duplicates[0].evidence == twelve_characters


def test_short_lines_and_markdown_headings_are_not_duplicate_lines():
    content = "短标题\n短标题\n# 这是一个足够长的Markdown标题\n# 这是一个足够长的Markdown标题"

    result = audit_prompt(mode="template", content=content)

    assert all(issue.code != "duplicate_line" for issue in result.suggestions)
    assert "没有发现明确重复行" in result.passed_checks


def test_markdown_sections_report_names_character_counts_and_percentages():
    content = "序言\n# 角色\n甲乙\n## 规则\n丙丁丁"

    result = audit_prompt(mode="final_call", content=content)

    assert [section.model_dump() for section in result.summary.sections] == [
        {"title": "开头", "characters": len("序言\n"), "percent": 15.0},
        {"title": "角色", "characters": len("甲乙\n"), "percent": 15.0},
        {"title": "规则", "characters": len("丙丁丁"), "percent": 15.0},
    ]


def test_explicit_empty_markdown_section_is_reported_but_empty_opening_is_not():
    result = audit_prompt(mode="final_call", content="# 空区块\n## 下一节\n正文")

    assert [section.model_dump() for section in result.summary.sections] == [
        {"title": "空区块", "characters": 0, "percent": 0.0},
        {"title": "下一节", "characters": 2, "percent": 13.3},
    ]


def test_whitespace_only_opening_is_omitted_but_explicit_empty_section_remains():
    result = audit_prompt(
        mode="final_call",
        content=" \n\t\n# 空区块\n## 下一节\n正文",
    )

    assert [section.title for section in result.summary.sections] == ["空区块", "下一节"]
    assert result.summary.sections[0].characters == 0


def test_oversized_section_is_only_a_suggestion_and_boundaries_do_not_warn():
    over_characters = audit_prompt(mode="final_call", content="# 大节\n" + "x" * 12_001)
    over_percent = audit_prompt(
        mode="final_call",
        content="# 大节\n" + "x" * 46 + "\n# 小节\n" + "y" * 46,
    )
    at_character_boundary = audit_prompt(
        mode="final_call",
        content=(
            "# 大节\n"
            + "x" * 11_999
            + "\n# 小节一\n"
            + "y" * 10_000
            + "\n# 小节二\n"
            + "z" * 10_000
        ),
    )
    at_percent_boundary = audit_prompt(
        mode="final_call",
        content="# A\n" + "x" * 44 + "\n# B\n" + "y" * 23 + "\n# C\n" + "z" * 19,
    )

    assert "oversized_section" in [issue.code for issue in over_characters.suggestions]
    assert "oversized_section" in [issue.code for issue in over_percent.suggestions]
    assert all(issue.code != "oversized_section" for issue in over_characters.must_fix)
    assert all(
        issue.code != "oversized_section"
        for result in (at_character_boundary, at_percent_boundary)
        for issue in result.suggestions
    )


def test_three_mechanical_conflicts_are_must_fix_items():
    content = (
        "只输出小说正文，同时最后输出分析报告。\n"
        "采用第一人称，并且采用第三人称。\n"
        "正文控制在1000-1200字，另要求2000至2500字。"
    )

    result = audit_prompt(mode="template", content=content)

    assert [issue.code for issue in result.must_fix] == [
        "conflicting_output_format",
        "conflicting_viewpoint",
        "conflicting_word_count",
    ]
    assert all(issue.title and issue.suggestion for issue in result.must_fix)
    assert "没有发现明确冲突" not in result.passed_checks


@pytest.mark.parametrize(
    "content",
    [
        "只输出正文，不要输出分析报告",
        "只输出正文，禁止输出报告",
        "只输出正文，无需输出解释",
        "只输出正文，不需要输出分析",
        "只输出正文，不要最后输出分析报告",
        "只输出正文，不能输出分析",
        "只输出正文，请勿输出报告",
        "只输出正文，不得输出解释",
    ],
)
def test_explicitly_negated_extra_output_does_not_conflict(content):
    result = audit_prompt(mode="final_call", content=content)

    assert all(issue.code != "conflicting_output_format" for issue in result.must_fix)


def test_positive_extra_output_still_conflicts():
    result = audit_prompt(mode="final_call", content="只输出正文，最后输出分析报告")

    assert [issue.code for issue in result.must_fix] == ["conflicting_output_format"]


@pytest.mark.parametrize(
    "content",
    [
        "不要使用第一人称，采用第三人称",
        "第一人称或第三人称均可",
    ],
)
def test_viewpoint_alternatives_and_explicit_negation_do_not_conflict(content):
    result = audit_prompt(mode="final_call", content=content)

    assert all(issue.code != "conflicting_viewpoint" for issue in result.must_fix)


def test_simultaneous_viewpoint_requirements_still_conflict():
    result = audit_prompt(
        mode="final_call",
        content="全文使用第一人称，同时使用第三人称",
    )

    assert [issue.code for issue in result.must_fix] == ["conflicting_viewpoint"]


def test_overlapping_word_ranges_do_not_conflict():
    content = "字数为1000到2000字，也可1500—2500字。"

    result = audit_prompt(mode="final_call", content=content)

    assert result.must_fix == []
    assert "没有发现明确冲突" in result.passed_checks


def test_reversed_disjoint_word_ranges_are_normalized_before_comparison():
    result = audit_prompt(
        mode="final_call",
        content="正文要求1200~1000字，另一处要求2500至2000字。",
    )

    assert [issue.code for issue in result.must_fix] == ["conflicting_word_count"]


def test_draft_and_final_word_ranges_are_not_compared_across_stages():
    result = audit_prompt(
        mode="final_call",
        content="初稿1000-1200字，终稿2000-2500字。",
    )

    assert all(issue.code != "conflicting_word_count" for issue in result.must_fix)


def test_word_count_ranges_with_stage_labels_inside_segments_do_not_conflict():
    result = audit_prompt(
        mode="final_call",
        content="初稿控制在1000-1200字，终稿控制在2000-2500字。",
    )

    assert all(issue.code != "conflicting_word_count" for issue in result.must_fix)


def test_word_count_ranges_presented_as_explicit_alternatives_do_not_conflict():
    result = audit_prompt(
        mode="final_call",
        content="字数可在1000-1200字或2000-2500字中任选。",
    )

    assert all(issue.code != "conflicting_word_count" for issue in result.must_fix)


def test_many_overlapping_word_ranges_complete_in_linear_time():
    unit = "1000-2000字,"
    content = (unit * (199_000 // len(unit)))[:199_000]

    started_at = perf_counter()
    result = audit_prompt(mode="final_call", content=content)
    elapsed = perf_counter() - started_at

    assert all(issue.code != "conflicting_word_count" for issue in result.must_fix)
    assert elapsed < 2.0


def test_redundant_summary_and_issue_sorting_are_stable():
    repeated = "这是一条足够长并且会被重复的明确规则。"
    content = "\n".join([repeated, repeated, repeated])

    first = audit_prompt(mode="final_call", content=content)
    second = audit_prompt(mode="final_call", content=content)

    duplicates = [issue for issue in first.suggestions if issue.code == "duplicate_line"]
    expected_redundant = len(repeated) * 2
    assert [issue.location for issue in duplicates] == ["第2行", "第3行"]
    assert first.summary.estimated_redundant_characters == expected_redundant
    assert first.summary.estimated_reduction_percent == round(
        expected_redundant * 100 / len(content), 1
    )
    assert first.model_dump() == second.model_dump()
