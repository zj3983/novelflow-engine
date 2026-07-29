from __future__ import annotations

import json
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.story_core.agent_base import parse_json_message_content
from packages.story_core.elastic_outline import outline_window_status
from packages.story_core.http_retry import post_json_with_retry
from packages.story_core.novel_type_catalog import novel_type_prompt_context, runtime_novel_type
from packages.story_core.novel_type_ids import canonical_novel_type_id
from packages.story_core.outline_planning import (
    CharacterTier,
    GeneratedOutlinePlan,
    INITIAL_OUTLINE_CHAPTER_COUNT,
    PlanningCharacterCard,
    sanitize_generated_outline_amounts,
    validate_generated_continuation_plan,
    validate_generated_opening_plan,
)
from packages.story_core.runtime_config import (
    StageRuntimeSettings,
    resolve_stage_runtime,
)
from packages.story_core.project_outline import ChapterPlan, ProjectOutline
from packages.story_core.world_blueprint_context import outline_power_system_context


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
    power_system_spec: dict[str, Any] = Field(default_factory=dict)


class GeneratedChapterWindow(_PlanningInput):
    chapters: list[ChapterPlan]


class GeneratedOutlineFoundation(_PlanningInput):
    outline: ProjectOutline


class GeneratedCharacterRoster(_PlanningInput):
    characters: list["PlanningCharacterSeed"]


class PlanningCharacterSeed(_PlanningInput):
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=80)
    character_tier: CharacterTier
    first_appearance: int = Field(default=0, ge=0)
    age: int | None = Field(default=None, ge=0)
    origin: str = Field(min_length=1, max_length=300)
    current_identity: str = Field(min_length=1, max_length=200)
    occupation: str = Field(min_length=1, max_length=120)
    authority_scope: str = Field(default="", max_length=300)
    immediate_problem: str = Field(min_length=1, max_length=300)
    immediate_goal: str = Field(min_length=1, max_length=300)
    long_term_goal: str = Field(default="", max_length=300)
    failure_stakes: str = Field(min_length=1, max_length=300)
    personality: str = Field(min_length=1, max_length=300)
    speech_style: str = Field(min_length=1, max_length=200)
    action_style: str = Field(min_length=1, max_length=200)
    emotional_trigger: str = Field(default="", max_length=200)
    decision_rule: str = Field(min_length=1, max_length=200)
    hidden_matter: str = Field(default="", max_length=300)
    dialogue_examples: list[str] = Field(min_length=2, max_length=2)


def _expand_character_seed(seed: PlanningCharacterSeed) -> PlanningCharacterCard:
    return PlanningCharacterCard.model_validate(
        {
            "name": seed.name,
            "role": seed.role,
            "character_tier": seed.character_tier,
            "first_appearance": seed.first_appearance,
            "identity_profile": {
                "age": seed.age,
                "origin": seed.origin,
                "current_identity": seed.current_identity,
                "occupation": seed.occupation,
            },
            "background_profile": {
                "formative_events": [seed.personality],
            },
            "current_life_profile": {
                "authority_scope": seed.authority_scope,
                "immediate_problem": seed.immediate_problem,
            },
            "story_drive": {
                "long_term_goal": seed.long_term_goal,
                "immediate_goal": seed.immediate_goal,
                "motivation": seed.personality,
                "failure_stakes": seed.failure_stakes,
                "hidden_matters": [seed.hidden_matter] if seed.hidden_matter else [],
            },
            "performance_profile": {
                "speech_style": seed.speech_style,
                "action_style": seed.action_style,
                "emotional_triggers": [seed.emotional_trigger] if seed.emotional_trigger else [],
                "decision_rules": [seed.decision_rule],
            },
            "dialogue_examples": seed.dialogue_examples,
            "relationship_notes": [],
        }
    )


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
            effective_novel_type_id = canonical_novel_type_id(
                getattr(genre, "id", None) or validated.novel_type_id
            )
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
                target_chapter_numbers = list(range(1, INITIAL_OUTLINE_CHAPTER_COUNT + 1))
            elif mode == "regenerate":
                target_chapter_numbers = list(
                    range(
                        validated.current_chapter + 1,
                        min(
                            validated.current_chapter + INITIAL_OUTLINE_CHAPTER_COUNT,
                            window["target_last_chapter"],
                        )
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
            financial_outline_rule = (
                "All outline narrative text may describe financial outcomes but must not contain "
                "exact currency amounts, account balances, or fee percentages."
            )
            power_system = outline_power_system_context(validated.power_system_spec)
            power_contract_rules = (
                [
                    "不得虚构主角已经拥有的技能或装备；新技能、新装备和其他能力必须先安排解锁过程，兑现后写入连续性账本。",
                    "每次晋升必须写明进入条件、支付代价和失败后果，不得免费晋升或无条件跨越阶段。",
                ]
                if power_system
                else []
            )
            if power_system and effective_novel_type_id == "game_webnovel":
                power_contract_rules.insert(
                    0,
                    "游戏力量里程碑必须固定：Lv10是正式转职，Lv20是专精节点而不是第二次转职，Lv30进入进阶分支，Lv60进入传承。",
                )

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

            validation_rules.append(financial_outline_rule)
            validation_rules.extend(power_contract_rules)

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
            if power_system:
                prompt_context["power_system"] = power_system
            payload = {
                "model": runtime.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"{financial_outline_rule} "
                            f"{' '.join(power_contract_rules)} "
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
            if runtime.provider == "codexcli" and mode == "initial":
                outline_context = {
                    **prompt_context,
                    "generation_phase": "outline",
                    "target_chapter_numbers": [],
                    "output_schema": GeneratedOutlineFoundation.model_json_schema(),
                }
                outline_payload = {
                    **payload,
                    "reasoning_effort": "low",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Generate only the story structure as JSON with the single root field outline. "
                                "Provide the complete overall plan and all core arcs. "
                                "Set outline.chapters to an empty array. Follow prompt_context.output_schema exactly."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(outline_context, ensure_ascii=False),
                        },
                    ],
                }
                try:
                    outline_response = self._post_json(
                        runtime.base_url,
                        "/chat/completions",
                        outline_payload,
                        runtime.api_key,
                        provider=runtime.provider,
                        codex_command=runtime.codex_command,
                    )
                except Exception as exc:
                    raise ValueError(
                        f"outline_generation_failed:{type(exc).__name__}"
                    ) from exc
                outline_data = parse_json_message_content(outline_response)
                if outline_data is None:
                    raise ValueError("invalid_outline_json")
                outline_foundation = GeneratedOutlineFoundation.model_validate(
                    outline_data
                ).model_dump(mode="json")
                outline_foundation["outline"]["chapters"] = []

                character_context = {
                    "generation_phase": "characters",
                    "title": validated.title,
                    "novel_type_id": effective_novel_type_id,
                    "opening_direction": validated.opening_direction.model_dump(mode="json"),
                    "author_constraints": validated.author_constraints,
                    "outline_foundation": outline_foundation["outline"],
                    "target_chapter_numbers": [],
                    "output_schema": GeneratedCharacterRoster.model_json_schema(),
                    "validation_rules": [
                        "Return 4 to 6 unique complete character cards.",
                        "Include protagonist, stage_antagonist, long_term_antagonist, and supporting tiers.",
                        "The stage_antagonist name must match the opening arc stage_antagonist.",
                    ],
                }
                character_payload = {
                    **payload,
                    "reasoning_effort": "low",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Generate only the opening character roster. Return JSON with the single root field characters. "
                                "Create 4 to 6 complete Chinese webnovel character cards that fit outline_foundation. "
                                "Follow prompt_context.output_schema exactly."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(character_context, ensure_ascii=False),
                        },
                    ],
                }
                try:
                    character_response = self._post_json(
                        runtime.base_url,
                        "/chat/completions",
                        character_payload,
                        runtime.api_key,
                        provider=runtime.provider,
                        codex_command=runtime.codex_command,
                    )
                except Exception as exc:
                    raise ValueError(
                        f"character_generation_failed:{type(exc).__name__}"
                    ) from exc
                character_data = parse_json_message_content(character_response)
                if character_data is None:
                    raise ValueError("invalid_character_json")
                character_roster = GeneratedCharacterRoster.model_validate(
                    character_data
                )
                foundation_data = {
                    "outline": outline_foundation["outline"],
                    "characters": [
                        _expand_character_seed(seed).model_dump(mode="json")
                        for seed in character_roster.characters
                    ],
                }

                chapter_context = {
                    "generation_phase": "chapters",
                    "title": validated.title,
                    "novel_type_id": effective_novel_type_id,
                    "opening_direction": validated.opening_direction.model_dump(mode="json"),
                    "author_constraints": validated.author_constraints,
                    "outline_foundation": foundation_data["outline"],
                    "characters": [
                        {
                            "name": card["name"],
                            "role": card["role"],
                            "character_tier": card["character_tier"],
                        }
                        for card in foundation_data["characters"]
                    ],
                    "genre_trope_templates": trope_candidates,
                    "target_chapter_numbers": target_chapter_numbers,
                    "output_schema": GeneratedChapterWindow.model_json_schema(),
                    "validation_rules": [
                        "Return exactly one chapter for every target_chapter_numbers value, in order.",
                        "Every cast name must exactly match one name in characters.",
                        "Use trope_beat only on a milestone and only from the active arc trope template.",
                        financial_outline_rule,
                    ],
                }
                chapter_payload = {
                    **payload,
                    "reasoning_effort": "low",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Generate only the requested Chinese webnovel chapter outline window. "
                                "Return JSON with the single root field chapters. Do not repeat overall, arcs, or character cards. "
                                "Follow prompt_context.output_schema and target_chapter_numbers exactly."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(chapter_context, ensure_ascii=False),
                        },
                    ],
                }
                try:
                    chapter_response = self._post_json(
                        runtime.base_url,
                        "/chat/completions",
                        chapter_payload,
                        runtime.api_key,
                        provider=runtime.provider,
                        codex_command=runtime.codex_command,
                    )
                except Exception as exc:
                    raise ValueError(
                        f"chapter_window_generation_failed:{type(exc).__name__}"
                    ) from exc
                chapter_data = parse_json_message_content(chapter_response)
                if chapter_data is None:
                    raise ValueError("invalid_chapter_window_json")
                chapter_window = GeneratedChapterWindow.model_validate(chapter_data)
                foundation_data["outline"]["chapters"] = [
                    chapter.model_dump(mode="json")
                    for chapter in chapter_window.chapters
                ]
                parsed = foundation_data
            else:
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
            parsed = sanitize_generated_outline_amounts(parsed)
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
