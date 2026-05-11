from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import _build_simulation_status, _story_snapshot
from packages.story_core.world_pulse import advance_world_pulse


def _pulse_story() -> StoryState:
    return StoryState(
        story_id="s-world-pulse",
        outline="VRMMO hidden drop advantage under real rent pressure.",
        genre="VRMMO",
        style="leveling",
        characters=[CharacterState(name="Su Ye", role="protagonist", game_id="Night Ember")],
        progression_ledger={
            "clock": {"elapsed_minutes": 24},
            "economy": {"inventory": {"wolf_pelt": 6, "venom_gland": 8}},
            "market": {"newbie_materials": {"supply": 47, "price_copper": 5}},
            "systems": {"chaos_seed": {"anomaly_score": 7}},
            "pressure": {"next": ["repair_weapon", "find_market_route"]},
            "reality": {"rent_due_days": 3, "cash_cny": 27.6},
        },
    )


def test_world_pulse_advances_background_actors_and_visibility_inbox():
    story = _pulse_story()

    pulse = advance_world_pulse(story, chapter_number=1)

    assert pulse["schema_version"] == "world-pulse/v1"
    assert pulse["chapter_number"] == 1
    assert pulse["visible_at_chapter"] == 2
    actor_ids = {event["actor"] for event in pulse["background_events"]}
    assert {"service_npc", "local_market", "white_robe_guild", "reality_pressure"} <= actor_ids
    assert any(item["channel"] == "npc_counter" for item in pulse["visibility_inbox"])
    assert any(item["channel"] == "price_board" for item in pulse["visibility_inbox"])
    assert any(item["channel"] == "phone_notice" for item in pulse["visibility_inbox"])

    inbox_text = " ".join(item["text"] for item in pulse["visibility_inbox"])
    forbidden = ("hidden talent", "real identity", "precise coordinates", "coordinates locked")
    assert not any(term in inbox_text.lower() for term in forbidden)

    ledger = story.progression_ledger
    assert ledger["reality"]["rent_due_days"] == 2
    assert ledger["persistent_world"]["npc_memory"]["service_counter"]["last_seen_batch_count"] == 14
    assert ledger["persistent_world"]["guild_intel"]["white_robe_guild"]["knowledge_state"] == "weak_pattern_only"
    assert ledger["visibility_inbox"][-1]["visible_at_chapter"] == 2
    assert ledger["world_pulse"]["latest"]["pulse_index"] == 1


def test_world_pulse_accumulates_without_erasing_prior_inbox():
    story = _pulse_story()
    story.progression_ledger["visibility_inbox"] = [
        {"id": "old_notice", "visible_at_chapter": 1, "text": "old"}
    ]

    advance_world_pulse(story, chapter_number=1)
    advance_world_pulse(story, chapter_number=2)

    assert story.progression_ledger["world_pulse"]["latest"]["pulse_index"] == 2
    assert story.progression_ledger["visibility_inbox"][0]["id"] == "old_notice"
    assert any(item["visible_at_chapter"] == 3 for item in story.progression_ledger["visibility_inbox"])


def test_story_snapshot_and_simulation_status_surface_latest_world_pulse():
    story = _pulse_story()
    pulse = advance_world_pulse(story, chapter_number=1)

    snapshot = _story_snapshot(story)
    status = _build_simulation_status(story)

    assert snapshot["world_pulse"]["latest"]["pulse_index"] == pulse["pulse_index"]
    assert snapshot["visibility_inbox"][0]["visible_at_chapter"] == 2
    assert status["world_pulse"]["latest"]["visible_at_chapter"] == 2
