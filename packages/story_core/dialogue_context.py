"""Build the small, scene-level contract that guides emotional dialogue."""

from __future__ import annotations

from typing import Any


def _text(value: Any, limit: int = 120) -> str:
    return str(value or "").strip()[:limit]


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
    cards = character_context.get("cards") if isinstance(character_context, dict) else []
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
    return {
        "emotional_job": emotional_target,
        "relationships": relationships[:6],
        "tone_gate": "先按关系和场合决定语气；没有亲近依据时，不突然开玩笑或接梗。",
        "dialogue_test": "关键台词说完后，至少改变情绪、关系、信息或行动中的一项。",
    }
