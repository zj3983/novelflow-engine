"""Integration tests for core refactoring changes.

Tests the key paths affected by the codebase cleanup:
1. Dynamic keyword extraction from story state
2. Unified prose texture review
3. Game genre defaults extraction
"""

from packages.story_core.models import CharacterState, GamePanel, StoryState


def _make_story(
    *,
    genre: str = "网游",
    characters: list | None = None,
    world_facts: list | None = None,
    progression_ledger: dict | None = None,
) -> StoryState:
    chars = characters or [
        CharacterState(
            name="林远",
            role="protagonist",
            lifecycle_state="active",
            game_id="远行者",
            goals=["查明真相"],
        ),
        CharacterState(
            name="沈离",
            role="supporting",
            lifecycle_state="active",
            goals=["寻找盟友"],
        ),
    ]
    return StoryState(
        story_id="test-integration",
        genre=genre,
        style="直白",
        outline="主角在游戏中探索真相。",
        characters=chars,
        world_facts=world_facts or [],
        progression_ledger=progression_ledger or {},
    )


# --- Test 1: Dynamic keyword extraction ---

def test_dynamic_keywords_extract_characters_and_game_ids():
    """Characters and their game_id aliases should appear in dynamic keywords."""
    from packages.story_core.memory import _story_dynamic_keywords

    story = _make_story()
    keywords = _story_dynamic_keywords(story)

    assert "林远" in keywords["characters"]
    assert "远行者" in keywords["characters"]
    assert "沈离" in keywords["characters"]


def test_dynamic_keywords_extract_locations_from_world_facts():
    """World facts containing location tokens should be extracted as locations."""
    from packages.story_core.memory import _story_dynamic_keywords

    story = _make_story(world_facts=["灰烬村", "青云城", "交易行规则"])
    keywords = _story_dynamic_keywords(story)

    assert "灰烬村" in keywords["locations"]
    assert "青云城" in keywords["locations"]
    # "交易行规则" contains "行" but not a location token, so shouldn't match
    assert "交易行规则" not in keywords["locations"]


def test_dynamic_keywords_extract_factions_from_world_facts():
    """World facts containing faction tokens should be extracted as factions."""
    from packages.story_core.memory import _story_dynamic_keywords

    story = _make_story(world_facts=["暗影公会", "凌云商会", "普通事实"])
    keywords = _story_dynamic_keywords(story)

    assert "暗影公会" in keywords["factions"]
    assert "凌云商会" in keywords["factions"]
    assert "普通事实" not in keywords["factions"]


def test_memory_index_uses_dynamic_keywords():
    """add_chapter_memory_index should tag entries with dynamic keywords from story."""
    from packages.story_core.memory import add_chapter_memory_index

    story = _make_story(world_facts=["交易行"])
    add_chapter_memory_index(
        story,
        chapter_number=1,
        chapter_title="初入游戏",
        summary="林远进入交易行，开始低调收集材料。",
    )

    entry = story.memory_index[0]
    # Should match character names from summary
    assert "林远" in entry.characters
    # Should match location/faction from summary
    assert "交易行" in entry.locations


# --- Test 2: Unified prose texture review ---

def test_prose_texture_review_detects_validator_terms():
    """Should flag planner/review terminology in prose."""
    from packages.story_core.prose_texture_review import review_prose_texture

    result = review_prose_texture("信息边界很清晰，NPC门槛也合理。")

    assert not result["pass"]
    assert result["overall"] < 80
    issue_types = [issue["type"] for issue in result["issues"]]
    assert "validator_language" in issue_types


def test_prose_texture_review_detects_slogan_patterns():
    """Should flag slogan-like symmetric sentences."""
    from packages.story_core.prose_texture_review import review_prose_texture

    result = review_prose_texture("代价很小，但代价存在。")

    assert not result["pass"]
    issue_types = [issue["type"] for issue in result["issues"]]
    assert "slogan_like_summary" in issue_types


def test_prose_texture_review_provides_cuts():
    """Should include replacement suggestions for cuttable sentences."""
    from packages.story_core.prose_texture_review import review_prose_texture

    result = review_prose_texture("代价很小，但代价存在。")

    assert len(result["cuts"]) > 0
    assert result["cut_pressure"] > 0


def test_prose_texture_review_clean_prose_passes():
    """Clean prose with no issues should pass."""
    from packages.story_core.prose_texture_review import review_prose_texture

    result = review_prose_texture(
        "他推开木门，柜台后的老人抬起眼皮看了他一眼。\n"
        "桌上摆着一盏油灯，火苗晃了晃。"
    )

    assert result["pass"]
    assert result["overall"] >= 80
    assert len(result["issues"]) == 0


def test_build_expression_patch_suggestions():
    """Patch suggestions should convert cuts to actionable replacements."""
    from packages.story_core.prose_texture_review import (
        review_prose_texture,
        build_expression_patch_suggestions,
    )

    review = review_prose_texture("代价很小，但代价存在。")
    patches = build_expression_patch_suggestions(review)

    assert len(patches) > 0
    assert "target_text" in patches[0]
    assert "replacement_text" in patches[0]


# --- Test 3: Game genre defaults extraction ---

def test_game_genre_defaults_from_ledger():
    """Should extract game ID and class path from progression ledger."""
    from packages.story_core.genre_stages.game_webnovel.writer import _game_genre_defaults

    story = _make_story(
        progression_ledger={
            "protagonist": {
                "game_id": "测试者",
                "class_path": "战士学徒",
                "level": "1",
            },
        },
    )
    defaults = _game_genre_defaults(story)

    assert defaults["game_id"] == "测试者"
    assert defaults["class_path"] == "战士学徒"


def test_game_genre_defaults_fallback_to_character():
    """Should fall back to character.game_id when ledger is empty."""
    from packages.story_core.genre_stages.game_webnovel.writer import _game_genre_defaults

    story = _make_story(
        progression_ledger={},
    )
    defaults = _game_genre_defaults(story)

    # Should use character's game_id
    assert defaults["game_id"] == "远行者"


def test_game_genre_defaults_generic_fallback():
    """Should use a generic placeholder when no game ID is available."""
    from packages.story_core.genre_stages.game_webnovel.writer import _game_genre_defaults

    story = _make_story(
        characters=[
            CharacterState(
                name="无名",
                role="protagonist",
                lifecycle_state="active",
                game_id="",  # No game ID set
                goals=["探索"],
            ),
        ],
        progression_ledger={},
    )
    defaults = _game_genre_defaults(story)

    # Should generate a generic fallback from the character name
    assert defaults["game_id"]
    assert "无名" not in defaults["game_id"]  # Should not leak real name


# --- Test 4: find_protagonist helper ---

def test_find_protagonist_by_role():
    """Should return the character with protagonist role."""
    from packages.story_core.agent_base import find_protagonist

    story = _make_story()
    protagonist = find_protagonist(story)

    assert protagonist is not None
    assert protagonist.name == "林远"
    assert protagonist.role == "protagonist"


def test_find_protagonist_fallback_to_first_active():
    """Should fall back to first active character when no protagonist role."""
    from packages.story_core.agent_base import find_protagonist

    story = _make_story(
        characters=[
            CharacterState(name="甲", role="supporting", lifecycle_state="active", goals=["a"]),
            CharacterState(name="乙", role="npc", lifecycle_state="active", goals=["b"]),
        ],
    )
    protagonist = find_protagonist(story)

    assert protagonist is not None
    assert protagonist.name == "甲"


def test_find_protagonist_skips_frozen():
    """Should skip frozen characters when finding protagonist."""
    from packages.story_core.agent_base import find_protagonist

    story = _make_story(
        characters=[
            CharacterState(name="已冻结", role="protagonist", lifecycle_state="active", frozen=True, goals=["a"]),
            CharacterState(name="活跃者", role="supporting", lifecycle_state="active", goals=["b"]),
        ],
    )
    protagonist = find_protagonist(story)

    assert protagonist is not None
    assert protagonist.name == "活跃者"


# --- Test 5: Non-game genre compatibility ---

def test_memory_keywords_for_non_game_genre():
    """Dynamic keyword extraction should work for non-game genres too."""
    from packages.story_core.memory import _story_dynamic_keywords, add_chapter_memory_index

    story = _make_story(
        genre="玄幻",
        characters=[
            CharacterState(name="萧炎", role="protagonist", lifecycle_state="active", goals=["变强"]),
        ],
        world_facts=["云岚宗", "加玛帝国"],
    )
    keywords = _story_dynamic_keywords(story)

    assert "萧炎" in keywords["characters"]
    assert "云岚宗" in keywords["factions"]

    add_chapter_memory_index(
        story,
        chapter_number=1,
        chapter_title="陨落的天才",
        summary="萧炎站在云岚宗山门前，握紧了拳头。",
    )

    entry = story.memory_index[0]
    assert "萧炎" in entry.characters
    assert "云岚宗" in entry.factions
