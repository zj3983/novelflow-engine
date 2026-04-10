from __future__ import annotations

from pydantic import BaseModel, Field

from packages.story_core.memory import (
    apply_post_chapter_updates,
    build_character_cards,
    build_foreshadowing,
)
from packages.story_core.models import StoryState
from packages.story_core.planner import (
    build_action_briefs,
    build_conflict_summary,
    build_event_beat,
    compute_chapter_cadence,
    plan_next_outline,
)
from packages.story_core.quality import validate_bundle
from packages.story_core.writer import write_chapter_body


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
    def generate_next_chapter(self, story: StoryState) -> ChapterBundle:
        chapter_number = story.current_chapter + 1

        updated_story = story.model_copy(deep=True)
        updated_story.current_chapter = chapter_number

        action_briefs = build_action_briefs(updated_story)
        conflict_summary = build_conflict_summary(updated_story, action_briefs)
        cadence = compute_chapter_cadence(updated_story, action_briefs, conflict_summary)
        event_beat = build_event_beat(conflict_summary)
        body = write_chapter_body(
            updated_story,
            chapter_number,
            conflict_summary=conflict_summary,
            event_beat=event_beat,
        )
        apply_post_chapter_updates(
            updated_story,
            body,
            chapter_number,
            conflict_summary=conflict_summary,
            event_beat=event_beat,
        )
        updated_story.chapter_summaries[-1].cadence = cadence

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
