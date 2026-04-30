from apps.api.storage import _project_world_facts
from packages.story_core.models import NovelProject, StoryState
from packages.story_core.orchestrator import _apply_ledger_updates, _normalize_memory_constraints, _story_snapshot
from packages.story_core.world_enrichment import _merge_enrichment


def test_game_world_gets_first_volume_plan_and_progression_ledger():
    project = NovelProject(
        project_id="p-longform-game",
        title="苟在网游里成神",
        seed_outline="网游开服，主角靠千倍爆率低调发育，交易行变现，被公会逐步注意。",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )

    enriched = _merge_enrichment(project, {})
    world = enriched.world_blueprint

    volume_plan = world["volume_plan"]
    ledger = world["progression_ledger"]

    assert volume_plan["target_chapters"] >= 30
    assert any("1-3" in beat["range"] for beat in volume_plan["phase_beats"])
    assert any("10级" in thread for thread in volume_plan["long_threads"])
    assert ledger["protagonist"]["level"] == 1
    assert "金币" in ledger["economy"]["currency"]
    assert ledger["pressure"]["guild_attention"] == 0


def test_project_world_facts_include_volume_plan_and_ledger():
    project = NovelProject(
        project_id="p-longform-facts",
        title="苟在网游里成神",
        world_blueprint={
            "volume_plan": {
                "volume_title": "第一卷 灰烬村蛰伏",
                "target_chapters": 30,
                "phase_beats": [{"range": "1-3", "purpose": "立住灰烬村和交易行。"}],
                "long_threads": ["安全升到10级。"],
            },
            "progression_ledger": {
                "protagonist": {"level": 1, "exp": "0/100", "class_path": "法师学徒"},
                "economy": {"currency": "0金币0银币0铜币", "market_anomaly": 0},
                "quests": {"active": ["元素回廊前置"], "completed": []},
                "pressure": {"guild_attention": 0, "goldfinger_exposure": 0},
            },
        },
    )

    facts = _project_world_facts(project)

    assert "第一卷规划：第一卷 灰烬村蛰伏，目标约30章。" in facts
    assert "卷纲阶段：1-3 - 立住灰烬村和交易行。" in facts
    assert "长期线索：安全升到10级。" in facts
    assert any("成长账本" in fact and "等级1" in fact for fact in facts)
    assert any("压力账本" in fact and "公会关注0" in fact for fact in facts)


def test_story_snapshot_exposes_progression_ledger():
    story = StoryState(
        story_id="s-ledger",
        outline="网游开服，主角低调发育。",
        genre="网游",
        style="升级流",
        progression_ledger={
            "protagonist": {"level": 2, "exp": "75/200", "class_path": "法师学徒"},
            "economy": {"currency": "0金币3银币20铜币", "market_anomaly": 2},
            "pressure": {"guild_attention": 1, "goldfinger_exposure": 1},
        },
    )

    snapshot = _story_snapshot(story)

    assert snapshot["progression_ledger"]["protagonist"]["level"] == 2
    assert snapshot["progression_ledger"]["economy"]["currency"] == "0金币3银币20铜币"


def test_memory_constraints_carry_ledger_updates():
    story = StoryState(
        story_id="s-ledger-update",
        outline="网游开服，主角低调发育。",
        genre="网游",
        style="升级流",
    )

    memory = _normalize_memory_constraints(
        {
            "ledger_updates": {
                "protagonist": {"level": 2, "exp": "75/200"},
                "economy": {"currency": "0金币2银币40铜币"},
                "pressure": {"guild_attention": 1},
            }
        },
        story,
    )

    assert memory["ledger_updates"]["protagonist"]["level"] == 2
    assert memory["ledger_updates"]["economy"]["currency"] == "0金币2银币40铜币"


def test_apply_ledger_updates_deep_merges_without_losing_existing_state():
    story = StoryState(
        story_id="s-ledger-merge",
        outline="网游开服，主角低调发育。",
        genre="网游",
        style="升级流",
        progression_ledger={
            "protagonist": {"level": 1, "exp": "0/100", "class_path": "法师学徒"},
            "economy": {"currency": "0金币0银币0铜币", "inventory": ["狼皮"], "market_anomaly": 0},
            "pressure": {"guild_attention": 0, "goldfinger_exposure": 0},
        },
    )

    _apply_ledger_updates(
        story,
        {
            "protagonist": {"level": 2, "exp": "75/200"},
            "economy": {"currency": "0金币2银币40铜币", "market_anomaly": 1},
            "pressure": {"guild_attention": 1},
        },
    )

    assert story.progression_ledger["protagonist"]["level"] == 2
    assert story.progression_ledger["protagonist"]["class_path"] == "法师学徒"
    assert story.progression_ledger["economy"]["inventory"] == ["狼皮"]
    assert story.progression_ledger["economy"]["market_anomaly"] == 1
    assert story.progression_ledger["pressure"]["goldfinger_exposure"] == 0
