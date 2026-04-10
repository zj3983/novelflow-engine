from packages.story_core.director_agent import DirectorAgent
from packages.story_core.models import CharacterProposal, DirectorDecision, StoryState


class FakeLLMDirectorProvider:
    def decide(
        self,
        story: StoryState,
        proposals: list[CharacterProposal],
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> DirectorDecision:
        return DirectorDecision(
            primary_conflict={
                "lead": "Lin Yue",
                "opposition": "Su Wan",
                "collision": "LLM-selected collision over the witness.",
            },
            secondary_conflict={
                "pressure": "time",
                "detail": "LLM-selected pressure keeps the court moving.",
                "participants": [{"name": "Su Wan", "goal": "protect the witness"}],
            },
            event_beat={
                "turn": "LLM turn",
                "pivot": "The witness becomes the center of the collision.",
            },
            cadence="urgent",
            chapter_title="Chapter 2: LLM Crossroads",
            approved_new_characters=["Old Archivist"],
            deferred_characters=[],
            rejected_characters=["Street Runner"],
            next_focus="Return to Lin Yue and Su Wan over the witness",
        )


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


def test_director_agent_auto_approves_named_candidates_when_policy_set():
    story = StoryState(
        story_id="s-dir-002",
        outline="A witness arrives under a false name.",
        genre="mystery",
        style="tense",
        agent_settings={
            "new_character_policy": "Auto-approve named candidates",
        },
    )
    proposals = [
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
            "lead": "Su Wan",
            "opposition": "",
            "collision": "Su Wan blocks the inquiry into the false name.",
        },
        "secondary_conflict": {
            "pressure": "time",
            "detail": "Every delay gives the court one more chance to hide the truth.",
            "participants": [{"name": "Su Wan", "goal": "protect the witness"}],
        },
    }
    event_beat = {
        "turn": "pressure spike",
        "pivot": "Su Wan blocks the inquiry into the false name.",
    }

    decision = DirectorAgent().decide(
        story,
        proposals,
        conflict_summary,
        event_beat,
        "urgent",
    )

    assert set(decision.approved_new_characters) == {"Old Archivist", "Street Runner"}
    assert not decision.deferred_characters
    assert not decision.rejected_characters


def test_director_agent_uses_injected_llm_provider_when_assisted_mode_is_enabled():
    story = StoryState(
        story_id="s-dir-003",
        outline="A witness arrives under a false name.",
        genre="mystery",
        style="tense",
        agent_settings={
            "mode": "LLM-assisted",
        },
    )
    proposals = [
        CharacterProposal(
            name="Lin Yue",
            goal="find the witness",
            emotion="alert",
            action="pushes hard to find the witness",
            priority=9,
        ),
    ]
    conflict_summary = {
        "primary_conflict": {
            "lead": "Lin Yue",
            "opposition": "",
            "collision": "Lin Yue presses toward the false name.",
        },
        "secondary_conflict": {
            "pressure": "time",
            "detail": "Every delay gives the court one more chance to hide the truth.",
            "participants": [{"name": "Lin Yue", "goal": "find the witness"}],
        },
    }
    event_beat = {
        "turn": "pressure spike",
        "pivot": "Lin Yue presses toward the false name.",
    }

    decision = DirectorAgent(llm_provider=FakeLLMDirectorProvider()).decide(
        story,
        proposals,
        conflict_summary,
        event_beat,
        "measured",
    )

    assert decision.chapter_title == "Chapter 2: LLM Crossroads"
    assert decision.cadence == "urgent"
    assert decision.approved_new_characters == ["Old Archivist"]
    assert decision.rejected_characters == ["Street Runner"]
