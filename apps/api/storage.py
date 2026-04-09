from __future__ import annotations

from dataclasses import dataclass, field

from packages.story_core.engine import ChapterBundle, StoryEngine
from packages.story_core.models import StoryState


@dataclass
class StoryRecord:
    story: StoryState
    history: list[ChapterBundle] = field(default_factory=list)


class InMemoryStoryStore:
    """Tiny in-memory store for Task 3.

    Later tasks can replace this with SQLite or another persistence layer.
    """

    def __init__(self) -> None:
        self._stories: dict[str, StoryRecord] = {}

    def create(self, story: StoryState) -> StoryRecord:
        record = StoryRecord(story=story)
        self._stories[story.story_id] = record
        return record

    def get(self, story_id: str) -> StoryRecord | None:
        return self._stories.get(story_id)

    def generate_next(self, story_id: str, engine: StoryEngine) -> ChapterBundle:
        record = self._stories[story_id]
        bundle = engine.generate_next_chapter(record.story)
        record.story = bundle.updated_story
        record.history.append(bundle)
        return bundle

    def rollback_last(self, story_id: str) -> StoryRecord:
        record = self._stories[story_id]
        if record.history:
            record.history.pop()
            record.story.current_chapter = max(0, record.story.current_chapter - 1)
        return record

