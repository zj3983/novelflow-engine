from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import _soften_repeated_paragraph_openers, apply_simulated_state_deltas


def test_apply_simulated_state_deltas_merges_world_event_and_scene_card_state():
    story = StoryState(
        story_id="s-delta",
        outline="VRMMO opening.",
        genre="VRMMO",
        style="leveling",
        characters=[CharacterState(name="Su Ye", role="protagonist", game_id="Night Ember")],
        progression_ledger={
            "protagonist": {"level": 1, "class_path": "Element Mage Apprentice", "exp": "0/100"},
            "economy": {"currency": "0 copper", "inventory": {"venom_gland": 0}},
        },
    )
    world_events = [
        {
            "event_id": "gain",
            "state_delta": {
                "economy": {"inventory": {"venom_gland": 36}},
                "pressure": {"market_trace": "low"},
            },
        }
    ]
    scene_cards = [
        {
            "scene_id": "panel",
            "state_delta": {
                "protagonist": {"level": 2, "exp": "35/100", "hp": "88/100", "mp": "42/80"},
                "economy": {"currency": "190 copper"},
            },
        }
    ]

    apply_simulated_state_deltas(story, world_events=world_events, scene_cards=scene_cards, chapter_number=1)

    assert story.progression_ledger["protagonist"]["level"] == 2
    assert story.progression_ledger["protagonist"]["hp"] == "88/100"
    assert story.progression_ledger["economy"]["inventory"]["venom_gland"] == 36
    assert story.progression_ledger["economy"]["currency"] == "190 copper"
    assert story.progression_ledger["pressure"]["market_trace"] == "low"
    panel = story.characters[0].game_panel
    assert panel.level == 2
    assert panel.hp == "88/100"
    assert panel.inventory["venom_gland"] == 36


def test_apply_simulated_state_deltas_ignores_empty_values():
    story = StoryState(
        story_id="s-delta-empty",
        outline="VRMMO opening.",
        genre="VRMMO",
        style="leveling",
        progression_ledger={"economy": {"currency": "50 copper"}},
    )
    world_events = [{"state_delta": {"economy": {"currency": ""}}}]

    apply_simulated_state_deltas(story, world_events=world_events, scene_cards=[], chapter_number=1)

    assert story.progression_ledger["economy"]["currency"] == "50 copper"


def test_apply_simulated_state_deltas_persists_systemic_ledger_delta():
    story = StoryState(
        story_id="s-systemic-delta",
        outline="VRMMO opening.",
        genre="VRMMO",
        style="systemic",
        characters=[CharacterState(name="Su Ye", role="protagonist", game_id="Night Ember")],
        progression_ledger={
            "economy": {"inventory": {"wolf_pelt": 1}},
            "market": {"newbie_materials": {"supply": 34}},
            "systems": {"chaos_seed": {"anomaly_score": 0}},
        },
    )
    scene_cards = [
        {
            "state_delta": {
                "game_world_simulation": {
                    "ledger_delta": {
                        "clock_minutes": 24,
                        "inventory_delta": {"wolf_pelt": 5, "venom_gland": 8},
                        "cost_delta": {"hp": -54, "mp": -60, "durability": -6},
                        "market_delta": {"material_supply": 13, "price_copper": 5},
                        "hidden_system_delta": {"chaos_seed_anomaly_score": 7},
                        "next_pressure": ["repair_weapon", "find_market_route"],
                    }
                }
            }
        }
    ]

    apply_simulated_state_deltas(story, world_events=[], scene_cards=scene_cards, chapter_number=1)

    assert story.progression_ledger["economy"]["inventory"] == {"wolf_pelt": 6, "venom_gland": 8}
    assert story.progression_ledger["protagonist"]["cost_delta"] == {"hp": -54, "mp": -60, "durability": -6}
    assert story.progression_ledger["market"]["newbie_materials"]["supply"] == 47
    assert story.progression_ledger["market"]["newbie_materials"]["price_copper"] == 5
    assert story.progression_ledger["systems"]["chaos_seed"]["anomaly_score"] == 7
    assert story.progression_ledger["pressure"]["next"] == ["repair_weapon", "find_market_route"]
    assert story.characters[0].game_panel.inventory["wolf_pelt"] == 6


def test_apply_simulated_state_deltas_does_not_persist_raw_game_world_simulation():
    story = StoryState(
        story_id="s-systemic-raw-skip",
        outline="VRMMO opening.",
        genre="VRMMO",
        style="systemic",
        progression_ledger={"protagonist": {"level": "Lv.1"}},
    )
    world_events = [
        {
            "state_delta": {
                "protagonist": {"exp": "30/100"},
                "game_world_simulation": {
                    "schema_version": "game-world-simulation/v1",
                    "ledger_delta": {"next_pressure": ["repair_weapon"]},
                },
            }
        }
    ]

    apply_simulated_state_deltas(story, world_events=world_events, scene_cards=[], chapter_number=2)

    assert story.progression_ledger["protagonist"]["exp"] == "30/100"
    assert story.progression_ledger["pressure"]["next"] == ["repair_weapon"]
    assert "game_world_simulation" not in story.progression_ledger


def test_apply_simulated_state_deltas_replaces_legacy_string_system_slots():
    story = StoryState(
        story_id="s-systemic-legacy-slots",
        outline="VRMMO opening.",
        genre="VRMMO",
        style="systemic",
        progression_ledger={
            "market": "quiet",
            "systems": {"chaos_seed": "未解析"},
        },
    )
    scene_cards = [
        {
            "state_delta": {
                "game_world_simulation": {
                    "ledger_delta": {
                        "market_delta": {"material_supply": 3, "price_copper": 2},
                        "hidden_system_delta": {"chaos_seed_anomaly_score": 4},
                    }
                }
            }
        }
    ]

    apply_simulated_state_deltas(story, world_events=[], scene_cards=scene_cards, chapter_number=2)

    assert story.progression_ledger["market"]["newbie_materials"]["supply"] == 3
    assert story.progression_ledger["market"]["newbie_materials"]["price_copper"] == 2
    assert story.progression_ledger["systems"]["chaos_seed"]["anomaly_score"] == 4


def test_repeated_paragraph_opener_softener_does_not_add_banned_time_crutches():
    body = "\n\n".join(
        [
            "夜烬看了一眼面板。",
            "夜烬把背包扣上。",
            "夜烬走到柜台前。",
            "夜烬递出材料。",
            "夜烬退回队伍边。",
            "夜烬摸了摸法杖。",
            "夜烬往村口走。",
        ]
    )

    softened = _soften_repeated_paragraph_openers(body)

    for token in ("这一次，", "下一刻，", "很快，", "片刻后，", "转眼，", "眼前，"):
        assert token not in softened
