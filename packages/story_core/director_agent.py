from __future__ import annotations

import json
import urllib.error
from typing import Protocol

from packages.story_core.agent_base import BaseOpenAIProvider
from packages.story_core.models import CharacterProposal, DirectorDecision, NewCharacterPolicy, StoryState
from packages.story_core.planner import build_chapter_title, select_primary_pair
from packages.story_core.runtime import record_agent_runtime


def _character_candidates(
    proposals: list[CharacterProposal],
    policy: NewCharacterPolicy,
) -> tuple[list[str], list[str], list[str]]:
    approved: list[str] = []
    deferred: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()

    for proposal in proposals:
        for candidate in proposal.new_character_candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            if policy == "Manual review":
                deferred.append(candidate)
                continue
            if policy == "Auto-approve named candidates":
                approved.append(candidate)
                continue

            # Default: director review keeps a conservative allow-list.
            if candidate == "Old Archivist":
                approved.append(candidate)
            else:
                deferred.append(candidate)

    return approved, deferred, rejected


def _string_list(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _nested_dict(value: object) -> dict:
    return value.copy() if isinstance(value, dict) else {}


def _normalize_cadence(value: object, fallback: str) -> str:
    candidate = str(value).strip()
    if candidate in {"urgent", "measured", "breathing"}:
        return candidate
    return fallback


class DirectorDecisionProvider(Protocol):
    def decide(
        self,
        story: StoryState,
        proposals: list[CharacterProposal],
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> DirectorDecision | None:
        pass


class RuleBasedDirectorDecisionProvider:
    def decide(
        self,
        story: StoryState,
        proposals: list[CharacterProposal],
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> DirectorDecision:
        action_briefs = [proposal.model_dump() for proposal in proposals]
        lead, rival = select_primary_pair(action_briefs)

        primary = conflict_summary.get("primary_conflict", {}).copy()
        secondary = conflict_summary.get("secondary_conflict", {}).copy()
        if lead:
            primary["lead"] = lead.get("name", primary.get("lead", ""))
            if rival:
                primary["opposition"] = rival.get("name", primary.get("opposition", ""))

        approved, deferred, rejected = _character_candidates(
            proposals,
            story.agent_settings.new_character_policy,
        )
        next_focus = story.chapter_summaries[-1].next_focus if story.chapter_summaries else ""
        chapter_title = build_chapter_title(
            story.current_chapter,
            conflict_summary,
            next_focus,
        )
        return DirectorDecision(
            primary_conflict=primary,
            secondary_conflict=secondary,
            event_beat=event_beat,
            cadence=cadence,
            chapter_title=chapter_title,
            approved_new_characters=approved,
            deferred_characters=deferred,
            rejected_characters=rejected,
            next_focus=next_focus,
        )


class OpenAIDirectorDecisionProvider(BaseOpenAIProvider):
    runtime_key = "director"

    def decide(
        self,
        story: StoryState,
        proposals: list[CharacterProposal],
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> DirectorDecision | None:
        settings = self._runtime_settings()
        if not settings.api_key:
            return None

        prompt = self._build_prompt(story, proposals, conflict_summary, event_beat, cadence)
        payload = {
            "model": story.agent_settings.director_model or story.agent_settings.global_model or "gpt-5.4",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the director agent for a novel engine. "
                        "Return JSON only with primary_conflict, secondary_conflict, event_beat, cadence, chapter_title, "
                        "approved_new_characters, deferred_characters, rejected_characters, and next_focus."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": float(story.agent_settings.temperature),
        }

        try:
            response = self._post_json("/chat/completions", payload, settings)
            content = response["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError, urllib.error.URLError, TimeoutError, ValueError):
            return None

        if not isinstance(parsed, dict):
            return None

        return DirectorDecision(
            primary_conflict=_nested_dict(parsed.get("primary_conflict")),
            secondary_conflict=_nested_dict(parsed.get("secondary_conflict")),
            event_beat=_nested_dict(parsed.get("event_beat")),
            cadence=_normalize_cadence(parsed.get("cadence"), cadence),
            chapter_title=str(parsed.get("chapter_title", "")).strip(),
            approved_new_characters=_string_list(parsed.get("approved_new_characters")),
            deferred_characters=_string_list(parsed.get("deferred_characters")),
            rejected_characters=_string_list(parsed.get("rejected_characters")),
            next_focus=str(parsed.get("next_focus", "")).strip(),
        )

    def _build_prompt(
        self,
        story: StoryState,
        proposals: list[CharacterProposal],
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> str:
        latest_summary = story.chapter_summaries[-1].summary if story.chapter_summaries else "No prior chapter."
        proposal_lines = []
        for proposal in proposals:
            proposal_lines.append(
                json.dumps(
                    {
                        "name": proposal.name,
                        "goal": proposal.goal,
                        "emotion": proposal.emotion,
                        "action": proposal.action,
                        "priority": proposal.priority,
                        "new_character_candidates": proposal.new_character_candidates,
                    },
                    ensure_ascii=False,
                )
            )

        return "\n".join(
            [
                f"Story outline: {story.outline}",
                f"Genre: {story.genre}",
                f"Style: {story.style}",
                f"Current chapter: {story.current_chapter}",
                f"Latest chapter summary: {latest_summary}",
                f"Suggested cadence: {cadence}",
                f"Conflict summary: {json.dumps(conflict_summary, ensure_ascii=False)}",
                f"Event beat: {json.dumps(event_beat, ensure_ascii=False)}",
                "Character proposals:",
                *proposal_lines,
                "Return a JSON object with these keys:",
                '{ "primary_conflict": {}, "secondary_conflict": {}, "event_beat": {}, "cadence": "measured", "chapter_title": "", "approved_new_characters": [], "deferred_characters": [], "rejected_characters": [], "next_focus": "" }',
            ]
        )


class DirectorAgent:
    def __init__(
        self,
        llm_provider: DirectorDecisionProvider | None = None,
        rule_provider: RuleBasedDirectorDecisionProvider | None = None,
    ) -> None:
        self.rule_provider = rule_provider or RuleBasedDirectorDecisionProvider()
        self.llm_provider = llm_provider or OpenAIDirectorDecisionProvider()

    def decide(
        self,
        story: StoryState,
        proposals: list[CharacterProposal],
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> DirectorDecision:
        if story.agent_settings.mode == "LLM-assisted":
            llm_decision = self.llm_provider.decide(
                story,
                proposals,
                conflict_summary,
                event_beat,
                cadence,
            )
            if llm_decision is not None:
                record_agent_runtime(
                    story,
                    "DirectorAgent",
                    story.agent_settings.mode,
                    "llm",
                    story.current_chapter,
                )
                return llm_decision
            fallback_reason = "LLM 生成没有可用裁决"
            if hasattr(self.llm_provider, "available") and not self.llm_provider.available():
                fallback_reason = "未配置 OPENAI_API_KEY"
            record_agent_runtime(
                story,
                "DirectorAgent",
                story.agent_settings.mode,
                "fallback",
                story.current_chapter,
                fallback_reason,
            )
        else:
            record_agent_runtime(
                story,
                "DirectorAgent",
                story.agent_settings.mode,
                "rule-based",
                story.current_chapter,
            )
        return self.rule_provider.decide(
            story,
            proposals,
            conflict_summary,
            event_beat,
            cadence,
        )
