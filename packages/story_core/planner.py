from __future__ import annotations

from packages.story_core.models import StoryState


def plan_next_outline(story: StoryState, chapter_number: int) -> str:
    lead = story.characters[0].name if story.characters else "the lead"
    return (
        f"Chapter {chapter_number + 1}: force {lead} to act on the newest clue, "
        "escalate trust tension, and move one unresolved thread closer to exposure."
    )
