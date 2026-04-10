from packages.story_core.director_agent import DirectorAgent
from packages.story_core.models import CharacterProposal, StoryState


def test_director_agent_approves_old_archivist_and_defers_others():
    story = StoryState(
        story_id="s-dir-001",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
    )
    proposals = [
        CharacterProposal(
            name="Lin Yue",
            goal="find the witness",
            emotion="alert",
            action="pushes hard to find the witness",
            priority=9,
        ),
        CharacterProposal(
            name="Su Wan",
            goal="protect the witness",
            emotion="wary",
            action="tries to shield the witness",
            priority=8,
            new_character_candidates=["Old Archivist", "Street Runner"],
        ),
    ]
    conflict_summary = {
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
    event_beat = {
        "turn": "pressure spike",
        "pivot": "Lin Yue and Su Wan collide over whether the witness can be controlled.",
    }

    decision = DirectorAgent().decide(
        story,
        proposals,
        conflict_summary,
        event_beat,
        "urgent",
    )

    assert decision.primary_conflict["lead"] == "Lin Yue"
    assert decision.primary_conflict["opposition"] == "Su Wan"
    assert "Old Archivist" in decision.approved_new_characters
    assert "Street Runner" in decision.deferred_characters
    assert not decision.rejected_characters

