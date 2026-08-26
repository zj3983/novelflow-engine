from copy import deepcopy
import json

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import stories as story_routes
from apps.api.storage import SQLiteStoryStore, _project_world_facts
from packages.story_core import novel_type_catalog, novel_type_library
from packages.story_core.engine import ChapterBundle
from packages.story_core.models import NovelProject, StoryState
from packages.story_core.model_gateway import ModelResponse
from packages.story_core.novel_type_catalog import novel_type_prompt_context
from packages.story_core.novel_type_library import NovelTypeLibrary
from packages.story_core.power_system_templates import (
    compact_power_system_template,
    copy_power_system_template,
)
from packages.story_core.power_systems import legacy_power_summary, validate_power_system_spec
from packages.story_core import world_enrichment


GAME_CLASSES = ("战士", "法师", "游侠", "盗贼", "牧师", "召唤师")


def test_derived_author_constraints_only_add_game_identity_rule_for_game_projects():
    urban = world_enrichment._derive_author_constraints({"genre_plugin_ids": ["urban"]})
    game = world_enrichment._derive_author_constraints({"genre_plugin_ids": ["game_webnovel"]})

    assert not any("游戏ID" in item for item in urban)
    assert any("游戏ID" in item for item in game)


def test_world_prompt_projection_includes_only_world_story_core_fields():
    project = NovelProject(
        project_id="p-world-core",
        title="断香炉",
        story_core_context={
            "logline": "守祠杂役林照从断香炉里看见旧案。",
            "protagonist_profile": "林照是守祠杂役，谨慎但不肯替人背罪。",
            "inciting_incident": "断香炉指出第一件旧案证物。",
            "main_conflict": "执事要销毁证物。",
            "excitement_point": "从旧物痕迹追查宗门旧案。",
        },
    )

    payload = world_enrichment._project_payload(project, chars=240, items=8, depth=4)

    assert set(payload["story_core"]) == {
        "logline",
        "protagonist_profile",
        "inciting_incident",
        "main_conflict",
        "excitement_point",
    }


def test_non_game_world_defaults_use_genre_neutral_actor_language():
    living_world = world_enrichment._default_living_world(
        NovelProject(project_id="p-xuanhuan-living-world", title="断香炉"),
        [{"id": "xuanhuan"}],
    )

    serialized = json.dumps(living_world, ensure_ascii=False)
    assert "玩家" not in serialized
    assert "角色与组织" in serialized


def test_character_profile_omits_empty_game_id():
    profiles = world_enrichment._as_character_profiles(
        [{"name": "林照", "game_id": "", "role": "主角"}],
        [],
    )

    assert profiles == [{
        "name": "林照",
        "role": "主角",
        "motivation": "",
        "current_state": "",
        "personality": "",
        "speech_style": "",
        "goals": [],
        "secrets": [],
        "conflict_hooks": [],
    }]


def complete_game_power_spec() -> dict[str, object]:
    spec = {
        "name": "神域职业体系",
        "origin": ["完成觉醒任务后获得职业权限"],
        "attributes": [{"name": "智力", "effect": "提高法术强度"}],
        "paths": [
            {
                "name": name,
                "role": f"{name}队伍职责",
                "core_resource": f"{name}职业资源",
                "core_attributes": [f"{name}核心属性"],
                "weapons": [f"{name}武器"],
                "armor": [f"{name}护甲"],
                "combat_loop": f"{name}战斗循环",
                "strengths": [f"{name}强项"],
                "weaknesses": [f"{name}弱项"],
                "skill_categories": [f"{name}主动技能", f"{name}被动技能"],
                "branches": [f"{name}烈焰分支", f"{name}守护分支"],
                "transfer_task": f"完成{name}转职任务",
                "advancement": [f"{name}进阶任务"],
            }
            for name in GAME_CLASSES
        ],
        "stages": [
            {"name": name, "level": level, "entry": entry, "change": change, "failure": failure}
            for name, level, entry, change, failure in (
                ("见习者", 1, "创建角色", "获得通用技能", "角色重建"),
                ("正式职业", 10, "Lv.10转职任务", "获得职业资源", "任务冷却"),
                ("专精", 20, "Lv.20专精试炼", "强化战斗方向", "专精材料损失"),
                ("进阶职业", 30, "Lv.30分支任务", "获得分支技能", "转职延期"),
                ("传承", 60, "Lv.60传承试炼", "获得职业权柄", "传承反噬"),
            )
        ],
        "skills": ["职业技能由导师、技能书和试炼获得"],
        "equipment": ["职业熟练度限制武器与护甲"],
        "resources": ["技能消耗职业资源并通过战斗恢复"],
        "advancement": ["晋升必须满足等级、任务和材料"],
        "costs": ["透支会造成虚弱并降低恢复速度"],
        "counters": ["控制克制蓄力，突进克制远程"],
        "boundaries": ["越级只能依赖情报、环境和克制"],
        "social_impact": ["公会按职业配置开荒队"],
        "visibility": ["只能观察已公开等级和装备"],
        "continuity_ledger": [
            "level", "class_path", "skills", "equipment", "resources", "conditions"
        ],
    }
    spec["class_advancement_tiers"] = [
        {
            "level": level,
            "name": name,
            "purpose": purpose,
            "common_requirements": [requirement],
            "failure_rule": failure,
        }
        for level, name, purpose, requirement, failure in (
            (10, "正式转职", "确定基础职业", "完成职业导师试炼", "七日后可重新挑战"),
            (30, "职业分支", "选择战斗分支", "完成分支资格任务", "保留原职业等待重试"),
            (60, "传承职业", "获得职业传承", "完成传承仪式", "传承材料进入修复状态"),
        )
    ]
    for path in spec["paths"]:
        path["advancement_tree"] = [
            {
                "level": level,
                "tier_name": tier_name,
                "options": [
                    {
                        "name": f"{path['name']}{suffix}",
                        "role": path["role"],
                        "requirements": [requirement],
                        "transfer_task": task,
                        "ability_changes": [change],
                        "new_resources": [path["core_resource"]],
                        "equipment_permissions": path["weapons"],
                        "failure_consequence": failure,
                        "next_options": [f"{path['name']}后续路线"] if level < 60 else [],
                    }
                ],
            }
            for level, tier_name, suffix, requirement, task, change, failure in (
                (10, "正式转职", "正式职业", "达到Lv.10", "完成导师试炼", "解锁职业资源", "七日后重试"),
                (30, "职业分支", "专精分支", "达到Lv.30", "完成分支任务", "解锁分支技能", "保留原职业"),
                (60, "传承职业", "传承者", "达到Lv.60", "完成传承仪式", "解锁职业权柄", "修复传承材料"),
            )
        ]
    return spec


def complete_custom_game_power_spec(*, levels: tuple[int, ...] | None = None) -> dict[str, object]:
    stage_names = ("建立据点", "扩大行动", "形成长期循环")
    stages = [
        {
            "name": name,
            "entry": f"满足{name}的前置条件",
            "change": f"解锁{name}对应的行动空间",
            "failure": f"保留资源并重新规划{name}",
        }
        for name in stage_names
    ]
    if levels is not None:
        for stage, level in zip(stages, levels, strict=True):
            stage["level"] = level
    return {
        "name": "雾海沙盒规则",
        "origin": ["参与者通过探索、经营和协作改变持续演化的雾海"],
        "attributes": [{"name": "航路掌握", "effect": "影响可安全抵达的区域"}],
        "paths": [
            {
                "name": "航路经营",
                "role": "规划行动与资源投放",
                "core_resource": "航路情报",
                "core_attributes": ["航路掌握"],
                "strengths": ["长期规划"],
                "weaknesses": ["即时应变成本较高"],
                "skill_categories": ["探索", "经营"],
                "branches": ["公开航路", "隐秘航路"],
                "advancement": ["通过可验证的行动成果扩大经营范围"],
            }
        ],
        "stages": stages,
        "skills": ["能力来自项目内明确的行动经验与协作关系"],
        "equipment": ["工具只提供场景能力，不绑定职业或等级"],
        "resources": ["情报、时间与行动机会形成可追踪收支"],
        "advancement": ["推进依据目标完成度和世界反馈"],
        "costs": ["失败会损失时间、信誉或行动机会"],
        "counters": ["情报优势可被误导和时效性克制"],
        "boundaries": ["任何行动都不能绕过已建立的世界规则"],
        "social_impact": ["行动结果会改变组织关系和区域秩序"],
        "visibility": ["参与者只能依据已获得的信息决策"],
        "continuity_ledger": ["行动目标", "资源收支", "关系变化", "世界反馈"],
    }


def test_game_power_system_requires_shared_class_advancement_levels() -> None:
    spec = complete_game_power_spec()

    validated = validate_power_system_spec(spec, novel_type_id="game_webnovel")

    assert [tier["level"] for tier in validated["class_advancement_tiers"]] == [10, 30, 60]
    assert [node["level"] for node in validated["paths"][0]["advancement_tree"]] == [10, 30, 60]
    assert validated["paths"][0]["advancement_tree"][0]["options"][0]["transfer_task"]


@pytest.mark.parametrize("missing_level", [10, 30, 60])
def test_game_power_system_rejects_missing_class_advancement_level(missing_level: int) -> None:
    spec = complete_game_power_spec()
    spec["class_advancement_tiers"] = [
        tier for tier in spec["class_advancement_tiers"] if tier["level"] != missing_level
    ]

    with pytest.raises(ValueError, match="game.invalid_class_advancement_tiers"):
        validate_power_system_spec(spec, novel_type_id="game_webnovel")


def test_level_less_game_power_spec_round_trips_through_full_enrichment_validation():
    spec = complete_custom_game_power_spec()
    project = game_project()

    validated = validate_power_system_spec(spec, novel_type_id="game_webnovel")
    enriched = world_enrichment._merge_enrichment(
        project,
        {"world_blueprint": {"power_system_spec": spec}},
        rules_only=False,
    )

    assert validated["name"] == "雾海沙盒规则"
    assert all("level" not in stage for stage in validated["stages"])
    assert enriched.world_blueprint["power_system_spec"] == validated


def test_leveled_game_without_class_advancement_is_not_treated_as_traditional():
    spec = complete_custom_game_power_spec(levels=(1, 2, 3))
    project = game_project()

    enriched = world_enrichment._merge_enrichment(
        project,
        {"world_blueprint": {"power_system_spec": spec}},
        rules_only=False,
    )

    assert [
        stage["level"]
        for stage in enriched.world_blueprint["power_system_spec"]["stages"]
    ] == [1, 2, 3]
    assert "class_advancement_tiers" not in enriched.world_blueprint["power_system_spec"]
    prompt = world_enrichment._build_prompt(enriched)
    assert "Lv.10正式转职、Lv.30选择职业分支、Lv.60晋升传承职业" not in prompt
    assert prompt_power_template(prompt)["fixed_milestones"] == []


def test_custom_game_power_spec_still_requires_generic_core_structure():
    spec = complete_custom_game_power_spec()
    spec["costs"] = []

    with pytest.raises(ValueError, match="costs"):
        validate_power_system_spec(spec, novel_type_id="game_webnovel")


def test_custom_game_power_spec_may_omit_advancement_in_full_enrichment():
    spec = complete_custom_game_power_spec()
    spec.pop("advancement")

    enriched = world_enrichment._merge_enrichment(
        game_project(),
        {"world_blueprint": {"power_system_spec": spec}},
        rules_only=False,
    )

    assert enriched.world_blueprint["power_system_spec"]["name"] == "雾海沙盒规则"
    assert "advancement" not in enriched.world_blueprint["power_system_spec"]


def test_traditional_game_power_spec_still_requires_advancement():
    spec = complete_game_power_spec()
    spec.pop("advancement")

    with pytest.raises(ValueError, match=r"missing_sections=\[advancement\]"):
        world_enrichment._merge_enrichment(
            game_project(),
            {"world_blueprint": {"power_system_spec": spec}},
            rules_only=False,
        )


def test_valid_saved_custom_game_spec_ignores_invalid_incoming_spec():
    current_spec = complete_custom_game_power_spec()
    invalid_incoming = complete_game_power_spec()
    invalid_incoming["stages"] = invalid_incoming["stages"][:2]
    project = game_project(power_system_spec=current_spec)

    enriched = world_enrichment._merge_enrichment(
        project,
        {"world_blueprint": {"power_system_spec": invalid_incoming}},
        rules_only=False,
    )

    assert enriched.world_blueprint["power_system_spec"] == validate_power_system_spec(
        current_spec,
        novel_type_id="game_webnovel",
    )


def test_invalid_saved_game_spec_does_not_hide_invalid_incoming_spec():
    invalid_current = complete_custom_game_power_spec()
    invalid_current["stages"] = invalid_current["stages"][:2]
    invalid_incoming = complete_game_power_spec()
    invalid_incoming["stages"] = invalid_incoming["stages"][:2]
    project = game_project(power_system_spec=invalid_current)

    with pytest.raises(ValueError, match="stages.minimum_count"):
        world_enrichment._merge_enrichment(
            project,
            {"world_blueprint": {"power_system_spec": invalid_incoming}},
            rules_only=False,
        )


def test_traditional_game_merge_still_rejects_missing_advancement_nodes():
    spec = complete_game_power_spec()
    spec["paths"][0]["advancement_tree"] = spec["paths"][0]["advancement_tree"][:-1]

    with pytest.raises(ValueError, match="game.path_invalid_advancement_tree"):
        world_enrichment._merge_enrichment(
            game_project(),
            {"world_blueprint": {"power_system_spec": spec}},
            rules_only=False,
        )


def game_project(*, power_system_spec=None, power_system=None) -> NovelProject:
    blueprint = {"genre_plugin_ids": ["game_webnovel"], "premise": "旧世界"}
    if power_system_spec is not None:
        blueprint["power_system_spec"] = power_system_spec
    if power_system is not None:
        blueprint["power_system"] = power_system
    return NovelProject(project_id="p-power", title="神域", world_blueprint=blueprint)


def test_world_enrichment_retries_once_with_power_validation_feedback() -> None:
    valid_spec = complete_game_power_spec()
    invalid_spec = deepcopy(valid_spec)
    invalid_spec["stages"] = invalid_spec["stages"][:2]
    requests = []

    class Gateway:
        def complete_stage(self, stage, request):
            requests.append((stage, request))
            spec = invalid_spec if len(requests) == 1 else valid_spec
            return ModelResponse.success(
                request,
                text=json.dumps(
                    {"world_blueprint": {"power_system_spec": spec}},
                    ensure_ascii=False,
                ),
            )

    enriched = world_enrichment._call_world_enrichment_model(
        game_project(),
        rules_only=False,
        model_gateway=Gateway(),
    )

    assert len(requests) == 2
    assert requests[0][0] == requests[1][0] == "planner"
    assert "stages.minimum_count" in requests[1][1].prompt
    assert enriched.world_blueprint["power_system_spec"]["stages"] == valid_spec["stages"]


def test_world_build_modules_are_genre_scoped_and_keep_game_runtime_separate() -> None:
    generic = NovelProject(
        project_id="p-world-modules-generic",
        title="旧城夜话",
        world_blueprint={"genre_plugin_ids": ["suspense"]},
    )
    game = game_project()

    assert [module.module_id for module in world_enrichment.world_build_modules(generic)] == [
        "core_rules",
        "society_and_livelihood",
        "story_engine",
    ]
    assert [module.module_id for module in world_enrichment.world_build_modules(game)] == [
        "core_rules",
        "society_and_livelihood",
        "game_ecology",
        "story_engine",
    ]


def test_world_build_artifacts_are_not_reused_as_model_context() -> None:
    project = NovelProject(
        project_id="p-world-artifact-context",
        title="旧城夜话",
        world_blueprint={
            "premise": "雨夜的旧城里，调解员必须在天亮前找回失踪的当事人。",
            "world_build_artifacts": [{"module_id": "core_rules", "output": {"secret": "不要回传"}}],
        },
    )

    payload = world_enrichment._project_payload(project, chars=240, items=8, depth=4)

    assert "world_build_artifacts" not in payload["world_blueprint"]


def test_modular_world_enrichment_persists_each_module_artifact() -> None:
    power_spec = complete_custom_game_power_spec()
    power_spec["paths"].append(
        {
            **deepcopy(power_spec["paths"][0]),
            "name": "旧物修复",
            "role": "从损坏旧物中还原被抹去的信息",
            "branches": ["公开鉴定", "私下修复"],
        }
    )
    project = NovelProject(
        project_id="p-world-modules-run",
        title="断香炉",
        world_summary="守祠杂役林照从断香炉里看见旧案。",
        current_focus="林照必须保住第一件证物。",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    outputs = {
        "core_rules": {
            "world_rules": ["香火能留下旧案痕迹，但每次动用都会折损寿数。"],
            "constraints": ["证物被毁后不能凭空复原。"],
            "power_system_spec": power_spec,
            "locations": [{"name": "守祠", "description": "林照看守香火与旧物的地方。"}],
            "factions": [{"name": "执事房", "description": "掌握祠内账簿与惩戒权。"}],
        },
        "society_and_livelihood": {
            "locations": [{"name": "守祠", "description": "林照看守香火与旧物的地方。"}],
            "factions": [{"name": "执事房", "description": "掌握祠内账簿与惩戒权。"}],
            "economy_rules": ["香灰、旧物修复与人情债构成基层交换。"],
            "world_systems": {
                "material_base": ["香火与旧物修复材料稀缺。"],
                "institutions": ["祠堂由执事房管理。"],
                "social_order": ["杂役依附祠堂获取生计。"],
                "conflict_engines": ["旧案证物会威胁既得者。"],
                "causal_loops": ["每次修复都会留下新的追查痕迹。"],
            },
            "living_world": {
                "daily_routines": ["杂役每日清扫香案、核对供奉。"],
                "economy": ["香客供奉换取祠堂庇护。"],
                "power_structure": ["执事房决定杂役去留。"],
                "information_network": ["香客与杂役会在后院交换消息。"],
                "information_visibility_rules": ["账簿只向执事开放。"],
                "world_reaction_ladder": ["证物异动先惊动看守，再惊动执事。"],
                "location_functions": ["守祠既是工作地也是证物库。"],
                "timeline": ["每月朔望清点旧物。"],
                "reaction_rules": ["公开修复会提高执事房的警惕。"],
            },
        },
        "story_engine": {
            "opening_arc": {"golden_three_chapters": {}},
            "volume_plan": {"volume_title": "第一卷 断炉旧案", "target_chapters": 50},
            "longform_framework": {"series_premise": "林照靠修复旧物追查被掩埋的旧案。"},
            "progression_ledger": {"protagonist": {"location": "守祠"}},
            "current_arc": "林照先保住证物，再查出是谁想毁掉它。",
        },
    }

    class Gateway:
        def complete_stage(self, stage, request):
            module_id = request.metadata["world_build_module"]
            return ModelResponse.success(
                request,
                text=json.dumps({"world_blueprint": outputs[module_id]}, ensure_ascii=False),
            )

    progress_events = []
    enriched = world_enrichment.enrich_project_world(
        project,
        model_gateway=Gateway(),
        progress_callback=progress_events.append,
    )

    artifacts = enriched.world_blueprint["world_build_artifacts"]
    assert [artifact["module_id"] for artifact in artifacts] == [
        "core_rules",
        "society_and_livelihood",
        "story_engine",
    ]
    assert enriched.world_blueprint["locations"][0]["name"] == "守祠"
    assert enriched.world_blueprint["volume_plan"]["volume_title"] == "第一卷 断炉旧案"
    assert "玩家" not in json.dumps(enriched.world_blueprint, ensure_ascii=False)
    assert [event["status"] for event in progress_events] == [
        "running", "done", "running", "done", "running", "done",
    ]


def test_world_build_module_required_fields_reject_missing_outputs() -> None:
    module = world_enrichment.WorldBuildModule(
        module_id="core_rules",
        title="核心规则",
        fields=("world_rules", "locations"),
        required_fields=("world_rules", "locations"),
        instructions="",
        max_tokens=1024,
    )

    parsed = {"world_blueprint": {"world_rules": ["仅写一条规则"]}}
    with pytest.raises(
        world_enrichment.WorldEnrichmentError,
        match=r"world_build_module_incomplete:core_rules:locations",
    ):
        world_enrichment._module_world_payload(parsed, module)


def test_world_build_module_required_fields_reject_blank_outputs() -> None:
    module = world_enrichment.WorldBuildModule(
        module_id="core_rules",
        title="核心规则",
        fields=("world_rules", "locations"),
        required_fields=("world_rules", "locations"),
        instructions="",
        max_tokens=1024,
    )

    parsed = {"world_blueprint": {"world_rules": ["一条规则"], "locations": []}}
    with pytest.raises(
        world_enrichment.WorldEnrichmentError,
        match=r"world_build_module_incomplete:core_rules:locations",
    ):
        world_enrichment._module_world_payload(parsed, module)


def test_core_rules_module_requires_rules_locations_factions() -> None:
    project = NovelProject(
        project_id="p-required-core",
        title="守祠",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    modules = world_enrichment.world_build_modules(project)
    core = next(module for module in modules if module.module_id == "core_rules")
    assert "world_rules" in core.required_fields
    assert "locations" in core.required_fields
    assert "factions" in core.required_fields


def test_core_rules_module_requires_power_system_spec_for_power_genres() -> None:
    project = NovelProject(
        project_id="p-required-core-power",
        title="网游",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    modules = world_enrichment.world_build_modules(project)
    core = next(module for module in modules if module.module_id == "core_rules")
    assert "power_system_spec" in core.required_fields


def test_society_and_livelihood_module_requires_world_systems_and_living_world() -> None:
    project = NovelProject(
        project_id="p-required-society",
        title="断香炉",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    modules = world_enrichment.world_build_modules(project)
    society = next(module for module in modules if module.module_id == "society_and_livelihood")
    assert "world_systems" in society.required_fields
    assert "living_world" in society.required_fields


def test_story_engine_module_requires_arc_volume_longform() -> None:
    project = NovelProject(
        project_id="p-required-story",
        title="断香炉",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    modules = world_enrichment.world_build_modules(project)
    story = next(module for module in modules if module.module_id == "story_engine")
    assert "opening_arc" in story.required_fields
    assert "volume_plan" in story.required_fields
    assert "longform_framework" in story.required_fields


def test_game_ecology_module_requires_npc_quest_server_map() -> None:
    project = NovelProject(
        project_id="p-required-game",
        title="网游",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )
    modules = world_enrichment.world_build_modules(project)
    ecology = next(module for module in modules if module.module_id == "game_ecology")
    assert "npc_system" in ecology.required_fields
    assert "quest_network" in ecology.required_fields
    assert "server_runtime" in ecology.required_fields
    assert "map_ecology" in ecology.required_fields


def test_world_build_module_complete_payload_passes_required_fields() -> None:
    module = world_enrichment.WorldBuildModule(
        module_id="core_rules",
        title="核心规则",
        fields=("world_rules", "locations"),
        required_fields=("world_rules", "locations"),
        instructions="",
        max_tokens=1024,
    )

    parsed = {
        "world_blueprint": {
            "world_rules": ["香火能留下旧案痕迹。"],
            "locations": [{"name": "守祠"}],
        }
    }
    payload = world_enrichment._module_world_payload(parsed, module)
    assert payload["world_rules"] == ["香火能留下旧案痕迹。"]
    assert payload["locations"] == [{"name": "守祠"}]


@pytest.fixture
def isolated_novel_type_storage(monkeypatch, tmp_path):
    missing = object()
    original_pin = getattr(novel_type_catalog._CONVERSION_KEYS, "pin", missing)
    monkeypatch.setenv(
        "NOVEL_AUTOGROWTH_NOVEL_TYPES_PATH",
        str(tmp_path / "novel-types.json"),
    )
    monkeypatch.setattr(novel_type_catalog, "_SNAPSHOT_TOKEN", None)
    monkeypatch.setattr(novel_type_catalog, "_RECORD_SNAPSHOT", {})
    monkeypatch.setattr(novel_type_catalog, "_CATALOG_SNAPSHOT", {})
    monkeypatch.setattr(
        novel_type_library,
        "_LIBRARY_REVISION",
        novel_type_library._LIBRARY_REVISION,
    )
    monkeypatch.setattr(
        novel_type_library,
        "_LIBRARY_REVISION_WRITER_THREAD_ID",
        novel_type_library._LIBRARY_REVISION_WRITER_THREAD_ID,
    )
    monkeypatch.setattr(
        novel_type_library,
        "_LIBRARY_WRITER_REVISIONS",
        dict(novel_type_library._LIBRARY_WRITER_REVISIONS),
    )
    monkeypatch.setattr(
        novel_type_library,
        "_PATH_LOCKS",
        dict(novel_type_library._PATH_LOCKS),
    )
    yield
    if original_pin is missing:
        if hasattr(novel_type_catalog._CONVERSION_KEYS, "pin"):
            del novel_type_catalog._CONVERSION_KEYS.pin
    else:
        novel_type_catalog._CONVERSION_KEYS.pin = original_pin


def prompt_power_template(prompt: str) -> dict[str, object]:
    prefix = "genre_power_system_template: "
    line = next(line for line in prompt.splitlines() if line.startswith(prefix))
    return json.loads(line.removeprefix(prefix))


def test_world_enrichment_prompt_requests_canonical_spec_and_carries_template_and_current_spec():
    current_spec = complete_game_power_spec()
    project = game_project(power_system_spec=current_spec)

    prompt = world_enrichment._build_prompt(project)

    assert "power_system_spec" in prompt
    assert "genre_power_system_template" in prompt
    assert "Lv.10正式转职、Lv.30选择职业分支、Lv.60晋升传承职业" in prompt
    assert "class_advancement_tiers" in prompt
    assert "advancement_tree" in prompt
    assert prompt_power_template(prompt)["fixed_milestones"] == [1, 10, 20, 30, 60]
    context_line = next(
        line for line in prompt.splitlines() if line.startswith("当前项目数据：")
    )
    context = json.loads(context_line.removeprefix("当前项目数据："))
    assert context["world_blueprint"]["power_system_spec"]["name"] == "神域职业体系"
    for field in (
        "name", "origin", "attributes", "paths", "stages", "skills", "equipment",
        "resources", "advancement", "costs", "counters", "boundaries",
        "social_impact", "visibility", "continuity_ledger",
    ):
        assert field in prompt


def test_level_less_game_prompt_keeps_machine_contract_without_fixed_class_levels():
    prompt = world_enrichment._build_prompt(game_project())

    assert (
        "class_advancement_tiers: "
        "[{level,name,purpose,common_requirements,failure_rule}]"
    ) in prompt
    assert "advancement_tree: [{level,tier_name,options}]" in prompt
    assert "机器可读 JSON 契约" in prompt
    for fixed_assumption in (
        "Lv.10",
        "Lv.30",
        "Lv.60",
        "基础职业",
        "隐藏职业",
        "转职任务",
    ):
        assert fixed_assumption not in prompt


def test_generic_world_enrichment_prompt_omits_game_only_world_contracts():
    project = NovelProject(
        project_id="p-realistic-generic",
        title="巷口早饭店",
        seed_outline="失业厨师回到老街接手一家早餐店。",
        world_blueprint={"genre_plugin_ids": ["generic_webnovel"]},
    )

    prompt = world_enrichment._build_prompt(project)

    assert "power_system_spec 必须" not in prompt
    assert "genre_power_system_template:" not in prompt
    assert "power_system" not in prompt
    assert "panel_rules" not in prompt
    assert "quest_rules" not in prompt
    assert "server_runtime" not in prompt
    assert "player_ecology" not in prompt
    assert "npc_system" not in prompt
    assert "quest_network" not in prompt
    assert "只整理世界观、角色档案、关系网、类型规则和后续写作约束" in prompt


def test_realistic_suspense_world_enrichment_does_not_invent_power_system():
    project = NovelProject(
        project_id="p-realistic-suspense",
        title="明天的调解书",
        seed_outline="社区调解员收到预告次日事故的匿名调解书，并靠证据追查来源。",
        world_blueprint={"genre_plugin_ids": ["suspense"]},
    )

    prompt = world_enrichment._build_prompt(project)

    assert "power_system_spec" not in prompt
    assert "genre_power_system_template:" not in prompt


def test_realistic_suspense_world_enrichment_drops_generated_power_system():
    project = NovelProject(
        project_id="p-realistic-suspense-merge",
        title="明天的调解书",
        world_blueprint={"genre_plugin_ids": ["suspense"]},
    )

    enriched = world_enrichment._merge_enrichment(
        project,
        {
            "world_blueprint": {
                "premise": "调解员追查事故预告的来源。",
                "power_system": ["超凡调查"],
                "power_system_spec": {"name": "超凡调查体系"},
            }
        },
        rules_only=False,
    )

    assert "power_system" not in enriched.world_blueprint
    assert "power_system_spec" not in enriched.world_blueprint


def test_generic_world_enrichment_drops_game_only_generated_sections():
    project = NovelProject(
        project_id="p-realistic-merge",
        title="巷口早饭店",
        world_blueprint={"genre_plugin_ids": ["generic_webnovel"]},
    )

    enriched = world_enrichment._merge_enrichment(
        project,
        {
            "world_blueprint": {
                "premise": "失业厨师接手欠租早餐店。",
                "server_runtime": {"phase": "开服期"},
                "npc_system": {"npcs": [{"name": "房东"}]},
                "quest_network": {"active_chains": [{"name": "补租任务"}]},
                "map_ecology": {"zones": [{"name": "早餐店"}]},
                "living_world": {"player_ecology": ["主角是低位经营者"]},
                "constraints": [
                    "不写成玄幻系统文，所有金手指必须表现为现实资源。",
                    "不写超自然，不出现凭空暴富或万能系统。",
                    "所有爽点来自专业能力、证据链推进和阶段性谈判成果。",
                    "人物借钱必须说明还款压力。",
                ],
            }
        },
        rules_only=False,
    )

    assert "power_system_spec" not in enriched.world_blueprint
    assert "power_system" not in enriched.world_blueprint
    assert "panel_rules" not in enriched.world_blueprint
    assert "quest_rules" not in enriched.world_blueprint
    assert "server_runtime" not in enriched.world_blueprint
    assert "npc_system" not in enriched.world_blueprint
    assert "quest_network" not in enriched.world_blueprint
    assert "map_ecology" not in enriched.world_blueprint
    assert "player_ecology" not in enriched.world_blueprint["living_world"]
    assert "不写成玄幻系统文，所有金手指必须表现为现实资源。" not in enriched.author_constraints
    assert "不写超自然，不出现凭空暴富或万能系统。" not in enriched.author_constraints
    assert "所有爽点来自专业能力、证据链推进和阶段性谈判成果。" not in enriched.author_constraints
    assert "人物借钱必须说明还款压力。" in enriched.author_constraints


def test_game_world_fallbacks_are_project_neutral_when_model_omits_optional_modules():
    power_spec = complete_game_power_spec()
    project = NovelProject(
        project_id="p-game-neutral-fallbacks",
        title="星海远征",
        seed_outline="周行以游戏ID行舟进入星海远征，从潮汐港接下第一份护航委托。",
        world_summary="周行在星海远征中靠航线判断积累优势。",
        current_focus="行舟准备完成潮汐港的护航委托。",
        world_blueprint={
            "genre_plugin_ids": ["game_webnovel"],
            "premise": "行舟从潮汐港起步，在开放世界中探索航线。",
            "power_system_spec": power_spec,
            "living_world": {"daily_routines": ["潮汐港玩家按航班组队承接护航委托。"]},
            "world_systems": {"material_base": ["潮汐矿用于修理舰船与制作导航组件。"]},
            "npc_system": {
                "npcs": [{"name": "港务员林岚", "role": "护航委托登记员"}],
            },
            "quest_network": {
                "active_chains": [{"name": "潮汐护航", "description": "护送补给船离港。"}],
            },
            "server_runtime": {"phase": "首批玩家正在探索近海航线。"},
            "map_ecology": {
                "zones": [{"name": "潮汐港", "description": "新玩家集结的港口。"}],
            },
            "opening_arc": {
                "golden_three_chapters": {
                    "chapter_1": {"purpose": "周行以行舟的身份完成首次护航。"},
                },
            },
            "volume_plan": {"volume_title": "第一卷 潮汐启航"},
            "longform_framework": {
                "series_premise": "周行沿未知航线逐步建立自己的远征队。",
            },
            "progression_ledger": {"protagonist": {"location": "潮汐港"}},
        },
        character_profiles=[
            {
                "name": "周行",
                "game_id": "行舟",
                "role": "主角",
                "motivation": "找到失踪的远征队。",
            }
        ],
    )

    enriched = world_enrichment._merge_enrichment(
        project,
        {
            "world_summary": "周行在星海远征中追查失踪航线。",
            "current_focus": "行舟从潮汐港接取首个护航委托。",
            "world_blueprint": {
                "premise": "行舟从潮汐港起步，在开放世界中探索航线。",
                "power_system_spec": deepcopy(power_spec),
            },
        },
        rules_only=False,
    )

    serialized = json.dumps(enriched.model_dump(mode="json"), ensure_ascii=False)
    assert not any(
        legacy_term in serialized
        for legacy_term in (
            "苏叶",
            "夜烬",
            "千倍爆率",
            "混沌之种",
            "灰烬村",
            "西林狼坡",
            "洛婶",
            "艾伦",
            "白袍",
        )
    )
    assert enriched.character_profiles[0]["name"] == "周行"
    assert enriched.character_profiles[0]["game_id"] == "行舟"
    assert len(enriched.character_profiles) == 1
    assert "潮汐港玩家按航班组队承接护航委托。" in enriched.world_blueprint["living_world"]["daily_routines"]
    assert "潮汐矿用于修理舰船与制作导航组件。" in enriched.world_blueprint["world_systems"]["material_base"]
    assert enriched.world_blueprint["npc_system"]["npcs"][0]["name"] == "港务员林岚"
    assert enriched.world_blueprint["quest_network"]["active_chains"][0]["name"] == "潮汐护航"
    assert enriched.world_blueprint["server_runtime"]["phase"] == "首批玩家正在探索近海航线。"
    assert enriched.world_blueprint["map_ecology"]["zones"][0]["name"] == "潮汐港"
    assert enriched.world_blueprint["opening_arc"]["golden_three_chapters"]["chapter_1"]["purpose"] == "周行以行舟的身份完成首次护航。"
    assert enriched.world_blueprint["volume_plan"]["volume_title"] == "第一卷 潮汐启航"
    assert enriched.world_blueprint["longform_framework"]["series_premise"] == "周行沿未知航线逐步建立自己的远征队。"
    assert enriched.world_blueprint["progression_ledger"]["protagonist"]["location"] == "潮汐港"


def test_game_world_enrichment_leaves_characters_empty_when_no_cards_are_available():
    power_spec = complete_game_power_spec()
    project = NovelProject(
        project_id="p-game-no-character-cards",
        title="星海远征",
        world_blueprint={
            "genre_plugin_ids": ["game_webnovel"],
            "premise": "玩家从未知港口开始探索。",
            "power_system_spec": power_spec,
        },
    )

    enriched = world_enrichment._merge_enrichment(
        project,
        {
            "world_blueprint": {
                "premise": "玩家从未知港口开始探索。",
                "power_system_spec": deepcopy(power_spec),
            },
        },
        rules_only=False,
    )

    assert enriched.character_profiles == []


def test_complete_model_game_entities_do_not_receive_default_entries():
    power_spec = complete_game_power_spec()
    project = NovelProject(
        project_id="p-game-model-entities",
        title="雾海漫游",
        world_blueprint={
            "genre_plugin_ids": ["game_webnovel"],
            "premise": "玩家驾驶纸舟探索雾海。",
            "power_system_spec": power_spec,
        },
    )

    enriched = world_enrichment._merge_enrichment(
        project,
        {
            "world_blueprint": {
                "premise": "玩家驾驶纸舟探索雾海。",
                "power_system_spec": deepcopy(power_spec),
                "npc_system": {
                    "npcs": [{"name": "摆渡人", "role": "航路见证者"}],
                    "rules": ["角色只知道亲眼见过的航路。"],
                },
                "quest_network": {
                    "quest_types": ["航路委托"],
                    "active_chains": [{"name": "雾钟回响", "description": "追踪雾中钟声。"}],
                    "reward_rules": ["奖励只提供新航路信息。"],
                    "failure_costs": ["错过潮汐窗口。"],
                },
                "map_ecology": {
                    "zones": [{"name": "纸舟码头", "description": "探索者停靠处。"}],
                    "rules": ["地点变化由潮汐驱动。"],
                },
            },
        },
        rules_only=False,
    )

    assert [item["name"] for item in enriched.world_blueprint["npc_system"]["npcs"]] == ["摆渡人"]
    assert [item["name"] for item in enriched.world_blueprint["quest_network"]["active_chains"]] == ["雾钟回响"]
    assert [item["name"] for item in enriched.world_blueprint["map_ecology"]["zones"]] == ["纸舟码头"]


def test_saved_game_world_values_win_model_conflicts_and_ledger_does_not_regress():
    power_spec = complete_game_power_spec()
    project = NovelProject(
        project_id="p-game-current-priority",
        title="雾海漫游",
        world_summary="已保存世界摘要",
        current_focus="已保存当前目标",
        world_blueprint={
            "genre_plugin_ids": ["game_webnovel"],
            "premise": "已保存世界前提",
            "power_system_spec": power_spec,
            "server_runtime": {"phase": "已保存服务器阶段"},
            "volume_plan": {"volume_title": "第一卷 雾海", "target_chapters": 60},
            "world_systems": {"material_base": ["已保存资源规则"]},
            "opening_arc": {
                "golden_three_chapters": {
                    "chapter_1": {"purpose": "已保存开篇目标"},
                },
            },
            "progression_ledger": {
                "protagonist": {"level": 7, "location": "雾海深处"},
                "economy": {"inventory": ["潮汐罗盘"]},
                "skills": {"active": []},
            },
        },
    )

    enriched = world_enrichment._merge_enrichment(
        project,
        {
            "world_summary": "模型新摘要",
            "current_focus": "模型新目标",
            "world_blueprint": {
                "premise": "模型新前提",
                "power_system_spec": deepcopy(power_spec),
                "server_runtime": {"phase": "模型阶段"},
                "volume_plan": {"volume_title": "模型卷名", "target_chapters": 50},
                "world_systems": {"material_base": ["模型资源规则"]},
                "opening_arc": {
                    "golden_three_chapters": {
                        "chapter_1": {
                            "purpose": "模型改写开篇目标",
                            "ending_hook": "模型补充的雾钟钩子",
                        },
                    },
                },
                "progression_ledger": {
                    "protagonist": {"level": 1, "location": "模型起点"},
                    "economy": {"inventory": []},
                    "skills": {"active": ["模型新增能力"]},
                },
            },
        },
        rules_only=False,
    )

    assert enriched.world_summary == "已保存世界摘要"
    assert enriched.current_focus == "已保存当前目标"
    assert enriched.world_blueprint["premise"] == "已保存世界前提"
    assert enriched.world_blueprint["server_runtime"]["phase"] == "已保存服务器阶段"
    assert enriched.world_blueprint["volume_plan"]["volume_title"] == "第一卷 雾海"
    assert enriched.world_blueprint["volume_plan"]["target_chapters"] == 60
    assert enriched.world_blueprint["world_systems"]["material_base"][0] == "已保存资源规则"
    chapter_1 = enriched.world_blueprint["opening_arc"]["golden_three_chapters"]["chapter_1"]
    assert chapter_1["purpose"] == "已保存开篇目标"
    assert chapter_1["ending_hook"] == "模型补充的雾钟钩子"
    assert enriched.world_blueprint["progression_ledger"]["protagonist"]["level"] == 7
    assert enriched.world_blueprint["progression_ledger"]["protagonist"]["location"] == "雾海深处"
    assert enriched.world_blueprint["progression_ledger"]["economy"]["inventory"] == ["潮汐罗盘"]
    assert enriched.world_blueprint["progression_ledger"]["skills"]["active"] == []


def test_saved_character_fields_win_while_model_fills_missing_fields_by_identity():
    power_spec = complete_game_power_spec()
    project = NovelProject(
        project_id="p-game-character-merge",
        title="雾海漫游",
        world_blueprint={
            "genre_plugin_ids": ["game_webnovel"],
            "premise": "玩家驾驶纸舟探索雾海。",
            "power_system_spec": power_spec,
        },
        character_profiles=[
            {
                "name": "周行",
                "game_id": "行舟",
                "role": "主角",
                "motivation": "寻找失踪航路",
            }
        ],
    )

    enriched = world_enrichment._merge_enrichment(
        project,
        {
            "world_blueprint": {
                "premise": "玩家驾驶纸舟探索雾海。",
                "power_system_spec": deepcopy(power_spec),
            },
            "character_profiles": [
                {
                    "name": "模型改名",
                    "game_id": "行舟",
                    "role": "模型角色",
                    "motivation": "模型改写动机",
                    "current_state": "刚刚听见雾钟",
                },
                {"name": "顾遥", "game_id": "望潮", "role": "同行者"},
            ],
        },
        rules_only=False,
    )

    assert len(enriched.character_profiles) == 2
    assert enriched.character_profiles[0]["name"] == "周行"
    assert enriched.character_profiles[0]["game_id"] == "行舟"
    assert enriched.character_profiles[0]["role"] == "主角"
    assert enriched.character_profiles[0]["motivation"] == "寻找失踪航路"
    assert enriched.character_profiles[0]["current_state"] == "刚刚听见雾钟"
    assert enriched.character_profiles[1]["name"] == "顾遥"


def test_character_merge_matches_saved_name_when_model_adds_game_id():
    current = [{"name": "周行", "role": "主角", "motivation": "探索雾海"}]
    incoming = [{"name": "周行", "game_id": "行舟", "motivation": "模型改写"}]

    merged = world_enrichment._merge_character_profiles(current, incoming)

    assert len(merged) == 1
    assert merged[0]["name"] == "周行"
    assert merged[0]["game_id"] == "行舟"
    assert merged[0]["motivation"] == "探索雾海"


def test_default_game_volume_is_a_complete_non_final_volume():
    plan = world_enrichment._default_volume_plan(
        NovelProject(project_id="p-game-volume-default", title="雾海漫游"),
        [{"id": "game_webnovel"}],
    )

    assert plan["target_chapters"] >= 50
    assert plan["phase_beats"][-1]["range"].endswith(str(plan["target_chapters"]))


def test_saved_short_non_final_game_volume_is_extended_to_fifty_chapters():
    project = game_project()
    current_world = {
        "volume_plan": {
            "volume_title": "旧版首卷",
            "target_chapters": 30,
            "phase_beats": [{"range": "1-30", "purpose": "完成旧版首卷目标"}],
        }
    }

    plan = world_enrichment._merge_volume_plan(
        project, {}, current_world, [{"id": "game_webnovel"}]
    )

    assert plan["target_chapters"] == 50
    assert plan["phase_beats"][0] == {
        "range": "1-30",
        "purpose": "完成旧版首卷目标",
    }
    assert plan["phase_beats"][-1]["range"] == "31-50"


def test_saved_short_final_game_volume_remains_short():
    project = game_project()
    current_world = {
        "volume_plan": {
            "volume_title": "终卷",
            "target_chapters": 30,
            "is_final_arc": True,
            "phase_beats": [{"range": "1-30", "purpose": "完成全书收尾"}],
        }
    }

    plan = world_enrichment._merge_volume_plan(
        project, {}, current_world, [{"id": "game_webnovel"}]
    )

    assert plan["target_chapters"] == 30
    assert plan["is_final_arc"] is True
    assert plan["phase_beats"] == [{"range": "1-30", "purpose": "完成全书收尾"}]


def test_relationship_graph_merges_by_stable_identity_with_saved_values_first():
    saved = [
        {
            "source": "周行",
            "target": "顾遥",
            "bond": "旧日同伴",
            "tension": "",
            "trust": 70,
        }
    ]
    incoming = [
        {
            "source": "周行",
            "target": "顾遥",
            "bond": "模型改写",
            "tension": 25,
            "trust": 10,
        },
        {"source": "顾遥", "target": "雾港议会", "bond": "观察对象", "trust": 15},
    ]

    project = game_project(power_system_spec=complete_game_power_spec())
    project.relationship_graph = saved
    enriched = world_enrichment._merge_enrichment(
        project,
        {"world_blueprint": {"relationship_graph": incoming}},
        rules_only=True,
    )

    assert enriched.relationship_graph == [
        {
            "source": "周行",
            "target": "顾遥",
            "bond": "旧日同伴",
            "tension": 25.0,
            "trust": 70.0,
        },
        {
            "source": "顾遥",
            "target": "雾港议会",
            "bond": "观察对象",
            "tension": 0.0,
            "trust": 15.0,
        },
    ]


def test_neutral_game_fallbacks_do_not_assume_levels_markets_reality_or_classic_maps():
    project = NovelProject(
        project_id="p-neutral-game-shape",
        title="雾海漫游",
        world_blueprint={
            "genre_plugin_ids": ["game_webnovel"],
            "premise": "周行驾驶纸舟探索不断变化的雾海。",
        },
        character_profiles=[{"name": "周行", "game_id": "行舟", "role": "主角"}],
    )

    enriched = world_enrichment._merge_enrichment(
        project,
        {"world_blueprint": {"premise": "周行驾驶纸舟探索不断变化的雾海。"}},
        rules_only=True,
    )

    serialized = json.dumps(enriched.world_blueprint, ensure_ascii=False)
    for assumption in (
        "10级",
        "铜币",
        "银币",
        "法杖",
        "兽皮",
        "铁匠铺",
        "新手村",
        "主城",
        "清场",
        "跨服裂隙",
        "现实资本",
        "虚拟文明",
        "交易行",
        "现实线",
    ):
        assert assumption not in serialized


def test_world_enrichment_prompt_bounds_hostile_maximum_project_context():
    class Hostile:
        def __str__(self):
            raise RuntimeError("must not stringify hostile context")

    spec = complete_game_power_spec()
    long_text = "界" * 240
    for field in (
        "origin", "skills", "equipment", "resources", "advancement", "costs",
        "counters", "boundaries", "social_impact", "visibility", "continuity_ledger",
    ):
        spec[field] = [f"{field}-{index}-{long_text}" for index in range(64)]
    spec["continuity_ledger"][:6] = [
        "level", "class_path", "skills", "equipment", "resources", "conditions"
    ]
    spec["attributes"] = [
        {"name": f"属性{index}", "effect": long_text} for index in range(64)
    ]
    for path in spec["paths"]:
        for field in (
            "core_attributes", "weapons", "armor", "strengths", "weaknesses",
            "skill_categories", "branches", "advancement",
        ):
            path[field] = [f"{field}-{index}-{long_text}" for index in range(64)]
    spec["hostile_unknown"] = Hostile()
    validate_power_system_spec(spec, novel_type_id="game_webnovel")
    project = NovelProject(
        project_id="p-hostile-prompt",
        title="边界项目",
        seed_outline=long_text * 20,
        world_summary="核心前提必须保留",
        world_blueprint={
            "genre_plugin_ids": ["game_webnovel"],
            "premise": "核心前提必须保留",
            "power_system_spec": spec,
            "oversized_systems": [
                {"name": f"系统{index}", "details": [long_text] * 80}
                for index in range(80)
            ],
            "hostile": Hostile(),
        },
        character_profiles=[
            {"name": f"角色{index}", "notes": [long_text] * 80}
            for index in range(80)
        ],
    )

    prompt = world_enrichment._build_prompt(project)

    context_prefix = "当前项目数据："
    context_line = next(line for line in prompt.splitlines() if line.startswith(context_prefix))
    context = json.loads(context_line.removeprefix(context_prefix))
    serialized_context = json.dumps(
        context, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    power_slice = context["world_blueprint"]["power_system_spec"]
    assert len(prompt) <= 30_000
    assert len(serialized_context) <= 24_000
    assert context["title"] == "边界项目"
    assert context["world_blueprint"]["genre_plugin_ids"] == ["game_webnovel"]
    assert context["world_blueprint"]["premise"] == "核心前提必须保留"
    assert power_slice["name"] == "神域职业体系"
    assert len(power_slice["stages"]) >= 2
    assert power_slice["stages"][0]["level"] == 1
    assert len(power_slice["paths"]) >= 2
    assert power_slice["paths"][0]["name"] == "战士"
    assert power_slice != spec


def test_world_enrichment_prompt_uses_explicit_custom_runtime_power_template(
    isolated_novel_type_storage,
):
    NovelTypeLibrary().create(
        {
            "id": "arena_progression",
            "name": "竞技成长",
            "power_system_template": {
                "system_form": "赛季段位与异能体系",
                "minimum_path_count": 4,
            },
        }
    )
    project = NovelProject(
        project_id="p-custom-template",
        title="竞技场",
        world_blueprint={"genre_plugin_ids": ["arena_progression"]},
    )
    persisted = NovelTypeLibrary().get("arena_progression")

    template = prompt_power_template(world_enrichment._build_prompt(project))

    assert persisted is not None
    assert template == compact_power_system_template(persisted.power_system_template)
    assert template["system_form"] == "赛季段位与异能体系"
    assert template["minimum_path_count"] == 4


def test_level_less_game_prompt_neutralizes_persisted_builtin_template_assumptions(
    isolated_novel_type_storage,
):
    template_override = copy_power_system_template("game_webnovel")
    template_override["system_form"] = "运行时覆盖职业体系"
    template_override["minimum_path_count"] = 8
    NovelTypeLibrary().update(
        "game_webnovel",
        {"power_system_template": template_override},
    )
    project = NovelProject(
        project_id="p-builtin-template",
        title="覆盖测试",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )
    persisted = NovelTypeLibrary().get("game_webnovel")

    template = prompt_power_template(world_enrichment._build_prompt(project))

    assert persisted is not None
    assert template["required_sections"] == compact_power_system_template(
        persisted.power_system_template
    )["required_sections"]
    assert template["system_form"] == "项目自定义的游戏成长或行动体系"
    assert template["minimum_path_count"] == 1
    assert template["fixed_milestones"] == []


def test_world_enrichment_prompt_budgets_persisted_huge_custom_template(
    isolated_novel_type_storage,
):
    huge = "超长运行时模板" * 500
    NovelTypeLibrary().create(
        {
            "id": "huge_runtime_type",
            "name": "超大运行时类型",
            "power_system_template": {
                "system_form": "保留体系形式-" + huge,
                "required_sections": [
                    "origin", "stages", "paths", "skills", "resources", "costs",
                    "counters", "boundaries", "continuity_ledger",
                ],
                "progression_shape": {
                    f"stage_{index}": [huge for _ in range(20)]
                    for index in range(20)
                },
                "branching_rules": [huge for _ in range(40)],
                "resource_rules": [huge for _ in range(40)],
                "cost_rules": [huge for _ in range(40)],
                "conflict_rules": [huge for _ in range(40)],
                "ledger_fields": [huge for _ in range(40)],
                "quality_checks": [huge for _ in range(40)],
                "minimum_path_count": 7,
                "fixed_milestones": [1, 10, 20, 40, 80],
            },
        }
    )
    persisted = NovelTypeLibrary().get("huge_runtime_type")
    assert persisted is not None
    expected = novel_type_prompt_context(persisted)["genre_power_system_template"]
    project = NovelProject(
        project_id="p-huge-template",
        title="超大模板项目",
        seed_outline=huge,
        world_summary="核心前提",
        world_blueprint={
            "genre_plugin_ids": ["huge_runtime_type"],
            "premise": "核心前提",
            "oversized": [huge for _ in range(100)],
        },
    )

    prompt = world_enrichment._build_prompt(project)

    template = prompt_power_template(prompt)
    context_prefix = "当前项目数据："
    context_line = next(line for line in prompt.splitlines() if line.startswith(context_prefix))
    context = json.loads(context_line.removeprefix(context_prefix))
    assert len(prompt) <= world_enrichment._FINAL_PROMPT_MAX
    assert template == expected
    assert template["system_form"].startswith("保留体系形式-")
    assert template["minimum_path_count"] == 7
    assert template["fixed_milestones"] == [1, 10, 20, 40, 80]
    assert context["title"] == "超大模板项目"
    assert context["world_blueprint"]["genre_plugin_ids"] == ["huge_runtime_type"]
    assert context["world_blueprint"]["premise"] == "核心前提"


def test_world_enrichment_prompt_rejects_fixed_instructions_over_budget(monkeypatch):
    monkeypatch.setattr(world_enrichment, "_FINAL_PROMPT_MAX", 100)
    project = NovelProject(
        project_id="p-fixed-overflow",
        title="固定指令超限",
        world_blueprint={"genre_plugin_ids": ["generic_webnovel"]},
    )

    with pytest.raises(
        world_enrichment.WorldEnrichmentError,
        match=r"^world_enrichment_prompt_fixed_instructions_exceed_budget$",
    ):
        world_enrichment._build_prompt(project)


def test_valid_game_spec_initializes_structured_module_without_replacing_saved_premise():
    incoming_spec = complete_game_power_spec()
    project = game_project(power_system=["旧版摘要原文"])

    enriched = world_enrichment._merge_enrichment(
        project,
        {"world_blueprint": {"premise": "新世界", "power_system_spec": incoming_spec}},
        rules_only=False,
    )

    assert enriched.world_blueprint["power_system_spec"] == incoming_spec
    assert enriched.world_blueprint["power_system"] == legacy_power_summary(incoming_spec)
    assert enriched.world_blueprint["premise"] == "旧世界"


def test_invalid_incoming_spec_rejects_before_any_partial_world_change():
    project = game_project(power_system=["旧版摘要原文"])
    before = project.model_dump()

    with pytest.raises(ValueError, match=r"^invalid_power_system_spec:") as caught:
        world_enrichment._merge_enrichment(
            project,
            {"world_blueprint": {"premise": "不得保存", "power_system_spec": {}}},
            rules_only=False,
        )

    assert "name" in str(caught.value)
    assert "stages.minimum_count" in str(caught.value)
    assert project.model_dump() == before


def test_full_enrichment_rejects_omitted_spec_without_valid_current_spec():
    project = game_project(power_system=["仅有旧版设定"])

    with pytest.raises(ValueError, match=r"^invalid_power_system_spec:"):
        world_enrichment._merge_enrichment(
            project,
            {"world_blueprint": {"premise": "不得保存"}},
            rules_only=False,
        )

    assert project.world_blueprint["premise"] == "旧世界"


def test_omitted_spec_preserves_valid_current_spec_and_legacy_list_verbatim():
    current_spec = complete_game_power_spec()
    legacy = ["手写摘要一", "手写摘要二"]
    project = game_project(power_system_spec=current_spec, power_system=legacy)

    enriched = world_enrichment._merge_enrichment(
        project,
        {"world_blueprint": {"premise": "新世界"}},
        rules_only=False,
    )

    assert enriched.world_blueprint["power_system_spec"] == current_spec
    assert enriched.world_blueprint["power_system"] == legacy
    assert enriched.world_blueprint["power_system_spec"] is not current_spec
    assert enriched.world_blueprint["power_system"] is not legacy


def test_unchanged_incoming_spec_preserves_current_legacy_list_verbatim():
    current_spec = complete_game_power_spec()
    legacy = ["作者手写摘要", "保持字面顺序"]
    project = game_project(power_system_spec=current_spec, power_system=legacy)

    enriched = world_enrichment._merge_enrichment(
        project,
        {"world_blueprint": {"power_system_spec": deepcopy(current_spec)}},
        rules_only=False,
    )

    assert enriched.world_blueprint["power_system_spec"] == current_spec
    assert enriched.world_blueprint["power_system"] == legacy


def test_invalid_incoming_spec_is_ignored_when_current_spec_is_valid():
    current_spec = complete_game_power_spec()
    project = game_project(power_system_spec=current_spec, power_system=["当前摘要"])

    enriched = world_enrichment._merge_enrichment(
        project,
        {"world_blueprint": {"power_system_spec": {"name": "残缺体系"}}},
        rules_only=False,
    )

    assert enriched.world_blueprint["power_system_spec"] == current_spec
    assert enriched.world_blueprint["power_system"] == ["当前摘要"]
    assert project.world_blueprint["power_system_spec"] == current_spec
    assert project.world_blueprint["power_system"] == ["当前摘要"]


def test_incoming_spec_is_deep_copied_without_aliasing_response_or_project():
    incoming_spec = complete_game_power_spec()
    project = game_project(power_system=["旧摘要"])

    enriched = world_enrichment._merge_enrichment(
        project,
        {"world_blueprint": {"power_system_spec": incoming_spec}},
        rules_only=False,
    )
    enriched.world_blueprint["power_system_spec"]["paths"][0]["branches"].append("结果修改")

    assert "结果修改" not in incoming_spec["paths"][0]["branches"]
    assert "power_system_spec" not in project.world_blueprint


def test_rules_only_enrichment_keeps_legacy_only_power_system_without_inventing_spec():
    project = game_project(power_system=["旧版规则原文"])

    enriched = world_enrichment._merge_enrichment(
        project,
        {"world_blueprint": {"economy_rules": ["新经济规则"]}},
        rules_only=True,
    )

    assert enriched.world_blueprint["power_system"] == ["旧版规则原文"]
    assert "power_system_spec" not in enriched.world_blueprint


def test_world_enrichment_tolerates_text_in_relationship_score_fields():
    relationships = world_enrichment._as_relationships(
        [
            {
                "source": "林越",
                "target": "调查局",
                "bond": "互相试探",
                "trust": "是否备案、是否隐瞒能力、是否接受任务",
                "tension": "120",
            }
        ],
        48,
    )

    assert relationships == [
        {
            "source": "林越",
            "target": "调查局",
            "bond": "互相试探",
            "trust": 0.0,
            "tension": 100.0,
        }
    ]


def test_project_world_enrichment_updates_project(monkeypatch, tmp_path):
    monkeypatch.setattr(story_routes, "store", SQLiteStoryStore(str(tmp_path / "stories.db")))
    client = TestClient(app)
    project_id = "p-enrich-test"
    client.post(
        "/projects",
        json={
            "project_id": project_id,
            "title": "Enrich Test",
            "world_summary": "A thin imported world.",
            "current_focus": "Prepare before chapter one.",
            "world_blueprint": {"premise": "A thin imported world."},
            "character_profiles": [{"name": "Lin Yue", "motivation": "Find the clue."}],
            "relationship_graph": [],
        },
    )

    def fake_enrich(project):
        project.world_blueprint = {
            "premise": "A deepened imported world.",
            "world_rules": ["The first clue must create pressure."],
            "power_system": ["Influence grows through secrets."],
            "progression_rules": ["Power must grow through paid clues."],
            "economy_rules": ["Clues have changing market prices."],
            "quest_rules": ["Each clue has a failure cost."],
            "faction_rules": ["Rivals react to visible progress."],
            "panel_rules": ["Status feedback stays short."],
            "chapter_formula": ["Every chapter closes a small gain loop."],
            "forbidden_breaks": ["Do not skip costs."],
            "locations": [{"name": "Ink Shop", "description": "The first scene anchor."}],
            "factions": [],
            "current_arc": "The lead prepares before chapter one.",
            "constraints": [],
            "relationship_graph": [{"source": "Lin Yue", "target": "Ink Shop", "bond": "investigates"}],
        }
        project.character_profiles = [
            {
                "name": "Lin Yue",
                "role": "protagonist",
                "motivation": "Find the clue before rivals erase it.",
                "current_state": "Ready for chapter one.",
            }
        ]
        project.relationship_graph = project.world_blueprint["relationship_graph"]
        project.world_summary = "A deepened imported world."
        return project

    monkeypatch.setattr(story_routes, "enrich_project_world", fake_enrich)

    response = client.post(f"/projects/{project_id}/enrich-world")

    assert response.status_code == 200
    payload = response.json()
    assert payload["world_blueprint"]["premise"] == "A deepened imported world."
    assert payload["pipeline_stage"] == "world_ready"
    assert payload["world_blueprint"]["progression_rules"] == ["Power must grow through paid clues."]
    assert payload["character_profiles"][0]["motivation"] == "Find the clue before rivals erase it."
    assert payload["relationship_graph"][0]["target"] == "Ink Shop"


def test_project_rulebook_enrichment_allowed_after_story_started(monkeypatch, tmp_path):
    monkeypatch.setattr(story_routes, "store", SQLiteStoryStore(str(tmp_path / "stories.db")))
    client = TestClient(app)
    project_id = "p-rulebook-test"
    story_id = "s-rulebook-test"
    client.post(
        "/stories",
        json={
            "story_id": story_id,
            "outline": "A game world with levels and guilds.",
            "genre": "网游",
            "style": "升级流",
            "characters": [{"name": "Su Ye", "role": "protagonist", "goals": ["hide the talent"], "frozen": False}],
        },
    )
    client.post(
        "/projects",
        json={
            "project_id": project_id,
            "title": "Rulebook Test",
            "world_summary": "A game world.",
            "current_focus": "Keep the hidden talent secret.",
            "active_story_id": story_id,
        },
    )

    def fake_enrich(project):
        project.world_blueprint = {
            **project.world_blueprint,
            "premise": "A game world.",
            "progression_rules": ["Levels and EXP must stay consistent."],
            "economy_rules": ["Rare drops need anonymous selling risk."],
            "constraints": ["Every chapter needs gain and pressure."],
        }
        project.author_constraints = ["Every chapter needs gain and pressure."]
        return project

    monkeypatch.setattr(story_routes, "enrich_project_rulebook", fake_enrich)

    response = client.post(f"/projects/{project_id}/enrich-rulebook")

    assert response.status_code == 200
    payload = response.json()
    assert payload["pipeline_stage"] == "simulating"
    assert payload["status"] == "simulating"
    assert payload["author_constraints"] == ["Every chapter needs gain and pressure."]
    assert payload["world_blueprint"]["economy_rules"] == ["Rare drops need anonymous selling risk."]


def test_project_world_facts_include_living_world_reactions():
    project = NovelProject(
        project_id="p-world-facts",
        title="Living World",
        world_summary="A market-driven starter town.",
        world_blueprint={
            "living_world": {
                "daily_routines": ["商人玩家每天盯交易行价差。"],
                "information_network": {"channels": ["交易行价格榜"]},
                "reaction_rules": ["大量低价材料会引起公会外围追踪。"],
            }
        },
    )

    facts = _project_world_facts(project)

    assert "世界摘要：A market-driven starter town." in facts
    assert "日常运转：商人玩家每天盯交易行价差。" in facts
    assert "消息渠道：交易行价格榜" in facts
    assert "世界反应：大量低价材料会引起公会外围追踪。" in facts


def test_project_generation_syncs_explicit_xianxia_context_before_engine(tmp_path):
    store = SQLiteStoryStore(str(tmp_path / "stories.db"))
    story_id = "s-xianxia-sync"
    project_id = "p-xianxia-sync"
    story = StoryState(
        story_id=story_id,
        outline="网游开服，主角登录游戏验证千倍爆率。",
        genre="网游",
        style="升级流",
        progression_ledger={"market": {"newbie_materials": {}}, "systems": {"chaos_seed": {}}},
    )
    project = NovelProject(
        project_id=project_id,
        title="我替宗门看守断香炉",
        seed_outline="林照被分去祖祠看守断香炉。",
        world_summary="林照刚入外门，被分去祖祠看守快熄灭的断香炉。",
        current_focus="第一章写祖祠守炉，不写游戏登录。",
        active_story_id=story_id,
        author_constraints=["不写网游面板、背包、掉落、铜币或玩家生态。"],
        world_blueprint={
            "genre_plugin_ids": ["xianxia"],
            "premise": "断香炉只给零碎反馈。",
            "progression_ledger": {"cultivation": {"realm": "外门候选"}},
        },
    )
    captured: dict[str, StoryState] = {}

    class FakeEngine:
        def generate_next_chapter(self, incoming: StoryState) -> ChapterBundle:
            captured["story"] = incoming.model_copy(deep=True)
            incoming.current_chapter = 1
            return ChapterBundle(
                chapter_number=1,
                chapter_title="第1章 守炉",
                body="林照守着断香炉。",
                next_outline="继续查旧册。",
                updated_story=incoming,
                simulation_status={"ok": True},
            )

    store.create(story)
    store.create_project(project)
    store.attach_story_to_project(project_id, story_id)

    store.generate_next(story_id, FakeEngine())

    synced = captured["story"]
    assert synced.outline == "林照被分去祖祠看守断香炉。"
    assert synced.genre == "xianxia"
    assert synced.style == ""
    assert "小说类型：xianxia" in synced.world_facts
    assert "当前焦点：第一章写祖祠守炉，不写游戏登录。" in synced.world_facts
    assert synced.author_constraints == ["不写网游面板、背包、掉落、铜币或玩家生态。"]
    assert synced.progression_ledger == {"cultivation": {"realm": "外门候选"}}
