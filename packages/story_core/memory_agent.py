from __future__ import annotations

import urllib.error
from typing import Protocol

from packages.story_core.agent_base import (
    BaseOpenAIProvider,
    compact_text,
    parse_json_message_content,
)
from packages.story_core.attribute_evidence import (
    character_evidence_names,
    character_update_names,
    protagonist_aliases_from_characters,
)
from packages.story_core.memory import apply_post_chapter_updates
from packages.story_core.models import DirectorDecision, StoryState, default_model_name
from packages.story_core.post_draft_memory import (
    build_post_draft_memory_prompt,
    fallback_post_draft_memory,
    normalize_post_draft_memory,
)


class MemorySummaryProvider(Protocol):
    def summarize(
        self,
        story: StoryState,
        body: str,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> dict | None:
        pass


class OpenAIMemorySummaryProvider(BaseOpenAIProvider):
    runtime_key = "memory"

    def summarize(
        self,
        story: StoryState,
        body: str,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> dict | None:
        settings = self._runtime_settings()
        if not settings.api_key:
            return None

        payload = {
            "model": story.agent_settings.memory_model or story.agent_settings.global_model or default_model_name(),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the memory agent for an evolving Chinese novel project. "
                        "Return JSON only. Every fact, unresolved thread, character update and ledger leaf "
                        "must include literal evidence from the final chapter body."
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_prompt(
                        story,
                        body,
                        chapter_number,
                        decision,
                        conflict_summary,
                        event_beat,
                        cadence,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": float(story.agent_settings.temperature),
            "max_tokens": 900,
        }

        try:
            response = self._post_json("/chat/completions", payload, settings)
            parsed = parse_json_message_content(response)
            if parsed is None:
                self._set_last_error("记忆代理返回的内容不是有效 JSON")
                return None
            self._clear_last_error()
            return parsed
        except urllib.error.HTTPError as exc:
            self._set_last_error(f"记忆代理 HTTP {exc.code}")
            return None
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            self._set_last_error(f"记忆代理请求失败：{exc}")
            return None

    def _build_prompt(
        self,
        story: StoryState,
        body: str,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> str:
        return build_post_draft_memory_prompt(
            body,
            previous_summary=(story.chapter_summaries[-1].summary if story.chapter_summaries else ""),
            existing_character_names=character_update_names(story.characters),
            genre=story.genre,
            fact_locks={
                "chapter_number": chapter_number,
                "director_decision": {
                    "chapter_title": compact_text(decision.chapter_title, 40),
                    "next_focus": compact_text(decision.next_focus, 120),
                },
                "conflict": compact_text(str(conflict_summary.get("summary", "")), 140),
                "event": compact_text(str(event_beat.get("turn", "")), 100),
                "cadence": cadence,
            },
        )


class MemoryAgent:
    def __init__(self, llm_provider: MemorySummaryProvider | None = None) -> None:
        self.llm_provider = llm_provider or OpenAIMemorySummaryProvider()

    def remember(
        self,
        story: StoryState,
        body: str,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> StoryState:
        memory = None
        if story.agent_settings.mode == "LLM-assisted":
            analysis = self.llm_provider.summarize(
                story,
                body,
                chapter_number,
                decision,
                conflict_summary,
                event_beat,
                cadence,
            )
            if analysis:
                memory = normalize_post_draft_memory(
                    analysis,
                    body=body,
                    existing_character_names=character_update_names(story.characters),
                    evidence_character_names=character_evidence_names(story.characters),
                    protagonist_aliases=protagonist_aliases_from_characters(story.characters),
                )

        if memory is None:
            memory = fallback_post_draft_memory(body)
        apply_post_chapter_updates(
            story,
            body,
            chapter_number,
            conflict_summary={},
            event_beat={},
            post_draft_memory=memory,
        )
        story.chapter_summaries[-1].cadence = cadence

        return story
