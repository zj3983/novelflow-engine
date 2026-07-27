from __future__ import annotations

from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _chapter_outline(director_context: Any) -> dict[str, Any]:
    if not isinstance(director_context, dict):
        return {}
    snapshot = director_context.get("project_snapshot")
    if not isinstance(snapshot, dict):
        return {}
    outline_context = snapshot.get("outline_context")
    if not isinstance(outline_context, dict):
        return {}
    chapter = outline_context.get("chapter")
    return chapter if isinstance(chapter, dict) else {}


def build_outline_chapter_plan(
    director_context: dict[str, Any],
    chapter_number: int,
) -> dict[str, Any] | None:
    """Translate an actionable detailed outline into the writer's plan contract."""

    chapter = _chapter_outline(director_context)
    try:
        outlined_number = int(chapter.get("chapter_number") or 0)
    except (TypeError, ValueError):
        return None
    if outlined_number != chapter_number:
        return None

    title = _text(chapter.get("title"))
    goal = _text(chapter.get("goal"))
    obstacle = _text(chapter.get("obstacle"))
    action = _text(chapter.get("action"))
    turn = _text(chapter.get("turn"))
    payoff = _text(chapter.get("payoff"))
    ending_hook = _text(chapter.get("ending_hook"))
    if not goal or not any((action, turn, payoff)):
        return None

    ordered_actions: list[str] = []
    for item in (goal, obstacle, action, turn, payoff, ending_hook):
        if item and item not in ordered_actions:
            ordered_actions.append(item)

    cast = chapter.get("cast") if isinstance(chapter.get("cast"), list) else []
    character_moves = []
    for index, raw_name in enumerate(cast):
        name = _text(raw_name)
        if not name:
            continue
        character_moves.append(
            {
                "name": name,
                "goal": goal,
                "emotion": "",
                "action": action or turn or payoff,
                "priority": "primary" if index == 0 else "secondary",
            }
        )

    chapter_satisfaction = {
        "core_event": action or goal,
        "obstacle": obstacle,
        "visible_payoff": payoff,
        "cost": "",
        "outsider_misread": "",
        "state_change": turn or payoff,
        "next_hook": ending_hook,
    }
    event_plan = {
        "chapter_title": title,
        "ordered_actions": ordered_actions,
        "chapter_satisfaction": chapter_satisfaction,
        "chapter_end_hook": {
            "type": "悬念钩",
            "strength": "medium",
            "content": ending_hook,
        }
        if ending_hook
        else {},
        "world_reactions": [],
        "stakes": obstacle,
        "next_focus": ending_hook,
    }
    decision = chapter.get("attribute_allocation_decision")
    if isinstance(decision, dict):
        event_plan["attribute_allocation_decision"] = decision
    return {
        "planning_source": "outline",
        "character_moves": character_moves,
        "chapter_intent": {
            "chapter_title": title,
            "cadence": "tight",
            "next_focus": ending_hook,
            "primary_conflict": {"collision": obstacle} if obstacle else {},
            "secondary_conflict": {},
        },
        "event_plan": event_plan,
        "memory_constraints": {},
    }
