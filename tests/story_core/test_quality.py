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


def test_validate_bundle_flags_body_over_target_range():
    bundle = {
        "chapter_number": 2,
        "chapter_title": "过长章节",
        "body": "字" * 5701,
        "cadence": "measured",
        "next_outline": "continue",
        "updated_story": {"timeline": ["x"], "chapter_summaries": ["x"]},
        "chapter_summary": {
            "chapter_title": "过长章节",
            "cadence": "measured",
            "facts": ["x"],
            "next_focus": "continue",
            "primary_conflict": {"collision": "x"},
            "secondary_conflict": {"detail": "x"},
            "event_beat": {"turn": "x"},
        },
    }

    report = validate_bundle(bundle)

    assert report["ok"] is False
    assert "body_too_long" in report["issues"]
    assert report["metrics"]["target_max_chars"] == 5500


def test_validate_bundle_allows_small_generation_length_tolerance():
    bundle = {
        "chapter_number": 2,
        "chapter_title": "边界篇幅",
        "body": "字" * 5503,
        "cadence": "measured",
        "next_outline": "continue",
        "updated_story": {"timeline": ["x"], "chapter_summaries": ["x"]},
        "chapter_summary": {
            "chapter_title": "边界篇幅",
            "cadence": "measured",
            "facts": ["x"],
            "next_focus": "continue",
            "primary_conflict": {"collision": "x"},
            "secondary_conflict": {"detail": "x"},
            "event_beat": {"turn": "x"},
        },
    }

    report = validate_bundle(bundle)

    assert "body_too_long" not in report["issues"]


def test_validate_bundle_allows_small_upper_length_tolerance():
    bundle = {
        "chapter_number": 2,
        "chapter_title": "边界篇幅",
        "body": "字" * 5587,
        "cadence": "measured",
        "next_outline": "continue",
        "updated_story": {"timeline": ["x"], "chapter_summaries": ["x"]},
        "chapter_summary": {
            "chapter_title": "边界篇幅",
            "cadence": "measured",
            "summary": "x",
        },
    }

    report = validate_bundle(bundle)

    assert "body_too_long" not in report["issues"]


def test_validate_bundle_flags_body_under_target_range():
    bundle = {
        "chapter_number": 1,
        "chapter_title": "篇幅不足",
        "body": "字" * 3799,
        "enforce_target_chars": True,
        "cadence": "measured",
        "next_outline": "continue",
        "updated_story": {"timeline": ["x"], "chapter_summaries": ["x"]},
        "chapter_summary": {
            "chapter_title": "篇幅不足",
            "cadence": "measured",
            "facts": ["x"],
            "next_focus": "continue",
            "primary_conflict": {"collision": "x"},
            "secondary_conflict": {"detail": "x"},
            "event_beat": {"turn": "x"},
        },
    }

    report = validate_bundle(bundle)

    assert report["ok"] is False
    assert "body_too_short" in report["issues"]
    assert report["metrics"]["target_min_chars"] == 3800


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
    assert bundle.chapter_summary["summary"]
    assert bundle.chapter_summary["next_focus"] == ""
    assert bundle.chapter_summary["primary_conflict"] == {}
    assert bundle.chapter_summary["secondary_conflict"] == {}
    assert bundle.chapter_summary["event_beat"] == {}
    assert bundle.updated_story.characters[0].lifecycle_state in {
        "proposed",
        "active",
        "rejected",
        "frozen",
    }
