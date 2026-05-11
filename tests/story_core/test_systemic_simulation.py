from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.engine import ChapterBundle
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.simulation import build_chapter_simulation_plan
from packages.story_core.world_simulation import select_scene_cards, simulate_world_events
from packages.story_core.writing_packet import build_codex_writing_packet


def _story() -> StoryState:
    return StoryState(
        story_id="s-systemic-sim",
        outline="VRMMO opening: the protagonist quietly verifies an unusual loot advantage.",
        genre="VRMMO",
        style="systemic webnovel",
        characters=[
            CharacterState(
                name="Su Ye",
                role="protagonist",
                game_id="Night Ember",
                goals=["verify the advantage", "avoid public attention"],
            )
        ],
    )


def test_scene_cards_surface_systemic_contract():
    story = _story()
    seed = build_chapter_seed(story, 1)
    plan = build_chapter_simulation_plan(story, 1, chapter_seed=seed).model_dump()
    events = simulate_world_events(story, 1, chapter_seed=seed, simulation_plan=plan)

    cards = select_scene_cards(events, chapter_seed=seed, simulation_plan=plan)
    verify_card = next(card for card in cards if card.template_id == "small_verification")
    surface = " ".join(verify_card.must_show)

    assert "SYSTEMIC_LEDGER" in surface
    assert "SYSTEMIC_CAUSE" in surface
    assert "SYSTEMIC_VISIBILITY" in surface
    assert verify_card.state_delta["game_world_simulation"]["ledger_delta"]["clock_minutes"] > 0
    assert "visibility_limits_knowledge" in verify_card.state_delta["game_world_simulation"]["systemic_rules"]


def test_writing_packet_exposes_systemic_simulation_summary():
    story = _story()
    seed = build_chapter_seed(story, 1)
    plan = build_chapter_simulation_plan(story, 1, chapter_seed=seed).model_dump()
    events = simulate_world_events(story, 1, chapter_seed=seed, simulation_plan=plan)
    cards = select_scene_cards(events, chapter_seed=seed, simulation_plan=plan)
    bundle = ChapterBundle(
        chapter_number=1,
        body="",
        next_outline="Continue toward a service counter or market route.",
        updated_story=story,
        scene_cards=[card.model_dump() for card in cards],
    )

    packet = build_codex_writing_packet(story, bundle)

    systemic = packet["systemic_simulation"]
    assert systemic["schema_version"] == "systemic-simulation/v1"
    assert "state_changes_must_be_written_back" in systemic["rules_fired"]
    assert any("combat_tick" in item for item in systemic["causal_chain"])
    assert systemic["ledger_delta"]["hidden_system_delta"]["chaos_seed_anomaly_score"] > 0
    assert systemic["visibility_layers"]["npc"]
    assert systemic["visibility_layers"]["guild"]
