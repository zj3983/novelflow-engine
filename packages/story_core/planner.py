from __future__ import annotations

from packages.story_core.models import StoryState


def _goal_action(goal: str) -> str:
    goal_text = goal.lower()
    if any(word in goal_text for word in ("protect", "save", "guard", "help")):
        return f"tries to shield the fragile truth while attempting to {goal}"
    if any(word in goal_text for word in ("expose", "find", "accuse", "hunt")):
        return f"pushes hard to {goal} before the court closes ranks"
    return f"moves carefully to {goal} without losing leverage"


def _goal_polarity(goal: str) -> str:
    goal_text = goal.lower()
    if any(word in goal_text for word in ("protect", "save", "guard", "help", "hide")):
        return "defensive"
    if any(word in goal_text for word in ("expose", "find", "accuse", "hunt")):
        return "aggressive"
    return "neutral"


def _goal_topic(goal: str) -> str:
    goal_text = goal.lower()
    for candidate in ("witness", "ledger", "truth", "forgery", "letter", "archives"):
        if candidate in goal_text:
            return candidate
    return goal_text.split()[-1] if goal_text.split() else "truth"


def build_action_briefs(story: StoryState) -> list[dict]:
    briefs: list[dict] = []
    for character in story.characters:
        goal = character.goals[0] if character.goals else "hold the line"
        briefs.append(
            {
                "name": character.name,
                "goal": goal,
                "emotion": character.current_emotion or "controlled",
                "action": _goal_action(goal),
            }
        )
    return briefs


def build_conflict_summary(story: StoryState, action_briefs: list[dict]) -> dict:
    if not action_briefs:
        return {
            "summary": "No active conflict has surfaced yet.",
            "stakes": "The chapter must first establish pressure.",
            "primary_conflict": {
                "lead": "",
                "opposition": "",
                "collision": "No collision yet.",
            },
            "secondary_conflict": {
                "pressure": "setup",
                "detail": "The cast still needs a spark to force decisions.",
                "participants": [],
            },
        }

    lead = action_briefs[0]
    rival = None
    best_score = -1
    for candidate in action_briefs[1:]:
        score = 0
        if _goal_topic(candidate["goal"]) == _goal_topic(lead["goal"]):
            score += 2
        if _goal_polarity(candidate["goal"]) != _goal_polarity(lead["goal"]):
            score += 2
        if candidate["emotion"] != lead["emotion"]:
            score += 1
        if score > best_score:
            best_score = score
            rival = candidate
    if rival is None:
        return {
            "summary": f"{lead['name']} acts alone, trying to {lead['goal']}.",
            "stakes": f"If {lead['name']} fails, the newest clue will lose all momentum.",
            "primary_conflict": {
                "lead": lead["name"],
                "opposition": "circumstance",
                "collision": f"{lead['name']} must {lead['goal']} before the trail collapses.",
            },
            "secondary_conflict": {
                "pressure": "time",
                "detail": "Delay will let the newest clue fade into rumor.",
                "participants": [lead["name"]],
            },
        }

    secondary_candidates = [
        candidate["name"]
        for candidate in action_briefs[1:]
        if candidate["name"] != rival["name"]
    ]

    return {
        "summary": (
            f"{lead['name']} tries to {lead['goal']}, while {rival['name']} moves to {rival['goal']}."
        ),
        "stakes": (
            f"If either side wins too cleanly, control over the witness and the truth shifts for the whole cast."
        ),
        "primary_conflict": {
            "lead": lead["name"],
            "opposition": rival["name"],
            "collision": f"{lead['name']} and {rival['name']} collide over whether the witness can be controlled.",
        },
        "secondary_conflict": {
            "pressure": "time",
            "detail": "Every delay gives the court one more chance to hide the truth.",
            "participants": secondary_candidates or [rival["name"]],
        },
    }


def build_event_beat(conflict_summary: dict) -> dict:
    primary = conflict_summary.get("primary_conflict", {})
    secondary = conflict_summary.get("secondary_conflict", {})
    pivot = primary.get("collision", "The chapter needs a pivot.")
    if secondary.get("participants"):
        pivot = f"{pivot} Meanwhile, {' and '.join(secondary['participants'])} strain the board from the side."
    return {
        "turn": "pressure spike",
        "pivot": pivot,
    }


def plan_next_outline(
    story: StoryState,
    chapter_number: int,
    conflict_summary: dict | None = None,
) -> str:
    lead = story.characters[0].name if story.characters else "the lead"
    if conflict_summary and conflict_summary.get("primary_conflict"):
        primary = conflict_summary["primary_conflict"]
        secondary = conflict_summary.get("secondary_conflict", {})
        return (
            f"Chapter {chapter_number + 1}: force {primary['lead']} and {primary['opposition']} "
            f"to push their collision harder, keep pressure on {secondary.get('pressure', 'the clock')}, "
            "and decide who gains the next hold over the witness."
        )

    return (
        f"Chapter {chapter_number + 1}: force {lead} to act on the newest clue, "
        "escalate trust tension, and move one unresolved thread closer to exposure."
    )
