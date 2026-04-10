from __future__ import annotations

from packages.story_core.models import (
    ChapterSummary,
    CharacterRelationship,
    ForeshadowingState,
    StoryState,
    TimelineEvent,
)


def _normalize_participant(item: dict | str) -> dict:
    if isinstance(item, dict):
        return {
            "name": item.get("name", ""),
            "goal": item.get("goal", ""),
        }
    return {
        "name": item,
        "goal": "",
    }


def _relationship_shift(goals: list[str]) -> tuple[float, float]:
    goal_text = " ".join(goals).lower()

    cooperative_words = ("protect", "save", "guard", "help")
    adversarial_words = ("expose", "find", "accuse", "hunt")

    if any(word in goal_text for word in cooperative_words):
        return 0.1, -0.1
    if any(word in goal_text for word in adversarial_words):
        return -0.1, 0.1
    return 0.05, 0.05


def _goal_topic(text: str) -> str:
    lowered = text.lower()
    for candidate in ("witness", "ledger", "truth", "forgery", "letter", "archives"):
        if candidate in lowered:
            return candidate
    return lowered.split()[-1] if lowered.split() else "truth"


def _promote_goal(character, intent: str) -> None:
    if not intent:
        return
    remaining = [goal for goal in character.goals if goal != intent]
    character.goals = [intent, *remaining]


def _primary_follow_up_intent(character_name: str, primary: dict) -> str:
    topic = _goal_topic(primary.get("collision", "the truth"))
    lead = primary.get("lead", "the lead")
    opposition = primary.get("opposition", "the court")
    if character_name == lead:
        return f"seize control of the {topic} before {opposition} recovers"
    if character_name == opposition:
        return f"block {lead} from taking the {topic}"
    return ""


def _secondary_follow_up_intent(goal: str, secondary: dict) -> str:
    topic = _goal_topic(goal or secondary.get("detail", "the truth"))
    return f"stabilize the {topic} before the side pressure breaks"


def apply_post_chapter_updates(
    story: StoryState,
    body: str,
    chapter_number: int,
    conflict_summary: dict | None = None,
    event_beat: dict | None = None,
) -> None:
    fact = f"Chapter {chapter_number} confirms the investigation is still unfolding."
    unresolved = f"Who will control the truth after chapter {chapter_number}?"

    participant_map = {character.name: character for character in story.characters}
    primary = (conflict_summary or {}).get("primary_conflict", {})
    secondary = (conflict_summary or {}).get("secondary_conflict", {})
    primary_names = {primary.get("lead"), primary.get("opposition")} - {None, ""}
    secondary_participants = [
        _normalize_participant(item) for item in secondary.get("participants", [])
    ]
    secondary_names = {item["name"] for item in secondary_participants}
    secondary_goals = {item["name"]: item.get("goal", "") for item in secondary_participants}

    for character in story.characters:
        if character.frozen:
            continue

        touched = False
        if character.name in primary_names:
            collision = primary.get("collision", "the main clash")
            character.memory.append(
                f"Chapter {chapter_number} forced {character.name} into the main clash over {collision}."
            )
            _promote_goal(character, _primary_follow_up_intent(character.name, primary))
            character.current_emotion = "alert"
            touched = True
        elif character.name in secondary_names:
            detail = secondary.get("detail", "side pressure")
            goal = secondary_goals.get(character.name, "hold the line")
            character.memory.append(
                f"Chapter {chapter_number} pulled {character.name} into the side pressure around {detail} while trying to {goal}."
            )
            _promote_goal(character, _secondary_follow_up_intent(goal, secondary))
            character.current_emotion = "wary"
            touched = True

        if touched and not character.location:
            character.location = "palace archive"

        if character.name == story.characters[0].name and character.relationships:
            key = next(iter(character.relationships))
            relation = character.relationships[key]
            trust_delta, tension_delta = _relationship_shift(character.goals)
            character.relationships[key] = CharacterRelationship(
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
            primary_conflict=primary,
            secondary_conflict=secondary,
            event_beat=event_beat or {},
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
