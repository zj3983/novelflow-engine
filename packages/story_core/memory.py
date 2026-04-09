from __future__ import annotations

from packages.story_core.models import (
    ChapterSummary,
    CharacterRelationship,
    ForeshadowingState,
    StoryState,
    TimelineEvent,
)


def _relationship_shift(goals: list[str]) -> tuple[float, float]:
    goal_text = " ".join(goals).lower()

    cooperative_words = ("protect", "save", "guard", "help")
    adversarial_words = ("expose", "find", "accuse", "hunt")

    if any(word in goal_text for word in cooperative_words):
        return 0.1, -0.1
    if any(word in goal_text for word in adversarial_words):
        return -0.1, 0.1
    return 0.05, 0.05


def apply_post_chapter_updates(story: StoryState, body: str, chapter_number: int) -> None:
    fact = f"Chapter {chapter_number} confirms the investigation is still unfolding."
    unresolved = f"Who will control the truth after chapter {chapter_number}?"

    if story.characters:
        lead = story.characters[0]
        if not lead.frozen:
            lead.memory.append(f"Chapter {chapter_number} changed the situation.")
            lead.current_emotion = "alert"
            if not lead.location:
                lead.location = "palace archive"
            if lead.relationships:
                key = next(iter(lead.relationships))
                relation = lead.relationships[key]
                trust_delta, tension_delta = _relationship_shift(lead.goals)
                lead.relationships[key] = CharacterRelationship(
                    target=relation.target,
                    trust=max(0.0, min(1.0, round(relation.trust + trust_delta, 2))),
                    tension=max(0.0, min(1.0, round(relation.tension + tension_delta, 2))),
                    bond=relation.bond,
                )

    story.world_facts.append(fact)
    story.timeline.append(
        TimelineEvent(
            chapter_number=chapter_number,
            summary=f"Chapter {chapter_number} pushes the core mystery forward.",
            impact="raises pressure on every major player",
        )
    )

    story.chapter_summaries.append(
        ChapterSummary(
            chapter_number=chapter_number,
            summary=body,
            facts=[fact],
            unresolved_threads=[unresolved],
        )
    )

    if not story.foreshadowing:
        story.foreshadowing.append(
            ForeshadowingState(
                text="A hidden letter appears.",
                first_chapter=chapter_number,
                status="open",
            )
        )
    else:
        story.foreshadowing[0].status = "reinforced"


def build_character_cards(story: StoryState) -> list[dict]:
    return [
        {
            "name": c.name,
            "role": c.role,
            "memory": list(c.memory),
            "current_emotion": c.current_emotion,
            "location": c.location,
            "goals": list(c.goals),
            "relationships": {key: value.model_dump() for key, value in c.relationships.items()},
        }
        for c in story.characters
    ]


def build_foreshadowing(story: StoryState, chapter_number: int) -> list[dict]:
    if not story.foreshadowing:
        return [
            {
                "text": "A hidden letter appears.",
                "first_chapter": chapter_number,
                "status": "open",
            }
        ]
    return [item.model_dump() for item in story.foreshadowing]
