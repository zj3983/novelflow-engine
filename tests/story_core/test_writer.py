from packages.story_core.models import ChapterSummary, CharacterState, DirectorDecision, StoryState
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

    # New format: 第1章《标题》
    assert "第1章" in body
    assert "Lin Yue" in body
    assert "Su Wan" in body


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

    assert "第2章" in body
    # next_focus from previous chapter should be used as opening hook
    assert "Return to Pei An over the ledger" in body


def test_writer_uses_existing_chapter_title_when_present_for_same_chapter():
    story = StoryState(
        story_id="s-writer-003",
        outline="A title may already be computed upstream.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=2,
                chapter_title="Chapter 2: Custom Crossroads",
                summary="Placeholder body for an already-titled chapter.",
                facts=[],
                unresolved_threads=[],
                next_focus="Return to someone over something",
                primary_conflict={},
                secondary_conflict={},
                event_beat={},
            )
        ],
        characters=[CharacterState(name="Pei An", role="protagonist", goals=["hide the ledger"])],
    )

    body = write_chapter_body(story, 2, conflict_summary=None, event_beat=None)

    # Custom chapter title should be used
    assert "Chapter 2: Custom Crossroads" in body


def test_writer_marks_urgent_tempo_when_conflict_is_dense():
    story = StoryState(
        story_id="s-writer-004",
        outline="Too many hands reach for the same witness.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(name="Lin Yue", role="protagonist", goals=["find the witness"]),
            CharacterState(name="Su Wan", role="supporting", goals=["protect the witness"]),
            CharacterState(name="Pei An", role="supporting", goals=["hide the ledger"]),
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
        "secondary_conflict": {
            "pressure": "time",
            "detail": "Delay hides the truth.",
            "participants": [{"name": "Pei An", "goal": "hide the ledger"}],
        },
    }
    event_beat = {"turn": "pressure spike", "pivot": "The witness shifts hands too fast."}

    body = write_chapter_body(story, 1, conflict_summary=conflict_summary, event_beat=event_beat)

    # New format: （节奏：紧绷）
    assert "节奏" in body
    assert "紧绷" in body
    # Closing sentence for urgent tempo
    assert "刀锋" in body


def test_writer_marks_breathing_tempo_when_conflict_is_light():
    story = StoryState(
        story_id="s-writer-005",
        outline="A lone investigator reviews old notes.",
        genre="mystery",
        style="quiet",
        current_chapter=0,
        characters=[CharacterState(name="Lin Yue", role="protagonist", goals=["hold the line"])],
    )

    body = write_chapter_body(story, 1, conflict_summary=None, event_beat=None)

    # New format: （节奏：舒张）
    assert "节奏" in body
    assert "舒张" in body


def test_writer_uses_engine_supplied_cadence_when_available():
    story = StoryState(
        story_id="s-writer-006",
        outline="An engine-supplied cadence should win over local heuristics.",
        genre="fantasy",
        style="quiet",
        current_chapter=0,
        characters=[CharacterState(name="Lin Yue", role="protagonist", goals=["hold the line"])],
    )

    body = write_chapter_body(
        story,
        1,
        conflict_summary=None,
        event_beat=None,
        cadence="urgent",
    )

    # Engine-supplied cadence overrides heuristics
    assert "节奏" in body
    assert "紧绷" in body
