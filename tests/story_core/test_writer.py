from packages.story_core.models import ChapterSummary, CharacterState, StoryState
from packages.story_core.writer import write_chapter_body


def test_writer_surfaces_compact_title_line_from_conflict_topic():
    story = StoryState(
        story_id="s-writer-001",
        outline="A witness drives a confrontation.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(name="Lin Yue", role="protagonist", goals=["find the witness"]),
            CharacterState(name="Su Wan", role="supporting", goals=["protect the witness"]),
        ],
    )
    conflict_summary = {
        "summary": "Lin Yue tries to find the witness, while Su Wan moves to protect the witness.",
        "stakes": "Control of the witness reshapes the court.",
        "primary_conflict": {
            "lead": "Lin Yue",
            "opposition": "Su Wan",
            "collision": "Lin Yue and Su Wan collide over whether the witness can be controlled.",
        },
        "secondary_conflict": {"pressure": "time", "detail": "Delay hides the truth.", "participants": []},
    }

    body = write_chapter_body(story, 1, conflict_summary=conflict_summary, event_beat=None)

    assert "Title:" in body
    assert "Chapter 1:" in body
    assert "Witness" in body


def test_writer_prefers_previous_next_focus_when_present():
    story = StoryState(
        story_id="s-writer-002",
        outline="A ledger hangs over the archives.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                chapter_title="Chapter 1: Ledger Crossroads",
                summary="Chapter 1 body.",
                facts=["The ledger is still hidden."],
                unresolved_threads=["Can Pei An keep the ledger hidden next?"],
                next_focus="Return to Pei An over the ledger",
                primary_conflict={"lead": "Pei An", "opposition": "circumstance", "collision": "Pei An must hide the ledger."},
                secondary_conflict={"pressure": "time", "detail": "The archive tightens.", "participants": []},
                event_beat={"turn": "pressure spike", "pivot": "Pei An must hide the ledger."},
            )
        ],
        characters=[CharacterState(name="Pei An", role="protagonist", goals=["hide the ledger"])],
    )

    body = write_chapter_body(story, 2, conflict_summary=None, event_beat=None)

    assert "Title:" in body
    assert "Chapter 2:" in body
    assert "Ledger" in body

