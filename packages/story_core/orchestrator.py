from __future__ import annotations

import json
import urllib.error

from packages.story_core.agent_base import compact_list, compact_text, parse_json_message_content
from packages.story_core.http_retry import post_json_with_retry
from packages.story_core.memory import apply_post_chapter_updates, build_character_cards, build_foreshadowing
from packages.story_core.models import DirectorDecision, StoryState, TimelineEvent
from packages.story_core.planner import build_conflict_summary, build_event_beat, compute_chapter_cadence, plan_next_outline
from packages.story_core.quality import validate_bundle
from packages.story_core.runtime import record_agent_runtime
from packages.story_core.runtime_config import resolve_openai_runtime_settings


def _extract_text_message(response: dict) -> str:
    try:
        message = response["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    content = message.get("content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("text"):
                parts.append(str(block["text"]))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts).strip()
    if isinstance(content, dict):
        return str(content.get("text", "")).strip()
    return str(content).strip()


def _story_snapshot(story: StoryState) -> dict:
    latest = story.chapter_summaries[-1] if story.chapter_summaries else None
    return {
        "outline": compact_text(story.outline, 700),
        "genre": story.genre,
        "style": story.style,
        "current_chapter": story.current_chapter,
        "author_constraints": compact_list(story.author_constraints, max_items=5, item_chars=80),
        "latest_summary": compact_text(latest.summary if latest else "", 200),
        "latest_facts": compact_list(latest.facts if latest else [], max_items=3, item_chars=70),
        "latest_threads": compact_list(latest.unresolved_threads if latest else [], max_items=3, item_chars=70),
        "current_focus": compact_text(latest.next_focus if latest else "", 120),
        "characters": [
            {
                "name": c.name,
                "role": c.role,
                "goal": compact_text(c.goals[0] if c.goals else "", 70),
                "emotion": c.current_emotion,
                "location": compact_text(c.location, 20),
            }
            for c in story.characters[:6]
            if c.lifecycle_state == "active" and not c.frozen
        ],
    }


def _normalize_moves(raw_moves: object) -> list[dict]:
    moves: list[dict] = []
    if not isinstance(raw_moves, list):
        return moves
    for item in raw_moves[:6]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        moves.append(
            {
                "name": name,
                "goal": compact_text(str(item.get("goal", "")).strip() or "推进当前主线", 80),
                "emotion": str(item.get("emotion", "")).strip() or "alert",
                "action": compact_text(str(item.get("action", "")).strip() or "继续推进当前主线", 100),
                "priority": int(item.get("priority", 0) or 0),
            }
        )
    return moves


def _normalize_intent(raw_intent: object) -> dict:
    if not isinstance(raw_intent, dict):
        return {}
    return {
        "chapter_title": compact_text(str(raw_intent.get("chapter_title", "")).strip(), 40),
        "cadence": str(raw_intent.get("cadence", "")).strip() or "measured",
        "next_focus": compact_text(str(raw_intent.get("next_focus", "")).strip(), 120),
        "primary_conflict": raw_intent.get("primary_conflict", {}) if isinstance(raw_intent.get("primary_conflict"), dict) else {},
        "secondary_conflict": raw_intent.get("secondary_conflict", {}) if isinstance(raw_intent.get("secondary_conflict"), dict) else {},
    }


def _normalize_event_plan(raw_event_plan: object, chapter_number: int, story: StoryState) -> dict:
    if not isinstance(raw_event_plan, dict):
        return {}
    return {
        "chapter_number": chapter_number,
        "chapter_title": compact_text(str(raw_event_plan.get("chapter_title", "")).strip(), 40),
        "turn": compact_text(str(raw_event_plan.get("turn", "")).strip(), 80),
        "pivot": compact_text(str(raw_event_plan.get("pivot", "")).strip(), 120),
        "collision": compact_text(str(raw_event_plan.get("collision", "")).strip(), 120),
        "ordered_actions": _normalize_moves(raw_event_plan.get("ordered_actions")),
        "stakes": compact_text(str(raw_event_plan.get("stakes", "")).strip(), 100),
        "next_focus": compact_text(str(raw_event_plan.get("next_focus", "")).strip(), 120),
        "author_constraints": list(story.author_constraints),
    }


def _normalize_memory_constraints(raw_memory: object, story: StoryState) -> dict:
    if not isinstance(raw_memory, dict):
        return {
            "must_keep_facts": [],
            "unresolved_threads": [],
            "protected_characters": [],
            "protected_foreshadowing": [],
            "author_constraints": list(story.author_constraints),
            "current_focus": "",
            "conflict_anchor": "",
            "event_guardrail": "",
        }
    return {
        "must_keep_facts": compact_list(raw_memory.get("must_keep_facts", []), max_items=4, item_chars=70),
        "unresolved_threads": compact_list(raw_memory.get("unresolved_threads", []), max_items=4, item_chars=70),
        "protected_characters": [str(v).strip() for v in raw_memory.get("protected_characters", []) if str(v).strip()][:4],
        "protected_foreshadowing": raw_memory.get("protected_foreshadowing", [])[:3] if isinstance(raw_memory.get("protected_foreshadowing"), list) else [],
        "author_constraints": compact_list(raw_memory.get("author_constraints", []), max_items=5, item_chars=80)
        or list(story.author_constraints),
        "current_focus": compact_text(str(raw_memory.get("current_focus", "")).strip(), 120),
        "conflict_anchor": compact_text(str(raw_memory.get("conflict_anchor", "")).strip(), 120),
        "event_guardrail": compact_text(str(raw_memory.get("event_guardrail", "")).strip(), 120),
    }


def _normalize_chapter_summary(raw_summary: object, chapter_number: int) -> dict:
    if not isinstance(raw_summary, dict):
        return {
            "chapter_number": chapter_number,
            "summary": "",
            "facts": [],
            "unresolved_threads": [],
            "next_focus": "",
            "chapter_title": "",
        }
    return {
        "chapter_number": chapter_number,
        "summary": compact_text(str(raw_summary.get("summary", "")).strip(), 220),
        "facts": compact_list(raw_summary.get("facts", []), max_items=4, item_chars=70),
        "unresolved_threads": compact_list(raw_summary.get("unresolved_threads", []), max_items=4, item_chars=70),
        "next_focus": compact_text(str(raw_summary.get("next_focus", "")).strip(), 120),
        "chapter_title": compact_text(str(raw_summary.get("chapter_title", "")).strip(), 40),
    }


def _record_success(story: StoryState) -> None:
    for agent_name in ("CharacterAgent", "DirectorAgent", "WriterAgent", "MemoryAgent"):
        record_agent_runtime(story, agent_name, story.agent_settings.mode, "llm", story.current_chapter)


def _record_failure(story: StoryState, reason: str, chapter_number: int) -> None:
    for agent_name in ("CharacterAgent", "DirectorAgent", "WriterAgent", "MemoryAgent"):
        record_agent_runtime(story, agent_name, story.agent_settings.mode, "fallback", chapter_number, reason)


def _build_simulation_status(story: StoryState) -> dict:
    agent_entries = {
        "character": story.agent_runtime.character_agent.model_dump(),
        "director": story.agent_runtime.director_agent.model_dump(),
        "writer": story.agent_runtime.writer_agent.model_dump(),
        "memory": story.agent_runtime.memory_agent.model_dump(),
    }
    fallback_agents = [name for name, entry in agent_entries.items() if entry.get("source") == "fallback"]
    return {
        "ok": not fallback_agents,
        "mode": "full" if not fallback_agents else "degraded",
        "fallback_agents": fallback_agents,
        "recent_events": list(story.agent_runtime.recent_events),
        "agents": agent_entries,
    }


def _failed_bundle(story: StoryState, chapter_number: int):
    from packages.story_core.engine import ChapterBundle

    bundle = ChapterBundle(
        chapter_number=chapter_number,
        body="",
        chapter_title="",
        cadence="measured",
        chapter_intent={},
        character_moves=[],
        memory_constraints={},
        event_plan={},
        simulation_status=_build_simulation_status(story),
        action_briefs=[],
        conflict_summary={},
        event_beat={},
        character_cards=build_character_cards(story),
        foreshadowing=build_foreshadowing(story, chapter_number),
        next_outline="",
        updated_story=story,
        chapter_summary={},
    )
    bundle.quality_report = validate_bundle(bundle.model_dump())
    return bundle


class StoryOrchestrator:
    def _chat(self, story: StoryState, prompt: str, *, max_tokens: int, json_mode: bool) -> tuple[str, str]:
        settings = resolve_openai_runtime_settings("director")
        if not settings.api_key:
            return "", "Missing OPENAI_API_KEY"

        payload = {
            "model": story.agent_settings.global_model or story.agent_settings.director_model or "gpt-5.4",
            "messages": [
                {"role": "system", "content": "You are a novel simulation engine."},
                {"role": "user", "content": prompt},
            ],
            "temperature": float(story.agent_settings.temperature),
            "max_tokens": max_tokens,
            "parameters": {
                "enable_thinking": False,
                "thinking_budget": 64,
            },
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            response = post_json_with_retry(settings.base_url, "/chat/completions", payload, settings.api_key)
            if json_mode:
                parsed = parse_json_message_content(response)
                if parsed is None:
                    return "", "计划返回内容不是有效 JSON"
                return json.dumps(parsed, ensure_ascii=False), ""
            text = _extract_text_message(response)
            return text, "" if text else "正文返回为空"
        except urllib.error.HTTPError as exc:
            return "", f"模型 HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            return "", f"模型请求失败：{exc}"

    def _plan_prompt(self, story: StoryState, chapter_number: int) -> str:
        snapshot = _story_snapshot(story)
        return "\n".join(
            [
                "请为中文小说项目生成本章推演计划，只返回 JSON。",
                f"目标章节：第{chapter_number}章",
                f"项目快照：{json.dumps(snapshot, ensure_ascii=False)}",
                "输出字段：character_moves, chapter_intent, event_plan, memory_constraints, chapter_summary。",
                "要求：动作具体，焦点明确，事件链简短但有效，不要写正文。",
            ]
        )

    def _body_prompt(self, story: StoryState, chapter_number: int, plan: dict) -> str:
        return "\n".join(
            [
                "根据下面的推演计划，写出一章中文小说正文。",
                f"题材：{story.genre}",
                f"风格：{story.style}",
                f"第{chapter_number}章计划：{json.dumps(plan, ensure_ascii=False)}",
                "要求：600到900字；有场景、有动作、有心理推进；结尾留下下一章压力；不要输出 JSON。",
            ]
        )

    def generate_next_chapter(self, story: StoryState):
        from packages.story_core.engine import ChapterBundle

        chapter_number = story.current_chapter + 1
        working_story = story.model_copy(deep=True)
        working_story.current_chapter = chapter_number

        plan_text, plan_error = self._chat(working_story, self._plan_prompt(working_story, chapter_number), max_tokens=700, json_mode=True)
        if plan_error:
            _record_failure(working_story, f"统一推演计划失败：{plan_error}", chapter_number)
            return _failed_bundle(working_story, chapter_number)

        plan = json.loads(plan_text)
        action_briefs = _normalize_moves(plan.get("character_moves"))
        chapter_intent = _normalize_intent(plan.get("chapter_intent"))
        event_plan = _normalize_event_plan(plan.get("event_plan"), chapter_number, working_story)
        memory_constraints = _normalize_memory_constraints(plan.get("memory_constraints"), working_story)
        chapter_summary_data = _normalize_chapter_summary(plan.get("chapter_summary"), chapter_number)

        conflict_summary = build_conflict_summary(working_story, action_briefs)
        cadence = chapter_intent.get("cadence") or compute_chapter_cadence(working_story, action_briefs, conflict_summary)
        event_beat = build_event_beat(conflict_summary)

        body, body_error = self._chat(
            working_story,
            self._body_prompt(
                working_story,
                chapter_number,
                {
                    "character_moves": action_briefs,
                    "chapter_intent": chapter_intent,
                    "event_plan": event_plan,
                    "memory_constraints": memory_constraints,
                },
            ),
            max_tokens=1000,
            json_mode=False,
        )
        if body_error or not body.strip():
            _record_failure(working_story, f"统一写作失败：{body_error or '正文为空'}", chapter_number)
            return _failed_bundle(working_story, chapter_number)

        decision = DirectorDecision(
            primary_conflict=chapter_intent.get("primary_conflict", {}) or conflict_summary.get("primary_conflict", {}),
            secondary_conflict=chapter_intent.get("secondary_conflict", {}) or conflict_summary.get("secondary_conflict", {}),
            event_beat=event_beat,
            cadence=cadence,  # type: ignore[arg-type]
            chapter_title=chapter_intent.get("chapter_title", "") or chapter_summary_data.get("chapter_title", ""),
            next_focus=chapter_intent.get("next_focus", "") or chapter_summary_data.get("next_focus", ""),
        )

        updated_story = working_story.model_copy(deep=True)
        apply_post_chapter_updates(
            updated_story,
            body,
            chapter_number,
            conflict_summary=conflict_summary,
            event_beat=event_beat,
        )

        latest_summary = updated_story.chapter_summaries[-1]
        latest_summary.summary = chapter_summary_data.get("summary") or compact_text(body, 220)
        latest_summary.facts = chapter_summary_data.get("facts") or latest_summary.facts
        latest_summary.unresolved_threads = chapter_summary_data.get("unresolved_threads") or latest_summary.unresolved_threads
        latest_summary.next_focus = chapter_summary_data.get("next_focus") or decision.next_focus or latest_summary.next_focus
        latest_summary.chapter_title = chapter_summary_data.get("chapter_title") or decision.chapter_title or latest_summary.chapter_title
        latest_summary.primary_conflict = decision.primary_conflict
        latest_summary.secondary_conflict = decision.secondary_conflict
        latest_summary.event_beat = event_beat

        if updated_story.timeline:
            updated_story.timeline[-1] = TimelineEvent(
                chapter_number=chapter_number,
                summary=compact_text(chapter_summary_data.get("summary") or latest_summary.summary, 160),
                impact=compact_text(event_plan.get("stakes", "") or "本章推动了主线局势。", 160),
            )

        for move in action_briefs:
            for character in updated_story.characters:
                if character.name == move["name"]:
                    character.current_emotion = move.get("emotion", character.current_emotion)
                    if move.get("goal"):
                        character.goals = [move["goal"], *[goal for goal in character.goals if goal != move["goal"]]]
                    break

        _record_success(updated_story)

        bundle_conflict_summary = {
            **conflict_summary,
        }

        bundle = ChapterBundle(
            chapter_number=chapter_number,
            body=body,
            chapter_title=latest_summary.chapter_title,
            cadence=cadence,
            chapter_intent={
                "chapter_title": latest_summary.chapter_title,
                "cadence": cadence,
                "next_focus": latest_summary.next_focus,
                "primary_conflict": decision.primary_conflict,
                "secondary_conflict": decision.secondary_conflict,
                "approved_new_characters": [],
                "deferred_characters": [],
                "rejected_characters": [],
            },
            character_moves=action_briefs,
            memory_constraints=memory_constraints,
            event_plan=event_plan,
            simulation_status=_build_simulation_status(updated_story),
            action_briefs=action_briefs,
            conflict_summary=bundle_conflict_summary,
            event_beat=event_beat,
            character_cards=build_character_cards(updated_story),
            foreshadowing=build_foreshadowing(updated_story, chapter_number),
            next_outline=plan_next_outline(
                updated_story,
                chapter_number,
                conflict_summary=conflict_summary,
                cadence=cadence,
            ),
            updated_story=updated_story,
            chapter_summary=latest_summary.model_dump(),
        )
        bundle.quality_report = validate_bundle(bundle.model_dump())
        return bundle
