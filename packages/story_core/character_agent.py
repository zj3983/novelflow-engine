from __future__ import annotations

import json
import re
import urllib.error
from typing import Protocol

from packages.story_core.agent_base import (
    BaseOpenAIProvider,
    compact_list,
    compact_text,
    parse_json_message_content,
)
from packages.story_core.models import CharacterProposal, CharacterState, StoryState, default_fast_model_name
from packages.story_core.runtime import record_agent_runtime


def _goal_topic(goal: str) -> str:
    goal_text = goal.lower()
    for candidate in (
        "witness",
        "ledger",
        "truth",
        "forgery",
        "letter",
        "archives",
        "archive",
        "secret",
        "artifact",
        "power",
        "cultivation",
        "treasure",
        "legacy",
        "realm",
        "formation",
    ):
        if candidate in goal_text:
            return candidate
    return goal_text.split()[-1] if goal_text.split() else "truth"


def _goal_action(goal: str) -> str:
    goal_text = goal.lower()
    if any(word in goal_text for word in ("protect", "save", "guard", "help")):
        return f"一边护住脆弱的真相，一边尝试{goal}"
    if any(word in goal_text for word in ("expose", "find", "accuse", "hunt")):
        return f"抢在对手合围之前，强行推进{goal}"
    return f"谨慎推进{goal}，同时不让自己失去筹码"


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
        secret_lower = secret.lower()
        for keyword in ("archivist", "keeper", "guardian", "elder", "master"):
            if keyword in secret_lower:
                match = re.search(r"\b([A-Za-z]+)\s+" + keyword, secret, re.IGNORECASE)
                if match:
                    title = match.group(1).capitalize() + " " + keyword.capitalize()
                else:
                    title = keyword.capitalize()
                if title not in candidates:
                    candidates.append(title)
    return candidates


def _constraint_texts(story: StoryState) -> list[str]:
    return [item.strip() for item in story.author_constraints if item.strip()]


class CharacterProposalProvider(Protocol):
    def propose_all(self, story: StoryState) -> list[CharacterProposal]:
        pass


class RuleBasedCharacterProposalProvider:
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


class OpenAICharacterProposalProvider(BaseOpenAIProvider):
    runtime_key = "character"

    def propose_all(self, story: StoryState) -> list[CharacterProposal]:
        settings = self._runtime_settings()
        if not settings.api_key:
            return []

        active_characters = [
            character
            for character in story.characters
            if not character.frozen and character.lifecycle_state == "active"
        ]
        if not active_characters:
            return []

        prompt = self._build_prompt(story, active_characters)
        payload = {
            "model": story.agent_settings.character_model or story.agent_settings.global_model or default_fast_model_name(),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a character action planner for an evolving Chinese novel project. "
                        "Return JSON only with a top-level object containing a proposals array. "
                        "Each proposal must include name, goal, emotion, action, priority, and new_character_candidates."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": float(story.agent_settings.temperature),
            "max_tokens": 700,
        }

        try:
            response = self._post_json("/chat/completions", payload, settings)
            parsed = parse_json_message_content(response)
            if parsed is None:
                self._set_last_error("角色代理返回的内容不是有效 JSON")
                return []
            self._clear_last_error()
        except urllib.error.HTTPError as exc:
            self._set_last_error(f"角色代理 HTTP {exc.code}")
            return []
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            self._set_last_error(f"角色代理请求失败：{exc}")
            return []

        raw_proposals = parsed.get("proposals", [])
        proposals: list[CharacterProposal] = []
        for item in raw_proposals if isinstance(raw_proposals, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            proposals.append(
                CharacterProposal(
                    name=name,
                    goal=str(item.get("goal", "")).strip() or "hold the line",
                    emotion=str(item.get("emotion", "neutral")).strip() or "neutral",
                    action=str(item.get("action", "")).strip(),
                    priority=int(item.get("priority", 0) or 0),
                    new_character_candidates=[
                        str(candidate).strip()
                        for candidate in item.get("new_character_candidates", [])
                        if str(candidate).strip()
                    ],
                )
            )

        proposals.sort(key=lambda proposal: (-proposal.priority, proposal.name))
        return proposals

    def _build_prompt(self, story: StoryState, characters: list[CharacterState]) -> str:
        current_summary = compact_text(
            story.chapter_summaries[-1].summary if story.chapter_summaries else "No prior chapter.",
            220,
        )
        character_lines: list[str] = []
        for character in characters:
            relationships = ", ".join(
                compact_text(
                    f"{relationship.target}(trust={relationship.trust}, tension={relationship.tension})",
                    48,
                )
                for relationship in list(character.relationships.values())[:3]
            ) or "none"
            goals = "; ".join(compact_list(character.goals, max_items=2, item_chars=60)) or "hold the line"
            secrets = "; ".join(compact_list(character.secrets, max_items=2, item_chars=50)) or "none"
            character_lines.append(
                compact_text(
                    f"- {character.name} [{character.role}] goals: {goals}; emotion: {character.current_emotion}; "
                    f"location: {character.location or 'unknown'}; relationships: {relationships}; secrets: {secrets}",
                    260,
                )
            )

        return "\n".join(
            [
                f"Story outline: {compact_text(story.outline, 520)}",
                f"Genre: {story.genre}",
                f"Style: {story.style}",
                f"Author constraints: {json.dumps(compact_list(_constraint_texts(story), max_items=4, item_chars=70), ensure_ascii=False)}",
                f"Current chapter: {story.current_chapter}",
                f"Latest chapter summary: {current_summary}",
                "Active characters:",
                *character_lines,
                "Treat author constraints as hard guardrails when proposing actions or suggesting new characters.",
                "Prefer concrete next moves grounded in the current world state instead of abstract summaries.",
                "Return JSON with this structure:",
                '{ "proposals": [ { "name": "...", "goal": "...", "emotion": "...", "action": "...", "priority": 0, "new_character_candidates": [] } ] }',
            ]
        )


class CharacterAgent:
    def __init__(
        self,
        llm_provider: CharacterProposalProvider | None = None,
        rule_provider: RuleBasedCharacterProposalProvider | None = None,
    ) -> None:
        self.rule_provider = rule_provider or RuleBasedCharacterProposalProvider()
        self.llm_provider = llm_provider or OpenAICharacterProposalProvider()

    def propose(self, story: StoryState, character: CharacterState) -> CharacterProposal:
        return self.rule_provider.propose(story, character)

    def propose_all(self, story: StoryState) -> list[CharacterProposal]:
        if story.agent_settings.mode == "LLM-assisted":
            llm_proposals = self.llm_provider.propose_all(story)
            if llm_proposals:
                record_agent_runtime(
                    story,
                    "CharacterAgent",
                    story.agent_settings.mode,
                    "llm",
                    story.current_chapter,
                )
                return llm_proposals

            fallback_reason = "LLM did not return usable proposals"
            if hasattr(self.llm_provider, "last_error_reason"):
                fallback_reason = self.llm_provider.last_error_reason() or fallback_reason
            if hasattr(self.llm_provider, "available") and not self.llm_provider.available():
                fallback_reason = "Missing OPENAI_API_KEY"
            record_agent_runtime(
                story,
                "CharacterAgent",
                story.agent_settings.mode,
                "fallback",
                story.current_chapter,
                fallback_reason,
            )
        return self.rule_provider.propose_all(story)
