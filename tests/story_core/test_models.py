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


def test_character_state_supports_lifecycle_tracking_fields():
    character = CharacterState(
        name="Old Archivist",
        role="supporting",
        lifecycle_state="proposed",
        last_proposed_chapter=3,
        last_approved_chapter=0,
        introduced_by="Su Wan",
    )

    assert character.lifecycle_state == "proposed"
    assert character.last_proposed_chapter == 3
    assert character.last_approved_chapter == 0
    assert character.introduced_by == "Su Wan"
