from packages.story_core.engine import StoryEngine
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.quality import validate_bundle


def test_validate_bundle_flags_missing_continuity():
    bundle = {
        "chapter_number": 1,
        "body": "Chapter 1 body.",
        "next_outline": "",
        "character_cards": [],
        "foreshadowing": [],
    }
    report = validate_bundle(bundle)
    assert report["ok"] is False
    assert "next_outline" in report["issues"]


def test_validate_bundle_accepts_engine_output_with_compressed_memory():
    story = StoryState(
        story_id="s-003",
        outline="A scholar tracks coded letters through the palace.",
        genre="fantasy",
        style="literary suspense",
        characters=[
            CharacterState(
                name="Pei An",
                role="scholar",
                goals=["decode the letters"],
            )
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)
    report = validate_bundle(bundle.model_dump())

    assert report["ok"] is True
    assert report["issues"] == []
