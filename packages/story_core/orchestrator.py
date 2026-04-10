from __future__ import annotations

from packages.story_core.agent_base import StoryAgentProvider
from packages.story_core.character_agent import CharacterAgent
from packages.story_core.memory import (
    apply_post_chapter_updates,
    build_character_cards,
    build_foreshadowing,
)
from packages.story_core.models import CharacterProposal, DirectorDecision, StoryState
from packages.story_core.planner import (
    build_chapter_title,
    build_conflict_summary,
    build_event_beat,
    compute_chapter_cadence,
    plan_next_outline,
)
from packages.story_core.quality import validate_bundle
from packages.story_core.writer import write_chapter_body


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
        primary = conflict_summary.get("primary_conflict", {})
        secondary = conflict_summary.get("secondary_conflict", {})
        chapter_title = build_chapter_title(
            story.current_chapter,
            conflict_summary,
            story.chapter_summaries[-1].next_focus if story.chapter_summaries else "",
        )
        return DirectorDecision(
            primary_conflict=primary,
            secondary_conflict=secondary,
            event_beat=event_beat,
            cadence=cadence,
            chapter_title=chapter_title,
            next_focus=story.chapter_summaries[-1].next_focus if story.chapter_summaries else "",
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
        return write_chapter_body(
            story,
            chapter_number,
            conflict_summary=conflict_summary,
            event_beat=event_beat,
            cadence=cadence,
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
        apply_post_chapter_updates(
            story,
            body,
            chapter_number,
            conflict_summary=conflict_summary,
            event_beat=event_beat,
        )
        story.chapter_summaries[-1].cadence = cadence
        return story


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

        bundle = ChapterBundle(
            chapter_number=chapter_number,
            body=body,
            chapter_title=updated_story.chapter_summaries[-1].chapter_title,
            cadence=cadence,
            action_briefs=action_briefs,
            conflict_summary=conflict_summary,
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
