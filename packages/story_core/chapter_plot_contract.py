"""Compact, writer-facing contract distilled from planning and simulation data."""

from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any, limit: int = 180) -> str:
    return str(value or "").strip()[:limit]


def _items(value: Any, limit: int = 5, chars: int = 120) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item, chars) for item in value if _text(item, chars)][:limit]


def build_chapter_plot_contract(plan: dict[str, Any] | None = None, chapter_seed: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return only the plot decisions the writer needs for one chapter."""
    plan = _as_dict(plan)
    seed = _as_dict(chapter_seed)
    event = _as_dict(plan.get("event_plan"))
    simulation = _as_dict(plan.get("simulation_plan"))
    satisfaction = _as_dict(event.get("chapter_satisfaction"))
    hook = _as_dict(event.get("chapter_end_hook"))

    raw_actions = event.get("ordered_actions") or simulation.get("ordered_actions") or []
    beats: list[dict[str, str]] = []
    for action in raw_actions[:5] if isinstance(raw_actions, list) else []:
        if isinstance(action, dict):
            beats.append(
                {
                    "desire": _text(action.get("goal") or action.get("desire")),
                    "action": _text(action.get("action")),
                    "obstacle": _text(action.get("obstacle") or action.get("collision")),
                    "choice": _text(action.get("choice") or action.get("decision")),
                    "result": _text(action.get("result") or action.get("payoff")),
                }
            )
        elif _text(action):
            beats.append({"desire": "", "action": _text(action), "obstacle": "", "choice": "", "result": ""})

    if not beats:
        for scene in plan.get("scene_cards", [])[:5] if isinstance(plan.get("scene_cards"), list) else []:
            if isinstance(scene, dict):
                beats.append(
                    {
                        "desire": _text(scene.get("goal") or scene.get("purpose")),
                        "action": _text(scene.get("required_surface") or scene.get("action")),
                        "obstacle": _text(scene.get("obstacle")),
                        "choice": _text(scene.get("choice")),
                        "result": _text(scene.get("exit_state") or scene.get("payoff")),
                    }
                )

    contract = {
        "chapter_goal": _text(
            satisfaction.get("core_event")
            or simulation.get("chapter_goal")
            or event.get("next_focus")
            or seed.get("chapter_goal")
        ),
        "emotional_goal": _text(
            satisfaction.get("emotion_target")
            or event.get("emotional_turn")
            or simulation.get("emotional_goal")
            or "让人物在章末改变一点态度或选择"
        ),
        "beats": beats,
        "visible_state_changes": _items(
            satisfaction.get("state_change")
            or simulation.get("visible_state_changes")
            or simulation.get("ledger_updates")
            or seed.get("allowed_progress"),
            limit=6,
        ),
        "next_hook": _text(
            hook.get("content")
            or satisfaction.get("next_hook")
            or event.get("next_focus")
            or simulation.get("next_focus")
        ),
        "fact_locks": _items(
            simulation.get("fact_locks")
            or simulation.get("must_keep_facts")
            or seed.get("must_keep_facts")
            or seed.get("forbidden_moves"),
            limit=8,
        ),
    }
    return {key: value for key, value in contract.items() if value not in ("", [], {})}
