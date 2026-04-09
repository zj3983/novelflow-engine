from __future__ import annotations

from packages.story_core.models import StoryState


def apply_post_chapter_updates(story: StoryState, body: str, chapter_number: int) -> None:
    # Minimal placeholder memory update logic for Task 2.
    if story.characters:
        story.characters[0].memory.append(f"Chapter {chapter_number} changed the situation.")


def build_character_cards(story: StoryState) -> list[dict]:
    return [{"name": c.name, "memory": list(c.memory)} for c in story.characters]


def build_foreshadowing(story: StoryState, chapter_number: int) -> list[dict]:
    # Keep this deterministic for tests; later we can make it dynamic.
    return [{"text": "A hidden letter appears."}]

