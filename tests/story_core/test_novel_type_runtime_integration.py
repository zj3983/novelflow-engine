from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest
from pydantic import ValidationError

from packages.story_core import novel_type_catalog
from packages.story_core.file_project_creation import FileProjectCreateSpec, create_file_project
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.genre_plugins import plugin_prompt_guide, select_genre_plugins
from packages.story_core.genre_types import EASTERN_FANTASY
from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.models import NovelProject, StoryState
from packages.story_core.novel_type_catalog import (
    NOVEL_TYPE_CATALOG,
    novel_type_options,
    novel_type_prompt_context,
    runtime_novel_type,
)
from packages.story_core.novel_type_library import NovelTypeLibrary
from packages.story_core.opening_directions import LLMOpeningDirectionGenerator, OpeningBrief
from packages.story_core.orchestrator import StoryOrchestrator, _writer_seed_summary
from packages.story_core.outline_planning import INITIAL_OUTLINE_CHAPTER_COUNT
from packages.story_core.outline_planning_generation import (
    LLMOutlinePlanningGenerator,
    OutlinePlanningBrief,
)
from packages.story_core.runtime_config import StageRuntimeSettings


XUANHUAN_DESCRIPTION = "运行时玄幻说明：力量异变必须落到现实选择。"
XUANHUAN_NAME = "运行时东方幻想"
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
            "name": XUANHUAN_NAME,
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


def _runtime_settings(_: str) -> StageRuntimeSettings:
    return StageRuntimeSettings(
        provider="openai",
        model="runtime-integration-model",
        base_url="http://runtime.test",
        api_key="test-key",
        codex_command="codex-test",
    )


def _primary_trope_id_for(novel_type_id: str) -> str | None:
    record = runtime_novel_type(novel_type_id)
    candidates = (
        novel_type_prompt_context(record).get("genre_trope_templates", [])
        if record is not None
        else []
    )
    return str(candidates[0]["id"]) if candidates else None


def _directions_payload(novel_type_id: str) -> dict:
    primary_trope_id = _primary_trope_id_for(novel_type_id)
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
                "primary_trope_id": primary_trope_id,
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


def _trope_plan(primary_trope_id: str | None, trope_beat: str | None) -> dict:
    characters = [
        ("Lead", "protagonist"),
        ("Rival", "stage_antagonist"),
        ("Patron", "supporting"),
        ("Hidden Hand", "long_term_antagonist"),
    ]
    return {
        "outline": {
            "overall": {
                "story": "The lead investigates a public failure.",
                "theme_statement": "Public facts matter more than protected status.",
                "foreground_story": "The lead investigates the failure and earns a formal hearing.",
                "background_story": "A hidden sponsor altered the rules to preserve control.",
                "book_objective": "Expose the altered rules and remove the sponsor's control.",
                "ending_image": "The verified evidence is entered into the public record.",
                "protagonist_goal": "Find the cause.",
                "main_conflict": "The rival blocks the investigation.",
                "growth_path": "Earn the authority to expose the truth.",
                "ending_direction": "Publish the evidence.",
                "primary_trope_id": primary_trope_id,
            },
            "arcs": [{
                "id": "opening",
                "title": "Opening case",
                "start_chapter": 1,
                "end_chapter": 30,
                "goal": "Secure the first piece of evidence.",
                "obstacle": "The rival controls access.",
                "payoff": "The lead earns a formal hearing.",
                "emotional_curve": "The lead moves from exclusion to a public challenge.",
                "key_results": [
                    "Secure the first piece of evidence.",
                    "Verify that the record was altered.",
                    "Earn a formal hearing.",
                ],
                "hook_plan": "The altered record points to a hidden sponsor.",
                "irreversible_change": "The dispute becomes public and cannot be buried quietly.",
                "trope_id": primary_trope_id,
                "end_state": "The case can no longer be buried.",
                "stage_antagonist": "Rival",
                "long_term_antagonist_traces": ["A hidden sponsor altered the record."],
            }],
            "chapters": [{
                "chapter_number": number,
                "title": f"Step {number}",
                "goal": "Advance the investigation.",
                "obstacle": "Access is restricted.",
                "action": "The lead verifies one record.",
                "turn": "The record points to a larger scheme.",
                "payoff": "One fact becomes public.",
                "ending_hook": "A witness asks for protection.",
                "trope_beat": trope_beat if number == 1 else None,
                "cast": ["Lead", "Rival"],
            } for number in range(1, INITIAL_OUTLINE_CHAPTER_COUNT + 1)],
        },
        "characters": [{
            "name": name,
            "role": tier,
            "character_tier": tier,
            "first_appearance": 0 if tier == "long_term_antagonist" else 1,
            "identity_profile": {
                "age": 30,
                "origin": "River City",
                "current_identity": tier,
                "occupation": "investigator",
            },
            "background_profile": {},
            "current_life_profile": {},
            "story_drive": {
                "immediate_goal": "Control the hearing.",
                "failure_stakes": "Lose public standing.",
            },
            "performance_profile": {},
            "dialogue_examples": ["State the evidence.", "Then show the record."],
            "relationship_notes": [],
        } for name, tier in characters],
    }


def test_trope_stage_locking_flows_from_opening_to_writer_summary(tmp_path) -> None:
    created = create_file_project(
        tmp_path / "projects",
        FileProjectCreateSpec(
            mode="inspiration",
            title="Working title",
            idea="A courier finds tomorrow's missing-person report.",
            novel_type_id="urban",
        ),
        project_id_factory=lambda: "p-trope-flow",
    )
    store = FileProjectStore(created.root)
    candidates = novel_type_prompt_context(runtime_novel_type("urban"))[
        "genre_trope_templates"
    ]
    selected = candidates[0]

    def opening_post(base_url, path, payload, api_key, **kwargs):
        return {
            "choices": [{
                "message": {
                    "content": json.dumps(_directions_payload("urban"), ensure_ascii=False)
                }
            }]
        }

    opening_generator = LLMOpeningDirectionGenerator(
        post_json=opening_post,
        runtime_resolver=_runtime_settings,
    )
    generated = store.generate_opening_directions(opening_generator)
    direction_id = generated["directions"][0]["id"]
    store.select_opening_direction(direction_id)

    plan_payload = _trope_plan(selected["id"], selected["beats"][0])

    def outline_post(base_url, path, payload, api_key, **kwargs):
        return {
            "choices": [{
                "message": {"content": json.dumps(plan_payload, ensure_ascii=False)}
            }]
        }

    saved = store.generate_outline_plan(
        LLMOutlinePlanningGenerator(
            post_json=outline_post,
            runtime_resolver=_runtime_settings,
        ),
        mode="initial",
    )
    story = StoryState.model_validate(
        store._story_state_payload_for_direction(store.state(), store.project(), 1)
    )
    seed = build_chapter_seed(story, 1)
    writer_summary = _writer_seed_summary(seed)
    summary_contracts = [
        value
        for value in writer_summary.values()
        if isinstance(value, dict) and "template_id" in value
    ]

    def nested_keys(value):
        if isinstance(value, dict):
            return {
                *value.keys(),
                *(key for item in value.values() for key in nested_keys(item)),
            }
        if isinstance(value, list):
            return {key for item in value for key in nested_keys(item)}
        return set()

    assert saved["outline"]["overall"]["primary_trope_id"] == selected["id"]
    assert saved["outline"]["arcs"][0]["trope_id"] == selected["id"]
    assert saved["outline"]["chapters"][0]["trope_beat"] == selected["beats"][0]
    assert seed["trope_contract"]["template_id"] == selected["id"]
    assert seed["trope_contract"]["current_beat"] == selected["beats"][0]
    assert summary_contracts == [seed["trope_contract"]]
    assert "trope_templates" not in nested_keys(writer_summary)
    assert "genre_trope_templates" not in nested_keys(writer_summary)


def test_legacy_outline_without_trope_fields_loads_and_builds_seed(tmp_path) -> None:
    created = create_file_project(
        tmp_path / "projects",
        FileProjectCreateSpec(mode="blank", title="Legacy", novel_type_id="urban"),
        project_id_factory=lambda: "p-legacy-tropes",
    )
    store = FileProjectStore(created.root)
    legacy_outline = _trope_plan(None, None)["outline"]
    legacy_outline["overall"].pop("primary_trope_id")
    legacy_outline["arcs"][0].pop("trope_id")
    for chapter in legacy_outline["chapters"]:
        chapter.pop("trope_beat")
    (store.webnovel_dir / "outline.json").write_text(
        json.dumps(legacy_outline, ensure_ascii=False),
        encoding="utf-8",
    )

    loaded = store.project_outline()
    story = StoryState.model_validate(
        store._story_state_payload_for_direction(store.state(), store.project(), 1)
    )
    seed = build_chapter_seed(story, 1)

    assert loaded["overall"]["primary_trope_id"] is None
    assert loaded["arcs"][0]["trope_id"] is None
    assert loaded["chapters"][0]["trope_beat"] is None
    assert "trope_contract" not in seed


def test_custom_type_allows_none_when_specific_and_generic_tropes_are_empty(
    runtime_type_library,
) -> None:
    runtime_type_library.update("generic_webnovel", {"trope_templates": []})
    runtime_type_library.update(CUSTOM_ID, {"trope_templates": []})
    candidates = novel_type_prompt_context(runtime_novel_type(CUSTOM_ID))[
        "genre_trope_templates"
    ]
    captured = {}

    def opening_post(base_url, path, payload, api_key, **kwargs):
        captured["opening"] = json.loads(payload["messages"][1]["content"])
        return {
            "choices": [{
                "message": {
                    "content": json.dumps(_directions_payload(CUSTOM_ID), ensure_ascii=False)
                }
            }]
        }

    directions = LLMOpeningDirectionGenerator(
        post_json=opening_post,
        runtime_resolver=_runtime_settings,
    ).generate(OpeningBrief(novel_type_id=CUSTOM_ID, idea="A final match."))

    def outline_post(base_url, path, payload, api_key, **kwargs):
        captured["outline"] = json.loads(payload["messages"][1]["content"])
        return {
            "choices": [{
                "message": {
                    "content": json.dumps(_trope_plan(None, None), ensure_ascii=False)
                }
            }]
        }

    plan = LLMOutlinePlanningGenerator(
        post_json=outline_post,
        runtime_resolver=_runtime_settings,
    ).generate(_planning_brief(CUSTOM_ID))

    assert candidates == []
    assert captured["opening"]["genre_trope_templates"] == []
    assert captured["outline"]["genre_trope_templates"] == []
    assert all(direction.primary_trope_id is None for direction in directions.directions)
    assert plan.outline.overall.primary_trope_id is None
    assert plan.outline.arcs[0].trope_id is None
    assert all(chapter.trope_beat is None for chapter in plan.outline.chapters)


def test_deleted_saved_trope_id_does_not_block_project_load_or_seed(
    runtime_type_library,
    tmp_path,
) -> None:
    deleted_id = "sports_upset"
    deleted_beat = "The favorite underestimates the challenger."
    runtime_type_library.update(
        CUSTOM_ID,
        {
            "trope_templates": [{
                "id": deleted_id,
                "name": "Upset",
                "trigger": "An overlooked team enters the final.",
                "beats": [deleted_beat],
                "payoff": "The ranking changes.",
                "avoid": ["Do not win by luck alone."],
            }]
        },
    )
    created = create_file_project(
        tmp_path / "projects",
        FileProjectCreateSpec(mode="blank", title="Deleted trope", novel_type_id=CUSTOM_ID),
        project_id_factory=lambda: "p-deleted-trope",
    )
    store = FileProjectStore(created.root)
    outline = _trope_plan(deleted_id, deleted_beat)["outline"]
    (store.webnovel_dir / "outline.json").write_text(
        json.dumps(outline, ensure_ascii=False),
        encoding="utf-8",
    )
    runtime_type_library.update(CUSTOM_ID, {"trope_templates": []})

    loaded = store.project_outline()
    story = StoryState.model_validate(
        store._story_state_payload_for_direction(store.state(), store.project(), 1)
    )
    seed = build_chapter_seed(story, 1)

    assert loaded["overall"]["primary_trope_id"] == deleted_id
    assert loaded["arcs"][0]["trope_id"] == deleted_id
    assert "trope_contract" not in seed


def test_direct_initial_and_opening_first_use_identical_trope_candidate_ids() -> None:
    captured: dict[str, list[dict]] = {}

    def opening_post(base_url, path, payload, api_key, **kwargs):
        context = json.loads(payload["messages"][1]["content"])
        captured["opening"] = context["genre_trope_templates"]
        return {
            "choices": [{
                "message": {
                    "content": json.dumps(_directions_payload("urban"), ensure_ascii=False)
                }
            }]
        }

    directions = LLMOpeningDirectionGenerator(
        post_json=opening_post,
        runtime_resolver=_runtime_settings,
    ).generate(OpeningBrief(novel_type_id="urban", idea="A city mystery."))
    selected_id = directions.directions[0].primary_trope_id
    selected = next(item for item in captured["opening"] if item["id"] == selected_id)

    def outline_post(label):
        def post(base_url, path, payload, api_key, **kwargs):
            context = json.loads(payload["messages"][1]["content"])
            captured[label] = context["genre_trope_templates"]
            return {
                "choices": [{
                    "message": {
                        "content": json.dumps(
                            _trope_plan(selected_id, selected["beats"][0]),
                            ensure_ascii=False,
                        )
                    }
                }]
            }
        return post

    brief_payload = _planning_brief("urban").model_dump(mode="json")
    direct_brief = OutlinePlanningBrief.model_validate(
        {
            **brief_payload,
            "opening_direction": {
                **brief_payload["opening_direction"],
                "primary_trope_id": None,
            },
        }
    )
    opening_first_brief = OutlinePlanningBrief.model_validate(
        {
            **brief_payload,
            "opening_direction": {
                **brief_payload["opening_direction"],
                "primary_trope_id": selected_id,
            },
        }
    )
    LLMOutlinePlanningGenerator(
        post_json=outline_post("direct"), runtime_resolver=_runtime_settings
    ).generate(direct_brief)
    LLMOutlinePlanningGenerator(
        post_json=outline_post("opening_first"), runtime_resolver=_runtime_settings
    ).generate(opening_first_brief)

    def candidate_ids(items):
        return [item["id"] for item in items]

    assert candidate_ids(captured["direct"]) == candidate_ids(captured["opening"])
    assert candidate_ids(captured["opening_first"]) == candidate_ids(captured["opening"])


def test_runtime_options_and_project_creation_use_edited_builtin(
    runtime_type_library, tmp_path
) -> None:
    reloaded = NovelTypeLibrary().get("xuanhuan")
    assert reloaded is not None
    assert reloaded.id == "xuanhuan"
    assert reloaded.builtin is True
    assert reloaded.name == XUANHUAN_NAME
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


@pytest.mark.parametrize(
    ("novel_type_id", "expected_name", "promise", "rule"),
    [
        ("xuanhuan", XUANHUAN_NAME, XUANHUAN_PROMISE, XUANHUAN_RULE),
        (CUSTOM_ID, CUSTOM_NAME, CUSTOM_PROMISE, CUSTOM_RULE),
    ],
)
def test_file_project_store_story_state_and_chapter_seed_preserve_runtime_type_id(
    runtime_type_library,
    tmp_path,
    novel_type_id,
    expected_name,
    promise,
    rule,
) -> None:
    created = create_file_project(
        tmp_path / "projects",
        FileProjectCreateSpec(
            mode="blank",
            title=f"{expected_name}写作链路",
            novel_type_id=novel_type_id,
        ),
        project_id_factory=lambda: f"p-seed-{novel_type_id}",
    )
    store = FileProjectStore(created.root)

    persisted_state = store.state()
    story_payload = store._story_state_payload_for_direction(
        persisted_state,
        store.project(),
        1,
    )
    story = StoryState.model_validate(story_payload)
    seed = build_chapter_seed(story, 1)

    assert persisted_state["genre"] == expected_name
    assert persisted_state["genre_plugin_ids"] == [novel_type_id]
    assert story.genre_plugin_ids == [novel_type_id]
    assert novel_type_id in seed["genre_plugins"]
    assert promise in seed["core_promises"]
    assert rule in seed["rulebook"]["chapter_formula"]


def test_update_project_switches_persisted_story_state_and_seed_to_custom_type(
    runtime_type_library,
    tmp_path,
) -> None:
    created = create_file_project(
        tmp_path / "projects",
        FileProjectCreateSpec(
            mode="blank",
            title="类型切换写作链路",
            novel_type_id="xuanhuan",
        ),
        project_id_factory=lambda: "p-switch-to-sports",
    )
    store = FileProjectStore(created.root)
    state_path = store.webnovel_dir / "state.json"
    initial_state = store.state()
    initial_state["world_facts"] = [
        "保留事实：训练场仍在开放。",
        "  小说类型：东方玄幻  ",
        "小说类型:xianxia",
        "小说类型：角色口中的分类并不可靠",
    ]
    state_path.write_text(json.dumps(initial_state, ensure_ascii=False), encoding="utf-8")

    store.update_project(
        {
            "world_blueprint": {
                "genre_plugin_ids": [" SPORTS "],
                "settings_marker": "preserved replacement payload",
            }
        }
    )

    project = store.project()
    state = store.state()
    story = StoryState.model_validate(
        store._story_state_payload_for_direction(state, project, 1)
    )
    seed = build_chapter_seed(story, 1)

    assert project["world_blueprint"] == {
        "genre_plugin_ids": [CUSTOM_ID],
        "settings_marker": "preserved replacement payload",
    }
    assert state["genre_plugin_ids"] == [CUSTOM_ID]
    assert state["world_facts"] == [
        "保留事实：训练场仍在开放。",
        "小说类型：角色口中的分类并不可靠",
        f"小说类型：{CUSTOM_ID}",
    ]
    assert story.genre_plugin_ids == [CUSTOM_ID]
    assert seed["genre_plugins"] == ["generic_webnovel", CUSTOM_ID]
    assert CUSTOM_PROMISE in seed["core_promises"]
    assert CUSTOM_RULE in seed["rulebook"]["chapter_formula"]
    assert XUANHUAN_PROMISE not in seed["core_promises"]
    assert XUANHUAN_RULE not in seed["rulebook"]["chapter_formula"]


def test_update_project_explicit_type_clear_does_not_leave_stale_state_id(
    runtime_type_library,
    tmp_path,
) -> None:
    created = create_file_project(
        tmp_path / "projects",
        FileProjectCreateSpec(mode="blank", title="清空类型", novel_type_id="xuanhuan"),
        project_id_factory=lambda: "p-clear-runtime-type",
    )
    store = FileProjectStore(created.root)
    state_path = store.webnovel_dir / "state.json"
    initial_state = store.state()
    initial_state["world_facts"] = [
        "保留事实：旧案仍未解决。",
        "  小说类型：东方玄幻  ",
        "小说类型:xianxia",
        "小说类型：角色口中的分类并不可靠",
    ]
    state_path.write_text(json.dumps(initial_state, ensure_ascii=False), encoding="utf-8")

    store.update_project({"world_blueprint": {"genre_plugin_ids": []}})

    state = store.state()
    story = StoryState.model_validate(
        store._story_state_payload_for_direction(state, store.project(), 1)
    )
    seed = build_chapter_seed(story, 1)
    assert state["genre_plugin_ids"] == []
    assert state["world_facts"] == [
        "保留事实：旧案仍未解决。",
        "小说类型：角色口中的分类并不可靠",
    ]
    assert story.genre_plugin_ids == []
    assert seed["genre_plugins"] == ["generic_webnovel"]
    assert XUANHUAN_PROMISE not in seed["core_promises"]
    assert XUANHUAN_RULE not in seed["rulebook"]["chapter_formula"]
    assert not set(EASTERN_FANTASY.core_promises) & set(seed["core_promises"])
    assert not set(EASTERN_FANTASY.rulebook["chapter_formula"]) & set(
        seed["rulebook"]["chapter_formula"]
    )


@pytest.mark.parametrize(
    "genre_plugin_ids",
    [["unknown-runtime-type"], ["xuanhuan", "unknown-runtime-type"]],
)
def test_update_project_rejects_invalid_genre_ids_without_writing_project_or_state(
    runtime_type_library,
    tmp_path,
    genre_plugin_ids,
) -> None:
    created = create_file_project(
        tmp_path / "projects",
        FileProjectCreateSpec(mode="blank", title="原子类型更新", novel_type_id="xuanhuan"),
        project_id_factory=lambda: "p-atomic-runtime-type",
    )
    store = FileProjectStore(created.root)
    project_path = store.webnovel_dir / "project.json"
    state_path = store.webnovel_dir / "state.json"
    before = (project_path.read_bytes(), state_path.read_bytes())

    with pytest.raises(ValueError, match="invalid_novel_type"):
        store.update_project(
            {
                "title": "不得落盘的新标题",
                "world_blueprint": {"genre_plugin_ids": genre_plugin_ids},
            }
        )

    assert (project_path.read_bytes(), state_path.read_bytes()) == before


def test_chapter_seed_resolves_unique_runtime_names_for_legacy_story_state(
    runtime_type_library,
) -> None:
    custom_story = StoryState(
        story_id="s-custom-name",
        genre=CUSTOM_NAME,
        style="白描",
        outline="球队争夺最后一个季后赛席位。",
    )
    renamed_builtin_story = StoryState(
        story_id="s-renamed-builtin-name",
        genre="",
        style="白描",
        outline="遗物在第一次使用后留下代价。",
        world_facts=[f"小说类型：{XUANHUAN_NAME}"],
    )

    custom_seed = build_chapter_seed(custom_story, 1)
    builtin_seed = build_chapter_seed(renamed_builtin_story, 1)

    assert custom_seed["genre_plugins"] == ["generic_webnovel", CUSTOM_ID]
    assert CUSTOM_PROMISE in custom_seed["core_promises"]
    assert "xuanhuan" in builtin_seed["genre_plugins"]
    assert XUANHUAN_PROMISE in builtin_seed["core_promises"]


def test_chapter_seed_does_not_guess_when_runtime_names_are_ambiguous(
    runtime_type_library,
) -> None:
    NovelTypeLibrary().create(
        {
            "id": "sports_duplicate",
            "name": CUSTOM_NAME,
            "core_promises": ["不应被歧义名称加载"],
        }
    )
    story = StoryState(
        story_id="s-ambiguous-name",
        genre=CUSTOM_NAME,
        style="白描",
        outline="名称重复时不应猜测类型。",
        world_facts=[f"小说类型：{CUSTOM_NAME}"],
    )

    seed = build_chapter_seed(story, 1)

    assert seed["genre_plugins"] == ["generic_webnovel"]
    assert CUSTOM_PROMISE not in seed["core_promises"]
    assert "不应被歧义名称加载" not in seed["core_promises"]


def test_catalog_is_dynamic_view_of_library_bootstrap(runtime_type_library) -> None:
    assert not isinstance(NOVEL_TYPE_CATALOG, dict)
    assert NOVEL_TYPE_CATALOG["xuanhuan"].label == XUANHUAN_NAME
    assert NOVEL_TYPE_CATALOG[CUSTOM_ID].label == CUSTOM_NAME


def test_dict_catalog_conversion_keeps_one_snapshot_across_runtime_crud(
    runtime_type_library,
) -> None:
    original_xuanhuan_name = NOVEL_TYPE_CATALOG["xuanhuan"].label

    class MutatingCatalog(Mapping[str, object]):
        def keys(self):
            keys = NOVEL_TYPE_CATALOG.keys()
            writer = threading.Thread(
                target=lambda: (
                    NovelTypeLibrary().update("xuanhuan", {"name": "转换后的玄幻名"}),
                    NovelTypeLibrary().delete(CUSTOM_ID),
                )
            )
            writer.start()
            writer.join()
            time.sleep(0.55)
            return keys

        def __getitem__(self, key):
            return NOVEL_TYPE_CATALOG[key]

        def __iter__(self):
            return iter(self.keys())

        def __len__(self):
            return len(NOVEL_TYPE_CATALOG)

    converted = dict(MutatingCatalog())

    assert converted["xuanhuan"].label == original_xuanhuan_name
    assert converted[CUSTOM_ID].label == CUSTOM_NAME
    assert novel_type_catalog._CONVERSION_KEYS.pin is None
    assert NOVEL_TYPE_CATALOG["xuanhuan"].label == "转换后的玄幻名"
    assert CUSTOM_ID not in dict(NOVEL_TYPE_CATALOG.items())


def test_out_of_order_saved_key_discards_conversion_pin_and_reads_latest_value(
    runtime_type_library,
) -> None:
    saved_keys = list(NOVEL_TYPE_CATALOG.keys())
    out_of_order_key = saved_keys[1]

    writer = threading.Thread(
        target=lambda: NovelTypeLibrary().update(
            str(out_of_order_key), {"name": "非顺序访问的新名称"}
        )
    )
    writer.start()
    writer.join()

    assert NOVEL_TYPE_CATALOG[out_of_order_key].label == "非顺序访问的新名称"
    assert novel_type_catalog._CONVERSION_KEYS.pin is None


def test_saved_catalog_keys_refresh_after_same_thread_update_and_delete(
    runtime_type_library,
) -> None:
    saved_keys = list(NOVEL_TYPE_CATALOG.keys())
    first_key = saved_keys[0]

    NovelTypeLibrary().update(str(first_key), {"name": "同线程立即改名"})

    assert NOVEL_TYPE_CATALOG[first_key].label == "同线程立即改名"

    saved_keys = list(NOVEL_TYPE_CATALOG.keys())
    NovelTypeLibrary().delete(CUSTOM_ID)

    for key in saved_keys:
        if key == CUSTOM_ID:
            with pytest.raises(KeyError):
                NOVEL_TYPE_CATALOG[key]
        else:
            assert NOVEL_TYPE_CATALOG[key].plugin_id == key


def test_catalog_snapshot_detects_external_file_replacement(runtime_type_library) -> None:
    saved_key = list(NOVEL_TYPE_CATALOG.keys())[0]
    path = runtime_type_library.path
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["overrides"].setdefault(str(saved_key), {})["name"] = "外部进程改名"
    previous_stat = path.stat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.utime(
        path,
        ns=(previous_stat.st_atime_ns, previous_stat.st_mtime_ns + 1_000_000_000),
    )

    assert NOVEL_TYPE_CATALOG[saved_key].label == "外部进程改名"


def test_build_chapter_seed_reuses_runtime_type_snapshot(
    runtime_type_library,
    monkeypatch,
) -> None:
    original_list = NovelTypeLibrary.list
    calls = 0

    def counted_list(self):
        nonlocal calls
        calls += 1
        return original_list(self)

    monkeypatch.setattr(NovelTypeLibrary, "list", counted_list)
    story = StoryState(
        story_id="s-snapshot-count",
        genre=CUSTOM_NAME,
        genre_plugin_ids=[CUSTOM_ID],
        style="白描",
        outline="球队争夺季后赛席位。",
    )

    seed = build_chapter_seed(story, 1)

    assert CUSTOM_ID in seed["genre_plugins"]
    assert calls <= 2


@pytest.mark.parametrize(
    "imports",
    [
        "import packages.story_core.novel_type_catalog; import packages.story_core.novel_type_library",
        "import packages.story_core.novel_type_library; import packages.story_core.novel_type_catalog",
    ],
)
def test_catalog_and_library_support_both_import_orders(imports) -> None:
    result = subprocess.run(
        [sys.executable, "-c", imports],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_novel_type_library_import_does_not_require_catalog() -> None:
    script = """
import importlib.abc
import sys

class BlockCatalog(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == 'packages.story_core.novel_type_catalog':
            raise ImportError('catalog import blocked')
        return None

sys.meta_path.insert(0, BlockCatalog())
import packages.story_core.novel_type_library
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


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


def test_runtime_non_game_type_does_not_inherit_web_game_writer_method(
    runtime_type_library,
) -> None:
    story = StoryState(
        story_id="s-runtime-sports",
        outline="替补队员调查训练数据被篡改的原因，并争取下一场首发。",
        genre=CUSTOM_NAME,
        genre_plugin_ids=[CUSTOM_ID],
        style="白描",
    )

    prompt = StoryOrchestrator()._body_prompt(
        story,
        1,
        {"event_plan": {"chapter_title": "首发名单"}},
    )

    assert CUSTOM_DESCRIPTION in prompt
    assert "通用写法：本章只推进一个主要目标" in prompt
    assert "悬疑写法" not in prompt
    assert "## 网游写法" not in prompt
    assert "怪物面板" not in prompt
    assert "玩家和NPC" not in prompt


@pytest.mark.parametrize(
    "outline",
    [
        "替补队员调查案件并争取下一场首发。",
        "替补队员进入都市公司争取赞助合同。",
        "替补队员在宗门修炼后参加联赛选拔。",
    ],
)
def test_runtime_non_game_type_ignores_builtin_genre_keyword_interference(
    runtime_type_library,
    outline,
) -> None:
    story = StoryState(
        story_id="s-runtime-sports-interference",
        outline=outline,
        genre=CUSTOM_NAME,
        genre_plugin_ids=[CUSTOM_ID],
        style="白描",
    )

    prompt = StoryOrchestrator()._body_prompt(story, 1, {})

    assert CUSTOM_DESCRIPTION in prompt
    assert "通用写法：本章只推进一个主要目标" in prompt
    for builtin_method in ("悬疑写法", "都市写法", "玄幻/修仙写法"):
        assert builtin_method not in prompt


def test_runtime_non_game_type_resolves_custom_record_from_genre_name(
    runtime_type_library,
) -> None:
    story = StoryState(
        story_id="s-runtime-sports-name-only",
        outline="替补队员调查训练数据并争取下一场首发。",
        genre=CUSTOM_NAME,
        genre_plugin_ids=[],
        style="白描",
    )

    prompt = StoryOrchestrator()._body_prompt(story, 1, {})

    assert CUSTOM_DESCRIPTION in prompt
    assert "通用写法：本章只推进一个主要目标" in prompt
    assert "悬疑写法" not in prompt


def test_builtin_general_type_keeps_generic_method_without_description_injection(
    runtime_type_library,
) -> None:
    record = runtime_novel_type("generic_webnovel")
    description = novel_type_prompt_context(record)["genre_description"]
    story = StoryState(
        story_id="s-runtime-builtin-general",
        outline="主角处理眼前的选择。",
        genre=record.name,
        genre_plugin_ids=[record.id],
        style="白描",
    )

    prompt = StoryOrchestrator()._body_prompt(story, 1, {})

    assert "通用写法：本章只推进一个主要目标" in prompt
    assert description not in prompt


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
                {"message": {"content": json.dumps(_directions_payload(novel_type_id), ensure_ascii=False)}}
            ]
        }

    generator = LLMOpeningDirectionGenerator(
        post_json=fake_post,
        runtime_resolver=_runtime_settings,
    )
    generator.generate(OpeningBrief(novel_type_id=novel_type_id, idea="一个具体开书灵感"))

    prompt = json.loads(captured["payload"]["messages"][1]["content"])
    assert prompt["genre_description"] == description
    assert promise in prompt["genre_core_promises"]
    assert prompt["genre_power_system_template"]["system_form"]
    assert prompt["genre_power_system_template"]["required_sections"]
    assert prompt["genre_power_system_template"]["minimum_path_count"] >= 1


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
    )
    with pytest.raises(ValueError, match="outline_planning_generation_failed"):
        generator.generate(_planning_brief(novel_type_id))

    prompt = json.loads(captured["payload"]["messages"][1]["content"])
    assert rule in prompt["genre_rulebook"]["chapter_formula"]


@pytest.mark.parametrize("generator_kind", ["opening", "outline"])
def test_generation_prompt_caps_runtime_novel_type_context(
    runtime_type_library,
    generator_kind,
) -> None:
    marker = "必须保留的运行时类型字段"
    huge = "超长配置" * 3000
    NovelTypeLibrary().update(
        "xuanhuan",
        {
            "description": marker + huge,
            "core_promises": [marker + huge, *[huge for _ in range(30)]],
            "rulebook": {
                field: [marker + huge, *[huge for _ in range(30)]]
                for field in (
                    "progression_rules",
                    "economy_rules",
                    "quest_rules",
                    "faction_rules",
                    "panel_rules",
                    "chapter_formula",
                    "forbidden_breaks",
                )
            },
            "quality_checks": [marker + huge, *[huge for _ in range(30)]],
        },
    )
    captured = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured["payload"] = payload
        if generator_kind == "opening":
            return {
                "choices": [
                    {"message": {"content": json.dumps(_directions_payload("xuanhuan"), ensure_ascii=False)}}
                ]
            }
        raise RuntimeError("stop after prompt capture")

    if generator_kind == "opening":
        generator = LLMOpeningDirectionGenerator(
            post_json=fake_post,
            runtime_resolver=_runtime_settings,
        )
        generator.generate(OpeningBrief(novel_type_id="xuanhuan", idea="限长测试"))
    else:
        generator = LLMOutlinePlanningGenerator(
            post_json=fake_post,
            runtime_resolver=_runtime_settings,
        )
        with pytest.raises(ValueError, match="outline_planning_generation_failed"):
            generator.generate(_planning_brief("xuanhuan"))

    prompt = json.loads(captured["payload"]["messages"][1]["content"])
    novel_type_context = {
        key: value for key, value in prompt.items() if key.startswith("genre_")
    }
    serialized = json.dumps(novel_type_context, ensure_ascii=False)
    assert marker in serialized
    assert set(novel_type_context) == {
        "genre_label",
        "genre_description",
        "genre_core_promises",
        "genre_rulebook",
        "genre_quality_checks",
        "genre_trope_templates",
        "genre_power_system_template",
        "genre_outline_template",
    }
    assert "genre_trope_templates" in captured["payload"]["messages"][1]["content"]
    assert len(serialized) <= 6000


def test_generation_prompt_keeps_normal_short_runtime_type_content_complete(
    runtime_type_library,
) -> None:
    short_rules = [f"短规则-{index}" for index in range(1, 5)]
    NovelTypeLibrary().update(
        "xuanhuan",
        {
            "description": "完整短说明",
            "core_promises": ["短承诺一", "短承诺二", "短承诺三"],
            "rulebook": {
                field: short_rules
                for field in (
                    "progression_rules",
                    "economy_rules",
                    "quest_rules",
                    "faction_rules",
                    "panel_rules",
                    "chapter_formula",
                    "forbidden_breaks",
                )
            },
            "quality_checks": ["短检查一", "短检查二", "短检查三"],
        },
    )
    captured = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured["payload"] = payload
        return {
            "choices": [
                {"message": {"content": json.dumps(_directions_payload("xuanhuan"), ensure_ascii=False)}}
            ]
        }

    LLMOpeningDirectionGenerator(
        post_json=fake_post,
        runtime_resolver=_runtime_settings,
    ).generate(OpeningBrief(novel_type_id="xuanhuan", idea="短配置完整性"))

    prompt = json.loads(captured["payload"]["messages"][1]["content"])
    assert prompt["genre_description"] == "完整短说明"
    assert prompt["genre_core_promises"] == ["短承诺一", "短承诺二", "短承诺三"]
    assert prompt["genre_quality_checks"] == ["短检查一", "短检查二", "短检查三"]
    assert all(rules == short_rules for rules in prompt["genre_rulebook"].values())


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
