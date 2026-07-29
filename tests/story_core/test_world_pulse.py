from packages.story_core.models import CharacterState, StoryState
from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.orchestrator import StoryOrchestrator, _build_simulation_status, _story_snapshot
from packages.story_core.simulation import build_chapter_simulation_plan
from packages.story_core.writing_taskbook import build_writing_taskbook
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
    assert ledger["persistent_world"]["npc_memory"]["service_counter"]["last_seen_batch_count"] == 0
    assert ledger["persistent_world"]["guild_intel"]["white_robe_guild"]["knowledge_state"] == "weak_pattern_only"
    assert ledger["visibility_inbox"][-1]["visible_at_chapter"] == 2
    assert ledger["world_pulse"]["latest"]["pulse_index"] == 1


def test_world_pulse_exposes_only_recorded_public_material_flow():
    story = _pulse_story()
    story.progression_ledger["market"]["newbie_materials"]["visible_batch_count"] = 6

    pulse = advance_world_pulse(story, chapter_number=1)

    counter = story.progression_ledger["persistent_world"]["npc_memory"]["service_counter"]
    assert counter["last_seen_batch_count"] == 6
    assert "batch of 6" in pulse["visibility_inbox"][0]["text"]
    assert "batch of 14" not in " ".join(item["text"] for item in pulse["visibility_inbox"])


def test_world_pulse_does_not_invent_zero_batch_or_zero_price_activity():
    story = _pulse_story()
    story.progression_ledger["market"]["newbie_materials"] = {
        "visible_batch_count": 0,
        "supply": 0,
        "price_copper": 0,
    }
    story.progression_ledger["systems"]["chaos_seed"]["anomaly_score"] = 20
    story.progression_ledger["reality"] = {}

    pulse = advance_world_pulse(story, chapter_number=1)

    assert pulse["visibility_inbox"] == []
    assert pulse["background_events"] == []
    assert pulse["market_order_book"]["buy_orders"] == []
    assert "npc_memory" not in story.progression_ledger["persistent_world"]
    assert "guild_intel" not in story.progression_ledger["persistent_world"]


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


def test_world_pulse_builds_persistent_actor_subsystems():
    story = _pulse_story()
    story.progression_ledger["market"]["newbie_materials"]["visible_batch_count"] = 14

    pulse = advance_world_pulse(story, chapter_number=1)

    persistent = story.progression_ledger["persistent_world"]
    npc_memory = persistent["npc_memory"]["service_counter"]
    assert npc_memory["stance"] == "watchful_service"
    assert npc_memory["next_service_bias"] == "posted_thresholds_only"
    assert npc_memory["memory_log"][-1]["batch_count"] == 14

    market_state = persistent["market_state"]["newbie_materials"]
    order_book = market_state["order_book"]
    assert order_book["sell_pressure"] == "localized_batch_pressure"
    assert order_book["buy_orders"][0]["price_copper"] == 5
    assert order_book["buy_orders"][0]["quantity"] == 10
    assert pulse["market_order_book"] == order_book

    guild = persistent["guild_intel"]["white_robe_guild"]
    assert guild["scouting_queue"][0]["target"] == "low_level_material_batches"
    assert guild["scouting_queue"][0]["next_action"] == "watch_public_traces"
    assert guild["confidence"] == "weak"
    assert guild["suspicion_score"] > 0


def test_world_pulse_accumulates_guild_suspicion_without_omniscience():
    story = _pulse_story()
    story.progression_ledger["market"]["newbie_materials"]["visible_batch_count"] = 14
    first = advance_world_pulse(story, chapter_number=1)
    first_score = story.progression_ledger["persistent_world"]["guild_intel"]["white_robe_guild"]["suspicion_score"]
    story.progression_ledger["systems"]["chaos_seed"]["anomaly_score"] = 18
    story.progression_ledger["economy"]["inventory"]["venom_gland"] = 20
    story.progression_ledger["market"]["newbie_materials"]["visible_batch_count"] = 26

    second = advance_world_pulse(story, chapter_number=2)

    guild = story.progression_ledger["persistent_world"]["guild_intel"]["white_robe_guild"]
    assert guild["suspicion_score"] > first_score
    assert guild["knowledge_state"] == "correlated_weak_pattern"
    assert guild["cannot_know"] == ["hidden_talent", "real_identity", "precise_coordinates"]
    assert any(item["channel"] == "player_chatter" for item in second["visibility_inbox"])

    leaked_text = " ".join(
        [
            str(guild),
            " ".join(item["text"] for item in first["visibility_inbox"]),
            " ".join(item["text"] for item in second["visibility_inbox"]),
        ]
    ).lower()
    assert "coordinates locked" not in leaked_text
    assert "real identity" not in leaked_text
    assert "hidden talent" not in leaked_text


def test_normal_generation_advances_world_pulse_for_next_chapter():
    story = _pulse_story()

    bundle = StoryOrchestrator().generate_next_chapter(story)

    ledger = bundle.updated_story.progression_ledger
    assert ledger["world_pulse"]["latest"]["chapter_number"] == 1
    assert ledger["world_pulse"]["latest"]["visible_at_chapter"] == 2
    assert any(item["visible_at_chapter"] == 2 for item in ledger["visibility_inbox"])

    next_seed = build_chapter_seed(bundle.updated_story, 2)
    assert next_seed["current_state"]["world_pulse"]["latest"]["pulse_index"] == 1


def test_chapter_simulation_plan_carries_long_running_world_context():
    story = _pulse_story()
    story.progression_ledger["market"]["newbie_materials"]["visible_batch_count"] = 14
    pulse = advance_world_pulse(story, chapter_number=1)
    seed = build_chapter_seed(story, 2)

    plan = build_chapter_simulation_plan(story, 2, chapter_seed=seed).model_dump()

    context = plan["world_context"]
    assert context["latest_pulse"]["pulse_index"] == pulse["pulse_index"]
    assert context["persistent_world"]["npc_memory"]["service_counter"]["last_seen_batch_count"] == 14
    assert any(item["channel"] == "npc_counter" for item in context["visible_inbox"])
    assert context["simulation_horizon"] == "long_running_world_then_chapter_slice"


def test_writing_taskbook_turns_world_context_into_visibility_rules():
    story = _pulse_story()
    advance_world_pulse(story, chapter_number=1)
    seed = build_chapter_seed(story, 2)
    simulation_plan = build_chapter_simulation_plan(story, 2, chapter_seed=seed).model_dump()

    taskbook = build_writing_taskbook(
        chapter_number=2,
        plan={"simulation_plan": simulation_plan},
        genre="VRMMO",
    )

    required = "\n".join(taskbook["global_required"])
    forbidden = "\n".join(taskbook["global_forbidden"])
    assert "world pulse" in required
    assert "npc_counter" in required
    assert "hidden_state" in forbidden
