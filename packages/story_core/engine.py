from __future__ import annotations

from pydantic import BaseModel, Field

from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator


class ChapterBundle(BaseModel):
    chapter_number: int
    body: str
    chapter_title: str = ""
    cadence: str = "measured"
    action_briefs: list[dict] = Field(default_factory=list)
    conflict_summary: dict = Field(default_factory=dict)
    event_beat: dict = Field(default_factory=dict)
    character_cards: list[dict] = Field(default_factory=list)
    foreshadowing: list[dict] = Field(default_factory=list)
    next_outline: str
    updated_story: StoryState
    chapter_summary: dict = Field(default_factory=dict)
    quality_report: dict = Field(default_factory=dict)


class StoryEngine:
    def __init__(self, orchestrator: StoryOrchestrator | None = None) -> None:
        self.orchestrator = orchestrator or StoryOrchestrator()

    def generate_next_chapter(self, story: StoryState) -> ChapterBundle:
        return self.orchestrator.generate_next_chapter(story)
