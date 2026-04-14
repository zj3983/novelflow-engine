from __future__ import annotations

from packages.story_core.models import (
    ChapterSummary,
    CharacterRelationship,
    ForeshadowingState,
    StoryState,
    TimelineEvent,
)
from packages.story_core.planner import build_chapter_title


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
    # Genre-agnostic topic extraction
    for candidate in (
        "witness", "ledger", "truth", "forgery", "letter",
        "archives", "archive", "secret", "artifact", "power",
        "cultivation", "treasure", "legacy", "realm", "formation",
    ):
        if candidate in lowered:
            return candidate
    return lowered.split()[-1] if lowered.split() else "truth"


def _promote_goal(character, intent: str) -> None:
    if not intent:
        return
    remaining = [goal for goal in character.goals if goal != intent]
    character.goals = [intent, *remaining]


def _primary_follow_up_intent(character_name: str, primary: dict) -> str:
    topic = _goal_topic(primary.get("collision", "the core objective"))
    lead = primary.get("lead", "the lead")
    opposition = primary.get("opposition", "the opposition")
    if character_name == lead:
        return f"在{opposition}缓过来之前抢先控制{topic}"
    if character_name == opposition:
        return f"阻止{lead}拿到{topic}"
    return ""


def _secondary_follow_up_intent(goal: str, secondary: dict) -> str:
    topic = _goal_topic(goal or secondary.get("detail", "the core objective"))
    return f"在侧面压力失控前先稳住{topic}"


def _build_next_focus(
    chapter_number: int,
    primary: dict,
    secondary: dict,
    unresolved_threads: list[str],
) -> str:
    for thread in unresolved_threads:
        lowered = thread.lower()
        if primary.get("lead", "").lower() in lowered or primary.get("opposition", "").lower() in lowered:
            return thread
        for participant in secondary.get("participants", []):
            participant_name = participant.get("name", "").lower() if isinstance(participant, dict) else str(participant).lower()
            if participant_name and participant_name in lowered:
                return thread

    lead = primary.get("lead", "")
    opposition = primary.get("opposition", "")
    if lead and opposition:
        topic = _goal_topic(primary.get("collision", "the main clash"))
        return f"回到{lead}与{opposition}围绕{topic}的争夺"

    if unresolved_threads:
        return unresolved_threads[0]

    return f"第{chapter_number}章之后，需要重新掀开最近一次压力爆点。"


def _generic_foreshadowing_text(chapter_number: int) -> str:
    """Generate a genre-agnostic foreshadowing hook."""
    hooks = [
        "某个被隐藏的秘密即将浮出水面。",
        "一场更大的风暴正在暗处酝酿。",
        "一个意想不到的身影在暗处注视着一切。",
        "某种被遗忘的力量正在苏醒。",
        "一条未被发现的线索悄然浮现。",
    ]
    # Use chapter number to deterministically pick a hook
    return hooks[chapter_number % len(hooks)]


def apply_post_chapter_updates(
    story: StoryState,
    body: str,
    chapter_number: int,
    conflict_summary: dict | None = None,
    event_beat: dict | None = None,
) -> None:
    fact = f"第{chapter_number}章确认调查仍在继续推进。"
    unresolved = f"第{chapter_number}章之后，谁会先掌控核心线索？"
    inherited_next_focus = story.chapter_summaries[-1].next_focus if story.chapter_summaries else ""

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
                f'第{chapter_number}章把{character.name}直接推入了围绕"{collision}"展开的正面冲突。'
            )
            _promote_goal(character, _primary_follow_up_intent(character.name, primary))
            character.current_emotion = "alert"
            touched = True
        elif character.name in secondary_names:
            detail = secondary.get("detail", "side pressure")
            goal = secondary_goals.get(character.name, "hold the line")
            character.memory.append(
                f'第{chapter_number}章把{character.name}卷进了"{detail}"带来的侧面压力中，而其行动目标是{goal}。'
            )
            _promote_goal(character, _secondary_follow_up_intent(goal, secondary))
            character.current_emotion = "wary"
            touched = True

        if touched and not character.location:
            character.location = "迷局深处"

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
            summary=f"第{chapter_number}章把核心谜团继续向前推进。",
            impact="主要角色承受的整体压力继续上升",
        )
    )

    story.chapter_summaries.append(
        ChapterSummary(
            chapter_number=chapter_number,
            chapter_title=build_chapter_title(
                chapter_number,
                conflict_summary or {},
                inherited_next_focus or _build_next_focus(chapter_number, primary, secondary, [unresolved]),
                genre=story.genre,
            ),
            summary=body,
            facts=[fact],
            unresolved_threads=[unresolved],
            next_focus=inherited_next_focus
            or _build_next_focus(chapter_number, primary, secondary, [unresolved]),
            primary_conflict=primary,
            secondary_conflict=secondary,
            event_beat=event_beat or {},
        )
    )

    # Genre-agnostic foreshadowing
    if not story.foreshadowing:
        story.foreshadowing.append(
            ForeshadowingState(
                text=_generic_foreshadowing_text(chapter_number),
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
                "text": _generic_foreshadowing_text(chapter_number),
                "first_chapter": chapter_number,
                "status": "open",
            }
        ]
    return [item.model_dump() for item in story.foreshadowing]
