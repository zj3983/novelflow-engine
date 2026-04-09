from packages.story_core.models import (
    CharacterRelationship,
    CharacterState,
    ChapterSummary,
    ForeshadowingState,
    StoryState,
    TimelineEvent,
)


def test_story_state_supports_long_running_memory_layers():
    story = StoryState(
        story_id="s-002",
        outline="A court investigator follows a missing ledger.",
        genre="fantasy",
        style="suspense",
        current_chapter=2,
        world_facts=["The treasury is missing silver."],
        timeline=[
            TimelineEvent(
                chapter_number=1,
                summary="The missing ledger is discovered.",
                impact="launches the main investigation",
            )
        ],
        foreshadowing=[
            ForeshadowingState(
                text="A burned wax seal points to the inner court.",
                first_chapter=1,
                status="open",
            )
        ],
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                summary="The prince notices a bookkeeping anomaly.",
                facts=["The seal belongs to the inner court."],
                unresolved_threads=["Who altered the books?"],
            )
        ],
    )

    assert story.world_facts[0] == "The treasury is missing silver."
    assert story.timeline[0].impact == "launches the main investigation"
    assert story.foreshadowing[0].status == "open"
    assert story.chapter_summaries[0].facts == ["The seal belongs to the inner court."]


def test_character_state_supports_relationships_and_freeze_flag():
    character = CharacterState(
        name="Lin Yue",
        role="protagonist",
        traits={"impulsive": 0.7},
        goals=["find the ledger"],
        relationships={
            "Lady Shen": CharacterRelationship(
                target="Lady Shen",
                trust=0.4,
                tension=0.8,
                bond="uneasy alliance",
            )
        },
        current_emotion="suspicious",
        location="archive hall",
        frozen=False,
    )

    assert character.relationships["Lady Shen"].tension == 0.8
    assert character.location == "archive hall"
    assert character.frozen is False
