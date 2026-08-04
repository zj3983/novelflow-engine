import json
import re

import pytest

from packages.story_core.prompt_templates import (
    PromptTemplate,
    get_default_prompt_template,
    load_global_prompt_templates,
    prompt_template_scope,
    render_prompt_template,
    save_global_prompt_template,
    template_variable_occurrences,
    template_variables,
)
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator


def test_game_director_prompt_reads_current_ledger_without_requesting_ledger_updates():
    template = get_default_prompt_template("director")

    assert "不生成章节摘要、既成事实或账本更新" in template.content
    assert "ledger_updates" not in template.content
    assert "以当前连续性账本为准" in template.content
    assert "numeric_plan" in template.content
    assert "经验" in template.content
    assert "净到账" in template.content


def test_template_variable_occurrences_preserves_duplicates_and_order():
    assert template_variable_occurrences("{{chapter}} {{chapter}} {{output}}") == (
        "chapter",
        "chapter",
        "output",
    )


def test_template_variables_deduplicates_in_first_occurrence_order():
    assert template_variables("{{chapter}} {{chapter}} {{output}} {{chapter}}") == (
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


def test_generic_director_template_documents_action_object_shapes():
    content = get_default_prompt_template("director_generic").content
    ordered_actions_example = re.search(r"ordered_actions（建议 (\[.*?\])）", content)

    assert "character_moves" in content
    assert "action" in content
    assert ordered_actions_example is not None
    try:
        parsed_example = json.loads(ordered_actions_example.group(1))
    except json.JSONDecodeError:
        pytest.fail("ordered_actions example must be valid JSON")
    assert parsed_example == [{"name": "角色名", "action": "具体动作"}]
    assert "chapter_satisfaction" in content
    assert "chapter_end_hook" in content
    assert "scene_chain" in content
    assert "3至5个" in content
    assert "场景变化" in content


def test_generic_director_template_excludes_game_only_outsider_misread():
    generic = get_default_prompt_template("director_generic").content
    game = get_default_prompt_template("director").content

    for game_only_term in ("outsider_misread", "游戏ID", "等级", "背包", "装备耐久", "任务进度"):
        assert game_only_term not in generic
    assert "outsider_misread" in game


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


@pytest.mark.parametrize(
    ("genre", "active_key", "inactive_key"),
    [
        ("网游", "director", "director_generic"),
        ("都市异能", "director_generic", "director"),
    ],
)
def test_project_prompt_templates_mark_current_genre_applicability(
    tmp_path,
    genre,
    active_key,
    inactive_key,
):
    store = FileProjectStore(tmp_path / genre)
    store.webnovel_dir.mkdir(parents=True, exist_ok=True)
    (store.webnovel_dir / "state.json").write_text(
        json.dumps({"genre": genre}, ensure_ascii=False),
        encoding="utf-8",
    )

    templates = {item["key"]: item for item in store.prompt_templates()}

    assert templates[active_key]["active_for_project"] is True
    assert templates[inactive_key]["active_for_project"] is False
    assert templates["director"]["applicability"] == "game_only"
    assert templates["director_generic"]["applicability"] == "non_game_only"
    assert templates["writer"]["applicability"] == "all"


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
