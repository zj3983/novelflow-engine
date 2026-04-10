from __future__ import annotations

from packages.story_core.models import StoryState
from packages.story_core.planner import build_chapter_title


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


def _conflict_participant_count(conflict_summary: dict | None) -> int:
    if not conflict_summary:
        return 0

    primary = conflict_summary.get("primary_conflict", {})
    names = {primary.get("lead"), primary.get("opposition")} - {None, "", "circumstance"}
    secondary = conflict_summary.get("secondary_conflict", {})
    for participant in secondary.get("participants", []) or []:
        if isinstance(participant, dict):
            name = participant.get("name", "")
        else:
            name = str(participant)
        if name:
            names.add(name)
    return len(names)


def _tempo(story: StoryState, conflict_summary: dict | None, event_beat: dict | None) -> str:
    style_text = (story.style or "").lower()
    genre_text = (story.genre or "").lower()

    score = 0
    participants = _conflict_participant_count(conflict_summary)
    score += 2 if participants >= 3 else 1 if participants == 2 else 0
    if conflict_summary and conflict_summary.get("stakes"):
        score += 1
    if conflict_summary and (conflict_summary.get("secondary_conflict") or {}).get("pressure") == "time":
        score += 1
    if event_beat and event_beat.get("turn"):
        score += 1

    if "tense" in style_text or "suspense" in style_text or "noir" in style_text:
        score += 2
    if "mystery" in genre_text:
        score += 1

    if score >= 5:
        return "urgent"
    if score >= 3:
        return "measured"
    return "breathing"


def _tempo_sentence(tempo: str) -> str:
    return f"Tempo: {tempo}"


def _closing_sentence(tempo: str) -> str:
    if tempo == "urgent":
        return "The chapter closes as the cut comes hard."
    if tempo == "measured":
        return "The chapter closes with a held breath."
    return "The chapter closes on a quiet note."


def _resolve_chapter_title(
    story: StoryState,
    chapter_number: int,
    conflict_summary: dict | None,
) -> str:
    # Prefer a title already computed upstream for this exact chapter.
    for summary in story.chapter_summaries:
        if summary.chapter_number == chapter_number and summary.chapter_title:
            return summary.chapter_title

    latest_next_focus = story.chapter_summaries[-1].next_focus if story.chapter_summaries else ""
    return build_chapter_title(
        chapter_number,
        conflict_summary,
        latest_next_focus,
    )


def _title_sentence(
    story: StoryState,
    chapter_number: int,
    conflict_summary: dict | None = None,
) -> str:
    chapter_title = _resolve_chapter_title(story, chapter_number, conflict_summary)
    return f"Title: {chapter_title}"


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
    tempo_value = _tempo(story, conflict_summary, event_beat)
    tempo_line = _tempo_sentence(tempo_value)
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
    closing_line = _closing_sentence(tempo_value)
    return (
        f"Chapter {chapter_number} body. {opening_hook_line} {title_line} {tempo_line} {lead} presses deeper into the intrigue, "
        f"trying to {lead_goal}. {conflict_line} {secondary_line} {event_line} {relation_line} {continuity_line} "
        f"{next_focus_line} "
        f"A hidden letter appears before the chapter closes. {closing_line}"
    )
