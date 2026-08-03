from __future__ import annotations

import json
import urllib.error
from typing import Protocol

from packages.story_core.agent_base import (
    BaseOpenAIProvider,
    _parse_json_text,
    compact_list,
    compact_text,
)
from packages.story_core.model_gateway import ModelRequest
from packages.story_core.models import CharacterProposal, DirectorDecision, NewCharacterPolicy, StoryState, default_model_name
from packages.story_core.planner import build_chapter_title, select_primary_pair


def _constraint_texts(story: StoryState) -> list[str]:
    return [item.strip() for item in story.author_constraints if item.strip()]


def _blocks_new_characters(story: StoryState) -> bool:
    return any(
        keyword in constraint.lower()
        for constraint in _constraint_texts(story)
        for keyword in ("不要引入新角色", "禁止引入新角色", "no new character", "no new characters")
    )


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
        if _blocks_new_characters(story):
            rejected.extend(approved)
            rejected.extend(deferred)
            approved = []
            deferred = []
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
        request = ModelRequest(
            prompt=self._build_prompt(story, proposals, conflict_summary, event_beat, cadence),
            system_prompt=(
                "You are the director agent for an evolving Chinese novel project. "
                "Return JSON only with primary_conflict, secondary_conflict, event_beat, cadence, chapter_title, "
                "approved_new_characters, deferred_characters, rejected_characters, and next_focus."
            ),
            provider=settings.provider,
            model=story.agent_settings.director_model or story.agent_settings.global_model or default_model_name(),
            operation="director",
            temperature=float(story.agent_settings.temperature),
            max_tokens=800,
            json_mode=True,
        )
        response = self.complete(request)
        parsed = _parse_json_text(response.text) if response.ok else None
        if parsed is None:
            if response.ok:
                self._set_last_error("导演代理返回的内容不是有效 JSON")
            return None
        self._clear_last_error()

        return DirectorDecision(
            primary_conflict=_nested_dict(parsed.get("primary_conflict")),
            secondary_conflict=_nested_dict(parsed.get("secondary_conflict")),
            event_beat=_nested_dict(parsed.get("event_beat")),
            cadence=_normalize_cadence(parsed.get("cadence"), cadence),
            chapter_title=compact_text(str(parsed.get("chapter_title", "")).strip(), 40),
            approved_new_characters=_string_list(parsed.get("approved_new_characters")),
            deferred_characters=_string_list(parsed.get("deferred_characters")),
            rejected_characters=_string_list(parsed.get("rejected_characters")),
            next_focus=compact_text(str(parsed.get("next_focus", "")).strip(), 120),
        )

    def _build_prompt(
        self,
        story: StoryState,
        proposals: list[CharacterProposal],
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> str:
        latest_summary = compact_text(
            story.chapter_summaries[-1].summary if story.chapter_summaries else "No prior chapter.",
            220,
        )
        proposal_lines = []
        for proposal in proposals[:4]:
            proposal_lines.append(
                json.dumps(
                    {
                        "name": proposal.name,
                        "goal": compact_text(proposal.goal, 60),
                        "emotion": proposal.emotion,
                        "action": compact_text(proposal.action, 90),
                        "priority": proposal.priority,
                        "new_character_candidates": proposal.new_character_candidates[:2],
                    },
                    ensure_ascii=False,
                )
            )

        compact_conflict = {
            "summary": compact_text(str(conflict_summary.get("summary", "")), 140),
            "primary_conflict": conflict_summary.get("primary_conflict", {}),
            "secondary_conflict": conflict_summary.get("secondary_conflict", {}),
            "stakes": compact_text(str(conflict_summary.get("stakes", "")), 120),
        }
        compact_event = {
            "turn": compact_text(str(event_beat.get("turn", "")), 80),
            "pivot": compact_text(str(event_beat.get("pivot", "")), 100),
            "closing": compact_text(str(event_beat.get("closing", "")), 80),
        }

        return "\n".join(
            [
                f"Story outline: {compact_text(story.outline, 520)}",
                f"Genre: {story.genre}",
                f"Style: {story.style}",
                f"Current chapter: {story.current_chapter}",
                f"Latest chapter summary: {latest_summary}",
                f"Author constraints: {json.dumps(compact_list(_constraint_texts(story), max_items=4, item_chars=70), ensure_ascii=False)}",
                f"Suggested cadence: {cadence}",
                f"Conflict summary: {json.dumps(compact_conflict, ensure_ascii=False)}",
                f"Event beat: {json.dumps(compact_event, ensure_ascii=False)}",
                "Character proposals:",
                *proposal_lines,
                "Treat author constraints as hard guardrails. Do not approve new characters if the constraints forbid them.",
                "Choose one main conflict and one secondary pressure that can naturally produce a full chapter scene.",
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
                return llm_decision
        return self.rule_provider.decide(
            story,
            proposals,
            conflict_summary,
            event_beat,
            cadence,
        )
