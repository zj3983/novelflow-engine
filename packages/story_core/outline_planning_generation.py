from __future__ import annotations

import json
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.story_core.agent_base import parse_json_message_content
from packages.story_core.http_retry import post_json_with_retry
from packages.story_core.models import AgentSettings
from packages.story_core.novel_type_catalog import NOVEL_TYPE_CATALOG
from packages.story_core.outline_planning import (
    GeneratedOutlinePlan,
    validate_generated_opening_plan,
)
from packages.story_core.runtime_config import (
    OpenAIRuntimeSettings,
    get_runtime_strategy_settings,
    resolve_openai_runtime_settings,
)


PlanningMode = Literal["initial", "regenerate", "extend"]


class _PlanningInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanningOpeningDirection(_PlanningInput):
    title: str = ""
    hook: str = Field(min_length=1, max_length=500)
    protagonist_goal: str = Field(min_length=1, max_length=500)
    main_conflict: str = Field(min_length=1, max_length=500)
    growth_path: str = Field(min_length=1, max_length=500)
    opening_promise: str = Field(min_length=1, max_length=500)


class OutlinePlanningBrief(_PlanningInput):
    novel_type_id: str = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=120)
    opening_direction: PlanningOpeningDirection
    author_constraints: list[str] = Field(default_factory=list)
    existing_outline: dict[str, Any] = Field(default_factory=dict)
    existing_characters: list[dict[str, Any]] = Field(default_factory=list)
    current_chapter: int = Field(default=0, ge=0)
    recent_chapter_summaries: list[dict[str, Any]] = Field(default_factory=list)


class LLMOutlinePlanningGenerator:
    def __init__(
        self,
        *,
        post_json: Callable[..., dict[str, Any]] = post_json_with_retry,
        runtime_resolver: Callable[[str], OpenAIRuntimeSettings] = resolve_openai_runtime_settings,
        strategy_resolver: Callable[[], AgentSettings] = get_runtime_strategy_settings,
    ) -> None:
        self._post_json = post_json
        self._runtime_resolver = runtime_resolver
        self._strategy_resolver = strategy_resolver

    def generate(
        self,
        brief: OutlinePlanningBrief,
        *,
        mode: PlanningMode = "initial",
        guidance: str = "",
    ) -> GeneratedOutlinePlan:
        validated = OutlinePlanningBrief.model_validate(brief)
        normalized_guidance = guidance.strip()
        if len(normalized_guidance) > 1000:
            raise ValueError("regeneration_guidance_too_long")

        try:
            genre = NOVEL_TYPE_CATALOG.get(validated.novel_type_id)
            if genre is None:
                raise ValueError("invalid_novel_type")
            runtime = self._runtime_resolver("director")
            strategy = self._strategy_resolver()
            if runtime.provider != "codexcli" and not runtime.api_key:
                raise ValueError("runtime_unavailable")
            if not strategy.director_model:
                raise ValueError("runtime_unavailable")

            prompt_context = {
                "mode": mode,
                "genre_label": genre.label,
                "genre_description": genre.description,
                "title": validated.title,
                "opening_direction": validated.opening_direction.model_dump(mode="json"),
                "author_constraints": validated.author_constraints,
                "existing_outline": validated.existing_outline,
                "existing_characters": validated.existing_characters,
                "current_chapter": validated.current_chapter,
                "recent_chapter_summaries": validated.recent_chapter_summaries,
                "one_time_guidance": normalized_guidance,
            }
            payload = {
                "model": strategy.director_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "你负责生成中文长篇网文的结构化开书计划，不写正文。只返回 JSON，根字段必须是 "
                            "outline 和 characters。initial/regenerate 模式必须给出完整总纲、从第1章开始的首阶段、"
                            "连续第1至5章，以及4至6张具体角色卡。角色卡必须包括主角、阶段对手、长期反派和重要配角，"
                            "并写清年龄或身份、来历、职业、当前生活、目标、失败代价、可观察行为和两句自然对白。"
                            "阶段对手要有现实利益和权力边界；长期反派只把允许露出的痕迹写进大纲。"
                            "章节字段为 chapter_number/title/goal/obstacle/action/turn/payoff/ending_hook/cast。"
                            "extend 模式只续写紧接当前计划的五章，并只补充确实要出场的新角色卡。"
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt_context, ensure_ascii=False)},
                ],
                "response_format": {"type": "json_object"},
                "temperature": float(strategy.temperature),
            }
            response = self._post_json(
                runtime.base_url,
                "/chat/completions",
                payload,
                runtime.api_key,
                provider=runtime.provider,
                codex_command=runtime.codex_command,
            )
            parsed = parse_json_message_content(response)
            if parsed is None:
                raise ValueError("invalid_json")
            if mode in {"initial", "regenerate"}:
                return validate_generated_opening_plan(parsed)
            return GeneratedOutlinePlan.model_validate(parsed)
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc) == "regeneration_guidance_too_long":
                raise
            raise ValueError("outline_planning_generation_failed") from exc
