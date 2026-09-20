from __future__ import annotations

import json
import re
import urllib.error
from typing import Protocol

from packages.story_core.agent_base import (
    BaseOpenAIProvider,
    _parse_json_text,
    compact_list,
    compact_text,
)
from packages.story_core.model_gateway import ModelRequest, ModelResponse, normalize_model_error
from packages.story_core.models import CharacterProposal, CharacterState, StoryState, default_fast_model_name


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
    if any(word in goal_text for word in ("伤", "伤势", "状态")):
        subject = goal
        for prefix in ("确认", "检查", "查看"):
            if subject.startswith(prefix):
                subject = subject[len(prefix) :].strip()
                break
        return f"先确认{subject or goal}，再决定是否进一步介入"
    if any(word in goal_text for word in ("气氛", "关系", "态度", "反应")):
        return "观察相关人的反应，找机会试探关系变化"
    if any(
        word in goal_text
        for word in (
            "查",
            "找",
            "揭",
            "追",
            "弄清",
            "确认",
            "调查",
            "原因",
            "动机",
            "来源",
            "实力",
            "线索",
            "expose",
            "find",
            "accuse",
            "hunt",
        )
    ):
        subject = goal
        for prefix in ("查清", "查找", "调查", "弄清", "确认", "找出", "揭开"):
            if subject.startswith(prefix):
                subject = subject[len(prefix) :].strip()
                break
        return f"围绕{subject or goal}主动搜集线索"
    if any(word in goal_text for word in ("protect", "save", "guard", "help", "守", "保", "护", "救")):
        subject = goal
        for prefix in ("守住", "保护", "保住", "护住", "救下"):
            if subject.startswith(prefix):
                subject = subject[len(prefix) :].strip()
                break
        return f"先守住{subject or goal}，再根据当前反馈决定下一步"
    return f"观察与{goal}相关的反馈，再决定是否介入"


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
    if any(word in goal_text for word in ("seize", "block", "corner", "force", "夺", "阻", "逼", "压", "抢", "设局")):
        return 4
    if any(word in goal_text for word in ("find", "expose", "accuse", "hunt", "查", "找", "揭", "追", "弄清", "确认")):
        return 3
    if any(word in goal_text for word in ("protect", "hide", "stabilize", "guard", "save", "help", "守", "保", "藏", "稳", "护", "救")):
        return 2
    return 1


def _relationship_drive(character: CharacterState) -> int:
    """Let current tension/trust break ties without activating role labels."""
    tension = max(
        (float(relationship.tension) for relationship in character.relationships.values()),
        default=0.0,
    )
    trust = max(
        (float(relationship.trust) for relationship in character.relationships.values()),
        default=0.0,
    )
    return (2 if tension >= 0.75 else 1 if tension >= 0.5 else 0) + (
        1 if trust >= 0.75 and tension < 0.5 else 0
    )


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
        explicit_goal = (
            character.goals[0]
            if character.goals
            else character.story_drive.immediate_goal
            or character.current_life_profile.immediate_problem
        )
        goal = explicit_goal or "暂不行动，先观察局势"
        emotion = character.current_emotion or "controlled"
        current_state = character.current_state
        if isinstance(current_state, dict):
            current_state = (
                current_state.get("current")
                if isinstance(current_state.get("current"), dict)
                else current_state
            )
        trigger = (
            str(current_state.get("summary") or "")
            if isinstance(current_state, dict)
            else ""
        )
        relationship_values = sorted(
            character.relationships.values(),
            key=lambda relationship: (relationship.tension, relationship.trust),
            reverse=True,
        )
        target = next(
            (
                relationship.target
                for relationship in relationship_values
                if relationship.target.strip()
            ),
            "",
        )
        return CharacterProposal(
            name=character.name,
            goal=goal,
            emotion=emotion,
            action=_goal_action(goal) if explicit_goal else "",
            target=target,
            trigger=trigger,
            speech_strategy=character.performance_profile.speech_style
            or "先观察，再用符合自身利益的方式试探或推进",
            withhold=character.performance_profile.reveal_limits[0]
            if character.performance_profile.reveal_limits
            else "不主动暴露会削弱自身筹码的信息",
            blocked_reaction=character.personality_portrait.behavior.conflict_response
            or "行动受阻后暂缓、转向或保留下一步筹码",
            dramatic_function=character.story_function or character.chapter_role,
            priority=(
                (
                    _goal_drive(goal)
                    + _role_drive(character.role)
                    + _relationship_drive(character)
                    + _latest_summary_boost(story, character.name, goal)
                    + _latest_thread_boost(story, character.name)
                )
                if explicit_goal
                else _emotion_drive(emotion) + _latest_thread_boost(story, character.name)
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

    def complete(self, request: ModelRequest) -> ModelResponse:
        from packages.story_core.agents._runtime_common import call_with_logging

        response, _provider, _model, _protocol = call_with_logging(
            gateway=self.model_gateway, stage="planner", request=request
        )
        if response.ok:
            self._clear_last_error()
        else:
            self._set_last_error(normalize_model_error(response))
        return response

    def propose_all(self, story: StoryState) -> list[CharacterProposal]:
        settings = self._runtime_settings()
        active_characters = [
            character
            for character in story.characters
            if not character.frozen and character.lifecycle_state == "active"
        ]
        if not active_characters:
            return []

        prompt = self._build_prompt(story, active_characters)
        chapter_context = (story.outline_context or {}).get("chapter", {})
        try:
            chapter_number = int(chapter_context.get("chapter_number") or story.current_chapter + 1)
        except (AttributeError, TypeError, ValueError):
            chapter_number = story.current_chapter + 1
        request = ModelRequest(
            prompt=prompt,
            system_prompt=(
                "You are a character-intent planner for an evolving Chinese novel. "
                "Return JSON only with a top-level object containing a proposals array. "
                "Each proposal describes what that character independently wants to do now; "
                "it is pressure on the director, not a command that must appear in the chapter."
            ),
            provider=settings.provider,
            model=story.agent_settings.character_model or story.agent_settings.global_model or default_fast_model_name(),
            operation="character",
            temperature=float(story.agent_settings.temperature),
            max_tokens=min(2200, 500 + 280 * len(active_characters)),
            json_mode=True,
            metadata={"chapter_number": chapter_number},
        )
        response = self.complete(request)
        parsed = _parse_json_text(response.text) if response.ok else None
        if parsed is None:
            if response.ok:
                self._set_last_error("角色代理返回的内容不是有效 JSON")
            return []
        self._clear_last_error()

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
                    goal=str(item.get("goal", "")).strip() or "暂不行动，先观察局势",
                    emotion=str(item.get("emotion", "neutral")).strip() or "neutral",
                    action=str(item.get("action", "")).strip(),
                    priority=int(item.get("priority", 0) or 0),
                    target=str(item.get("target", "")).strip(),
                    trigger=str(item.get("trigger", "")).strip(),
                    activation_reason=str(item.get("activation_reason", "")).strip(),
                    speech_strategy=str(item.get("speech_strategy", "")).strip(),
                    withhold=str(item.get("withhold", "")).strip(),
                    blocked_reaction=str(item.get("blocked_reaction", "")).strip(),
                    dramatic_function=str(item.get("dramatic_function", "")).strip(),
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
            260,
        )
        chapter_context = {}
        if isinstance(story.outline_context, dict):
            raw_chapter = story.outline_context.get("chapter")
            if isinstance(raw_chapter, dict):
                chapter_context = {
                    key: raw_chapter.get(key)
                    for key in (
                        "chapter_number",
                        "title",
                        "goal",
                        "obstacle",
                        "action",
                        "turn",
                        "payoff",
                        "ending_hook",
                        "cast",
                        "core_conflict",
                        "gain",
                        "cost",
                        "state_delta",
                        "planned_hook",
                        "hook",
                        "opening_carry",
                        "chapter_sop",
                        "payoff_contract",
                        "must_not_write",
                        "execution_contract",
                    )
                    if raw_chapter.get(key) not in (None, "", [], {})
                }

        character_lines: list[str] = []
        for character in characters:
            relationships = "; ".join(
                compact_text(
                    f"{relationship.target}(trust={relationship.trust}, tension={relationship.tension}, bond={relationship.bond})",
                    90,
                )
                for relationship in list(character.relationships.values())[:3]
            ) or "none"
            relationship_notes = "; ".join(
                compact_text(
                    f"{note.target}:{note.relation_type}/{note.current_attitude}/{note.shared_interest_or_conflict}",
                    110,
                )
                for note in character.relationship_notes[:3]
            ) or "none"
            goals = "; ".join(compact_list(character.goals, max_items=2, item_chars=80)) or "none"
            drive = character.story_drive
            portrait = character.personality_portrait
            performance = character.performance_profile
            character_lines.append(
                "\n".join(
                    [
                        f"- {character.name} [{character.role}; narrative_function={character.narrative_function}]",
                        f"  current goals: {goals}; emotion: {character.current_emotion}; location: {character.location or 'unknown'}",
                        f"  drive: immediate={compact_text(drive.immediate_goal, 100)}; motivation={compact_text(drive.motivation, 120)}; conflict={compact_text(drive.main_conflict_reason, 120)}",
                        f"  psychology: desire={compact_text(portrait.psychology.desire, 90)}; fear={compact_text(portrait.psychology.fear, 90)}",
                        f"  behaviour: pressure={compact_text(portrait.behavior.pressure_mode, 100)}; conflict_response={compact_text(portrait.behavior.conflict_response, 100)}",
                        f"  voice/action: speech={compact_text(performance.speech_style, 100)}; action={compact_text(performance.action_style, 100)}",
                        f"  relationships: {relationships}; notes: {relationship_notes}",
                        f"  secrets/private knowledge: {'; '.join(compact_list(character.secrets, max_items=2, item_chars=80)) or 'none'}",
                    ]
                )
            )

        return "\n".join(
            [
                f"Story outline: {compact_text(story.outline, 520)}",
                f"Genre: {story.genre}",
                f"Style: {story.style}",
                f"Author constraints: {json.dumps(compact_list(_constraint_texts(story), max_items=4, item_chars=90), ensure_ascii=False)}",
                f"Current chapter: {story.current_chapter + 1}",
                "Chapter execution contract (highest authority): "
                + json.dumps(chapter_context, ensure_ascii=False),
                f"Latest chapter summary: {current_summary}",
                "Candidate characters:",
                *character_lines,
                "",
                "Character proposals must stay inside the current chapter execution contract.",
                "The contract decides the chapter core conflict, gain, cost, state transition, payoff, forbidden changes, and planned hook.",
                "Character intent only decides how a person pressures, resists, hesitates, misunderstands, speaks, stays silent, or reacts inside that contract.",
                "Do not replace the chapter goal, promised gain/cost/state transition, forbidden changes, or planned hook with a character preference.",
                "For each candidate, decide what this person independently wants to do in the current contracted chapter situation.",
                "Ground the proposal in personal interest, relationship pressure, personality, current emotion, and what this character actually knows.",
                "Secrets/private knowledge may influence only their own decision; never assume other characters know them.",
                "A character may observe, wait, withdraw, stay silent, or receive a low priority when there is no strong trigger.",
                "Do not force love interests to be jealous, antagonists to attack, or comic characters to joke in every chapter.",
                "Do not complete the chapter plot. Do not make every character serve the protagonist or share the same goal.",
                "dramatic_function describes a useful possible scene function, not a mandatory beat.",
                "activation_reason explains why that function is appropriate now; leave it empty when it should stay dormant.",
                "Return concrete current moves, not abstract arc summaries.",
                "Return JSON with this structure:",
                '{ "proposals": [ { "name": "...", "goal": "...", "target": "...", "trigger": "...", "emotion": "...", "action": "...", "speech_strategy": "...", "withhold": "...", "blocked_reaction": "...", "dramatic_function": "...", "activation_reason": "...", "priority": 0, "new_character_candidates": [] } ] }',
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
        self.last_result_source = "empty"

    def propose(self, story: StoryState, character: CharacterState) -> CharacterProposal:
        return self.rule_provider.propose(story, character)

    def propose_all(self, story: StoryState) -> list[CharacterProposal]:
        self.last_result_source = "empty"
        if story.agent_settings.mode == "LLM-assisted":
            try:
                llm_proposals = self.llm_provider.propose_all(story)
            except Exception:
                llm_proposals = []
            if llm_proposals:
                self.last_result_source = "llm"
                return llm_proposals
        try:
            proposals = self.rule_provider.propose_all(story)
            if proposals:
                self.last_result_source = "rule_fallback"
            return proposals
        except Exception:
            return []
