from __future__ import annotations

from typing import Any

from packages.story_core.character_profiles import (
    normalize_character_profile,
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


def _has_meaningful_value(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, dict):
        return any(_has_meaningful_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_meaningful_value(item) for item in value)
    return True


def normalize_character_persistence_card(
    card: dict[str, Any],
    *,
    is_game_story: bool,
) -> dict[str, Any]:
    raw_card = dict(card)
    normalized = normalize_character_state(card, is_game_story=is_game_story)
    # Taxonomy and completeness are derived fields.  Recompute them after the
    # mutable state projection so stale client values cannot survive a read or
    # write round trip.
    normalized = normalize_character_profile(normalized)

    # Keep legacy persistence compact.  The canonical profile normalizer fills
    # model defaults for validation, but an all-empty block that was not part
    # of the source should not suddenly appear in writer packets.
    for field_name in (
        "identity_profile",
        "background_profile",
        "current_life_profile",
    ):
        if (
            not _has_meaningful_value(raw_card.get(field_name))
            and not _has_meaningful_value(normalized.get(field_name))
        ):
            normalized.pop(field_name, None)
    if (
        not _has_meaningful_value(raw_card.get("story_drive"))
        and not _has_meaningful_value(normalized.get("story_drive"))
        and not any(
            _has_meaningful_value(raw_card.get(field_name))
            for field_name in ("motivation", "core_motivation", "goals")
        )
    ):
        normalized.pop("story_drive", None)
    if (
        not _has_meaningful_value(raw_card.get("performance_profile"))
        and not _has_meaningful_value(normalized.get("performance_profile"))
        and not _has_meaningful_value(raw_card.get("speech_style"))
    ):
        normalized.pop("performance_profile", None)
    for field_name in ("dialogue_examples", "relationship_notes"):
        if field_name not in raw_card and not _has_meaningful_value(normalized.get(field_name)):
            normalized.pop(field_name, None)
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
