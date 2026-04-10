from packages.story_core.memory_agent import MemoryAgent
from packages.story_core.models import CharacterState, DirectorDecision, StoryState


def test_memory_agent_writes_back_chapter_state_layers():
    story = StoryState(
        story_id="s-memory-agent-001",
        outline="A witness dispute fractures the court.",
        genre="mystery",
        style="tense",
        current_chapter=1,
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
        "secondary_conflict": {
            "pressure": "time",
            "detail": "Every delay gives the court one more chance to hide the truth.",
            "participants": [{"name": "Su Wan", "goal": "protect the witness"}],
        },
    }
    decision = DirectorDecision(
        primary_conflict=conflict_summary["primary_conflict"],
        secondary_conflict=conflict_summary["secondary_conflict"],
        event_beat={"turn": "pressure spike", "pivot": "The witness slips away under fire."},
        cadence="urgent",
        chapter_title="Chapter 2: Witness Dossier",
        next_focus="Return to Lin Yue and Su Wan over the witness",
    )

    updated = MemoryAgent().remember(
        story,
        body="Chapter 2 body placeholder.",
        chapter_number=2,
        decision=decision,
        conflict_summary=conflict_summary,
        event_beat=decision.event_beat,
        cadence=decision.cadence,
    )

    assert updated.timeline
    assert updated.chapter_summaries
    assert updated.chapter_summaries[-1].chapter_number == 2
    assert updated.chapter_summaries[-1].cadence == "urgent"
    assert updated.chapter_summaries[-1].chapter_title
    assert updated.foreshadowing
    assert updated.characters[0].memory
