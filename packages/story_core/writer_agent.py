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
        event_plan: dict | None = None,
        memory_constraints: dict | None = None,
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
        event_plan: dict | None = None,
        memory_constraints: dict | None = None,
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
                        "只返回 JSON，并且只能包含一个 body 字段。"
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
                        event_plan,
                        memory_constraints,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": float(story.agent_settings.temperature),
            "max_tokens": 1800,
        }

        try:
            response = self._post_json("/chat/completions", payload, settings)
            parsed = parse_json_message_content(response)
            if parsed is None:
                self._set_last_error("写作代理返回的内容不是有效 JSON")
                return None
            self._clear_last_error()
        except urllib.error.HTTPError as exc:
            self._set_last_error(f"写作代理 HTTP {exc.code}")
            return None
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            self._set_last_error(f"写作代理请求失败：{exc}")
            return None

        body = compact_text(str(parsed.get("body", "")).strip(), 8000)
        return body or None

    def _build_prompt(
        self,
        story: StoryState,
        chapter_number: int,
        decision: DirectorDecision,
        conflict_summary: dict,
        event_beat: dict,
        cadence: str,
        event_plan: dict | None,
        memory_constraints: dict | None,
    ) -> str:
        latest_summary = compact_text(
            story.chapter_summaries[-1].summary if story.chapter_summaries else "暂无上一章摘要。",
            220,
        )
        compact_decision = {
            "chapter_title": compact_text(decision.chapter_title, 40),
            "next_focus": compact_text(decision.next_focus, 120),
            "primary_conflict": decision.primary_conflict,
            "secondary_conflict": decision.secondary_conflict,
        }
        compact_event_plan = {
            "turn": compact_text(str((event_plan or {}).get("turn", "")), 70),
            "pivot": compact_text(str((event_plan or {}).get("pivot", "")), 100),
            "collision": compact_text(str((event_plan or {}).get("collision", "")), 100),
            "stakes": compact_text(str((event_plan or {}).get("stakes", "")), 100),
            "next_focus": compact_text(str((event_plan or {}).get("next_focus", "")), 120),
            "ordered_actions": (event_plan or {}).get("ordered_actions", [])[:3],
        }
        compact_memory = {
            "must_keep_facts": compact_list((memory_constraints or {}).get("must_keep_facts", []), max_items=3, item_chars=70),
            "unresolved_threads": compact_list((memory_constraints or {}).get("unresolved_threads", []), max_items=3, item_chars=70),
            "protected_foreshadowing": (memory_constraints or {}).get("protected_foreshadowing", [])[:2],
            "author_constraints": compact_list((memory_constraints or {}).get("author_constraints", []), max_items=4, item_chars=70),
        }
        compact_conflict = {
            "summary": compact_text(str(conflict_summary.get("summary", "")), 140),
            "stakes": compact_text(str(conflict_summary.get("stakes", "")), 120),
        }
        compact_event = {
            "turn": compact_text(str(event_beat.get("turn", "")), 70),
            "pivot": compact_text(str(event_beat.get("pivot", "")), 90),
            "closing": compact_text(str(event_beat.get("closing", "")), 70),
        }

        return "\n".join(
            [
                f"小说大纲：{compact_text(story.outline, 520)}",
                f"题材：{story.genre}",
                f"风格：{story.style}",
                f"当前章节：第 {chapter_number} 章",
                f"上一章摘要：{latest_summary}",
                f"作者约束：{json.dumps(compact_list(story.author_constraints, max_items=4, item_chars=70), ensure_ascii=False)}",
                f"导演裁决：{json.dumps(compact_decision, ensure_ascii=False)}",
                f"冲突摘要：{json.dumps(compact_conflict, ensure_ascii=False)}",
                f"事件节拍：{json.dumps(compact_event, ensure_ascii=False)}",
                f"事件计划：{json.dumps(compact_event_plan, ensure_ascii=False)}",
                f"记忆约束：{json.dumps(compact_memory, ensure_ascii=False)}",
                f"节奏：{cadence}",
                "要求：",
                "1. 必须写成中文小说正文，不要输出解释、提示词或模板标签。",
                "2. 先遵守事件计划，再组织场景，不要跳过关键碰撞。",
                "3. 记忆约束里的事实、悬念和伏笔必须自然继承。",
                "4. 作者约束是硬边界，不要用巧合、天降答案、突然升级来偷懒。",
                "5. 这是一章小说，不是一份总结。要有场景、动作、对话或心理推进。",
                "6. 结尾要留下下一章的压力或钩子。",
                '只返回 JSON，对象里包含 body 字段，body 是完整章节正文。',
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
        event_plan: dict | None = None,
        memory_constraints: dict | None = None,
    ) -> str:
        if story.agent_settings.mode == "LLM-assisted":
            llm_body = self.llm_provider.write(
                story,
                chapter_number,
                decision,
                conflict_summary,
                event_beat,
                cadence,
                event_plan,
                memory_constraints,
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

            fallback_reason = "LLM did not return usable chapter text"
            if hasattr(self.llm_provider, "last_error_reason"):
                fallback_reason = self.llm_provider.last_error_reason() or fallback_reason
            if hasattr(self.llm_provider, "available") and not self.llm_provider.available():
                fallback_reason = "Missing OPENAI_API_KEY"
            record_agent_runtime(
                story,
                "WriterAgent",
                story.agent_settings.mode,
                "fallback",
                story.current_chapter,
                fallback_reason,
            )

        return write_chapter_body(
            story,
            chapter_number,
            conflict_summary=conflict_summary,
            event_beat=event_beat,
            cadence=cadence,
            chapter_title_override=decision.chapter_title or None,
            event_plan=event_plan,
            memory_constraints=memory_constraints,
        )
