from __future__ import annotations

import json
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.story_core.agent_base import parse_json_message_content
from packages.story_core.elastic_outline import outline_window_status
from packages.story_core.http_retry import post_json_with_retry
from packages.story_core.novel_type_catalog import novel_type_prompt_context, runtime_novel_type
from packages.story_core.outline_planning import (
    GeneratedOutlinePlan,
    validate_generated_continuation_plan,
    validate_generated_opening_plan,
)
from packages.story_core.runtime_config import (
    StageRuntimeSettings,
    resolve_stage_runtime,
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
    primary_trope_id: str | None = Field(default=None, max_length=120)


class OutlinePlanningBrief(_PlanningInput):
    novel_type_id: str = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=120)
    opening_direction: PlanningOpeningDirection
    author_constraints: list[str] = Field(default_factory=list)
    existing_outline: dict[str, Any] = Field(default_factory=dict)
    existing_characters: list[dict[str, Any]] = Field(default_factory=list)
    existing_character_names: list[str] = Field(default_factory=list)
    current_chapter: int = Field(default=0, ge=0)
    recent_chapter_summaries: list[dict[str, Any]] = Field(default_factory=list)


class LLMOutlinePlanningGenerator:
    def __init__(
        self,
        *,
        post_json: Callable[..., dict[str, Any]] = post_json_with_retry,
        runtime_resolver: Callable[[str], StageRuntimeSettings] = resolve_stage_runtime,
    ) -> None:
        self._post_json = post_json
        self._runtime_resolver = runtime_resolver

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
            genre = runtime_novel_type(validated.novel_type_id)
            if genre is None:
                raise ValueError("invalid_novel_type")
            genre_context = novel_type_prompt_context(genre)
            trope_candidates = [
                dict(item)
                for item in genre_context.get("genre_trope_templates", [])
                if isinstance(item, dict)
            ]
            window = outline_window_status(
                validated.existing_outline,
                current_chapter=validated.current_chapter,
            )
            if mode == "initial":
                if validated.current_chapter != 0:
                    raise ValueError("initial_outline_requires_unstarted_project")
                target_chapter_numbers = list(range(1, 31))
            elif mode == "regenerate":
                target_chapter_numbers = list(
                    range(
                        validated.current_chapter + 1,
                        min(validated.current_chapter + 30, window["target_last_chapter"])
                        + 1,
                    )
                )
                if not target_chapter_numbers:
                    raise ValueError("outline_window_already_full")
            else:
                target_chapter_numbers = window["next_chapter_numbers"]
                if not target_chapter_numbers:
                    raise ValueError("outline_window_already_full")

            runtime = self._runtime_resolver("planner")
            if runtime.provider != "codexcli" and not runtime.api_key:
                raise ValueError("runtime_unavailable")

            existing_character_names = list(
                dict.fromkeys(
                    [
                        *(
                            str(name).strip()
                            for name in validated.existing_character_names
                            if str(name).strip()
                        ),
                        *(
                            str(item.get("name") or "").strip()
                            for item in validated.existing_characters
                            if isinstance(item, dict)
                            and str(item.get("name") or "").strip()
                        ),
                    ]
                )
            )
            opening_primary_trope_id = str(
                validated.opening_direction.primary_trope_id or ""
            ).strip() or None
            existing_overall = (
                validated.existing_outline.get("overall")
                if isinstance(validated.existing_outline.get("overall"), dict)
                else {}
            )
            existing_primary_trope_id = str(
                existing_overall.get("primary_trope_id") or ""
            ).strip() or None
            expected_primary_trope_id = (
                existing_primary_trope_id
                if mode in {"regenerate", "extend"} and existing_primary_trope_id
                else opening_primary_trope_id
            )

            trope_validation_rules = [
                "If prompt_context.genre_trope_templates is non-empty, overall.primary_trope_id must be one id from those candidates.",
                "If prompt_context.genre_trope_templates is non-empty, every arc.trope_id must be one id from those candidates and must not change inside that arc.",
                "chapter.trope_beat only on milestone chapters; when present it must exactly equal a beat from the active arc's trope template.",
                "Do not assign trope_beat to every chapter.",
                "If prompt_context.genre_trope_templates is empty, overall.primary_trope_id, every arc.trope_id, and every chapter.trope_beat must be null.",
            ]

            if mode == "extend":
                validation_rules = [
                    "chapter_number values must exactly equal prompt_context.target_chapter_numbers in order.",
                    "characters must contain only newly introduced character cards; do not repeat cards named in prompt_context.existing_character_names.",
                    "Every chapter cast name must equal either a name in prompt_context.existing_character_names or a name in characters.",
                    "Every new character must have non-empty identity_profile.origin, identity_profile.current_identity, identity_profile.occupation, story_drive.immediate_goal, and story_drive.failure_stakes.",
                    *trope_validation_rules,
                ]
            else:
                validation_rules = [
                    "For initial/regenerate, characters must contain 4 to 6 unique names and include the protagonist, stage_antagonist, and long_term_antagonist tiers.",
                    "The opening arc must start at chapter 1, and its stage_antagonist must be exactly equal to the name of the character whose character_tier is stage_antagonist.",
                    "The opening arc must contain at least one long_term_antagonist_traces item.",
                    "chapter_number values must exactly equal prompt_context.target_chapter_numbers in order.",
                    "Every name in every chapter cast must exactly equal a name in characters.",
                    "Every character must have non-empty identity_profile.origin, identity_profile.current_identity, identity_profile.occupation, story_drive.immediate_goal, and story_drive.failure_stakes.",
                    *trope_validation_rules,
                ]

            prompt_context = {
                "mode": mode,
                **genre_context,
                "title": validated.title,
                "opening_direction": validated.opening_direction.model_dump(mode="json"),
                "author_constraints": validated.author_constraints,
                "existing_outline": validated.existing_outline,
                "existing_characters": validated.existing_characters,
                "existing_character_names": existing_character_names,
                "current_chapter": validated.current_chapter,
                "recent_chapter_summaries": validated.recent_chapter_summaries,
                "target_chapter_numbers": target_chapter_numbers,
                "current_strategy": validated.existing_outline.get("overall", {}).get(
                    "current_strategy", "observe"
                ),
                "one_time_guidance": normalized_guidance,
                "output_schema": GeneratedOutlinePlan.model_json_schema(),
                "validation_rules": validation_rules,
            }
            payload = {
                "model": runtime.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Follow prompt_context.output_schema exactly. Do not add fields, rename fields, "
                            "or use values outside the declared enums. Return every required field. "
                            "chapter_number values must exactly equal prompt_context.target_chapter_numbers in order. "
                            "For initial/regenerate, provide the complete core arcs through core_ending_chapter, but only those detailed chapters. "
                            "For extend, continue from committed facts and the active arc; obey current_strategy. "
                            "For extend, characters must contain only newly introduced character cards, while chapter cast may also use names from prompt_context.existing_character_names. "
                            "Every core arc must state a concrete game_line_payoff and reality_line_payoff. "
                            "observe follows the core route, expand uses only the next continue_route, and close uses the active close_route. "
                            "Choose one overall.primary_trope_id from prompt_context.genre_trope_templates and one arc.trope_id per arc from those same candidates. "
                            "Use chapter.trope_beat only on milestone chapters, and the value must exactly equal a beat of that arc's locked template. "
                            "Do not assign trope_beat to every chapter. Do not change trope_id inside an arc. "
                            "Use null for overall.primary_trope_id, arc.trope_id, and chapter.trope_beat when prompt_context.genre_trope_templates is empty. "
                            "你负责生成中文长篇网文的结构化开书计划，不写正文。只返回 JSON，根字段必须是 "
                            "outline 和 characters。initial/regenerate 模式必须给出完整总纲和全部核心卷，"
                            "但细纲只能覆盖目标章节，并给出4至6张具体角色卡。角色卡必须包括主角、阶段对手、长期反派和重要配角，"
                            "并写清年龄或身份、来历、职业、当前生活、目标、失败代价、可观察行为和两句自然对白。"
                            "阶段对手要有现实利益和权力边界；长期反派只把允许露出的痕迹写进大纲。"
                            "章节字段为 chapter_number/title/goal/obstacle/action/turn/payoff/ending_hook/cast。"
                            "extend 模式只生成 target_chapter_numbers 指定的缺章，并只补充确实要出场的新角色卡。"
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt_context, ensure_ascii=False)},
                ],
                "response_format": {"type": "json_object"},
                "temperature": float(runtime.temperature),
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
            if mode == "extend":
                return validate_generated_continuation_plan(
                    parsed,
                    expected_chapter_numbers=target_chapter_numbers,
                    existing_character_names=set(existing_character_names),
                    trope_templates=trope_candidates,
                    expected_primary_trope_id=expected_primary_trope_id,
                    fallback_outline=validated.existing_outline,
                )
            fallback_outline = (
                validated.existing_outline
                if mode == "regenerate"
                else None
            )
            return validate_generated_opening_plan(
                parsed,
                expected_chapter_numbers=target_chapter_numbers,
                trope_templates=trope_candidates,
                expected_primary_trope_id=expected_primary_trope_id,
                fallback_outline=fallback_outline,
            )
        except Exception as exc:
            if isinstance(exc, ValueError):
                error = str(exc)
                if error in {
                    "regeneration_guidance_too_long",
                    "initial_outline_requires_unstarted_project",
                    "outline_window_already_full",
                }:
                    raise
            raise ValueError("outline_planning_generation_failed") from exc
