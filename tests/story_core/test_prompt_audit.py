from hashlib import sha256

import pytest
from pydantic import ValidationError

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
    assert [issue.code for issue in result.suggestions] == ["repeated_template_variable"]
    assert [issue.evidence for issue in result.must_fix] == [
        "{{chapter_direction}}",
        "{{unexpected}}",
    ]
    assert result.suggestions[0].evidence == "{{output_section}}"
    assert result.summary.characters == len("{{output_section}}\n{{unexpected}}\n{{output_section}}")
    assert result.summary.lines == 3
    assert result.summary.estimated_redundant_characters == 0
    assert result.summary.estimated_reduction_percent == 0.0
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
    assert result.suggestions[0].estimated_reduction_characters == 1


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

    assert result.passed_checks == ["模板变量完整且没有未知变量"]


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
