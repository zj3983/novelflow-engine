"""Build the small, scene-level contract that guides emotional dialogue."""

from __future__ import annotations

from typing import Any


def _text(value: Any, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


def _first_text(values: list[Any], limit: int = 160) -> str:
    for value in values:
        if isinstance(value, list):
            value = next((item for item in value if _text(item, limit)), "")
        if isinstance(value, dict):
            value = value.get("summary") or value.get("description") or value.get("content") or ""
        if text := _text(value, limit):
            return text
    return ""


def build_dialogue_context(character_context: dict[str, Any], plan: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = plan if isinstance(plan, dict) else {}
    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {}
    satisfaction = event_plan.get("chapter_satisfaction") if isinstance(event_plan.get("chapter_satisfaction"), dict) else {}
    emotional_target = _text(
        satisfaction.get("emotion_target")
        or event_plan.get("emotional_turn")
        or plan.get("emotional_turn")
        or "让人物在说完后改变一点态度、判断或下一步选择",
    )
    cards_value = character_context.get("cards") if isinstance(character_context, dict) else []
    cards = cards_value if isinstance(cards_value, list) else []
    card_names = [
        _text((card.get("identity") or {}).get("name"), 60)
        for card in cards[:4] if isinstance(card, dict)
    ]
    relationships: list[dict[str, Any]] = []
    for card in cards[:4] if isinstance(cards, list) else []:
        if not isinstance(card, dict):
            continue
        name = _text((card.get("identity") or {}).get("name"))
        for relation in card.get("relationship_context", []) if isinstance(card.get("relationship_context"), list) else []:
            if isinstance(relation, dict):
                relationships.append(
                    {
                        "character": name,
                        "target": _text(relation.get("target"), 60),
                        "trust": relation.get("trust", 0),
                        "tension": relation.get("tension", 0),
                        "bond": _text(relation.get("bond"), 80),
                    }
                )
    moves = plan.get("character_moves")
    moves_by_name: dict[str, list[dict[str, Any]]] = {}
    if isinstance(moves, dict):
        for name, entries in moves.items():
            normalized = entries if isinstance(entries, list) else [entries]
            moves_by_name[_text(name, 60)] = [item for item in normalized if isinstance(item, dict)]
    elif isinstance(moves, list):
        for item in moves:
            if not isinstance(item, dict):
                continue
            name = _text(item.get("name") or item.get("game_id"), 60)
            if name:
                moves_by_name.setdefault(name, []).append(item)
    move_owners: dict[tuple[str, str, str], list[str]] = {}
    for name, entries in moves_by_name.items():
        if not entries:
            continue
        move = entries[0]
        signature = (
            _text(move.get("goal"), 80),
            _text(move.get("emotion"), 60),
            _text(move.get("action"), 90),
        )
        move_owners.setdefault(signature, []).append(name)
    participants: list[dict[str, str]] = []
    for name in card_names:
        entries = moves_by_name.get(name) or []
        if not entries:
            continue
        move = entries[0]
        signature = (
            _text(move.get("goal"), 80),
            _text(move.get("emotion"), 60),
            _text(move.get("action"), 90),
        )
        owners = move_owners.get(signature, [])
        named_goal_owners = [owner for owner in owners if owner and owner in signature[0]]
        if len(owners) > 1 and len(named_goal_owners) == 1 and name != named_goal_owners[0]:
            continue
        participants.append(
            {
                "name": name,
                "want": _text(move.get("goal"), 80),
                "emotion": _text(move.get("emotion"), 60),
            }
        )
    memory_constraints = plan.get("memory_constraints") if isinstance(plan.get("memory_constraints"), dict) else {}
    unsaid_pressure = _first_text(
        [
            event_plan.get("unsaid_pressure"),
            event_plan.get("hidden_fact"),
            plan.get("unsaid_pressure"),
            plan.get("hidden_fact"),
            memory_constraints.get("unresolved_threads"),
        ]
    )
    return {
        "conversation_reason": emotional_target,
        "participants": participants,
        "relationships": relationships[:6],
        "tone_boundary": "按人物关系和当前场合决定语气；没有亲近依据时，不突然开玩笑或接梗。",
        "unsaid_pressure": unsaid_pressure,
        "expected_change": emotional_target,
    }
