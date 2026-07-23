from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.models import CharacterState, StoryState, WorldEvent
from packages.story_core.simulation import build_chapter_simulation_plan
from packages.story_core.world_simulation import select_scene_cards, simulate_world_events


def test_combat_scene_card_carries_level_gap_boundary():
    events = [
        WorldEvent(
            event_id="fight-1",
            template_id="combat",
            actor="夜烬",
            action="挑战Lv.8精英怪",
            consequences=["尝试击杀腐沼鳄"],
        )
    ]

    scene_cards = select_scene_cards(events, chapter_seed={}, simulation_plan={})
    surface = "\n".join("\n".join(card.must_show) for card in scene_cards)

    assert "高出3级及以上" in surface
    assert "走位、计算和操作不能单独" in surface


def test_world_events_capture_visibility_and_state_delta_for_game_opening():
    story = StoryState(
        story_id="s-world-events",
        outline="网游开服，苏叶以夜烬身份低调验证千倍爆率。",
        genre="网游",
        style="番茄升级流",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="夜烬",
                goals=["小额验证千倍爆率，不暴露现实身份"],
            )
        ],
        progression_ledger={
            "protagonist": {"level": 1, "class_path": "元素法师学徒", "exp": "0/100"},
            "economy": {"currency": "0金币0银币0铜币", "inventory": {}},
        },
    )
    seed = build_chapter_seed(story, 1)
    plan = build_chapter_simulation_plan(story, 1, chapter_seed=seed).model_dump()

    events = simulate_world_events(story, 1, chapter_seed=seed, simulation_plan=plan)

    assert events
    assert all(event.event_id for event in events)
    assert any(event.actor == "夜烬" and "验证" in event.action for event in events)
    assert not any("交易行" in event.location for event in events)
    assert not any("寄售" in event.action or "成交" in event.action or "到账" in event.action for event in events)
    next_step_event = next(event for event in events if event.event_id == "c1-next-step-hook")
    assert next_step_event.visible_to == ["夜烬"]
    assert next_step_event.state_delta.get("economy", {}).get("inventory_hint") == "保留低级材料"


def test_world_events_preserve_authorized_first_chapter_trade_payoff():
    story = StoryState(
        story_id="s-world-events-authorized-trade",
        outline="主角在网游开服首日验证隐藏爆率。",
        genre="网游",
        style="白描",
        author_constraints=[
            "第一章必须通过裂纹狼心担保交易解决现实急账，并写清到账结果。",
        ],
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
    )
    seed = build_chapter_seed(story, 1)
    plan = build_chapter_simulation_plan(story, 1, chapter_seed=seed).model_dump()

    events = simulate_world_events(story, 1, chapter_seed=seed, simulation_plan=plan)
    next_step_event = next(event for event in events if event.event_id == "c1-next-step-hook")
    surface = "\n".join(
        [next_step_event.action, next_step_event.cause, *next_step_event.consequences]
    )

    assert "担保交易" in surface
    assert "到账" in surface
    assert "不提前展开交易线" not in surface
    assert "本章不发生寄售" not in surface
    assert "公会追查" in surface


def test_scene_cards_turn_world_events_into_writeable_scenes():
    story = StoryState(
        story_id="s-scene-cards",
        outline="网游开服，主角先建号，再小额验证千倍爆率。",
        genre="网游",
        style="番茄升级流",
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
    )
    seed = build_chapter_seed(story, 1)
    plan = build_chapter_simulation_plan(story, 1, chapter_seed=seed).model_dump()
    events = simulate_world_events(story, 1, chapter_seed=seed, simulation_plan=plan)

    scene_cards = select_scene_cards(events, chapter_seed=seed, simulation_plan=plan)

    assert 3 <= len(scene_cards) <= 6
    assert scene_cards[0].purpose
    assert any("角色面板" in " ".join(card.must_show) for card in scene_cards)
    assert not any("交易行" in card.location for card in scene_cards)
    assert any("下一章目标" in card.purpose or "下一步目标" in card.conflict for card in scene_cards)
    assert all("爽点" in " ".join(card.must_not_explain) for card in scene_cards)


def test_scene_cards_surface_simulation_ticks_as_actions_not_author_rules():
    story = StoryState(
        story_id="s-scene-ticks",
        outline="网游开服，主角先小额验证千倍爆率。",
        genre="网游",
        style="白描升级流",
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
    )
    seed = build_chapter_seed(story, 1)
    plan = build_chapter_simulation_plan(story, 1, chapter_seed=seed).model_dump()
    events = simulate_world_events(story, 1, chapter_seed=seed, simulation_plan=plan)

    scene_cards = select_scene_cards(events, chapter_seed=seed, simulation_plan=plan)
    surface = "\n".join("\n".join(card.must_show) for card in scene_cards)

    assert "simulation tick" in surface
    assert "cost=" in surface
    assert "visible_to=" in surface
    assert "hidden_delta=" in surface
    assert "爽点" not in surface
    assert "钩子" not in surface


def test_later_game_chapters_keep_world_simulation_in_scene_cards():
    story = StoryState(
        story_id="s-later-scene-ticks",
        outline="网游开服，夜烬低调滚雪球。",
        genre="网游",
        style="白描升级流",
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
        progression_ledger={
            "protagonist": {
                "game_id": "夜烬",
                "level": "Lv.1",
                "exp": "30/100",
                "hp": "42/100",
                "mp": "0/60",
            },
            "economy": {
                "game_currency": "0铜",
                "inventory": {"灰狼毒腺": 8, "粗糙狼皮": 7},
            },
        },
    )
    seed = build_chapter_seed(story, 2)
    plan = build_chapter_simulation_plan(story, 2, chapter_seed=seed).model_dump()
    events = simulate_world_events(story, 2, chapter_seed=seed, simulation_plan=plan)

    ledger_event = next(event for event in events if event.event_id == "c2-inherit-ledger")
    game_world = ledger_event.state_delta["game_world_simulation"]
    scene_cards = select_scene_cards(events, chapter_seed=seed, simulation_plan=plan)
    surface = "\n".join("\n".join(card.must_show) for card in scene_cards)

    assert game_world["simulation_ticks"]
    assert "simulation tick" in surface
    assert "resource_wait" in surface
    assert "quest_service" in surface
    assert "chapter_goal" in surface
    assert "cost=" in surface
    assert "visible_to=" in surface


def test_scene_cards_do_not_surface_question_mark_identity_placeholders():
    story = StoryState(
        story_id="s-scene-cards-clean-id",
        outline="网游开服，苏叶以夜烬身份低调验证千倍爆率。",
        genre="网游",
        style="升级流",
        characters=[CharacterState(name="苏叶", role="主角", game_id="??")],
    )
    seed = build_chapter_seed(story, 1)
    plan = build_chapter_simulation_plan(story, 1, chapter_seed=seed).model_dump()
    events = simulate_world_events(story, 1, chapter_seed=seed, simulation_plan=plan)
    scene_cards = select_scene_cards(events, chapter_seed=seed, simulation_plan=plan)

    serialized = " ".join(card.model_dump_json() for card in scene_cards)

    assert "??" not in serialized
    assert any(card.pov == "夜烬" for card in scene_cards)
