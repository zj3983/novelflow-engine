from __future__ import annotations

from packages.story_core.memory import apply_post_chapter_updates
from packages.story_core.models import DirectorDecision, StoryState


class MemoryAgent:
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
        if decision.chapter_title:
            story.chapter_summaries[-1].chapter_title = decision.chapter_title
        return story
