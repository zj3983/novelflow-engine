from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from packages.story_core.models import StoryState


def _usable_label(value: Any) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or set(cleaned) <= {"?", "锛?", "\ufffd"}:
        return ""
    return cleaned


def _lead_label(story: StoryState) -> str:
    for character in story.characters:
        if character.role in {"protagonist", "主角"}:
            return (
                _usable_label(character.game_id)
                or _usable_label(character.game_panel.game_id)
                or _usable_label(character.name)
                or "protagonist"
            )
    if story.characters:
        character = story.characters[0]
        return (
            _usable_label(character.game_id)
            or _usable_label(character.game_panel.game_id)
            or _usable_label(character.name)
            or "protagonist"
        )
    return "protagonist"


def _minutes(value: Any) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else 0


def _sum_drops(ticks: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for tick in ticks:
        drop_roll = tick.get("drop_roll") if isinstance(tick.get("drop_roll"), dict) else {}
        actual = drop_roll.get("actual") if isinstance(drop_roll.get("actual"), dict) else {}
        for item, amount in actual.items():
            try:
                count = int(amount)
            except (TypeError, ValueError):
                count = 0
            totals[str(item)] = totals.get(str(item), 0) + count
    return totals


def _dominant_item_names(drops: dict[str, int]) -> tuple[str, str]:
    names = sorted(drops, key=lambda item: (-drops[item], item))
    first = names[0] if names else "primary_material"
    second = names[1] if len(names) > 1 else "secondary_material"
    return first, second


def initial_game_world_state(story: StoryState, chapter_number: int, *, variant: str = "") -> dict[str, Any]:
    """Create a compact state snapshot that can be advanced by rules.

    This is intentionally data-first. Prose can rename or dramatize these facts,
    but the simulation layer needs stable ledgers, clocks, actors, markets, and
    hidden-system counters before it can produce believable consequences.
    """

    lead = _lead_label(story)
    return {
        "schema_version": "systemic-world-state/v1",
        "chapter_number": chapter_number,
        "clock": {"minute": 0, "label": "chapter_start"},
        "variant": variant or "default",
        "actors": {
            "protagonist": {
                "label": lead,
                "location": "newbie_field",
                "goals": ["verify_advantage", "avoid_attention", "preserve_exit_route"],
                "resources": {"hp": 100, "mp": 60, "weapon_durability": 10, "coins": 0},
                "knowledge": ["own_panel", "visible_drops", "local_npc_prices"],
            },
            "service_npc": {
                "label": "local_service_npc",
                "location": "newbie_village",
                "goals": ["keep_counter_order", "protect_inventory", "avoid_bad_debt"],
                "resources": {"inventory_slots": 12, "cashbox_copper": 230},
                "knowledge": ["posted_prices", "quest_thresholds", "counter_queue"],
            },
            "local_guild": {
                "label": "white_robe_guild",
                "location": "newbie_village",
                "goals": ["control_profitable_routes", "notice_repeatable_edges"],
                "resources": {"scouts": 2, "market_watch": 0},
                "knowledge": ["public_listings", "visible_route_noise"],
            },
        },
        "markets": {
            "newbie_materials": {
                "supply": 34,
                "demand": 71,
                "base_price_copper": 6,
                "price_copper": 6,
                "guild_control": 0.8,
                "recent_batches": [],
            }
        },
        "systems": {
            "chaos_seed": {
                "parsed": False,
                "anomaly_score": 0,
                "public_signal": "none",
                "private_signal": "unresolved",
            }
        },
    }


def resolve_systemic_game_simulation(
    story: StoryState,
    chapter_number: int,
    *,
    variant: str,
    ticks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Advance game-world state from concrete ticks.

    The output separates private truth from public observations so later scenes
    cannot let NPCs or guilds know more than the world has exposed.
    """

    state = initial_game_world_state(story, chapter_number, variant=variant)
    current = deepcopy(state)
    resolved_ticks: list[dict[str, Any]] = []
    causal_chain: list[str] = []
    public_observations: list[str] = []
    private_observations: list[str] = []

    combat_ticks = [tick for tick in ticks if isinstance(tick, dict) and tick.get("kind") == "combat"]
    npc_ticks = [tick for tick in ticks if isinstance(tick, dict) and tick.get("kind") == "npc_service"]
    total_drops: dict[str, int] = {}
    total_minutes = 0
    total_cost = {"hp": 0, "mp": 0, "durability": 0}

    for tick in ticks:
        if not isinstance(tick, dict):
            continue
        before = {
            "minute": current["clock"]["minute"],
            "market_supply": current["markets"]["newbie_materials"]["supply"],
            "anomaly_score": current["systems"]["chaos_seed"]["anomaly_score"],
        }
        delta_minutes = _minutes(tick.get("time_delta"))
        current["clock"]["minute"] += delta_minutes
        total_minutes += delta_minutes

        cost = tick.get("cost") if isinstance(tick.get("cost"), dict) else {}
        for key in total_cost:
            try:
                total_cost[key] += int(cost.get(key, 0))
            except (TypeError, ValueError):
                pass

        drop_roll = tick.get("drop_roll") if isinstance(tick.get("drop_roll"), dict) else {}
        actual = drop_roll.get("actual") if isinstance(drop_roll.get("actual"), dict) else {}
        drop_count = 0
        for item, amount in actual.items():
            try:
                count = int(amount)
            except (TypeError, ValueError):
                count = 0
            drop_count += count
            total_drops[str(item)] = total_drops.get(str(item), 0) + count

        if tick.get("kind") == "combat":
            market = current["markets"]["newbie_materials"]
            market["supply"] += drop_count
            market["recent_batches"].append({"minute": current["clock"]["minute"], "count": drop_count})
            current["systems"]["chaos_seed"]["anomaly_score"] += max(0, drop_count - 1)
            causal_chain.append(
                "combat_tick -> material_batch -> local_supply_delta -> private_anomaly_score"
            )
            public_observations.append(
                "Nearby players can see fighting rhythm and some loot flashes, not the full inventory ledger."
            )
            private_observations.append(
                "The protagonist can compare each loot batch against the baseline and notice the advantage is repeatable."
            )
        elif tick.get("kind") == "npc_service":
            causal_chain.append("npc_service -> counter_rule -> service_boundary -> next_decision")
            public_observations.append(
                "The service NPC only reacts through posted rules, queue pressure, inventory, or price thresholds."
            )

        after = {
            "minute": current["clock"]["minute"],
            "market_supply": current["markets"]["newbie_materials"]["supply"],
            "anomaly_score": current["systems"]["chaos_seed"]["anomaly_score"],
        }
        resolved_ticks.append(
            {
                "tick_id": tick.get("tick_id", ""),
                "kind": tick.get("kind", ""),
                "before": before,
                "after": after,
                "visible_to": tick.get("visible_to", []),
            }
        )

    primary_item, secondary_item = _dominant_item_names(total_drops)
    anomaly_score = current["systems"]["chaos_seed"]["anomaly_score"]
    if anomaly_score >= 5:
        current["systems"]["chaos_seed"]["private_signal"] = "low_level_batches_exceed_baseline"
        private_observations.append(
            "A hidden counter records the repeated low-level material surplus, but it is not public evidence yet."
        )
    if len(combat_ticks) >= 5 and total_drops:
        causal_chain.append("repeatable_drop_pattern -> hidden_system_record -> future_hook_candidate")
    if npc_ticks:
        causal_chain.append("material_inventory -> service_counter_threshold -> monetization_route")

    market = current["markets"]["newbie_materials"]
    batch_pressure = sum(batch["count"] for batch in market["recent_batches"])
    if batch_pressure >= 12:
        market["price_copper"] = max(1, market["base_price_copper"] - 1)
        public_observations.append(
            "Only a small local price wobble is plausible at this scale; guild pursuit still needs more public signals."
        )

    ledger_delta = {
        "clock_minutes": total_minutes,
        "inventory_delta": total_drops,
        "cost_delta": total_cost,
        "market_delta": {
            "material_supply": market["supply"] - state["markets"]["newbie_materials"]["supply"],
            "price_copper": market["price_copper"],
        },
        "hidden_system_delta": {"chaos_seed_anomaly_score": anomaly_score},
        "next_pressure": [
            f"convert_or_submit_{primary_item}",
            f"manage_capacity_for_{secondary_item}",
            "avoid_turning_private_pattern_into_public_signal",
        ],
    }

    return {
        "schema_version": "systemic-simulation/v1",
        "initial_state": state,
        "final_state": current,
        "resolved_ticks": resolved_ticks,
        "causal_chain": causal_chain,
        "visibility_layers": {
            "private": private_observations,
            "public": public_observations,
            "npc": [
                "NPCs can know service inputs, posted thresholds, and queue behavior.",
                "NPCs cannot know hidden talent, real identity, or the complete route unless exposed by later actions.",
            ],
            "guild": [
                "Guilds can infer only from repeated public listings, route witnesses, rare items, or NPC anomalies.",
                "A first small batch should create at most weak interest, not omniscient pursuit.",
            ],
        },
        "ledger_delta": ledger_delta,
        "rules_fired": [
            "state_changes_must_be_written_back",
            "visibility_limits_knowledge",
            "market_reacts_by_scale",
            "hidden_system_tracks_private_anomaly",
        ],
    }
