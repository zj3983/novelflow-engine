from __future__ import annotations

import pytest

from packages.story_core.character_profiles import normalize_character_profile
from packages.story_core.dual_state import (
    infer_scene_kind,
    merge_state_change,
    normalize_character_state,
    normalize_dual_state,
    project_dual_state,
    project_character_for_scene,
    scene_kind_for_cards,
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


def test_non_game_character_state_migrates_legacy_namespaces_without_static_duplicates() -> None:
    normalized = normalize_character_state(
        {
            "name": "沈墨",
            "identity_profile": {"current_identity": "外门弟子"},
            "current_state": "左臂受伤，正在祖祠值夜",
            "real_state": {
                "current": {
                    "identity_profile": {"current_identity": "外门弟子"},
                    "location": "祖祠",
                    "injury": "左臂轻伤",
                },
                "recent_changes": [{"chapter": 1, "fact": "被调去祖祠值夜"}],
            },
            "game_state": {"current": {"level": "Lv.1"}},
            "game_panel": {"level": "Lv.1"},
        },
        is_game_story=False,
    )

    assert normalized["current_state"] == {
        "current": {
            "location": "祖祠",
            "injury": "左臂轻伤",
            "summary": "左臂受伤，正在祖祠值夜",
        },
        "recent_changes": [{"chapter": 1, "fact": "被调去祖祠值夜"}],
    }
    assert "real_state" not in normalized
    assert "game_state" not in normalized
    assert "game_panel" not in normalized


def test_non_game_structured_current_state_wins_and_recent_changes_are_deduplicated() -> None:
    normalized = normalize_character_state(
        {
            "name": "沈墨",
            "current_state": {
                "current": {"location": "藏经阁", "emotion": "警惕"},
                "recent_changes": [{"chapter": 2, "fact": "进入藏经阁"}],
            },
            "real_state": {
                "current": {"location": "祖祠", "injury": "左臂轻伤"},
                "recent_changes": [
                    {"chapter": 2, "fact": "进入藏经阁"},
                    {"chapter": 1, "fact": "左臂受伤"},
                ],
            },
        },
        is_game_story=False,
    )

    assert normalized["current_state"]["current"] == {
        "location": "藏经阁",
        "injury": "左臂轻伤",
        "emotion": "警惕",
    }
    assert normalized["current_state"]["recent_changes"] == [
        {"chapter": 2, "fact": "进入藏经阁"},
        {"chapter": 1, "fact": "左臂受伤"},
    ]


def test_game_character_state_keeps_dual_state_contract() -> None:
    normalized = normalize_character_state(
        {
            "name": "夜烬",
            "real_state": {"current": {"occupation": "代练"}},
            "game_panel": {"level": "Lv.1"},
        },
        is_game_story=True,
    )

    assert normalized["real_state"]["current"]["occupation"] == "代练"
    assert normalized["game_state"]["current"]["level"] == "Lv.1"
    assert "current_state" not in normalized


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


def test_infer_scene_kind_prefers_explicit_line_over_scene_markers() -> None:
    assert infer_scene_kind({"line": "reality", "title": "副本背包升级"}, is_game_story=True) == "reality"
    assert infer_scene_kind({"scene_line": "game", "scene": "出租屋交房租"}, is_game_story=True) == "game"


def test_infer_scene_kind_classifies_chinese_scene_markers_and_defaults() -> None:
    assert infer_scene_kind({"title": "副本入口", "action": "检查等级"}, is_game_story=True) == "game"
    assert infer_scene_kind({"scene": "出租屋", "action": "去银行处理房租"}, is_game_story=True) == "reality"
    assert infer_scene_kind({"location": "出租屋", "purpose": "核对银行余额"}, is_game_story=True) == "reality"
    assert infer_scene_kind({"location": "副本入口", "purpose": "领取任务"}, is_game_story=False) == "reality"
    assert infer_scene_kind({"title": "门口停了一会儿", "action": "他抬头看灯"}, is_game_story=True) == "transition"
    assert infer_scene_kind({"title": "门口停了一会儿"}, is_game_story=False) == "reality"


def test_non_game_story_forces_text_markers_to_reality_but_keeps_explicit_transition() -> None:
    assert infer_scene_kind({"title": "客户任务", "action": "完成工作"}, is_game_story=False) == "reality"
    assert infer_scene_kind({"title": "副本任务", "line": "game"}, is_game_story=False) == "reality"
    assert infer_scene_kind({"title": "回到现实", "line": "transition"}, is_game_story=False) == "reality"


def test_scene_kind_for_cards_is_shared_and_non_game_safe() -> None:
    assert scene_kind_for_cards(
        [{"title": "出租屋催租"}, {"title": "副本入口"}],
        is_game_story=True,
    ) == "transition"
    assert scene_kind_for_cards([{"title": "领取任务并完成工作"}], is_game_story=False) == "reality"


def test_projected_state_scrubs_long_term_private_fields_without_losing_public_current_values() -> None:
    card = {
        "story_drive": {"hidden_matters": ["长期秘密"], "immediate_goal": "核对余额"},
        "secrets": ["不可见秘密"],
        "real_state": {
            "current": {
                "balance": "27.60",
                "private_note": "现实私密备注",
                "secret_real": "现实秘密",
            }
        },
        "game_state": {
            "current": {
                "level": "Lv.2",
                "private_route": "游戏私密路线",
                "hidden_matters": ["游戏秘密"],
            }
        },
    }

    reality = project_dual_state(card, scene_kind="reality")
    game = project_dual_state(card, scene_kind="game")
    transition = project_dual_state(card, scene_kind="transition")

    assert reality["real_state"]["current"]["balance"] == "27.60"
    assert game["game_state"]["current"]["level"] == "Lv.2"
    assert set(transition) == {"real_state", "game_state"}
    assert "长期秘密" not in str(transition)
    assert "不可见秘密" not in str(transition)
    assert "私密" not in str(transition)


def test_projected_state_drops_continuity_locks_from_each_state_line() -> None:
    card = {
        "real_state": {
            "current": {"balance": "27.60", "continuity_locks": {"secret": "现实秘密"}}
        },
        "game_state": {
            "current": {"level": "Lv.2", "continuity_locks": {"game_panel": {"level": "Lv.2"}}}
        },
    }

    for scene_kind in ("reality", "game", "transition"):
        projected = project_dual_state(card, scene_kind=scene_kind)
        assert "continuity_locks" not in str(projected)


def test_project_character_for_scene_keeps_public_card_and_only_projected_state() -> None:
    card = {
        "name": "苏叶",
        "role": "主角",
        "game_panel": {"game_id": "夜烬", "level": "Lv.2"},
        "continuity_locks": {"game_panel": {"level": "Lv.2"}},
        "secrets": ["长期秘密"],
        "story_drive": {"immediate_goal": "核对余额", "hidden_matters": ["隐藏秘密"]},
        "real_state": {"current": {"balance": "27.60"}},
        "game_state": {"current": {"level": "Lv.2"}},
    }

    projected = project_character_for_scene(card, scene_kind="reality")

    assert projected["name"] == "苏叶"
    assert projected["role"] == "主角"
    assert set(projected["state_context"]) == {"real_state"}
    assert projected["state_context"]["real_state"]["current"]["balance"] == "27.60"
    assert "continuity_locks" not in str(projected)
    assert "game_panel" not in str(projected)
    assert "长期秘密" not in str(projected)
    assert "隐藏秘密" not in str(projected)


def test_project_non_game_character_for_scene_exposes_only_generic_current_state() -> None:
    card = {
        "name": "沈墨",
        "role": "主角",
        "current_state": {
            "current": {"location": "祖祠", "injury": "左臂轻伤"},
            "recent_changes": [{"chapter": 1, "fact": "被调来值夜"}],
        },
        "real_state": {"current": {"location": "旧住处"}},
        "game_state": {"current": {"level": "Lv.1"}},
    }

    projected = project_character_for_scene(
        card,
        scene_kind="reality",
        is_game_story=False,
    )

    assert set(projected["state_context"]) == {"current_state"}
    assert projected["state_context"]["current_state"]["current"]["location"] == "祖祠"
    assert "real_state" not in str(projected)
    assert "game_state" not in str(projected)


def test_scene_projection_has_no_cross_line_state_leakage() -> None:
    card = {
        "name": "苏叶",
        "real_state": {"current": {"balance": "27.60", "secret_real": "现实秘密"}},
        "game_state": {"current": {"level": "Lv.2", "secret_game": "游戏秘密"}},
    }

    game = project_dual_state(card, scene_kind="game")
    reality = project_dual_state(card, scene_kind="reality")
    transition = project_dual_state(card, scene_kind="transition")

    assert set(game) == {"game_state"}
    assert set(reality) == {"real_state"}
    assert set(transition) == {"real_state", "game_state"}


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


def test_character_state_accepts_legacy_current_state_string_as_structured_state() -> None:
    character = CharacterState.model_validate(
        {"name": "沈墨", "role": "主角", "current_state": "正在祖祠值夜"}
    )

    assert character.current_state == {
        "current": {"summary": "正在祖祠值夜"},
        "recent_changes": [],
    }


def test_character_profile_normalization_is_genre_neutral_by_default() -> None:
    card = {"name": "Su Ye", "role": "protagonist", "game_panel": {"level": "Lv.1"}}

    normalized = normalize_character_profile(card)
    game_normalized = normalize_character_profile(card, is_game_story=True)

    assert "game_state" not in normalized
    assert game_normalized["game_state"]["current"]["level"] == "Lv.1"
