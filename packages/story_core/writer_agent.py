from __future__ import annotations

import json
import urllib.error
from typing import Protocol

from packages.story_core.agent_base import BaseOpenAIProvider
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


class OpenAIWriterTextProvider(BaseOpenAIProvider):
    runtime_key = "writer"

    def write(
        self,
        story: StoryState,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
    ) -> str | None:
        settings = self._runtime_settings()
        if not settings.api_key:
            return None

        payload = {
            "model": story.agent_settings.writer_model or story.agent_settings.global_model or "gpt-5.4",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是小说自动演化引擎的写作代理。"
                        "请输出自然、连贯、带悬念的中文章节正文。"
                        "只返回 JSON，且只能包含一个 body 字段。"
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
            response = self._post_json("/chat/completions", payload, settings)
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
        latest_summary = story.chapter_summaries[-1].summary if story.chapter_summaries else "暂无上一章摘要。"
        return "\n".join(
            [
                f"小说大纲：{story.outline}",
                f"题材：{story.genre}",
                f"风格：{story.style}",
                f"当前章节：第 {chapter_number} 章",
                f"上一章摘要：{latest_summary}",
                f"导演裁决：{json.dumps(decision.model_dump(), ensure_ascii=False)}",
                f"冲突摘要：{json.dumps(conflict_summary, ensure_ascii=False)}",
                f"事件节拍：{json.dumps(event_beat, ensure_ascii=False)}",
                f"节奏：{cadence}",
                "要求：",
                "1. 必须写成中文小说正文，不要英文模板。",
                "2. 不要解释系统设定，不要输出 JSON 以外的文字。",
                "3. 章节要有场景推进、人物动作和结尾钩子。",
                "只返回 JSON，对象里包含 body 字段，body 是完整章节正文。",
            ]
        )


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
            fallback_reason = "LLM 没有返回可用正文"
            if hasattr(self.llm_provider, "available") and not self.llm_provider.available():
                fallback_reason = "未配置 API 密钥"
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
            chapter_title_override=decision.chapter_title or None,
        )
