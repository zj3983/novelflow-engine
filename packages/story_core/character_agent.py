from __future__ import annotations

from packages.story_core.models import CharacterProposal, CharacterState, StoryState


def _goal_topic(goal: str) -> str:
    goal_text = goal.lower()
    for candidate in ("witness", "ledger", "truth", "forgery", "letter", "archives", "archive"):
        if candidate in goal_text:
            return candidate
    return goal_text.split()[-1] if goal_text.split() else "truth"


def _goal_action(goal: str) -> str:
    goal_text = goal.lower()
    if any(word in goal_text for word in ("protect", "save", "guard", "help")):
        return f"tries to shield the fragile truth while attempting to {goal}"
    if any(word in goal_text for word in ("expose", "find", "accuse", "hunt")):
        return f"pushes hard to {goal} before the court closes ranks"
    return f"moves carefully to {goal} without losing leverage"


def _emotion_drive(emotion: str) -> int:
    emotion_text = emotion.lower()
    if emotion_text == "alert":
        return 2
    if emotion_text in {"defiant", "driven", "wary"}:
        return 1
    return 0


def _role_drive(role: str) -> int:
    return 1 if role.lower() == "protagonist" else 0


def _goal_drive(goal: str) -> int:
    goal_text = goal.lower()
    if any(word in goal_text for word in ("seize", "block", "corner", "force")):
        return 4
    if any(word in goal_text for word in ("find", "expose", "accuse", "hunt")):
        return 3
    if any(word in goal_text for word in ("protect", "hide", "stabilize", "guard", "save", "help")):
        return 2
    return 1


def _latest_summary_boost(story: StoryState, character_name: str, goal: str) -> int:
    if not story.chapter_summaries:
        return 0

    latest = story.chapter_summaries[-1]
    boost = 0
    if character_name in latest.primary_conflict.get("lead", ""):
        boost += 2
    if character_name in latest.primary_conflict.get("opposition", ""):
        boost += 1

    summary_text = " ".join(
        [
            latest.summary,
            " ".join(latest.facts),
            " ".join(latest.unresolved_threads),
            " ".join(latest.event_beat.values()) if latest.event_beat else "",
        ]
    ).lower()
    if _goal_topic(goal) in summary_text:
        boost += 1
    return boost


def _latest_thread_boost(story: StoryState, character_name: str) -> int:
    if not story.chapter_summaries:
        return 0

    latest = story.chapter_summaries[-1]
    thread_text = " ".join(latest.unresolved_threads).lower()
    if not thread_text:
        return 0

    boost = 0
    if character_name.lower() in thread_text:
        boost += 6
    if "next" in thread_text:
        boost += 1
    return boost


def _new_character_candidates(character: CharacterState) -> list[str]:
    candidates: list[str] = []
    for secret in character.secrets:
        if "archivist" in secret.lower() and "Old Archivist" not in candidates:
            candidates.append("Old Archivist")
    return candidates


class CharacterAgent:
    def propose(self, story: StoryState, character: CharacterState) -> CharacterProposal:
        goal = character.goals[0] if character.goals else "hold the line"
        emotion = character.current_emotion or "controlled"
        return CharacterProposal(
            name=character.name,
            goal=goal,
            emotion=emotion,
            action=_goal_action(goal),
            priority=(
                _goal_drive(goal)
                + _emotion_drive(emotion)
                + _role_drive(character.role)
                + _latest_summary_boost(story, character.name, goal)
                + _latest_thread_boost(story, character.name)
            ),
            new_character_candidates=_new_character_candidates(character),
        )

    def propose_all(self, story: StoryState) -> list[CharacterProposal]:
        proposals = [
            self.propose(story, character)
            for character in story.characters
            if not character.frozen and character.lifecycle_state == "active"
        ]
        proposals.sort(key=lambda proposal: (-proposal.priority, proposal.name))
        return proposals
