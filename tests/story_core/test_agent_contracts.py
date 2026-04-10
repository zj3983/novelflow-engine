from packages.story_core.models import (
    CharacterLifecycleState,
    CharacterProposal,
    CharacterState,
    DirectorDecision,
)


def test_agent_contract_models_support_new_character_lifecycle():
    proposal = CharacterProposal(
        name="Su Wan",
        goal="protect the witness",
        emotion="alert",
        action="tries to shield the witness from exposure",
        priority=8,
        new_character_candidates=["Old Archivist"],
    )
    decision = DirectorDecision(
        primary_conflict={"lead": "Lin Yue", "opposition": "Su Wan", "collision": "fight for the witness"},
        secondary_conflict={
            "pressure": "time",
            "detail": "the archive burns",
            "participants": [{"name": "Pei An", "goal": "stabilize the ledger"}],
        },
        event_beat={"turn": "the witness slips away", "pivot": "the chase becomes public"},
        cadence="urgent",
        chapter_title="Chapter 3: Witness Dossier",
        approved_new_characters=["Old Archivist"],
        deferred_characters=["Street Runner"],
        rejected_characters=["Unknown Guard"],
        next_focus="Return to the witness before the court closes ranks.",
    )
    character = CharacterState(
        name="Old Archivist",
        role="supporting",
        lifecycle_state="active",
    )
    lifecycle: CharacterLifecycleState = "proposed"

    assert proposal.priority == 8
    assert decision.cadence == "urgent"
    assert character.lifecycle_state == "active"
    assert lifecycle == "proposed"
