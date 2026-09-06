from packages.story_core.genre_plugins import merge_plugin_rulebooks, plugin_prompt_guide, plugin_simulation_blueprint, select_genre_plugins
from packages.story_core.models import NovelProject
from packages.story_core.world_enrichment import _merge_enrichment
from packages.story_core.orchestrator import _normalize_event_plan, _story_snapshot
from packages.story_core.models import StoryState
from packages.story_core.genre_types.game_webnovel import GAME_WEBNOVEL


def plugin_ids(project: NovelProject) -> list[str]:
    return [plugin.plugin_id for plugin in select_genre_plugins(project)]


def test_selects_game_webnovel_plugin_for_game_project():
    project = NovelProject(
        project_id="p-game",
        title="苟在网游里成神",
        seed_outline="主角在VRMMO里靠千倍爆率升级，交易行卖装备，被公会盯上。",
    )

    assert plugin_ids(project)[:2] == ["generic_webnovel", "game_webnovel"]


def test_game_genre_rulebook_defines_level_gap_boundary():
    rules = "\n".join(GAME_WEBNOVEL.rulebook["progression_rules"])

    assert "高出1至2级" in rules
    assert "高出3级及以上" in rules
    assert "走位、计算和操作不能单独" in rules


def test_selects_xianxia_plugin_for_cultivation_project():
    project = NovelProject(
        project_id="p-xianxia",
        title="凡人修仙传承",
        seed_outline="少年进入宗门，凭残缺功法争夺灵石和秘境机缘，逐步突破境界。",
    )

    assert plugin_ids(project) == ["generic_webnovel", "eastern_fantasy", "xianxia"]


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
    assert "quest_rules" not in world
    assert any("规则" in rule for rule in world["chapter_formula"])
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

    # 模块骨架存在且规则可用
    assert any("NPC" in rule or "服务" in rule for rule in world["npc_system"]["rules"])
    assert world["quest_network"]["quest_types"]
    assert "channels" in world["server_runtime"]
    assert "zones" in world["map_ecology"]
    # 清理规则：默认骨架不再注入旧书的固定 NPC、任务链和地图
    assert not any(npc.get("name") == "职业导师艾伦" for npc in world["npc_system"]["npcs"])
    assert not any(chain.get("name") == "元素回廊前置" for chain in world["quest_network"]["active_chains"])
    assert not any(zone.get("name") == "灰烬村" for zone in world["map_ecology"]["zones"])


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


def test_specific_genre_plugins_live_in_separate_modules():
    from packages.story_core.genre_types.game_webnovel import GAME_WEBNOVEL
    from packages.story_core.genre_types.xianxia import XIANXIA

    assert GAME_WEBNOVEL.plugin_id == "game_webnovel"
    assert XIANXIA.plugin_id == "xianxia"
    assert "网游" in GAME_WEBNOVEL.keywords
    assert "修仙" in XIANXIA.keywords


def test_legacy_genre_plugins_entrypoint_uses_split_modules():
    from packages.story_core import genre_plugins
    from packages.story_core.genre_types import EASTERN_FANTASY

    project = NovelProject(
        project_id="p-split-entry",
        title="我替宗门看守断香炉",
        seed_outline="外门弟子被分去祖祠守炉，断香炉只给残缺机缘。",
        world_blueprint={"genre_plugin_ids": ["xianxia"]},
    )

    plugins = genre_plugins.select_genre_plugins(project)

    assert [plugin.plugin_id for plugin in plugins] == ["generic_webnovel", "eastern_fantasy", "xianxia"]
    assert any("残缺机缘" in rule for rule in EASTERN_FANTASY.rulebook["chapter_formula"])


def test_eastern_fantasy_subtype_plugins_and_shared_blueprint_are_exported():
    from packages.story_core.genre_types import (
        EASTERN_FANTASY,
        EASTERN_FANTASY_SIMULATION_BLUEPRINT,
        XIANXIA,
        XUANHUAN,
    )

    assert EASTERN_FANTASY.plugin_id == "eastern_fantasy"
    assert XUANHUAN.plugin_id == "xuanhuan"
    assert XIANXIA.plugin_id == "xianxia"
    assert EASTERN_FANTASY_SIMULATION_BLUEPRINT["plugin_id"] == "eastern_fantasy"
    assert EASTERN_FANTASY_SIMULATION_BLUEPRINT["opening_scene_templates"]
    shared_promises = "\n".join(EASTERN_FANTASY.core_promises)
    assert "残缺机缘" in shared_promises
    assert "宗门差事" in shared_promises
    assert any("残缺机缘" in rule for rule in EASTERN_FANTASY.rulebook["chapter_formula"])
    assert "宗门差事" in EASTERN_FANTASY.quality_checks


def test_legacy_xianxia_blueprint_is_an_isolated_compatibility_copy():
    from packages.story_core.genre_types import EASTERN_FANTASY_SIMULATION_BLUEPRINT
    from packages.story_core.genre_types.xianxia import XIANXIA_SIMULATION_BLUEPRINT

    assert EASTERN_FANTASY_SIMULATION_BLUEPRINT["plugin_id"] == "eastern_fantasy"
    assert XIANXIA_SIMULATION_BLUEPRINT["plugin_id"] == "xianxia"
    assert XIANXIA_SIMULATION_BLUEPRINT is not EASTERN_FANTASY_SIMULATION_BLUEPRINT
    assert (
        XIANXIA_SIMULATION_BLUEPRINT["opening_scene_templates"]
        is not EASTERN_FANTASY_SIMULATION_BLUEPRINT["opening_scene_templates"]
    )

    xianxia_marker = "仅兼容模板可见"
    shared_marker = "仅共享模板可见"
    xianxia_must_show = XIANXIA_SIMULATION_BLUEPRINT["opening_scene_templates"][0]["must_show"]
    shared_must_show = EASTERN_FANTASY_SIMULATION_BLUEPRINT["opening_scene_templates"][0]["must_show"]
    try:
        xianxia_must_show.append(xianxia_marker)
        assert xianxia_marker not in shared_must_show

        shared_must_show.append(shared_marker)
        assert shared_marker not in xianxia_must_show
    finally:
        xianxia_must_show.remove(xianxia_marker)
        shared_must_show.remove(shared_marker)


def test_eastern_fantasy_subtypes_keep_their_default_promises_separate():
    from packages.story_core.genre_types import XIANXIA, XUANHUAN

    xuanhuan_promises = "\n".join(XUANHUAN.core_promises)
    assert "自创力量" in xuanhuan_promises
    assert "异常物件" in xuanhuan_promises
    assert {"血脉", "体质", "武魂", "异火", "遗物"}.issubset(XUANHUAN.keywords)
    for xianxia_term in ("灵根", "渡劫", "飞升", "长生求道"):
        assert xianxia_term not in xuanhuan_promises
        assert xianxia_term not in XUANHUAN.keywords
        assert all(xianxia_term not in field for field in XUANHUAN.ledger_fields)

    assert XIANXIA.name == "修仙仙侠"
    xianxia_promises = "\n".join(XIANXIA.core_promises)
    assert {"灵根", "剑修", "炼丹", "法宝", "天劫", "渡劫", "飞升"}.issubset(XIANXIA.keywords)
    assert "道法因果" in xianxia_promises
    assert "渡劫飞升" in xianxia_promises
    for xianxia_path in ("剑修", "炼丹", "法宝"):
        assert xianxia_path in xianxia_promises
    assert "剑修" in "\n".join(XIANXIA.rulebook["progression_rules"])
    assert "炼丹" in "\n".join(XIANXIA.rulebook["economy_rules"])
    assert "法宝" in XIANXIA.ledger_fields
    for xuanhuan_term in ("武魂", "血脉觉醒"):
        assert xuanhuan_term not in xianxia_promises
        assert xuanhuan_term not in XIANXIA.keywords
        assert all(xuanhuan_term not in field for field in XIANXIA.ledger_fields)


def test_explicit_eastern_fantasy_subtypes_include_shared_plugin_once():
    for subtype in ("xuanhuan", "xianxia"):
        project = NovelProject(
            project_id=f"p-{subtype}-explicit",
            title="东方幻想测试",
            seed_outline="主角从一件低位差事中发现异常。",
            world_blueprint={"genre_plugin_ids": [subtype]},
        )

        assert plugin_ids(project) == ["generic_webnovel", "eastern_fantasy", subtype]


def test_inferred_eastern_fantasy_subtype_includes_shared_plugin_once():
    project = NovelProject(
        project_id="p-xuanhuan-inferred",
        title="血脉遗物",
        seed_outline="少年凭特殊体质唤醒古族血脉，并追查遗物后的世界秘密。",
    )

    ids = plugin_ids(project)

    assert ids == ["generic_webnovel", "eastern_fantasy", "xuanhuan"]
    assert ids.count("eastern_fantasy") == 1


def test_subtype_simulation_blueprints_are_isolated_shared_copies():
    from packages.story_core.genre_types import EASTERN_FANTASY_SIMULATION_BLUEPRINT

    blueprints = {}
    for subtype in ("xuanhuan", "xianxia"):
        project = NovelProject(
            project_id=f"p-{subtype}-blueprint",
            title="东方幻想测试",
            seed_outline="主角接下一件低位差事。",
            world_blueprint={"genre_plugin_ids": [subtype]},
        )
        blueprints[subtype] = plugin_simulation_blueprint(select_genre_plugins(project))

    assert blueprints["xuanhuan"]["plugin_id"] == "xuanhuan"
    assert blueprints["xianxia"]["plugin_id"] == "xianxia"
    assert blueprints["xuanhuan"] is not EASTERN_FANTASY_SIMULATION_BLUEPRINT
    assert blueprints["xianxia"] is not EASTERN_FANTASY_SIMULATION_BLUEPRINT
    assert blueprints["xuanhuan"]["opening_scene_templates"] is not blueprints["xianxia"]["opening_scene_templates"]

    marker = "只写入玄幻副本"
    blueprints["xuanhuan"]["opening_scene_templates"][0]["must_show"].append(marker)
    assert marker not in blueprints["xianxia"]["opening_scene_templates"][0]["must_show"]
    assert marker not in EASTERN_FANTASY_SIMULATION_BLUEPRINT["opening_scene_templates"][0]["must_show"]


def test_game_simulation_blueprint_returns_isolated_nested_copies():
    from packages.story_core.genre_types import GAME_WEBNOVEL_SIMULATION_BLUEPRINT

    project = NovelProject(
        project_id="p-game-blueprint-copy",
        title="网游测试",
        seed_outline="玩家进入游戏，通过爆率优势推进任务。",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )

    first = plugin_simulation_blueprint(select_genre_plugins(project))
    second = plugin_simulation_blueprint(select_genre_plugins(project))

    assert first["plugin_id"] == "game_webnovel"
    assert first is not GAME_WEBNOVEL_SIMULATION_BLUEPRINT
    assert first is not second
    assert first["opening_scene_templates"] is not second["opening_scene_templates"]

    marker = "只写入当前网游蓝图副本"
    first["opening_scene_templates"][0]["must_show"].append(marker)
    assert marker not in second["opening_scene_templates"][0]["must_show"]
    assert marker not in GAME_WEBNOVEL_SIMULATION_BLUEPRINT["opening_scene_templates"][0]["must_show"]


def test_genre_plugins_expose_reusable_trope_templates_in_prompt_guide():
    import json

    project = NovelProject(
        project_id="p-game-tropes",
        title="网游套路模板测试",
        seed_outline="主角登录游戏，靠隐藏爆率优势推进任务。",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )

    guide = json.loads(plugin_prompt_guide(select_genre_plugins(project)))

    generic = next(plugin for plugin in guide if plugin["id"] == "generic_webnovel")
    game = next(plugin for plugin in guide if plugin["id"] == "game_webnovel")

    assert any(template["id"] == "low_status_reversal" for template in generic["trope_templates"])
    assert any(template["id"] == "first_advantage_verification" for template in game["trope_templates"])
    assert all({"id", "name", "trigger", "beats", "payoff", "avoid"}.issubset(template) for plugin in guide for template in plugin["trope_templates"])


def test_simulation_blueprint_carries_isolated_trope_templates():
    project = NovelProject(
        project_id="p-game-blueprint-tropes",
        title="网游蓝图套路模板测试",
        seed_outline="新手村、隐藏任务、交易行、公会压力。",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )

    first = plugin_simulation_blueprint(select_genre_plugins(project))
    second = plugin_simulation_blueprint(select_genre_plugins(project))

    assert any(template["id"] == "first_advantage_verification" for template in first["trope_templates"])

    marker = "只污染当前蓝图副本"
    first["trope_templates"][0]["beats"].append(marker)
    assert marker not in second["trope_templates"][0]["beats"]
