from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Protocol

from packages.story_core.models import DirectorDecision, StoryState
from packages.story_core.runtime import record_agent_runtime
from packages.story_core.writer import write_chapter_body


class WriterTextProvider(Protocol):
    def write(
        self,
        story: StoryState,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> str | None:
        pass


class OpenAIWriterTextProvider:
    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")

    def available(self) -> bool:
        return bool(self.api_key)

    def write(
        self,
        story: StoryState,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> str | None:
        if not self.available():
            return None

        payload = {
            "model": story.agent_settings.writer_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the writer agent for a novel engine. "
                        "Return JSON only with a single body field containing the chapter prose."
                    ),
                },
                {
                    "role": "user",
                    "content": self._build_prompt(
                        story,
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

        if not isinstance(parsed, dict):
            return None

        body = str(parsed.get("body", "")).strip()
        return body or None

    def _build_prompt(
        self,
        story: StoryState,
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
                f"Director decision: {json.dumps(decision.model_dump(), ensure_ascii=False)}",
                f"Conflict summary: {json.dumps(conflict_summary, ensure_ascii=False)}",
                f"Event beat: {json.dumps(event_beat, ensure_ascii=False)}",
                f"Cadence: {cadence}",
                "Return a JSON object with a body field containing the full chapter prose.",
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


class WriterAgent:
    def __init__(self, llm_provider: WriterTextProvider | None = None) -> None:
        self.llm_provider = llm_provider or OpenAIWriterTextProvider()

    def write(
        self,
        story: StoryState,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> str:
        if story.agent_settings.mode == "LLM-assisted":
            llm_body = self.llm_provider.write(
                story,
                chapter_number,
                decision,
                conflict_summary,
                event_beat,
                cadence,
            )
            if llm_body:
                record_agent_runtime(
                    story,
                    "WriterAgent",
                    story.agent_settings.mode,
                    "llm",
                    story.current_chapter,
                )
                return llm_body
            fallback_reason = "LLM provider returned no usable body"
            if hasattr(self.llm_provider, "available") and not self.llm_provider.available():
                fallback_reason = "OPENAI_API_KEY missing"
            record_agent_runtime(
                story,
                "WriterAgent",
                story.agent_settings.mode,
                "fallback",
                story.current_chapter,
                fallback_reason,
            )
        else:
            record_agent_runtime(
                story,
                "WriterAgent",
                story.agent_settings.mode,
                "rule-based",
                story.current_chapter,
            )
        return write_chapter_body(
            story,
            chapter_number,
            conflict_summary=conflict_summary,
            event_beat=event_beat,
            cadence=cadence,
        )
