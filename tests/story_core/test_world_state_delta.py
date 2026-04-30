from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import apply_simulated_state_deltas


def test_apply_simulated_state_deltas_merges_world_event_and_scene_card_state():
    story = StoryState(
        story_id="s-delta",
        outline="网游开服。",
        genre="网游",
        style="升级流",
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
        progression_ledger={
            "protagonist": {"level": 1, "class_path": "元素法师学徒", "exp": "0/100"},
            "economy": {"currency": "0金币0银币0铜币", "inventory": {"狼毒腺": 0}},
        },
    )
    world_events = [
        {
            "event_id": "gain",
            "state_delta": {
                "economy": {"inventory": {"狼毒腺": 36}},
                "pressure": {"market_trace": "low"},
            },
        }
    ]
    scene_cards = [
        {
            "scene_id": "panel",
            "state_delta": {
                "protagonist": {"level": 2, "exp": "35/100", "hp": "88/100", "mp": "42/80"},
                "economy": {"currency": "0金币1银币90铜币"},
            },
        }
    ]

    apply_simulated_state_deltas(story, world_events=world_events, scene_cards=scene_cards, chapter_number=1)

    assert story.progression_ledger["protagonist"]["level"] == 2
    assert story.progression_ledger["protagonist"]["hp"] == "88/100"
    assert story.progression_ledger["economy"]["inventory"]["狼毒腺"] == 36
    assert story.progression_ledger["economy"]["currency"] == "0金币1银币90铜币"
    assert story.progression_ledger["pressure"]["market_trace"] == "low"
    panel = story.characters[0].game_panel
    assert panel.level == 2
    assert panel.hp == "88/100"
    assert panel.inventory["狼毒腺"] == 36


def test_apply_simulated_state_deltas_ignores_empty_values():
    story = StoryState(
        story_id="s-delta-empty",
        outline="网游开服。",
        genre="网游",
        style="升级流",
        progression_ledger={"economy": {"currency": "0金币0银币50铜币"}},
    )
    world_events = [{"state_delta": {"economy": {"currency": ""}}}]

    apply_simulated_state_deltas(story, world_events=world_events, scene_cards=[], chapter_number=1)

    assert story.progression_ledger["economy"]["currency"] == "0金币0银币50铜币"
