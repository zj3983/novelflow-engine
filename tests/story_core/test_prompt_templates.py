import pytest

from packages.story_core.prompt_templates import (
    PromptTemplate,
    get_default_prompt_template,
    render_prompt_template,
)


def test_writer_template_source_contains_placeholders_not_project_content():
    template = get_default_prompt_template("writer")

    assert "{{output_section}}" in template.content
    assert "{{chapter_direction}}" in template.content
    assert "{{chapter_facts}}" in template.content
    assert "{{character_context}}" in template.content
    assert "{{prose_method}}" in template.content
    assert "夜烬" not in template.content


def test_render_rejects_missing_template_variable():
    template = PromptTemplate(
        key="writer",
        title="正文写作",
        stage="writing",
        content="正文：{{chapter_direction}}",
        required_variables=("chapter_direction",),
    )

    with pytest.raises(ValueError, match="missing_template_variable:chapter_direction"):
        render_prompt_template(template, {})


def test_render_rejects_unknown_template_variable():
    template = PromptTemplate(
        key="writer",
        title="正文写作",
        stage="writing",
        content="正文：{{unexpected}}",
        required_variables=("chapter_direction",),
    )

    with pytest.raises(ValueError, match="unknown_template_variable:unexpected"):
        render_prompt_template(template, {"unexpected": "x"})


def test_render_preserves_chinese_and_inserts_values():
    template = PromptTemplate(
        key="writer",
        title="正文写作",
        stage="writing",
        content="本章方向\n{{chapter_direction}}",
        required_variables=("chapter_direction",),
    )

    assert render_prompt_template(template, {"chapter_direction": "主角进入灰狼坡"}) == "本章方向\n主角进入灰狼坡"
