"""Project game-only character state into the writer's current context."""

from __future__ import annotations

from typing import Any


def _project_fields(value: Any, allowed: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: value[key]
        for key in allowed
        if key in value and value[key] not in (None, "", [], {})
    }


def project_real_character_state(value: Any) -> dict[str, Any]:
    """Keep only present-tense reality facts needed in the next scene."""

    if not isinstance(value, dict):
        return {}
    current = value.get("current") if isinstance(value.get("current"), dict) else value
    identity = _project_fields(
        value.get("identity_profile"),
        ("current_identity", "occupation"),
    )
    life = _project_fields(
        value.get("current_life_profile"),
        (
            "residence",
            "livelihood",
            "economic_state",
            "resources_and_ability",
            "immediate_problem",
        ),
    )
    visible_current = _project_fields(
        current,
        (
            "current_identity",
            "occupation",
            "location",
            "status",
            "condition",
            "health",
            "balance",
            "economic_state",
            "resources",
            "immediate_problem",
        ),
    )
    return {**identity, **life, **visible_current}


def project_game_character_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    source = value.get("current") if isinstance(value.get("current"), dict) else value
    allowed = (
        "game_id",
        "level",
        "class_path",
        "experience",
        "exp",
        "hp",
        "mp",
        "attributes",
        "equipment",
        "inventory",
        "currency",
        "tasks",
        "quests",
        "skills",
        "location",
        "status",
    )
    return {
        key: source[key]
        for key in allowed
        if key in source and source[key] not in (None, "", [], {})
    }


__all__ = ["project_game_character_state", "project_real_character_state"]
