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
from packages.story_core.models import DirectorDecision, StoryState, default_model_name
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
            "model": story.agent_settings.writer_model or story.agent_settings.global_model or default_model_name(),
            "messages": [
                {
                    "role": "system",
                    "content": "你是中文网文写作助手。只返回 JSON，结构为 {\"body\": \"...\"}。",
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
                self._set_last_error("写作模型返回结果不是标准 JSON")
                return None
            self._clear_last_error()
        except urllib.error.HTTPError as exc:
            self._set_last_error(f"写作调用 HTTP {exc.code}")
            return None
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            self._set_last_error(f"写作调用失败：{exc}")
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
            story.chapter_summaries[-1].summary if story.chapter_summaries else "暂无上章梗概",
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
                f"网文大纲：{compact_text(story.outline, 260)}",
                f"题材：{story.genre}",
                f"文体：{story.style}",
                f"当前章节：第 {chapter_number} 章",
                f"上一章梗概：{latest_summary}",
                f"作者约束：{json.dumps(compact_list(story.author_constraints, max_items=4, item_chars=70), ensure_ascii=False)}",
                f"章节目标：{json.dumps(compact_decision, ensure_ascii=False)}",
                f"核心冲突：{json.dumps(compact_conflict, ensure_ascii=False)}",
                f"章节事实：{json.dumps(compact_event, ensure_ascii=False)}",
                f"计划动作：{json.dumps(compact_event_plan, ensure_ascii=False)}",
                f"保留约束：{json.dumps(compact_memory, ensure_ascii=False)}",
                f"节奏设定：{cadence}",
                "输出要求：只写中文正文，不引入未给定事实。",
                "先写动作与反馈，再接对白与选择；对白要完整对话，不做规则清单式汇报。",
                "优先突出每一步的现场选择和结果链，避免“先分析后总结”式说明。",
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
            try:
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
            except TypeError:
                # Backward compatibility for older test/user providers that
                # predate event_plan and memory_constraints.
                llm_body = self.llm_provider.write(
                    story,
                    chapter_number,
                    decision,
                    conflict_summary,
                    event_beat,
                    cadence,
                )
            if llm_body:
                return llm_body

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
