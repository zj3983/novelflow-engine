from __future__ import annotations

from packages.story_core.agent_base import StoryAgentProvider
from packages.story_core.character_agent import CharacterAgent
from packages.story_core.director_agent import DirectorAgent
from packages.story_core.memory_agent import MemoryAgent
from packages.story_core.memory import (
    build_character_cards,
    build_foreshadowing,
)
from packages.story_core.models import CharacterProposal, DirectorDecision, StoryState
from packages.story_core.planner import (
    build_conflict_summary,
    build_event_beat,
    compute_chapter_cadence,
    plan_next_outline,
)
from packages.story_core.quality import validate_bundle
from packages.story_core.writer_agent import WriterAgent


class RuleBasedStoryAgentProvider:
    def propose(self, story: StoryState) -> list[CharacterProposal]:
        return CharacterAgent().propose_all(story)

    def decide(
        self,
        story: StoryState,
        proposals: list[CharacterProposal],
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> DirectorDecision:
        return DirectorAgent().decide(
            story,
            proposals,
            conflict_summary,
            event_beat,
            cadence,
        )

    def write(
        self,
        story: StoryState,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> str:
        return WriterAgent().write(
            story,
            chapter_number,
            decision,
            conflict_summary,
            event_beat,
            cadence,
        )

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
        return MemoryAgent().remember(
            story,
            body,
            chapter_number,
            decision,
            conflict_summary,
            event_beat,
            cadence,
        )


class StoryOrchestrator:
    def __init__(self, provider: StoryAgentProvider | None = None) -> None:
        self.provider: StoryAgentProvider = provider or RuleBasedStoryAgentProvider()

    def generate_next_chapter(self, story: StoryState):
        from packages.story_core.engine import ChapterBundle

        chapter_number = story.current_chapter + 1
        working_story = story.model_copy(deep=True)
        working_story.current_chapter = chapter_number

        proposals = self.provider.propose(working_story)
        action_briefs = [proposal.model_dump() for proposal in proposals]
        conflict_summary = build_conflict_summary(working_story, action_briefs)
        cadence = compute_chapter_cadence(working_story, action_briefs, conflict_summary)
        event_beat = build_event_beat(conflict_summary)
        decision = self.provider.decide(
            working_story,
            proposals,
            conflict_summary,
            event_beat,
            cadence,
        )
        body = self.provider.write(
            working_story,
            chapter_number,
            decision,
            conflict_summary,
            event_beat,
            cadence,
        )
        updated_story = self.provider.remember(
            working_story,
            body,
            chapter_number,
            decision,
            conflict_summary,
            event_beat,
            cadence,
        )
        bundle_conflict_summary = {
            **conflict_summary,
            "approved_new_characters": decision.approved_new_characters,
            "deferred_characters": decision.deferred_characters,
            "rejected_characters": decision.rejected_characters,
        }

        bundle = ChapterBundle(
            chapter_number=chapter_number,
            body=body,
            chapter_title=updated_story.chapter_summaries[-1].chapter_title,
            cadence=cadence,
            action_briefs=action_briefs,
            conflict_summary=bundle_conflict_summary,
            event_beat=event_beat,
            character_cards=build_character_cards(updated_story),
            foreshadowing=build_foreshadowing(updated_story, chapter_number),
            next_outline=plan_next_outline(
                updated_story,
                chapter_number,
                conflict_summary=conflict_summary,
                cadence=cadence,
            ),
            updated_story=updated_story,
            chapter_summary=updated_story.chapter_summaries[-1].model_dump(),
        )
        bundle.quality_report = validate_bundle(bundle.model_dump())
        return bundle
