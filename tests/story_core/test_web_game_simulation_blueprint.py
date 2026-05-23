from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.models import CharacterState, StoryState, WorldEvent
from packages.story_core.simulation import build_chapter_simulation_plan
from packages.story_core.world_simulation import select_scene_cards, simulate_world_events


def test_game_chapter_seed_carries_structured_simulation_blueprint():
    story = StoryState(
        story_id="s-game-blueprint",
        outline="网游开服，主角低调验证千倍爆率。",
        genre="网游",
        style="番茄升级流",
    )

    seed = build_chapter_seed(story, 1)
    blueprint = seed["simulation_blueprint"]

    assert blueprint["plugin_id"] == "game_webnovel"
    assert [item["id"] for item in blueprint["opening_scene_templates"][:5]] == [
        "reality_entry",
        "character_creation",
        "small_verification",
        "single_npc_service",
        "chapter_1_next_step",
    ]
    assert "market_overreaction" in blueprint["forbidden_conflict_modes"]["chapter_1"]
    assert blueprint["visibility_matrix"]["trade_house"]["can_see"]
    assert "现实身份" in blueprint["visibility_matrix"]["trade_house"]["cannot_see"]


def test_scene_cards_follow_web_game_template_order_and_conflict_ladder():
    story = StoryState(
        story_id="s-game-scenes",
        outline="网游开服，苏叶以夜烬身份低调验证千倍爆率。",
        genre="网游",
        style="番茄升级流",
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
    )
    seed = build_chapter_seed(story, 1)
    plan = build_chapter_simulation_plan(story, 1, chapter_seed=seed).model_dump()
    events = simulate_world_events(story, 1, chapter_seed=seed, simulation_plan=plan)

    cards = select_scene_cards(events, chapter_seed=seed, simulation_plan=plan)

    assert [card.template_id for card in cards[:5]] == [
        "reality_entry",
        "character_creation",
        "small_verification",
        "single_npc_service",
        "chapter_1_next_step",
    ]
    assert all("market_overreaction" not in card.conflict for card in cards)
    next_step_card = next(card for card in cards if card.template_id == "chapter_1_next_step")
    assert any("下一步" in item or "材料" in item for item in next_step_card.must_show)


def test_scene_cards_use_default_game_blueprint_when_seed_lacks_blueprint():
    events = [
        WorldEvent(
            event_id="market",
            template_id="market_weak_trace",
            actor="夜烬",
            action="小额寄售材料。",
            location="交易行",
            prose_priority=9,
        ),
        WorldEvent(
            event_id="npc",
            template_id="single_npc_service",
            actor="命名NPC",
            action="提供岗位服务。",
            location="灰烬村",
            prose_priority=8,
        ),
    ]

    cards = select_scene_cards(events, chapter_seed={}, simulation_plan={})

    assert [card.template_id for card in cards] == ["single_npc_service", "market_weak_trace"]
    market_card = next(card for card in cards if card.template_id == "market_weak_trace")
    assert any("价格" in item and "批次" in item for item in market_card.must_show)


def test_game_opening_scene_cards_inherit_world_simulation_ticks():
    story = StoryState(
        story_id="s-game-director-scenes",
        outline="网游开服，苏叶以夜烬身份验证千倍爆率。",
        genre="网游",
        style="番茄升级流",
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
    )
    seed = build_chapter_seed(story, 1)
    plan = build_chapter_simulation_plan(story, 1, chapter_seed=seed).model_dump()
    events = simulate_world_events(story, 1, chapter_seed=seed, simulation_plan=plan)

    cards = select_scene_cards(events, chapter_seed=seed, simulation_plan=plan)

    verification_card = next(card for card in cards if card.template_id == "small_verification")
    next_step_card = next(card for card in cards if card.template_id == "chapter_1_next_step")
    verification_surface = "\n".join(verification_card.must_show)
    next_step_surface = "\n".join(next_step_card.must_show)

    assert "simulation tick" in verification_surface
    assert "cost=" in verification_surface
    assert "visible_to=" in verification_surface
    assert "hidden_delta=" in verification_surface
    assert "wow_beat" not in verification_surface
    assert "explicit_chapter_end_hook" not in next_step_surface
    assert "reality_game_bridge" not in next_step_surface
