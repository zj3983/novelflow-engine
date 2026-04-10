from __future__ import annotations

from packages.story_core.models import StoryState


def _topic(text: str) -> str:
    lowered = text.lower()
    for candidate in ("witness", "ledger", "archives", "truth", "forgery", "letter"):
        if candidate in lowered:
            return candidate
    return lowered.split()[-1] if lowered.split() else "pressure"


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


def _continuity_sentence(story: StoryState) -> str:
    parts: list[str] = []

    if story.world_facts:
        parts.append(f"Carries forward: {story.world_facts[-1]}")
    if story.foreshadowing:
        parts.append(f"Foreshadowing lingers: {story.foreshadowing[0].text}")

    return " ".join(parts)


def _next_focus_sentence(story: StoryState) -> str:
    if not story.chapter_summaries:
        return ""

    next_focus = story.chapter_summaries[-1].next_focus
    if not next_focus:
        return ""

    return f"Next focus: {next_focus}"


def _opening_hook_sentence(story: StoryState) -> str:
    if not story.chapter_summaries:
        return ""

    next_focus = story.chapter_summaries[-1].next_focus
    if not next_focus:
        return ""

    return f"Opening hook: {next_focus}"


def _title_sentence(
    story: StoryState,
    chapter_number: int,
    conflict_summary: dict | None = None,
) -> str:
    source_text = ""
    if story.chapter_summaries and story.chapter_summaries[-1].next_focus:
        source_text = story.chapter_summaries[-1].next_focus
    elif conflict_summary:
        primary = conflict_summary.get("primary_conflict", {})
        source_text = primary.get("collision", "") or conflict_summary.get("summary", "")

    topic = _topic(source_text or "pressure")
    topic_word = "Pressure" if topic == "truth" else topic.title()
    return f"Title: Chapter {chapter_number}: {topic_word} Crossroads"


def write_chapter_body(
    story: StoryState,
    chapter_number: int,
    conflict_summary: dict | None = None,
    event_beat: dict | None = None,
) -> str:
    lead = story.characters[0].name if story.characters else "The investigator"
    lead_goal = story.characters[0].goals[0] if story.characters and story.characters[0].goals else "find the truth"
    relation_line = _relationship_sentence(story)
    continuity_line = _continuity_sentence(story)
    opening_hook_line = _opening_hook_sentence(story)
    title_line = _title_sentence(story, chapter_number, conflict_summary=conflict_summary)
    conflict_line = (
        f"Conflict: {conflict_summary['summary']} Stakes: {conflict_summary['stakes']}"
        if conflict_summary
        else ""
    )
    secondary_line = (
        f"Secondary pressure: {conflict_summary['secondary_conflict']['detail']}"
        if conflict_summary and conflict_summary.get("secondary_conflict")
        else ""
    )
    event_line = (
        f"Event beat: {event_beat['pivot']}"
        if event_beat
        else ""
    )
    next_focus_line = _next_focus_sentence(story)
    return (
        f"Chapter {chapter_number} body. {opening_hook_line} {title_line} {lead} presses deeper into the intrigue, "
        f"trying to {lead_goal}. {conflict_line} {secondary_line} {event_line} {relation_line} {continuity_line} "
        f"{next_focus_line} "
        "A hidden letter appears before the chapter closes."
    )
