from __future__ import annotations

import json
import urllib.error
from typing import Protocol

from packages.story_core.agent_base import (
    BaseOpenAIProvider,
    compact_list,
    compact_text,
    parse_json_message_content,
)
from packages.story_core.memory import apply_post_chapter_updates
from packages.story_core.models import DirectorDecision, StoryState
from packages.story_core.runtime import record_agent_runtime


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
            "model": story.agent_settings.memory_model or story.agent_settings.global_model or "gpt-5.4",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the memory agent for an evolving Chinese novel project. "
                        "Return JSON only with summary, facts, unresolved_threads, next_focus, chapter_title, "
                        "timeline_summary, timeline_impact, foreshadowing, and character_memory_notes."
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
        latest_summary = compact_text(
            story.chapter_summaries[-1].summary if story.chapter_summaries else "No prior chapter.",
            220,
        )
        compact_decision = {
            "chapter_title": compact_text(decision.chapter_title, 40),
            "next_focus": compact_text(decision.next_focus, 120),
            "primary_conflict": decision.primary_conflict,
            "secondary_conflict": decision.secondary_conflict,
        }
        compact_conflict = {
            "summary": compact_text(str(conflict_summary.get("summary", "")), 140),
            "stakes": compact_text(str(conflict_summary.get("stakes", "")), 120),
        }
        compact_event = {
            "turn": compact_text(str(event_beat.get("turn", "")), 80),
            "pivot": compact_text(str(event_beat.get("pivot", "")), 100),
            "closing": compact_text(str(event_beat.get("closing", "")), 80),
        }
        return "\n".join(
            [
                f"Story outline: {compact_text(story.outline, 480)}",
                f"Genre: {story.genre}",
                f"Style: {story.style}",
                f"Author constraints: {json.dumps(compact_list(story.author_constraints, max_items=4, item_chars=70), ensure_ascii=False)}",
                f"Current chapter: {chapter_number}",
                f"Latest chapter summary: {latest_summary}",
                f"Chapter body: {compact_text(body, 1200)}",
                f"Director decision: {json.dumps(compact_decision, ensure_ascii=False)}",
                f"Conflict summary: {json.dumps(compact_conflict, ensure_ascii=False)}",
                f"Event beat: {json.dumps(compact_event, ensure_ascii=False)}",
                f"Cadence: {cadence}",
                "Keep only durable story memory: facts that should matter next chapter, unresolved threads, and explicit timeline impact.",
                "Return a JSON object with summary, facts, unresolved_threads, next_focus, chapter_title, timeline_summary, timeline_impact, foreshadowing, and character_memory_notes.",
            ]
        )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _string_text(value: object) -> str:
    return str(value).strip() if value is not None else ""


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
        apply_post_chapter_updates(
            story,
            body,
            chapter_number,
            conflict_summary=conflict_summary,
            event_beat=event_beat,
        )
        story.chapter_summaries[-1].cadence = cadence
        if decision.chapter_title:
            story.chapter_summaries[-1].chapter_title = decision.chapter_title

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
                record_agent_runtime(
                    story,
                    "MemoryAgent",
                    story.agent_settings.mode,
                    "llm",
                    story.current_chapter,
                )
                summary = _string_text(analysis.get("summary"))
                if summary:
                    story.chapter_summaries[-1].summary = summary

                facts = _string_list(analysis.get("facts"))
                if facts:
                    story.chapter_summaries[-1].facts = facts

                unresolved_threads = _string_list(analysis.get("unresolved_threads"))
                if unresolved_threads:
                    story.chapter_summaries[-1].unresolved_threads = unresolved_threads

                next_focus = _string_text(analysis.get("next_focus"))
                if next_focus:
                    story.chapter_summaries[-1].next_focus = next_focus

                chapter_title = _string_text(analysis.get("chapter_title"))
                if chapter_title:
                    story.chapter_summaries[-1].chapter_title = chapter_title

                timeline_summary = _string_text(analysis.get("timeline_summary"))
                timeline_impact = _string_text(analysis.get("timeline_impact"))
                if timeline_summary or timeline_impact:
                    story.timeline[-1].summary = timeline_summary or story.timeline[-1].summary
                    story.timeline[-1].impact = timeline_impact or story.timeline[-1].impact

                foreshadowing = analysis.get("foreshadowing")
                if isinstance(foreshadowing, list) and foreshadowing:
                    first = foreshadowing[0]
                    if isinstance(first, dict):
                        text = _string_text(first.get("text"))
                        status = _string_text(first.get("status"))
                        if text:
                            story.foreshadowing[0].text = text
                        if status:
                            story.foreshadowing[0].status = status  # type: ignore[assignment]

                notes = analysis.get("character_memory_notes")
                if isinstance(notes, list):
                    by_name = {character.name: character for character in story.characters}
                    for note in notes:
                        if not isinstance(note, dict):
                            continue
                        name = _string_text(note.get("name"))
                        memory = _string_text(note.get("memory"))
                        if name and memory and name in by_name:
                            by_name[name].memory.append(memory)
            else:
                fallback_reason = "LLM did not return a usable memory summary"
                if hasattr(self.llm_provider, "last_error_reason"):
                    fallback_reason = self.llm_provider.last_error_reason() or fallback_reason
                if hasattr(self.llm_provider, "available") and not self.llm_provider.available():
                    fallback_reason = "Missing OPENAI_API_KEY"
                record_agent_runtime(
                    story,
                    "MemoryAgent",
                    story.agent_settings.mode,
                    "fallback",
                    story.current_chapter,
                    fallback_reason,
                )

        return story
