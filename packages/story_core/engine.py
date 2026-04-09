from __future__ import annotations

from pydantic import BaseModel, Field

from packages.story_core.memory import (
    apply_post_chapter_updates,
    build_character_cards,
    build_foreshadowing,
)
from packages.story_core.models import StoryState
from packages.story_core.planner import plan_next_outline
from packages.story_core.writer import write_chapter_body


class ChapterBundle(BaseModel):
    chapter_number: int
    body: str
    character_cards: list[dict] = Field(default_factory=list)
    foreshadowing: list[dict] = Field(default_factory=list)
    next_outline: str
    updated_story: StoryState


class StoryEngine:
    def generate_next_chapter(self, story: StoryState) -> ChapterBundle:
        chapter_number = story.current_chapter + 1

        updated_story = story.model_copy(deep=True)
        updated_story.current_chapter = chapter_number

        body = write_chapter_body(updated_story, chapter_number)
        apply_post_chapter_updates(updated_story, body, chapter_number)

        return ChapterBundle(
            chapter_number=chapter_number,
            body=body,
            character_cards=build_character_cards(updated_story),
            foreshadowing=build_foreshadowing(updated_story, chapter_number),
            next_outline=plan_next_outline(updated_story, chapter_number),
            updated_story=updated_story,
        )

