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


def complete_game_power_spec() -> dict[str, object]:
    return {
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


def game_project(*, power_system_spec=None, power_system=None) -> NovelProject:
    blueprint = {"genre_plugin_ids": ["game_webnovel"], "premise": "旧世界"}
    if power_system_spec is not None:
        blueprint["power_system_spec"] = power_system_spec
    if power_system is not None:
        blueprint["power_system"] = power_system
    return NovelProject(project_id="p-power", title="神域", world_blueprint=blueprint)


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


def test_world_enrichment_prompt_uses_persisted_builtin_runtime_template_override(
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
    assert template == compact_power_system_template(persisted.power_system_template)
    assert template["system_form"] == "运行时覆盖职业体系"
    assert template["minimum_path_count"] == 8


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


def test_valid_game_spec_replaces_structured_module_and_derives_legacy_summary():
    incoming_spec = complete_game_power_spec()
    project = game_project(power_system=["旧版摘要原文"])

    enriched = world_enrichment._merge_enrichment(
        project,
        {"world_blueprint": {"premise": "新世界", "power_system_spec": incoming_spec}},
        rules_only=False,
    )

    assert enriched.world_blueprint["power_system_spec"] == incoming_spec
    assert enriched.world_blueprint["power_system"] == legacy_power_summary(incoming_spec)
    assert enriched.world_blueprint["premise"] == "新世界"


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


def test_invalid_incoming_spec_does_not_overwrite_valid_current_spec():
    current_spec = complete_game_power_spec()
    project = game_project(power_system_spec=current_spec, power_system=["当前摘要"])

    with pytest.raises(ValueError, match=r"^invalid_power_system_spec:"):
        world_enrichment._merge_enrichment(
            project,
            {"world_blueprint": {"power_system_spec": {"name": "残缺体系"}}},
            rules_only=False,
        )

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
