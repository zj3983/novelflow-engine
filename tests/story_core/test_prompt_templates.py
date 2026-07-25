import pytest

from packages.story_core.prompt_templates import (
    PromptTemplate,
    get_default_prompt_template,
    load_global_prompt_templates,
    prompt_template_scope,
    render_prompt_template,
    save_global_prompt_template,
    template_variable_occurrences,
)
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator


def test_template_variable_occurrences_preserves_duplicates_and_order():
    assert template_variable_occurrences("{{chapter}} {{chapter}} {{output}}") == (
        "chapter",
        "chapter",
        "output",
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


def test_global_template_override_round_trips_atomically(tmp_path):
    storage_path = tmp_path / "templates.json"
    original = get_default_prompt_template("writer")
    changed = original.content.replace("{{chapter_direction}}", "方向：{{chapter_direction}}")

    saved = save_global_prompt_template("writer", changed, storage_path=storage_path)
    loaded = {item.key: item for item in load_global_prompt_templates(storage_path=storage_path)}

    assert saved.content == changed
    assert loaded["writer"].content == changed
    assert loaded["writer"].version == saved.version


def test_project_override_changes_only_that_project(tmp_path):
    first = FileProjectStore(tmp_path / "first")
    second = FileProjectStore(tmp_path / "second")
    content = get_default_prompt_template("writer").content.replace(
        "{{chapter_direction}}",
        "项目方向：{{chapter_direction}}",
    )

    first.set_prompt_template_override("writer", content)

    assert first.effective_prompt_template("writer")["source"] == "project_override"
    assert first.effective_prompt_template("writer")["content"] == content
    assert second.effective_prompt_template("writer")["source"] == "global_default"


def test_delete_project_override_restores_default(tmp_path):
    store = FileProjectStore(tmp_path)
    content = get_default_prompt_template("writer").content.replace(
        "{{chapter_direction}}",
        "项目方向：{{chapter_direction}}",
    )
    store.set_prompt_template_override("writer", content)

    restored = store.delete_prompt_template_override("writer")

    assert restored["source"] == "global_default"
    assert restored["content"] == get_default_prompt_template("writer").content


def test_project_override_rejects_missing_required_variable(tmp_path):
    store = FileProjectStore(tmp_path)

    with pytest.raises(ValueError, match="missing_required_template_variable:chapter_direction"):
        store.set_prompt_template_override("writer", "只写正文：{{output_section}}")


def test_orchestrator_uses_template_from_current_project_scope():
    base = get_default_prompt_template("writer")
    project_template = PromptTemplate(
        key=base.key,
        title=base.title,
        stage=base.stage,
        content=f"项目模板生效\n{base.content}",
        required_variables=base.required_variables,
    )
    story = StoryState(story_id="s-template-scope", outline="外门守炉", genre="玄幻", style="白描")

    with prompt_template_scope(lambda key: project_template if key == "writer" else get_default_prompt_template(key)):
        prompt = StoryOrchestrator()._body_prompt(story, 1, {})

    assert prompt.startswith("项目模板生效")
