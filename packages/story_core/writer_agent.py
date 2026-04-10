from __future__ import annotations

from packages.story_core.models import DirectorDecision, StoryState
from packages.story_core.writer import write_chapter_body


class WriterAgent:
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
