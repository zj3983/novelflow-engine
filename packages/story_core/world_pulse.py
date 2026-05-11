from __future__ import annotations

from typing import Any

from packages.story_core.models import StoryState


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _numeric_inventory_total(inventory: dict[str, Any]) -> int:
    total = 0
    for value in inventory.values():
        total += _as_int(value)
    return total


def advance_world_pulse(story: StoryState, *, chapter_number: int) -> dict[str, Any]:
    """Advance background world state once after a chapter settles.

    The pulse is deliberately conservative: it records what background actors
    can infer, then exposes only player-visible traces to the next chapter.
    """

    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    story.progression_ledger = ledger

    economy = ledger.setdefault("economy", {})
    inventory = _as_dict(economy.get("inventory"))
    market = ledger.setdefault("market", {}).setdefault("newbie_materials", {})
    systems = ledger.setdefault("systems", {})
    chaos_seed = systems.setdefault("chaos_seed", {})
    reality = ledger.setdefault("reality", {})
    persistent = ledger.setdefault("persistent_world", {})

    inventory_total = _numeric_inventory_total(inventory)
    price_copper = _as_int(market.get("price_copper"), 0)
    supply = _as_int(market.get("supply"), 0)
    anomaly_score = _as_int(chaos_seed.get("anomaly_score"), 0)
    prior_pulse = _as_dict(ledger.get("world_pulse")).get("latest")
    pulse_index = _as_int(_as_dict(prior_pulse).get("pulse_index"), 0) + 1
    visible_at_chapter = int(chapter_number) + 1

    npc_memory = persistent.setdefault("npc_memory", {}).setdefault("service_counter", {})
    npc_memory["last_seen_batch_count"] = inventory_total
    npc_memory["knowledge_boundary"] = "service_inputs_only"

    guild_intel = persistent.setdefault("guild_intel", {}).setdefault("white_robe_guild", {})
    guild_intel["knowledge_state"] = "weak_pattern_only" if anomaly_score > 0 else "no_signal"
    guild_intel["cannot_know"] = ["hidden_talent", "real_identity", "precise_coordinates"]

    market_state = persistent.setdefault("market_state", {}).setdefault("newbie_materials", {})
    market_state["supply"] = supply
    market_state["price_copper"] = price_copper
    market_state["signal"] = "small_price_wobble" if price_copper else "unchanged"

    background_events = [
        {
            "id": f"pulse-{pulse_index}-npc-counter",
            "actor": "service_npc",
            "action": "records material batch through counter rules",
            "visible_to": ["protagonist", "queue_players"],
        },
        {
            "id": f"pulse-{pulse_index}-market",
            "actor": "local_market",
            "action": "updates local material price board from small supply change",
            "visible_to": ["public_price_board"],
        },
        {
            "id": f"pulse-{pulse_index}-guild",
            "actor": "white_robe_guild",
            "action": "keeps only weak route and batch suspicion",
            "visible_to": ["background_only"],
        },
    ]

    visibility_inbox = [
        {
            "id": f"pulse-{pulse_index}-npc-counter",
            "visible_at_chapter": visible_at_chapter,
            "channel": "npc_counter",
            "text": f"Service counter notices a batch of {inventory_total} low-level materials and applies posted thresholds.",
            "source_event": "service_npc",
        },
        {
            "id": f"pulse-{pulse_index}-price-board",
            "visible_at_chapter": visible_at_chapter,
            "channel": "price_board",
            "text": f"Newbie material price board shows a small local wobble near {price_copper} copper with supply {supply}.",
            "source_event": "local_market",
        },
    ]

    if "rent_due_days" in reality:
        due_days = max(0, _as_int(reality.get("rent_due_days"), 0) - 1)
        reality["rent_due_days"] = due_days
        background_events.append(
            {
                "id": f"pulse-{pulse_index}-rent",
                "actor": "reality_pressure",
                "action": "rent deadline advances by one chapter beat",
                "visible_to": ["protagonist"],
            }
        )
        visibility_inbox.append(
            {
                "id": f"pulse-{pulse_index}-rent",
                "visible_at_chapter": visible_at_chapter,
                "channel": "phone_notice",
                "text": f"Rent reminder tightens: {due_days} days remain; available cash stays at {reality.get('cash_cny', 0)} CNY.",
                "source_event": "reality_pressure",
            }
        )

    pulse = {
        "schema_version": "world-pulse/v1",
        "chapter_number": chapter_number,
        "visible_at_chapter": visible_at_chapter,
        "pulse_index": pulse_index,
        "background_events": background_events,
        "visibility_inbox": visibility_inbox,
        "hidden_state": {
            "chaos_seed_anomaly_score": anomaly_score,
            "guild_knowledge_state": guild_intel["knowledge_state"],
        },
    }

    pulse_store = ledger.setdefault("world_pulse", {})
    pulse_store["latest"] = pulse
    history = _as_list(pulse_store.get("history"))
    pulse_store["history"] = [*history, pulse][-12:]
    ledger["visibility_inbox"] = [*_as_list(ledger.get("visibility_inbox")), *visibility_inbox]
    return pulse
