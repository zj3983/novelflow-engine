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


def _npc_memory_update(
    *,
    npc_memory: dict[str, Any],
    inventory_total: int,
    pulse_index: int,
    chapter_number: int,
) -> None:
    npc_memory["last_seen_batch_count"] = inventory_total
    npc_memory["knowledge_boundary"] = "service_inputs_only"
    npc_memory["stance"] = "watchful_service" if inventory_total >= 10 else "routine_service"
    npc_memory["next_service_bias"] = "posted_thresholds_only"
    memory_log = _as_list(npc_memory.get("memory_log"))
    memory_log.append(
        {
            "pulse_index": pulse_index,
            "chapter_number": chapter_number,
            "batch_count": inventory_total,
            "knows": ["material_count", "posted_thresholds", "queue_pressure"],
            "cannot_know": ["hidden_talent", "real_identity", "complete_route"],
        }
    )
    npc_memory["memory_log"] = memory_log[-12:]


def _market_order_book(
    *,
    inventory_total: int,
    price_copper: int,
    supply: int,
) -> dict[str, Any]:
    bid = max(1, price_copper)
    ask = max(bid + 1, price_copper + 2)
    buy_quantity = min(10, max(1, inventory_total))
    sell_pressure = "localized_batch_pressure" if inventory_total >= 10 else "normal_newbie_flow"
    return {
        "buy_orders": [
            {
                "buyer": "village_service_counter",
                "quantity": buy_quantity,
                "price_copper": bid,
                "visibility": "posted_threshold",
            }
        ],
        "sell_orders": [
            {
                "seller": "public_newbie_flow",
                "quantity_hint": max(0, supply),
                "price_copper": ask,
                "visibility": "public_price_board",
            }
        ],
        "spread_copper": {"bid": bid, "ask": ask},
        "sell_pressure": sell_pressure,
    }


def _guild_intel_update(
    *,
    guild_intel: dict[str, Any],
    inventory_total: int,
    anomaly_score: int,
) -> None:
    prior_score = _as_int(guild_intel.get("suspicion_score"), 0)
    increment = max(0, anomaly_score // 2)
    if inventory_total >= 10:
        increment += 1
    suspicion_score = min(100, prior_score + increment)
    confidence = "weak" if suspicion_score < 12 else "correlated"
    knowledge_state = "weak_pattern_only" if confidence == "weak" else "correlated_weak_pattern"
    guild_intel["knowledge_state"] = knowledge_state
    guild_intel["confidence"] = confidence
    guild_intel["suspicion_score"] = suspicion_score
    guild_intel["cannot_know"] = ["hidden_talent", "real_identity", "precise_coordinates"]
    guild_intel["scouting_queue"] = [
        {
            "target": "low_level_material_batches",
            "confidence": confidence,
            "evidence": ["price_board_wobble", "service_counter_batch", "route_noise"],
            "required_evidence": ["repeat_batch", "rare_item", "eyewitness", "service_counter_anomaly"],
            "next_action": "watch_public_traces",
        }
    ]


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
    _npc_memory_update(
        npc_memory=npc_memory,
        inventory_total=inventory_total,
        pulse_index=pulse_index,
        chapter_number=chapter_number,
    )

    guild_intel = persistent.setdefault("guild_intel", {}).setdefault("white_robe_guild", {})
    _guild_intel_update(
        guild_intel=guild_intel,
        inventory_total=inventory_total,
        anomaly_score=anomaly_score,
    )

    market_state = persistent.setdefault("market_state", {}).setdefault("newbie_materials", {})
    market_state["supply"] = supply
    market_state["price_copper"] = price_copper
    market_state["signal"] = "small_price_wobble" if price_copper else "unchanged"
    order_book = _market_order_book(
        inventory_total=inventory_total,
        price_copper=price_copper,
        supply=supply,
    )
    market_state["order_book"] = order_book

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
            "action": f"keeps {guild_intel['confidence']} route and batch suspicion",
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
    if inventory_total >= 10:
        visibility_inbox.append(
            {
                "id": f"pulse-{pulse_index}-player-chatter",
                "visible_at_chapter": visible_at_chapter,
                "channel": "player_chatter",
                "text": "Nearby players only gossip about low-level material batches, price wobble, and route noise.",
                "source_event": "route_noise",
            }
        )

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
        "market_order_book": order_book,
    }

    pulse_store = ledger.setdefault("world_pulse", {})
    pulse_store["latest"] = pulse
    history = _as_list(pulse_store.get("history"))
    pulse_store["history"] = [*history, pulse][-12:]
    ledger["visibility_inbox"] = [*_as_list(ledger.get("visibility_inbox")), *visibility_inbox]
    return pulse


def visibility_inbox_for_chapter(
    story: StoryState,
    chapter_number: int,
    *,
    max_items: int = 4,
) -> list[dict[str, Any]]:
    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    inbox = _as_list(ledger.get("visibility_inbox"))
    consumed = set(visibility_inbox_consumed_ids(story))
    due_items: list[dict[str, Any]] = []
    for item in inbox:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if item_id and item_id in consumed:
            continue
        if _as_int(item.get("visible_at_chapter"), -1) != int(chapter_number):
            continue
        text = str(item.get("text") or "")
        lowered = text.lower()
        if any(term in lowered for term in ("hidden talent", "real identity", "precise coordinates", "coordinates locked")):
            continue
        due_items.append(dict(item))
    return due_items[:max_items]


def visibility_inbox_consumed_ids(story: StoryState) -> list[str]:
    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    pressure = _as_dict(ledger.get("visibility_inbox_pressure"))
    consumed_ids: list[str] = []
    for item in _as_list(pressure.get("consumed_ids")):
        item_id = str(item).strip()
        if item_id and item_id not in consumed_ids:
            consumed_ids.append(item_id)
    return consumed_ids
