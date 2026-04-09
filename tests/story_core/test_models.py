from packages.story_core.models import CharacterState, StoryState


def test_story_state_can_store_outline_and_chapter_index():
    story = StoryState(
        story_id="s-001",
        outline="A fallen prince becomes a detective.",
        genre="fantasy",
        style="moody",
        current_chapter=1,
    )
    assert story.story_id == "s-001"
    assert story.current_chapter == 1


def test_character_state_supports_memory_and_goals():
    character = CharacterState(
        name="Lin Yue",
        role="protagonist",
        traits={"impulsive": 0.7, "patient": 0.2},
        goals=["find the truth"],
    )
    assert "find the truth" in character.goals
    assert character.traits["impulsive"] == 0.7

