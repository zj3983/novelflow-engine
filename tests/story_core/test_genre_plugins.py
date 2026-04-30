from packages.story_core.genre_plugins import merge_plugin_rulebooks, select_genre_plugins
from packages.story_core.models import NovelProject
from packages.story_core.world_enrichment import _merge_enrichment
from packages.story_core.orchestrator import _normalize_event_plan, _story_snapshot
from packages.story_core.models import StoryState


def plugin_ids(project: NovelProject) -> list[str]:
    return [plugin.plugin_id for plugin in select_genre_plugins(project)]


def test_selects_game_webnovel_plugin_for_game_project():
    project = NovelProject(
        project_id="p-game",
        title="苟在网游里成神",
        seed_outline="主角在VRMMO里靠千倍爆率升级，交易行卖装备，被公会盯上。",
    )

    assert plugin_ids(project)[:2] == ["generic_webnovel", "game_webnovel"]


def test_selects_xianxia_plugin_for_cultivation_project():
    project = NovelProject(
        project_id="p-xianxia",
        title="凡人修仙传承",
        seed_outline="少年进入宗门，凭残缺功法争夺灵石和秘境机缘，逐步突破境界。",
    )

    assert "xianxia" in plugin_ids(project)


def test_merge_enrichment_adds_genre_plugin_rules():
    project = NovelProject(
        project_id="p-merge",
        title="规则怪谈观察员",
        seed_outline="主角进入异常公寓，每晚必须遵守规则并验证禁忌代价。",
        world_summary="异常公寓里规则会污染认知。",
    )

    enriched = _merge_enrichment(project, {"world_blueprint": {"premise": "异常规则世界。"}})
    world = enriched.world_blueprint

    assert world["genre_plugins"][0]["id"] == "generic_webnovel"
    assert any(plugin["id"] == "rules_mystery" for plugin in world["genre_plugins"])
    assert any("规则" in rule for rule in world["quest_rules"])
    assert world["living_world"]["daily_routines"]
    assert world["living_world"]["reaction_rules"]
    assert enriched.author_constraints


def test_game_living_world_has_market_and_guild_reactions():
    project = NovelProject(
        project_id="p-living-game",
        title="苟在网游里成神",
        seed_outline="网游开服，主角靠千倍爆率刷材料，通过交易行低调变现，被公会注意。",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )

    enriched = _merge_enrichment(project, {})
    living_world = enriched.world_blueprint["living_world"]

    assert any("交易行" in item for item in living_world["information_network"]["channels"])
    assert any("公会" in item for item in living_world["reaction_rules"])
    assert any("普通玩家" in item for item in living_world["daily_routines"])

    assert enriched.world_blueprint["world_systems"]["material_base"]
    assert enriched.world_blueprint["world_systems"]["institutions"]
    assert enriched.world_blueprint["world_systems"]["causal_loops"]


def test_game_plugin_builds_npc_quest_server_and_map_modules():
    project = NovelProject(
        project_id="p-game-plugin-pack",
        title="苟在网游里成神",
        seed_outline="网游开服，主角靠千倍爆率刷材料，通过交易行低调变现，后续接入职业试炼和隐藏任务。",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )

    enriched = _merge_enrichment(project, {})
    world = enriched.world_blueprint

    assert any(npc["name"] == "职业导师艾伦" for npc in world["npc_system"]["npcs"])
    assert any("NPC" in rule or "服务" in rule for rule in world["npc_system"]["rules"])
    assert any(chain["name"] == "元素回廊前置" for chain in world["quest_network"]["active_chains"])
    assert "世界频道" in world["server_runtime"]["channels"]
    assert any(zone["name"] == "灰烬村" and "职业导师艾伦" in zone["npcs"] for zone in world["map_ecology"]["zones"])


def test_story_snapshot_and_event_plan_carry_world_reactions():
    story = StoryState(
        story_id="s-world-reactions",
        outline="主角低调卖材料。",
        genre="网游",
        style="升级流",
        world_facts=["世界反应：交易行价格异常会引起商人玩家追踪。"],
    )

    snapshot = _story_snapshot(story)
    event_plan = _normalize_event_plan(
        {
            "chapter_title": "交易行暗流",
            "world_reactions": ["赵胖子开始记录上架规律。", "白袍公会外围注意狼皮低价流。"],
        },
        2,
        story,
    )

    assert snapshot["world_facts"] == ["世界反应：交易行价格异常会引起商人玩家追踪。"]
    assert event_plan["world_reactions"] == ["赵胖子开始记录上架规律。", "白袍公会外围注意狼皮低价流。"]


def test_plugin_rulebooks_are_merged_without_duplicates():
    project = NovelProject(
        project_id="p-romance",
        title="豪门替身追妻",
        seed_outline="替身文，关系拉扯、误会、追妻和豪门利益压力并行。",
    )
    plugins = select_genre_plugins(project)
    rulebook = merge_plugin_rulebooks(plugins)

    assert "romance" in [plugin.plugin_id for plugin in plugins]
    assert len(rulebook["chapter_formula"]) == len(set(rulebook["chapter_formula"]))
    assert rulebook["forbidden_breaks"]


def test_explicit_plugin_ids_prevent_accidental_secondary_genres():
    project = NovelProject(
        project_id="p-explicit",
        title="苟在网游里成神",
        seed_outline="网游、等级、爆率、交易行、公会，以及若干职业试炼线索。",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )

    assert plugin_ids(project) == ["generic_webnovel", "game_webnovel"]
