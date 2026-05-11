from packages.story_core.models import CharacterState, StoryState
from packages.story_core.world_simulation import select_scene_cards, simulate_world_events


def _story_with_inbox() -> StoryState:
    return StoryState(
        story_id="s-inbox-scene",
        outline="VRMMO hidden drop advantage.",
        genre="VRMMO",
        style="leveling",
        characters=[CharacterState(name="Su Ye", role="protagonist", game_id="Night Ember")],
        progression_ledger={
            "visibility_inbox": [
                {
                    "id": "pulse-1-price-board",
                    "visible_at_chapter": 2,
                    "channel": "price_board",
                    "text": "Newbie material price board shows a small local wobble near 5 copper.",
                    "source_event": "local_market",
                },
                {
                    "id": "pulse-1-rent",
                    "visible_at_chapter": 2,
                    "channel": "phone_notice",
                    "text": "Rent reminder tightens: 2 days remain.",
                    "source_event": "reality_pressure",
                },
                {
                    "id": "pulse-2-player-chatter",
                    "visible_at_chapter": 3,
                    "channel": "player_chatter",
                    "text": "Future players gossip about route noise.",
                    "source_event": "route_noise",
                },
            ],
            "persistent_world": {
                "guild_intel": {
                    "white_robe_guild": {
                        "knowledge_state": "correlated_weak_pattern",
                        "cannot_know": ["hidden_talent", "real_identity", "precise_coordinates"],
                    }
                }
            },
        },
    )


def test_visibility_inbox_becomes_due_world_event_for_next_chapter():
    story = _story_with_inbox()

    events = simulate_world_events(
        story,
        2,
        chapter_seed={"genre_plugins": ["game_webnovel"]},
        simulation_plan={"chapter_goal": "Find a safe service route."},
    )

    inbox_event = next(event for event in events if event.template_id == "visibility_inbox_pressure")

    assert inbox_event.event_id == "c2-visibility-inbox"
    assert "price_board" in inbox_event.action
    assert "phone_notice" in inbox_event.action
    assert "Future players" not in inbox_event.action
    assert inbox_event.state_delta["visibility_inbox_pressure"]["consumed_ids"] == [
        "pulse-1-price-board",
        "pulse-1-rent",
    ]
    assert inbox_event.visible_to == ["Night Ember"]


def test_visibility_inbox_world_event_becomes_scene_card_pressure():
    story = _story_with_inbox()
    events = simulate_world_events(
        story,
        2,
        chapter_seed={"genre_plugins": ["game_webnovel"]},
        simulation_plan={"chapter_goal": "Find a safe service route."},
    )

    cards = select_scene_cards(events, chapter_seed={"chapter_number": 2}, simulation_plan={})
    inbox_card = next(card for card in cards if card.template_id == "visibility_inbox_pressure")
    surface = " ".join(inbox_card.must_show)

    assert "price_board" in surface
    assert "phone_notice" in surface
    assert "small local wobble" in surface
    assert "Rent reminder" in surface
    assert "Future players" not in surface
    assert "hidden_talent" in inbox_card.must_not_explain
    assert "real_identity" in inbox_card.must_not_explain
    assert "precise_coordinates" in inbox_card.must_not_explain
    assert inbox_card.ending_pressure == "Treat these as next-scene pressure, not solved background exposition."
