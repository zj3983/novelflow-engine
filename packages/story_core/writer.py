from __future__ import annotations

from packages.story_core.models import StoryState


def write_chapter_body(story: StoryState, chapter_number: int) -> str:
    lead = story.characters[0].name if story.characters else "The investigator"
    lead_goal = story.characters[0].goals[0] if story.characters and story.characters[0].goals else "find the truth"
    return (
        f"Chapter {chapter_number} body. {lead} presses deeper into the intrigue, "
        f"trying to {lead_goal}. A hidden letter appears before the chapter closes."
    )
