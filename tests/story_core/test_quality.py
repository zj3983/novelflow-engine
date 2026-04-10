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


def test_validate_bundle_preserves_multi_agent_summary_fields():
    story = StoryState(
        story_id="s-quality-004",
        outline="An archivist and investigator contest control of one witness.",
        genre="mystery",
        style="tense",
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                secrets=["An archivist once forged the registry seal."],
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)
    report = validate_bundle(bundle.model_dump())

    assert report["ok"] is True
    assert bundle.chapter_summary["cadence"] in {"urgent", "measured", "breathing"}
    assert bundle.chapter_summary["next_focus"]
    assert bundle.chapter_summary["primary_conflict"]
    assert bundle.chapter_summary["secondary_conflict"]
    assert bundle.chapter_summary["event_beat"]
    assert bundle.updated_story.characters[0].lifecycle_state in {
        "proposed",
        "active",
        "rejected",
        "frozen",
    }
