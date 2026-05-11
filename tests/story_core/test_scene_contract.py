from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.engine import ChapterBundle
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.simulation import build_chapter_simulation_plan
from packages.story_core.world_consistency_review import review_world_event_consistency
from packages.story_core.world_simulation import select_scene_cards, simulate_world_events
from packages.story_core.writing_packet import build_codex_writing_packet


def _game_story() -> StoryState:
    return StoryState(
        story_id="s-scene-contract",
        outline="VRMMO opening chapter with a hidden drop advantage.",
        genre="VRMMO",
        style="Tomato webnovel",
        characters=[CharacterState(name="Su Ye", role="protagonist", game_id="Night Ember")],
    )


def test_scene_cards_expose_scene_contract_from_systemic_simulation():
    story = _game_story()
    seed = build_chapter_seed(story, 1)
    plan = build_chapter_simulation_plan(story, 1, chapter_seed=seed).model_dump()
    events = simulate_world_events(story, 1, chapter_seed=seed, simulation_plan=plan)

    cards = select_scene_cards(events, chapter_seed=seed, simulation_plan=plan)
    verify_card = next(card for card in cards if card.template_id == "small_verification")
    sandbox = verify_card.state_delta["game_world_simulation"]

    contract = verify_card.scene_contract

    assert contract["schema_version"] == "scene-contract/v1"
    assert contract["source_event"] == "c1-small-verify"
    assert contract["required_state_changes"]["inventory_delta"] == sandbox["ledger_delta"]["inventory_delta"]
    assert contract["required_state_changes"]["cost_delta"] == sandbox["ledger_delta"]["cost_delta"]
    assert contract["required_state_changes"]["clock_minutes"] == sandbox["ledger_delta"]["clock_minutes"]
    assert contract["hidden_consequences"]
    assert contract["visibility_limits"]["guild"]
    visible_ids = {item["id"] for item in contract["visible_consequences"]}
    assert {"resource_cost_surface", "inventory_delta_surface", "visibility_boundary_surface"} <= visible_ids
    assert any("mana" in item["requires_any"] for item in contract["visible_consequences"])


def test_writing_packet_promotes_scene_contracts_to_top_level():
    story = _game_story()
    contract = {
        "schema_version": "scene-contract/v1",
        "scene_id": "s-test",
        "visible_consequences": [
            {
                "id": "resource_cost_surface",
                "description": "Show the spent mana.",
                "requires_any": ["mana bottomed out", "low mana"],
                "revision": "Add a panel/resource check that shows mana cost.",
            }
        ],
    }
    bundle = ChapterBundle(
        chapter_number=1,
        body="",
        next_outline="Continue the monetization route.",
        updated_story=story,
        scene_cards=[
            {
                "scene_id": "s-test",
                "template_id": "small_verification",
                "location": "newbie field",
                "pov": "Night Ember",
                "purpose": "Verify the advantage.",
                "conflict": "The test costs resources.",
                "must_show": ["drop feedback"],
                "scene_contract": contract,
            }
        ],
    )

    packet = build_codex_writing_packet(story, bundle)

    assert packet["scene_cards"][0]["scene_contract"] == contract
    assert packet["scene_contracts"] == [contract]
    assert any("scene_contract" in rule for rule in packet["prose_renderer"]["body_contract"])


def test_world_consistency_review_flags_unconsumed_scene_contract():
    scene_cards = [
        {
            "scene_id": "s3-small-verify",
            "scene_contract": {
                "schema_version": "scene-contract/v1",
                "visible_consequences": [
                    {
                        "id": "resource_cost_surface",
                        "description": "Show that the fight consumed mana.",
                        "requires_any": ["mana bottomed out", "low mana", "MP 0"],
                        "revision": "Add a resource check that shows the spent mana.",
                    },
                    {
                        "id": "inventory_delta_surface",
                        "description": "Show the loot entering inventory.",
                        "requires_any": ["backpack", "inventory", "loot"],
                        "revision": "Add a backpack or loot feedback line.",
                    },
                ],
            },
        }
    ]
    body = "Night Ember won the fight and walked back to the village."

    review = review_world_event_consistency(body, world_events=[], scene_cards=scene_cards)

    assert not review["pass"]
    assert review["scores"]["scene_contract_consumption"] < 8
    assert any("scene contract" in issue.lower() for issue in review["issues"])
    assert any("spent mana" in item for item in review["revision_plan"])


def test_world_consistency_review_accepts_consumed_scene_contract():
    scene_cards = [
        {
            "scene_id": "s3-small-verify",
            "scene_contract": {
                "schema_version": "scene-contract/v1",
                "visible_consequences": [
                    {
                        "id": "resource_cost_surface",
                        "description": "Show that the fight consumed mana.",
                        "requires_any": ["mana bottomed out", "low mana", "MP 0"],
                        "revision": "Add a resource check that shows the spent mana.",
                    },
                    {
                        "id": "inventory_delta_surface",
                        "description": "Show the loot entering inventory.",
                        "requires_any": ["backpack", "inventory", "loot"],
                        "revision": "Add a backpack or loot feedback line.",
                    },
                ],
            },
        }
    ]
    body = "Night Ember checked the backpack: the loot was inside, and his mana bottomed out."

    review = review_world_event_consistency(body, world_events=[], scene_cards=scene_cards)

    assert review["scores"]["scene_contract_consumption"] == 8
    assert review["issues"] == []
