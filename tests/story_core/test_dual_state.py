from __future__ import annotations

import pytest

from packages.story_core.character_profiles import normalize_character_profile
from packages.story_core.dual_state import (
    merge_state_change,
    normalize_dual_state,
    project_dual_state,
)
from packages.story_core.models import CharacterState


def test_legacy_game_panel_is_mapped_to_game_state_current_without_losing_panel() -> None:
    card = {
        "name": "Night Ember",
        "game_panel": {"game_id": "Night Ember", "level": "Lv.1", "currency": "0 coins"},
    }

    normalized = normalize_dual_state(card, is_game_story=True)

    assert normalized["game_state"]["current"]["game_id"] == "Night Ember"
    assert normalized["game_state"]["current"]["level"] == "Lv.1"
    assert normalized["game_panel"]["currency"] == "0 coins"


def test_legacy_real_fields_are_mapped_without_removing_the_old_fields() -> None:
    card = {
        "name": "Su Ye",
        "identity_profile": {"current_identity": "student"},
        "background_profile": {"family": "merchant family"},
        "current_life_profile": {"residence": "old town"},
        "story_drive": {"immediate_goal": "find the clue"},
    }

    normalized = normalize_dual_state(card, is_game_story=False)

    assert normalized["real_state"]["current"] == {
        "identity_profile": {"current_identity": "student"},
        "background_profile": {"family": "merchant family"},
        "current_life_profile": {"residence": "old town"},
        "story_drive": {"immediate_goal": "find the clue"},
    }
    assert normalized["identity_profile"]["current_identity"] == "student"
    assert "game_state" not in normalized


def test_non_game_story_does_not_create_game_state() -> None:
    normalized = normalize_dual_state(
        {"name": "Shen Mo", "current_life_profile": {"occupation": "copyist"}},
        is_game_story=False,
    )

    assert "real_state" in normalized
    assert "game_state" not in normalized


def test_scene_projection_keeps_only_requested_line() -> None:
    card = {
        "name": "Night Ember",
        "real_state": {"current": {"balance": "27.60"}},
        "game_state": {"current": {"level": "Lv.1"}},
    }

    assert project_dual_state(card, scene_kind="game") == {
        "game_state": {"current": {"level": "Lv.1"}},
    }
    assert project_dual_state(card, scene_kind="reality") == {
        "real_state": {"current": {"balance": "27.60"}},
    }
    assert set(project_dual_state(card, scene_kind="transition")) == {"real_state", "game_state"}


def test_scene_projection_rejects_unknown_scene_kind() -> None:
    with pytest.raises(ValueError, match="scene_kind"):
        project_dual_state({}, scene_kind="dream")


def test_merge_state_change_updates_only_selected_line_and_records_fact() -> None:
    card = {
        "real_state": {"current": {"balance": "27.60"}},
        "game_state": {"current": {"level": "Lv.1"}},
    }

    merged = merge_state_change(
        card,
        line="game",
        change={"current": {"level": "Lv.2", "currency": "10 coins"}, "fact": "level up"},
        chapter=4,
    )

    assert merged["game_state"]["current"] == {"level": "Lv.2", "currency": "10 coins"}
    assert merged["game_state"]["recent_changes"] == [{"chapter": 4, "fact": "level up"}]
    assert merged["real_state"] == {"current": {"balance": "27.60"}}


def test_merge_state_change_reality_line_does_not_change_game_state() -> None:
    card = {
        "real_state": {
            "current": {"balance": "27.60"},
            "recent_changes": [{"chapter": 2, "fact": "opened account"}],
        },
        "game_state": {
            "current": {"level": "Lv.1"},
            "recent_changes": [{"chapter": 2, "fact": "entered the game"}],
        },
    }
    original_game_state = card["game_state"].copy()

    merged = merge_state_change(
        card,
        line="reality",
        change={"current": {"balance": "32.60", "income": "5.00"}, "fact": "received income"},
        chapter=4,
    )

    assert merged["real_state"]["current"] == {"balance": "32.60", "income": "5.00"}
    assert merged["real_state"]["recent_changes"] == [
        {"chapter": 2, "fact": "opened account"},
        {"chapter": 4, "fact": "received income"},
    ]
    assert merged["game_state"] == original_game_state


def test_character_state_keeps_legacy_panel_and_accepts_both_state_namespaces() -> None:
    character = CharacterState.model_validate(
        {
            "name": "Night Ember",
            "role": "protagonist",
            "game_panel": {"game_id": "Night Ember", "level": "Lv.1"},
            "real_state": {"current": {"balance": "27.60"}},
            "game_state": {"current": {"level": "Lv.1"}},
        }
    )

    assert character.game_panel.game_id == "Night Ember"
    assert character.real_state["current"]["balance"] == "27.60"
    assert character.game_state["current"]["level"] == "Lv.1"


def test_character_profile_normalization_is_genre_neutral_by_default() -> None:
    card = {"name": "Su Ye", "role": "protagonist", "game_panel": {"level": "Lv.1"}}

    normalized = normalize_character_profile(card)
    game_normalized = normalize_character_profile(card, is_game_story=True)

    assert "game_state" not in normalized
    assert game_normalized["game_state"]["current"]["level"] == "Lv.1"
