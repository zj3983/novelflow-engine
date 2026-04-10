from packages.story_core.character_agent import CharacterAgent
from packages.story_core.models import CharacterState, StoryState


def test_character_agent_emits_new_character_candidate_when_secret_mentions_archivist():
    story = StoryState(
        story_id="s-agent-001",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                secrets=["Old archivist knows where the wax seal came from."],
            )
        ],
    )

    proposal = CharacterAgent().propose(story, story.characters[0])

    assert "Old Archivist" in proposal.new_character_candidates


def test_character_agent_propose_all_filters_non_active_or_frozen_characters():
    story = StoryState(
        story_id="s-agent-002",
        outline="A court drifts toward open fracture.",
        genre="mystery",
        style="tense",
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="alert",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                frozen=True,
            ),
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["hide the ledger"],
                lifecycle_state="proposed",
            ),
        ],
    )

    proposals = CharacterAgent().propose_all(story)

    assert [proposal.name for proposal in proposals] == ["Lin Yue"]
