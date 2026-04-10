from __future__ import annotations

from typing import Protocol

from packages.story_core.models import CharacterProposal, DirectorDecision, StoryState


class StoryAgentProvider(Protocol):
    def propose(self, story: StoryState) -> list[CharacterProposal]:
        pass

    def decide(
        self,
        story: StoryState,
        proposals: list[CharacterProposal],
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> DirectorDecision:
        pass

    def write(
        self,
        story: StoryState,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> str:
        pass

    def remember(
        self,
        story: StoryState,
        body: str,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> StoryState:
        pass
