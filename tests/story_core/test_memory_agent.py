import packages.story_core.memory_agent as memory_agent_module
from packages.story_core.memory_agent import MemoryAgent
from packages.story_core.models import CharacterState, DirectorDecision, StoryState


class FakeLLMMemoryProvider:
    def summarize(
        self,
        story: StoryState,
        body: str,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> dict:
        return {
            "summary": "Lin Yue secures the witness and is asked to return at dawn.",
            "facts": [
                {
                    "text": "The witness is secure in the west hall",
                    "evidence": "secures the witness in the west hall",
                }
            ],
            "unresolved_threads": [
                {
                    "text": "Why must Lin Yue return at dawn",
                    "evidence": "asks Lin Yue to return at dawn",
                }
            ],
            "next_focus": "return at dawn",
            "chapter_title": "Chapter 2: LLM Memory Dossier",
            "character_updates": [
                {
                    "name": "Lin Yue",
                    "goal": "return at dawn",
                    "location": "west hall",
                    "evidence": "Lin Yue secures the witness in the west hall",
                }
            ],
            "ledger_updates": {},
            "ledger_evidence": {},
        }


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
    assert not updated.foreshadowing
    assert not updated.characters[0].memory


def test_memory_agent_uses_injected_llm_provider_when_assisted_mode_is_enabled():
    story = StoryState(
        story_id="s-memory-agent-002",
        outline="A witness dispute fractures the court.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        agent_settings={"mode": "LLM-assisted"},
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

    updated = MemoryAgent(llm_provider=FakeLLMMemoryProvider()).remember(
        story,
        body="Lin Yue secures the witness in the west hall. Su Wan asks Lin Yue to return at dawn.",
        chapter_number=2,
        decision=decision,
        conflict_summary=conflict_summary,
        event_beat=decision.event_beat,
        cadence=decision.cadence,
    )

    assert updated.chapter_summaries[-1].summary == "Lin Yue secures the witness in the west hall. Su Wan asks Lin Yue to return at dawn."
    assert updated.chapter_summaries[-1].facts == ["The witness is secure in the west hall"]
    assert updated.chapter_summaries[-1].unresolved_threads == ["Why must Lin Yue return at dawn"]
    assert updated.chapter_summaries[-1].next_focus == "return at dawn"
    assert updated.chapter_summaries[-1].chapter_title != "Chapter 2: LLM Memory Dossier"
    assert updated.chapter_summaries[-1].event_beat == {}
    assert updated.timeline[-1].summary == updated.chapter_summaries[-1].summary
    assert updated.timeline[-1].impact == "The witness is secure in the west hall"
    assert not updated.foreshadowing
    assert updated.characters[0].location == "west hall"
    assert updated.characters[0].goals[0] == "return at dawn"
    assert updated.characters[0].memory[-1] == "第2章：Lin Yue secures the witness in the west hall"


def test_memory_agent_passes_real_name_and_game_id_as_protagonist_aliases(monkeypatch):
    captured = {}

    class Provider:
        def summarize(self, *_args, **_kwargs):
            return {"ledger_updates": {"protagonist": {"attribute_allocation": {}}}}

    def fake_normalize(payload, *, body, existing_character_names, protagonist_aliases=None):
        captured["existing_character_names"] = existing_character_names
        captured["protagonist_aliases"] = protagonist_aliases
        return {
            "summary": "",
            "facts": [],
            "unresolved_threads": [],
            "next_focus": "",
            "chapter_title": "",
            "character_updates": [],
            "ledger_updates": {},
            "ledger_evidence": {},
        }

    monkeypatch.setattr(memory_agent_module, "normalize_post_draft_memory", fake_normalize)
    story = StoryState(
        story_id="s-memory-agent-aliases",
        outline="网游开局。",
        genre="game_webnovel",
        style="紧凑",
        current_chapter=1,
        agent_settings={"mode": "LLM-assisted"},
        characters=[
            CharacterState(name="苏叶", game_id="夜烬", role="主角"),
            CharacterState(name="短发玩家", role="supporting"),
        ],
    )

    MemoryAgent(llm_provider=Provider()).remember(
        story,
        body="短发玩家把五点加到智力上。",
        chapter_number=2,
        decision=DirectorDecision(),
        conflict_summary={},
        event_beat={},
        cadence="measured",
    )

    assert captured["protagonist_aliases"] == {"苏叶", "夜烬"}
    assert captured["existing_character_names"] == {"苏叶", "短发玩家"}
