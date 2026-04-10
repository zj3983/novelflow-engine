from __future__ import annotations

from dataclasses import dataclass, field

from packages.story_core.engine import ChapterBundle, StoryEngine
from packages.story_core.models import StoryState


@dataclass
class StoryRecord:
    story: StoryState
    initial_story: StoryState
    history: list[ChapterBundle] = field(default_factory=list)
    parent_story_id: str | None = None
    branched_from_chapter: int | None = None


class InMemoryStoryStore:
    """Tiny in-memory store for Task 3.

    Later tasks can replace this with SQLite or another persistence layer.
    """

    def __init__(self) -> None:
        self._stories: dict[str, StoryRecord] = {}

    def create(self, story: StoryState) -> StoryRecord:
        record = StoryRecord(
            story=story,
            initial_story=story.model_copy(deep=True),
        )
        self._stories[story.story_id] = record
        return record

    def get(self, story_id: str) -> StoryRecord | None:
        return self._stories.get(story_id)

    def list(self) -> list[StoryRecord]:
        return list(self._stories.values())

    def rename(self, story_id: str, new_story_id: str) -> StoryRecord:
        record = self._stories.get(story_id)
        if record is None:
            raise KeyError(story_id)
        if new_story_id in self._stories:
            raise ValueError("story_exists")

        self._stories.pop(story_id)
        record.story.story_id = new_story_id
        record.initial_story.story_id = new_story_id
        for bundle in record.history:
            bundle.updated_story.story_id = new_story_id
        for child in self._stories.values():
            if child.parent_story_id == story_id:
                child.parent_story_id = new_story_id
        self._stories[new_story_id] = record
        return record

    def delete(self, story_id: str) -> StoryRecord:
        record = self._stories.get(story_id)
        if record is None:
            raise KeyError(story_id)
        if record.parent_story_id is None:
            raise ValueError("cannot_delete_root")
        if any(child.parent_story_id == story_id for child in self._stories.values()):
            raise ValueError("story_has_children")
        return self._stories.pop(story_id)

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
            if record.history:
                record.story = record.history[-1].updated_story.model_copy(deep=True)
            else:
                record.story = record.initial_story.model_copy(deep=True)
        return record

    def branch_from(self, story_id: str, new_story_id: str, from_chapter: int) -> StoryRecord:
        record = self._stories[story_id]
        if new_story_id in self._stories:
            raise ValueError("story_exists")

        if from_chapter < 0 or from_chapter > len(record.history):
            raise IndexError(from_chapter)

        if from_chapter == 0:
            branch_story = record.initial_story.model_copy(deep=True)
            branch_history: list[ChapterBundle] = []
        else:
            branch_history = [bundle.model_copy(deep=True) for bundle in record.history[:from_chapter]]
            branch_story = branch_history[-1].updated_story.model_copy(deep=True)

        branch_story.story_id = new_story_id
        for bundle in branch_history:
            bundle.updated_story.story_id = new_story_id

        branch_record = StoryRecord(
            story=branch_story,
            initial_story=record.initial_story.model_copy(deep=True),
            history=branch_history,
            parent_story_id=story_id,
            branched_from_chapter=from_chapter,
        )
        branch_record.initial_story.story_id = new_story_id
        self._stories[new_story_id] = branch_record
        return branch_record

    def freeze_character(self, story_id: str, character_name: str) -> StoryRecord:
        record = self._stories[story_id]
        for character in record.story.characters:
            if character.name == character_name:
                character.frozen = True
                return record
        raise KeyError(character_name)
