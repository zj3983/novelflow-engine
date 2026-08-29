from __future__ import annotations

from typing import Any

from packages.story_core.character_profiles import (
    normalize_speech_style_for_writing,
)
from packages.story_core.dual_state import normalize_character_state


def _state_namespace_has_content(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    current = value.get("current")
    if isinstance(current, dict) and any(
        item not in (None, "", [], {}) for item in current.values()
    ):
        return True
    recent_changes = value.get("recent_changes")
    return isinstance(recent_changes, list) and bool(recent_changes)


def normalize_character_persistence_card(
    card: dict[str, Any],
    *,
    is_game_story: bool,
) -> dict[str, Any]:
    normalized = normalize_character_state(card, is_game_story=is_game_story)
    performance = normalized.get("performance_profile")
    if isinstance(performance, dict):
        performance = dict(performance)
        performance["speech_style"] = normalize_speech_style_for_writing(
            performance.get("speech_style")
        )
        if (
            performance.get("speech_style")
            == "白话、完整、少装腔；解释选择时把原因说清。"
        ):
            performance["speech_style"] = (
                "白话、完整、少装腔；只说当下会说的话，理由藏在语气、动作和必要回答里。"
            )
        normalized["performance_profile"] = performance
    if is_game_story:
        game_state = normalized.get("game_state")
        current = (
            game_state.get("current") if isinstance(game_state, dict) else None
        )
        if isinstance(current, dict):
            panel = dict(normalized.get("game_panel") or {})
            for field in (
                "game_id",
                "level",
                "class_path",
                "exp",
                "hp",
                "mp",
                "attributes",
                "skills",
                "equipment",
                "inventory",
                "currency",
                "quests",
                "risk",
            ):
                value = current.get(field)
                if value not in (None, "", [], {}):
                    panel[field] = value
            normalized["game_panel"] = panel
    for state_name in ("current_state", "real_state", "game_state"):
        if not _state_namespace_has_content(normalized.get(state_name)):
            normalized.pop(state_name, None)
    return normalized


__all__ = ["normalize_character_persistence_card"]
