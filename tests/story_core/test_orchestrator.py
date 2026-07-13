from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import StoryOrchestrator


def test_orchestrator_runs_all_phases_and_returns_bundle():
    story = StoryState(
        story_id="s-orc-001",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
            )
        ],
    )

    bundle = StoryOrchestrator().generate_next_chapter(story)

    assert bundle.chapter_number == 1
    assert bundle.body
    assert bundle.chapter_title
    assert bundle.next_outline
    assert "writing_review" in bundle.quality_report


def test_whole_chapter_writing_is_default_path():
    orchestrator = StoryOrchestrator()

    assert orchestrator._use_segmented_writing(1, {}) is False


def test_segmented_writing_is_disabled_in_production():
    orchestrator = StoryOrchestrator()

    assert orchestrator._use_segmented_writing(1, {"writing_settings": {"use_segmented_writing": True}}) is False
