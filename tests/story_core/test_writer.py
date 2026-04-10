from packages.story_core.models import ChapterSummary, CharacterState, DirectorDecision, StoryState
from packages.story_core.writer_agent import WriterAgent
from packages.story_core.writer import write_chapter_body


class FakeLLMWriterProvider:
    def write(
        self,
        story: StoryState,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> str:
        return "LLM-assisted chapter body."


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

    assert "Title:" in body
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

    assert "Tempo: urgent" in body
    assert "cut comes hard" in body


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

    assert "Tempo: breathing" in body
    assert "quiet note" in body


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

    assert "Tempo: urgent" in body
    assert "cut comes hard" in body


def test_writer_agent_keeps_existing_prose_markers():
    story = StoryState(
        story_id="s-writer-agent-001",
        outline="A witness drives a confrontation.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                chapter_title="Chapter 1: Witness Dossier",
                summary="A previous clash over the witness.",
                facts=["The witness vanished in the archive hall."],
                unresolved_threads=["Can Lin Yue reclaim control of the witness?"],
                next_focus="Return to Lin Yue and Su Wan over the witness",
                primary_conflict={"lead": "Lin Yue", "opposition": "Su Wan", "collision": "They clash over the witness."},
                secondary_conflict={"pressure": "time", "detail": "The court closes in.", "participants": []},
                event_beat={"turn": "pressure spike", "pivot": "The witness slips away."},
            )
        ],
        characters=[
            CharacterState(name="Lin Yue", role="protagonist", goals=["find the witness"]),
            CharacterState(name="Su Wan", role="supporting", goals=["protect the witness"]),
        ],
    )
    conflict_summary = {
        "summary": "Lin Yue pushes to secure the witness while Su Wan shields them.",
        "stakes": "Control of the witness reshapes the court.",
        "primary_conflict": {
            "lead": "Lin Yue",
            "opposition": "Su Wan",
            "collision": "Lin Yue and Su Wan collide over whether the witness can be controlled.",
        },
        "secondary_conflict": {"pressure": "time", "detail": "Delay hides the truth.", "participants": []},
    }
    decision = DirectorDecision(
        primary_conflict=conflict_summary["primary_conflict"],
        secondary_conflict=conflict_summary["secondary_conflict"],
        event_beat={"turn": "pressure spike", "pivot": "The witness slips away."},
        cadence="urgent",
        chapter_title="Chapter 2: Witness Dossier",
        next_focus="Return to Lin Yue and Su Wan over the witness",
    )

    body = WriterAgent().write(
        story,
        chapter_number=2,
        decision=decision,
        conflict_summary=conflict_summary,
        event_beat=decision.event_beat,
        cadence="urgent",
    )

    assert "Title:" in body
    assert "Tempo: urgent" in body
    assert "Opening hook:" in body
    assert "Conflict:" in body
    assert "Secondary pressure:" in body
    assert "Next focus:" in body


def test_writer_agent_uses_injected_llm_provider_when_assisted_mode_is_enabled():
    story = StoryState(
        story_id="s-writer-agent-002",
        outline="A witness drives a confrontation.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        agent_settings={"mode": "LLM-assisted"},
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                chapter_title="Chapter 1: Witness Dossier",
                summary="A previous clash over the witness.",
                facts=["The witness vanished in the archive hall."],
                unresolved_threads=["Can Lin Yue reclaim control of the witness?"],
                next_focus="Return to Lin Yue and Su Wan over the witness",
                primary_conflict={"lead": "Lin Yue", "opposition": "Su Wan", "collision": "They clash over the witness."},
                secondary_conflict={"pressure": "time", "detail": "The court closes in.", "participants": []},
                event_beat={"turn": "pressure spike", "pivot": "The witness slips away."},
            )
        ],
        characters=[
            CharacterState(name="Lin Yue", role="protagonist", goals=["find the witness"]),
            CharacterState(name="Su Wan", role="supporting", goals=["protect the witness"]),
        ],
    )
    conflict_summary = {
        "summary": "Lin Yue pushes to secure the witness while Su Wan shields them.",
        "stakes": "Control of the witness reshapes the court.",
        "primary_conflict": {
            "lead": "Lin Yue",
            "opposition": "Su Wan",
            "collision": "Lin Yue and Su Wan collide over whether the witness can be controlled.",
        },
        "secondary_conflict": {"pressure": "time", "detail": "Delay hides the truth.", "participants": []},
    }
    decision = DirectorDecision(
        primary_conflict=conflict_summary["primary_conflict"],
        secondary_conflict=conflict_summary["secondary_conflict"],
        event_beat={"turn": "pressure spike", "pivot": "The witness slips away."},
        cadence="urgent",
        chapter_title="Chapter 2: Witness Dossier",
        next_focus="Return to Lin Yue and Su Wan over the witness",
    )

    body = WriterAgent(llm_provider=FakeLLMWriterProvider()).write(
        story,
        chapter_number=2,
        decision=decision,
        conflict_summary=conflict_summary,
        event_beat=decision.event_beat,
        cadence="urgent",
    )

    assert body == "LLM-assisted chapter body."
