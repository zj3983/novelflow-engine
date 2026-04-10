from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol

from packages.story_core.memory import apply_post_chapter_updates
from packages.story_core.models import DirectorDecision, StoryState


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


class OpenAIMemorySummaryProvider:
    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")

    def available(self) -> bool:
        return bool(self.api_key)

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
        if not self.available():
            return None

        payload = {
            "model": story.agent_settings.writer_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the memory agent for a novel engine. "
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
        }

        try:
            response = self._post_json("/chat/completions", payload)
            content = response["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError, urllib.error.URLError, TimeoutError, ValueError):
            return None

        return parsed if isinstance(parsed, dict) else None

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
        latest_summary = story.chapter_summaries[-1].summary if story.chapter_summaries else "No prior chapter."
        return "\n".join(
            [
                f"Story outline: {story.outline}",
                f"Genre: {story.genre}",
                f"Style: {story.style}",
                f"Current chapter: {chapter_number}",
                f"Latest chapter summary: {latest_summary}",
                f"Chapter body: {body}",
                f"Director decision: {json.dumps(decision.model_dump(), ensure_ascii=False)}",
                f"Conflict summary: {json.dumps(conflict_summary, ensure_ascii=False)}",
                f"Event beat: {json.dumps(event_beat, ensure_ascii=False)}",
                f"Cadence: {cadence}",
                "Return a JSON object with summary, facts, unresolved_threads, next_focus, chapter_title, timeline_summary, timeline_impact, foreshadowing, and character_memory_notes.",
            ]
        )

    def _post_json(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))


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

        return story
