from apps.api.storage import _project_world_facts
import json

import pytest

from packages.story_core.models import ChapterSummary, NovelProject, StoryState
from packages.story_core.orchestrator import _apply_ledger_updates, _normalize_memory_constraints, _story_snapshot
from packages.story_core.plot_contract import build_longform_plot_contract
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


@pytest.mark.parametrize(
    ("genre", "game_story", "expected_mode", "required_terms", "forbidden_terms"),
    [
        (
            "xuanhuan",
            False,
            "xuanhuan",
            ("身份", "力量体系", "势力压力", "机缘", "代价"),
            ("千倍爆率", "铜币", "角色面板", "修行因果", "炼气", "筑基"),
        ),
        (
            "xianxia",
            False,
            "xianxia",
            ("修行", "因果", "宗门", "社会秩序", "资源代价"),
            ("千倍爆率", "铜币", "角色面板", "力量体系", "炼气", "筑基"),
        ),
        (
            "game_webnovel",
            True,
            "game_webnovel",
            ("等级", "任务", "资源", "千倍爆率", "铜币"),
            ("修行因果", "社会秩序", "力量体系"),
        ),
        (
            "historical_mystery",
            False,
            "unknown",
            ("目标", "关系", "信息", "资源", "风险"),
            ("千倍爆率", "铜币", "角色面板", "力量体系", "修行", "因果", "宗门", "境界", "道具", "任务"),
        ),
    ],
)
def test_longform_plot_contract_keeps_genre_vocabulary_isolated(
    genre, game_story, expected_mode, required_terms, forbidden_terms
):
    story = StoryState(
        story_id=f"s-longform-{expected_mode}",
        outline="主角守住眼前位置，并追查前任留下的秘密。",
        genre=genre,
        style="白描",
    )

    contract = build_longform_plot_contract(story, 6, game_story=game_story)
    contract_text = json.dumps(contract, ensure_ascii=False)

    assert contract["genre_mode"] == expected_mode
    for term in required_terms:
        assert term in contract_text
    for term in forbidden_terms:
        assert term not in contract_text


def test_longform_plot_contract_prioritizes_story_intent_over_chapter_defaults():
    story = StoryState(
        story_id="s-longform-priority",
        outline="用户大纲要求主角先救出被扣下的妹妹，不参加势力比斗。",
        genre="xuanhuan",
        style="白描",
        chapter_summaries=[
            ChapterSummary(
                chapter_number=11,
                summary="主角查到妹妹被关在西院。",
                next_focus="上一轮要求先拿到西院钥匙。",
            )
        ],
    )

    contract = build_longform_plot_contract(
        story,
        12,
        chapter_goal="本章目标是借账册换出西院钥匙。",
    )
    priority = contract["story_priority"]

    assert contract["chapter_goal"] == "本章目标是借账册换出西院钥匙。"
    assert priority["outline"].startswith("用户大纲要求")
    assert priority["previous_next_focus"] == "上一轮要求先拿到西院钥匙。"
    assert priority["chapter_goal"] == contract["chapter_goal"]
    assert "高于章节号默认节奏" in priority["rule"]
