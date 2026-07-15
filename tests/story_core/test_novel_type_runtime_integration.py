from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from packages.story_core.file_project_creation import FileProjectCreateSpec, create_file_project
from packages.story_core.genre_plugins import plugin_prompt_guide, select_genre_plugins
from packages.story_core.models import AgentSettings, NovelProject
from packages.story_core.novel_type_catalog import novel_type_options
from packages.story_core.novel_type_library import NovelTypeLibrary
from packages.story_core.opening_directions import LLMOpeningDirectionGenerator, OpeningBrief
from packages.story_core.outline_planning_generation import (
    LLMOutlinePlanningGenerator,
    OutlinePlanningBrief,
)
from packages.story_core.runtime_config import OpenAIRuntimeSettings


XUANHUAN_DESCRIPTION = "运行时玄幻说明：力量异变必须落到现实选择。"
XUANHUAN_PROMISE = "运行时玄幻承诺：每次变强都改变一段外部关系。"
XUANHUAN_RULE = "运行时玄幻规则：每阶段必须验证一次力量代价。"
XUANHUAN_QUALITY = "运行时玄幻检查：力量收益与代价必须同时出现。"

CUSTOM_ID = "sports"
CUSTOM_NAME = "竞技体育"
CUSTOM_DESCRIPTION = "运行时竞技说明：比赛结果必须来自可见训练和临场决策。"
CUSTOM_PROMISE = "运行时竞技承诺：每场比赛都改变排名或队内关系。"
CUSTOM_RULE = "运行时竞技规则：关键回合必须交代战术选择。"
CUSTOM_QUALITY = "运行时竞技检查：胜负原因必须可追溯。"


@pytest.fixture
def runtime_type_library(monkeypatch, tmp_path) -> NovelTypeLibrary:
    path = tmp_path / "runtime-novel-types.json"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_NOVEL_TYPES_PATH", str(path))
    library = NovelTypeLibrary()
    library.update(
        "xuanhuan",
        {
            "description": XUANHUAN_DESCRIPTION,
            "core_promises": [XUANHUAN_PROMISE],
            "rulebook": {"chapter_formula": [XUANHUAN_RULE]},
            "quality_checks": [XUANHUAN_QUALITY],
        },
    )
    library.create(
        {
            "id": CUSTOM_ID,
            "name": CUSTOM_NAME,
            "description": CUSTOM_DESCRIPTION,
            "keywords": ["联赛", "冠军"],
            "core_promises": [CUSTOM_PROMISE],
            "ledger_fields": ["排名", "体能"],
            "rulebook": {"chapter_formula": [CUSTOM_RULE]},
            "quality_checks": [CUSTOM_QUALITY],
        }
    )
    return library


def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _runtime_settings(_: str) -> OpenAIRuntimeSettings:
    return OpenAIRuntimeSettings(
        provider="codexcli",
        base_url="http://runtime.test",
        codex_command="codex-test",
    )


def _strategy_settings() -> AgentSettings:
    return AgentSettings(director_model="runtime-integration-model")


def _directions_payload() -> dict:
    return {
        "directions": [
            {
                "id": f"direction-{index}",
                "title": f"方向{index}",
                "hook": f"钩子{index}",
                "protagonist_goal": f"目标{index}",
                "main_conflict": f"冲突{index}",
                "growth_path": f"成长{index}",
                "opening_promise": f"承诺{index}",
            }
            for index in range(1, 4)
        ]
    }


def _planning_brief(novel_type_id: str) -> OutlinePlanningBrief:
    return OutlinePlanningBrief(
        novel_type_id=novel_type_id,
        title="运行时类型测试",
        opening_direction={
            "hook": "主角在第一场较量前发现规则被人改过。",
            "protagonist_goal": "查清规则并赢下较量。",
            "main_conflict": "既得利益者不允许规则被公开。",
            "growth_path": "从执行规则成长为能重建规则的人。",
            "opening_promise": "每次行动都会得到可验证的结果。",
        },
    )


def test_runtime_options_and_project_creation_use_edited_builtin(
    runtime_type_library, tmp_path
) -> None:
    reloaded = NovelTypeLibrary().get("xuanhuan")
    assert reloaded is not None
    assert reloaded.id == "xuanhuan"
    assert reloaded.builtin is True
    assert reloaded.description == XUANHUAN_DESCRIPTION

    xuanhuan_option = next(item for item in novel_type_options() if item["id"] == "xuanhuan")
    assert xuanhuan_option["description"] == XUANHUAN_DESCRIPTION

    spec = FileProjectCreateSpec(
        mode="blank",
        title="运行时玄幻项目",
        novel_type_id="东方玄幻",
    )
    created = create_file_project(
        tmp_path / "projects",
        spec,
        project_id_factory=lambda: "p-runtime-xuanhuan",
    )
    project = _read_json(created.root / ".webnovel" / "project.json")
    assert spec.novel_type_id == "xuanhuan"
    assert project["world_blueprint"]["genre_plugin_ids"] == ["xuanhuan"]


def test_custom_type_creates_project_with_stable_lowercase_id(
    runtime_type_library, tmp_path
) -> None:
    spec = FileProjectCreateSpec(
        mode="blank",
        title="冠军之路",
        novel_type_id=" SPORTS ",
    )
    created = create_file_project(
        tmp_path / "projects",
        spec,
        project_id_factory=lambda: "p-runtime-sports",
    )

    project = _read_json(created.root / ".webnovel" / "project.json")
    state = _read_json(created.root / ".webnovel" / "state.json")
    assert spec.novel_type_id == CUSTOM_ID
    assert project["world_blueprint"]["genre_plugin_ids"] == [CUSTOM_ID]
    assert state["genre"] == CUSTOM_NAME


@pytest.mark.parametrize(
    ("novel_type_id", "description", "promise"),
    [
        ("xuanhuan", XUANHUAN_DESCRIPTION, XUANHUAN_PROMISE),
        (CUSTOM_ID, CUSTOM_DESCRIPTION, CUSTOM_PROMISE),
    ],
)
def test_opening_prompt_reads_latest_runtime_description_and_promise(
    runtime_type_library, novel_type_id, description, promise
) -> None:
    captured = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured["payload"] = payload
        return {
            "choices": [
                {"message": {"content": json.dumps(_directions_payload(), ensure_ascii=False)}}
            ]
        }

    generator = LLMOpeningDirectionGenerator(
        post_json=fake_post,
        runtime_resolver=_runtime_settings,
        strategy_resolver=_strategy_settings,
    )
    generator.generate(OpeningBrief(novel_type_id=novel_type_id, idea="一个具体开书灵感"))

    prompt = json.loads(captured["payload"]["messages"][1]["content"])
    assert prompt["genre_description"] == description
    assert promise in prompt["genre_core_promises"]


@pytest.mark.parametrize(
    ("novel_type_id", "rule"),
    [("xuanhuan", XUANHUAN_RULE), (CUSTOM_ID, CUSTOM_RULE)],
)
def test_outline_prompt_reads_latest_runtime_rulebook(
    runtime_type_library, novel_type_id, rule
) -> None:
    captured = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured["payload"] = payload
        raise RuntimeError("stop after prompt capture")

    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=_runtime_settings,
        strategy_resolver=_strategy_settings,
    )
    with pytest.raises(ValueError, match="outline_planning_generation_failed"):
        generator.generate(_planning_brief(novel_type_id))

    prompt = json.loads(captured["payload"]["messages"][1]["content"])
    assert rule in prompt["genre_rulebook"]["chapter_formula"]


@pytest.mark.parametrize(
    ("novel_type_id", "promise", "rule", "quality"),
    [
        ("xuanhuan", XUANHUAN_PROMISE, XUANHUAN_RULE, XUANHUAN_QUALITY),
        (CUSTOM_ID, CUSTOM_PROMISE, CUSTOM_RULE, CUSTOM_QUALITY),
    ],
)
def test_writing_plugin_selection_and_guide_use_latest_runtime_content(
    runtime_type_library, novel_type_id, promise, rule, quality
) -> None:
    project = NovelProject(
        project_id=f"p-{novel_type_id}-writing",
        title="运行时写作测试",
        world_blueprint={"genre_plugin_ids": [novel_type_id]},
    )

    plugins = select_genre_plugins(project)
    selected = next(plugin for plugin in plugins if plugin.plugin_id == novel_type_id)
    guide = json.loads(plugin_prompt_guide(plugins))
    selected_guide = next(item for item in guide if item["id"] == novel_type_id)

    assert selected.core_promises == (promise,)
    assert selected.rulebook["chapter_formula"] == (rule,)
    assert selected.quality_checks == (quality,)
    assert selected_guide["core_promises"] == [promise]
    assert selected_guide["rulebook"]["chapter_formula"] == [rule]
    assert selected_guide["quality_checks"] == [quality]


def test_unknown_type_is_rejected_and_builtin_alias_still_normalizes(
    runtime_type_library,
) -> None:
    with pytest.raises(ValidationError, match="invalid_novel_type"):
        FileProjectCreateSpec(mode="blank", title="未知类型", novel_type_id="not_registered")

    alias_spec = FileProjectCreateSpec(
        mode="blank",
        title="别名回归",
        novel_type_id=" 修仙仙侠 ",
    )
    assert alias_spec.novel_type_id == "xianxia"
