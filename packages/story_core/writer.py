from __future__ import annotations

from packages.story_core.models import StoryState


def _goal_direction(goals: list[str]) -> str:
    goal_text = " ".join(goals).lower()
    if any(word in goal_text for word in ("protect", "save", "guard", "help")):
        return "cooperative"
    if any(word in goal_text for word in ("expose", "find", "accuse", "hunt")):
        return "adversarial"
    return "uncertain"


def _relationship_sentence(story: StoryState) -> str:
    if not story.characters or not story.characters[0].relationships:
        return "The room offers no certainty, only pressure."

    lead = story.characters[0]
    relation = next(iter(lead.relationships.values()))
    direction = _goal_direction(lead.goals)
    if direction == "adversarial" or relation.tension >= 0.8:
        return f"Each exchange with {relation.target} needles the alliance closer to open fracture."
    if direction == "cooperative" or (relation.trust >= 0.5 and relation.tension <= 0.5):
        return f"{lead.name} works in fragile step with {relation.target}, trusting the silence between them."
    return f"{lead.name} studies {relation.target} carefully, unsure which way the balance will tip."


def write_chapter_body(story: StoryState, chapter_number: int) -> str:
    lead = story.characters[0].name if story.characters else "The investigator"
    lead_goal = story.characters[0].goals[0] if story.characters and story.characters[0].goals else "find the truth"
    relation_line = _relationship_sentence(story)
    return (
        f"Chapter {chapter_number} body. {lead} presses deeper into the intrigue, "
        f"trying to {lead_goal}. {relation_line} A hidden letter appears before the chapter closes."
    )
