from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.story_core.agent_base import parse_json_message_content
from packages.story_core.character_profiles import normalize_speech_style_for_writing
from packages.story_core.elastic_outline import outline_window_status
from packages.story_core.http_retry import post_json_with_retry
from packages.story_core.model_gateway import ModelRequest, RuntimeModelGateway
from packages.story_core.novel_type_catalog import novel_type_prompt_context, runtime_novel_type
from packages.story_core.novel_type_ids import canonical_novel_type_id
from packages.story_core.outline_planning import (
    CHAPTER_SOP_MODULE_ID,
    CharacterTier,
    GeneratedOutlinePlan,
    INITIAL_OUTLINE_CHAPTER_COUNT,
    PlanningCharacterCard,
    sanitize_generated_outline_amounts,
    validate_concrete_chapter_contract,
    validate_generated_continuation_plan,
    validate_generated_opening_plan,
)
from packages.story_core.runtime_config import (
    StageRuntimeSettings,
    resolve_stage_runtime,
)
from packages.story_core.skill_packs import skill_pack_prompt_context
from packages.story_core.title_strategy import (
    build_chapter_title_guidance,
    select_adjacent_chapter_titles,
    select_chapter_title_neighbors,
    select_previous_chapter_titles,
    validate_chapter_title_window,
)
from packages.story_core.project_outline import (
    ChapterPlan,
    ChapterScenePlan,
    ProjectOutline,
    select_outline_context,
)
from packages.story_core.world_blueprint_context import outline_power_system_context


PlanningMode = Literal["initial", "regenerate", "extend"]

_OUTLINE_SKILL_GUARD = (
    "Skill methods may shape conflict and payoff, but must not invent canon, "
    "must not replace prompt_context.output_schema, and must not override the "
    "established outline, world, or characters. "
)
_OUTLINE_SKILL_CONTEXT_MAX_CHARS = 3600
_OUTLINE_SKILL_LIST_MAX_CHARS = _OUTLINE_SKILL_CONTEXT_MAX_CHARS - (
    len(json.dumps({"outline": []}, ensure_ascii=False))
    - len(json.dumps([], ensure_ascii=False))
)
_CHAPTER_SKILL_CONTEXT_MAX_CHARS = 1200
_CHAPTER_SKILL_LIST_MAX_CHARS = _CHAPTER_SKILL_CONTEXT_MAX_CHARS - (
    len(json.dumps({"chapter_plan": []}, ensure_ascii=False))
    - len(json.dumps([], ensure_ascii=False))
)
_CHAPTER_CONTRACT_FIELDS = ("payoff_contract", "chapter_sop")
CHAPTER_CONTRACT_RULE = (
    "Every chapter must include payoff_contract.need/pressure/hidden_advantage/"
    "concrete_reward and chapter_sop.opening_carry/mid_feedback/turn/ending_hook. "
    "Each chapter_contract value must name an observable event/action/result grounded "
    "in the total outline, active stage outline, current project facts, established "
    "world, and established characters; it must not invent canon. Reject vague labels "
    "such as 提升压力, 情况复杂, 留下悬念, 获得爽点, 事情不简单, or continue. "
    "These fields describe the selected chapter's contract and must not force a full macro loop."
)


def chapter_output_schema(
    model: type[BaseModel],
    *,
    require_chapter_contracts: bool,
) -> dict[str, Any]:
    schema = deepcopy(model.model_json_schema())
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        return schema

    chapter_definitions = [
        definition
        for name, definition in definitions.items()
        if name in {"ChapterPlan", "GeneratedDetailedChapter"}
        and isinstance(definition, dict)
    ]
    if not require_chapter_contracts:
        for definition in chapter_definitions:
            properties = definition.get("properties")
            if isinstance(properties, dict):
                for field_name in _CHAPTER_CONTRACT_FIELDS:
                    properties.pop(field_name, None)
            required = definition.get("required")
            if isinstance(required, list):
                definition["required"] = [
                    field_name
                    for field_name in required
                    if field_name not in _CHAPTER_CONTRACT_FIELDS
                ]
        definitions.pop("ChapterPayoffContract", None)
        definitions.pop("ChapterSop", None)
        return schema

    for definition in chapter_definitions:
        properties = definition.get("properties")
        if not isinstance(properties, dict):
            continue
        required = list(definition.get("required") or [])
        for field_name in _CHAPTER_CONTRACT_FIELDS:
            property_schema = properties.get(field_name)
            if isinstance(property_schema, dict):
                non_null = next(
                    (
                        option
                        for option in property_schema.get("anyOf", [])
                        if isinstance(option, dict) and "$ref" in option
                    ),
                    None,
                )
                if non_null is not None:
                    properties[field_name] = non_null
            if field_name not in required:
                required.append(field_name)
        definition["required"] = required
    for name in ("ChapterPayoffContract", "ChapterSop"):
        definition = definitions.get(name)
        if isinstance(definition, dict) and isinstance(definition.get("properties"), dict):
            definition["required"] = list(definition["properties"])
    return schema


def _drop_chapter_contracts_from_outline(outline: Any) -> None:
    if not isinstance(outline, dict):
        return
    chapters = outline.get("chapters")
    if not isinstance(chapters, list):
        return
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        for field_name in _CHAPTER_CONTRACT_FIELDS:
            chapter.pop(field_name, None)


def _drop_disabled_chapter_contracts(payload: Any) -> None:
    if isinstance(payload, dict):
        _drop_chapter_contracts_from_outline(payload.get("outline"))


def _runtime_gateway_for_legacy_injection(
    post_json: Callable[..., dict[str, Any]],
    runtime_resolver: Callable[[str], StageRuntimeSettings],
) -> RuntimeModelGateway:
    if post_json is post_json_with_retry:
        return RuntimeModelGateway(runtime_resolver=runtime_resolver)
    active: dict[str, Any] = {}

    def compatible_runtime(stage: str) -> StageRuntimeSettings:
        runtime = runtime_resolver(stage)
        active["runtime"] = runtime
        provider = str(getattr(runtime, "provider_id", getattr(runtime, "provider", "")))
        protocol = getattr(runtime, "protocol", "openai_compatible")
        if str(protocol).endswith("_cli") or provider in {"codexcli", "antigravity"}:
            provider, protocol = "custom_openai", "openai_compatible"
        return StageRuntimeSettings(
            provider_id=provider,
            protocol=protocol,
            model=runtime.model,
            api_key=runtime.api_key or ("legacy-injected" if provider == "custom_openai" else ""),
            base_url=runtime.base_url or "http://legacy-injected.invalid",
            codex_command=runtime.codex_command,
            temperature=runtime.temperature,
        )

    def transport(*, url: str, payload: dict[str, Any], headers: dict[str, str], config: Any) -> dict[str, Any]:
        runtime = active["runtime"]
        base_url = str(runtime.base_url).rstrip("/")
        path = url[len(base_url) :] if url.startswith(base_url) else url
        return post_json(
            base_url,
            path,
            payload,
            runtime.api_key,
            provider=runtime.provider,
            codex_command=runtime.codex_command,
        )

    return RuntimeModelGateway(runtime_resolver=compatible_runtime, transport=transport)


def _complete_payload(
    gateway: RuntimeModelGateway,
    payload: dict[str, Any],
    *,
    operation: str,
) -> dict[str, Any]:
    response = gateway.complete_stage(
        "planner",
        ModelRequest(
            prompt="",
            messages=tuple(payload.get("messages", ())),
            provider="",
            model="",
            operation=operation,
            temperature=payload.get("temperature"),
            max_tokens=payload.get("max_tokens"),
            json_mode=payload.get("response_format") == {"type": "json_object"},
        ),
    )
    if not response.ok:
        raise ValueError(response.error or "model_call_failed")
    return {"choices": [{"message": {"content": response.text}}]}


def _compact_historical_chapter_summaries(
    summaries: list[dict[str, Any]],
    *,
    block_size: int = 10,
    digest_chars: int = 100,
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for offset in range(0, len(summaries), block_size):
        source_block = summaries[offset : offset + block_size]
        chapter_digest: list[str] = []
        chapter_numbers: list[int] = []
        for item in source_block:
            number = int(item.get("chapter_number") or 0)
            title = re.sub(r"^第\s*\d+\s*章\s*", "", str(item.get("title") or "").strip())
            summary = re.sub(r"\s+", " ", str(item.get("summary") or "").strip())
            prefix = f"第{number}章"
            if title:
                prefix += f" {title}"
            prefix += "："
            chapter_digest.append(f"{prefix}{summary[:max(0, digest_chars - len(prefix))]}")
            chapter_numbers.append(number)
        if chapter_numbers:
            blocks.append(
                {
                    "start_chapter": min(chapter_numbers),
                    "end_chapter": max(chapter_numbers),
                    "chapter_digest": chapter_digest,
                }
            )
    return blocks


class _PlanningInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanningOpeningDirection(_PlanningInput):
    title: str = ""
    hook: str = Field(min_length=1, max_length=500)
    protagonist_goal: str = Field(default="", max_length=500, exclude=True)
    main_conflict: str = Field(default="", max_length=500, exclude=True)
    growth_path: str = Field(default="", max_length=500, exclude=True)
    opening_promise: str = Field(min_length=1, max_length=500)
    primary_trope_id: str | None = Field(default=None, max_length=120)


class OutlinePlanningBrief(_PlanningInput):
    novel_type_id: str = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=120)
    overall_context: dict[str, Any] = Field(default_factory=dict)
    opening_direction: PlanningOpeningDirection
    author_constraints: list[str] = Field(default_factory=list)
    existing_outline: dict[str, Any] = Field(default_factory=dict)
    existing_characters: list[dict[str, Any]] = Field(default_factory=list)
    existing_character_names: list[str] = Field(default_factory=list)
    current_chapter: int = Field(default=0, ge=0)
    recent_chapter_summaries: list[dict[str, Any]] = Field(default_factory=list)
    continuation_start_chapter: int | None = Field(default=None, ge=1)
    historical_chapter_summaries: list[dict[str, Any]] = Field(default_factory=list)
    power_system_spec: dict[str, Any] = Field(default_factory=dict)
    enabled_skill_ids: list[str] = Field(default_factory=list)
    enabled_skill_module_ids: list[str] | None = None


class GeneratedChapterWindow(_PlanningInput):
    chapters: list["GeneratedDetailedChapter"]


class GeneratedDetailedChapter(ChapterPlan):
    """Planner-stage chapter row carrying the rolling fields.

    The plan rule: the chapter window returned by the planner is
    the *only* place future chapter detail is generated. The
    rows it returns extend the legacy ``ChapterPlan`` shape with
    the rolling-only fields (``core_conflict`` / ``gain`` /
    ``cost`` / ``foreshadowing`` / ``state_delta_summary`` /
    ``scene_chain``) so the bootstrapper can project them into
    the independent rolling schema in one deterministic pass.

    Before merging into ``ProjectOutline`` the bootstrapper
    re-validates the rows through ``ChapterPlan.model_validate``,
    which silently drops these fields. The three-level outline
    schema therefore never sees the rolling-only keys.
    """

    core_conflict: str = Field(min_length=1)
    gain: str = Field(min_length=1)
    cost: str = Field(min_length=1)
    foreshadowing: list[str] = Field(default_factory=list)
    state_delta_summary: str = Field(min_length=1)
    scene_chain: list[ChapterScenePlan] = Field(min_length=2, max_length=4)


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
    dialogue_examples = []
    for example in seed.dialogue_examples:
        text = str(example or "").strip()
        if len(text) < 10:
            text = f"{text.rstrip('。！？?!')}，具体情况要先说清楚。"
        dialogue_examples.append(text)
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
            "background_profile": {"formative_events": []},
            "current_life_profile": {
                "authority_scope": seed.authority_scope,
                "immediate_problem": seed.immediate_problem,
            },
            "story_drive": {
                "long_term_goal": seed.long_term_goal,
                "immediate_goal": seed.immediate_goal,
                "motivation": seed.immediate_goal,
                "failure_stakes": seed.failure_stakes,
                "hidden_matters": [seed.hidden_matter] if seed.hidden_matter else [],
            },
            "performance_profile": {
                "speech_style": normalize_speech_style_for_writing(seed.speech_style),
                "action_style": seed.action_style,
                "emotional_triggers": [seed.emotional_trigger] if seed.emotional_trigger else [],
                "decision_rules": [seed.decision_rule],
            },
            "dialogue_examples": dialogue_examples,
            "relationship_notes": [],
        }
    )


def _validate_game_dual_line_payoffs(plan: GeneratedOutlinePlan) -> None:
    core_ending = plan.outline.overall.core_ending_chapter
    for arc in plan.outline.arcs:
        if arc.start_chapter > core_ending:
            continue
        if not arc.game_line_payoff.strip() or not arc.reality_line_payoff.strip():
            raise ValueError(f"missing_game_dual_line_payoff:{arc.id}")


def _clear_non_game_dual_line_payoffs(payload: dict[str, Any]) -> None:
    outline = payload.get("outline")
    if not isinstance(outline, dict):
        return
    arcs = outline.get("arcs")
    if not isinstance(arcs, list):
        return
    for arc in arcs:
        if isinstance(arc, dict):
            arc["game_line_payoff"] = ""
            arc["reality_line_payoff"] = ""


def _drop_invalid_optional_trope_beats(
    payload: dict[str, Any],
    trope_templates: list[dict[str, Any]],
    *,
    fallback_outline: dict[str, Any] | None = None,
) -> None:
    outline = payload.get("outline")
    if not isinstance(outline, dict):
        return
    chapters = outline.get("chapters")
    if not isinstance(chapters, list):
        return

    beats_by_trope_id = {
        str(template.get("id") or "").strip(): {
            str(beat).strip()
            for beat in template.get("beats", [])
            if str(beat).strip()
        }
        for template in trope_templates
        if isinstance(template, dict) and str(template.get("id") or "").strip()
    }
    context_outline = outline
    if isinstance(fallback_outline, dict):
        generated_arc_ids = {
            str(arc.get("id") or "")
            for arc in outline.get("arcs", [])
            if isinstance(arc, dict)
        }
        fallback_arcs = [
            arc
            for arc in fallback_outline.get("arcs", [])
            if isinstance(arc, dict)
            and arc.get("trope_id") is not None
            and str(arc.get("id") or "") not in generated_arc_ids
        ]
        context_outline = {
            **outline,
            "arcs": [*outline.get("arcs", []), *fallback_arcs],
        }

    for chapter in chapters:
        if not isinstance(chapter, dict) or chapter.get("trope_beat") is None:
            continue
        chapter_number = int(chapter.get("chapter_number") or 0)
        context = select_outline_context(context_outline, chapter_number)
        active_arc = context.get("active_arc")
        trope_id = (
            str(active_arc.get("trope_id") or "").strip()
            if isinstance(active_arc, dict)
            else ""
        )
        valid_beats = beats_by_trope_id.get(trope_id, set())
        beat = str(chapter.get("trope_beat") or "").strip()
        if not beat or beat not in valid_beats:
            chapter["trope_beat"] = None


def _preserve_unlocked_legacy_tropes(
    payload: dict[str, Any],
    fallback_outline: dict[str, Any],
) -> None:
    """Keep an untagged legacy book untagged while extending its outline."""

    outline = payload.get("outline")
    if not isinstance(outline, dict):
        return
    overall = outline.get("overall")
    if isinstance(overall, dict):
        overall["primary_trope_id"] = None

    fallback_arcs = {
        str(arc.get("id") or ""): arc
        for arc in fallback_outline.get("arcs", [])
        if isinstance(arc, dict) and str(arc.get("id") or "")
    }
    for arc in outline.get("arcs", []):
        if not isinstance(arc, dict):
            continue
        fallback_arc = fallback_arcs.get(str(arc.get("id") or ""))
        arc["trope_id"] = (
            fallback_arc.get("trope_id")
            if isinstance(fallback_arc, dict)
            else None
        )
    for chapter in outline.get("chapters", []):
        if isinstance(chapter, dict):
            chapter["trope_beat"] = None


class LLMOutlinePlanningGenerator:
    def __init__(
        self,
        *,
        post_json: Callable[..., dict[str, Any]] = post_json_with_retry,
        runtime_resolver: Callable[[str], StageRuntimeSettings] = resolve_stage_runtime,
        model_gateway: RuntimeModelGateway | None = None,
    ) -> None:
        runtime_cache: dict[str, StageRuntimeSettings] = {}

        def cached_runtime_resolver(stage: str) -> StageRuntimeSettings:
            if stage not in runtime_cache:
                runtime_cache[stage] = runtime_resolver(stage)
            return runtime_cache[stage]

        self._runtime_resolver = cached_runtime_resolver
        self._model_gateway = model_gateway or _runtime_gateway_for_legacy_injection(
            post_json, cached_runtime_resolver
        )

    def generate(
        self,
        brief: OutlinePlanningBrief,
        *,
        mode: PlanningMode = "initial",
        guidance: str = "",
        phase_payloads: dict[str, dict[str, Any]] | None = None,
        phase_callback: Callable[[str, str, dict[str, Any] | None, str], None] | None = None,
        stop_after_phase: str | None = None,
    ) -> GeneratedOutlinePlan:
        validated = OutlinePlanningBrief.model_validate(brief)
        chapter_contracts_enabled = (
            validated.enabled_skill_module_ids is None
            and CHAPTER_SOP_MODULE_ID.split("::", 1)[0]
            in validated.enabled_skill_ids
        ) or CHAPTER_SOP_MODULE_ID in {
            str(module_id).strip()
            for module_id in (validated.enabled_skill_module_ids or [])
        }
        normalized_guidance = guidance.strip()
        if len(normalized_guidance) > 1000:
            raise ValueError("regeneration_guidance_too_long")
        split_plan_completed = False

        try:
            genre = runtime_novel_type(validated.novel_type_id)
            if genre is None:
                raise ValueError("invalid_novel_type")
            genre_context = novel_type_prompt_context(genre)
            outline_template = genre_context.get("genre_outline_template")
            if not isinstance(outline_template, dict) or not outline_template:
                raise ValueError("outline_template_missing")
            effective_novel_type_id = canonical_novel_type_id(
                getattr(genre, "id", None) or validated.novel_type_id
            )
            trope_candidates = [
                dict(item)
                for item in genre_context.get("genre_trope_templates", [])
                if isinstance(item, dict)
            ]
            window = None
            if mode != "regenerate" or validated.continuation_start_chapter is None:
                window = outline_window_status(
                    validated.existing_outline,
                    current_chapter=validated.current_chapter,
                )
            if mode == "initial":
                if validated.current_chapter != 0:
                    raise ValueError("initial_outline_requires_unstarted_project")
                target_chapter_numbers = list(range(1, INITIAL_OUTLINE_CHAPTER_COUNT + 1))
            elif mode == "regenerate":
                if validated.current_chapter == 0:
                    target_chapter_numbers = list(
                        range(1, INITIAL_OUTLINE_CHAPTER_COUNT + 1)
                    )
                else:
                    target_last_chapter = (
                        validated.current_chapter + INITIAL_OUTLINE_CHAPTER_COUNT
                        if validated.continuation_start_chapter is not None
                        else window["target_last_chapter"]
                    )
                    target_chapter_numbers = list(
                        range(validated.current_chapter + 1, target_last_chapter + 1)
                    )
                if not target_chapter_numbers:
                    raise ValueError("outline_window_already_full")
            else:
                assert window is not None
                target_chapter_numbers = window["next_chapter_numbers"]
                if not target_chapter_numbers:
                    raise ValueError("outline_window_already_full")

            runtime = self._runtime_resolver("planner")
            if runtime.provider not in {"codexcli", "antigravity"} and not runtime.api_key:
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
            preserve_unlocked_legacy_tropes = (
                mode == "extend"
                and validated.current_chapter > 0
                and expected_primary_trope_id is None
            )
            if preserve_unlocked_legacy_tropes:
                trope_candidates = []
                genre_context = {
                    **genre_context,
                    "genre_trope_templates": [],
                }

            trope_validation_rules = [
                "If prompt_context.genre_trope_templates is non-empty, overall.primary_trope_id must exactly equal one candidate id.",
                "If prompt_context.genre_trope_templates is non-empty, every arc.trope_id must exactly equal one candidate id and must not change inside that arc.",
                "Use chapter.trope_beat only on milestone chapters; when present it must exactly equal a beat from the active arc's trope template.",
                "Do not assign trope_beat to every chapter.",
                "If prompt_context.genre_trope_templates is empty, overall.primary_trope_id, every arc.trope_id, and every chapter.trope_beat must be null.",
            ]
            financial_outline_rule = (
                "All outline narrative text may describe financial outcomes but must not contain "
                "exact currency amounts, account balances, or fee percentages."
            )
            if effective_novel_type_id in {"game_webnovel", "system_webnovel", "urban_wealth"}:
                financial_outline_rule = ""
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
                    "Every character name and every arc stage_antagonist must be a concrete personal name, never a role, occupation, faction, or placeholder label.",
                    "The opening arc must start at chapter 1, and its stage_antagonist must be exactly equal to the name of the character whose character_tier is stage_antagonist.",
                    "The opening arc must contain at least one long_term_antagonist_traces item.",
                    "chapter_number values must exactly equal prompt_context.target_chapter_numbers in order.",
                    "Every name in every chapter cast must exactly equal a name in characters.",
                    "Every character must have non-empty identity_profile.origin, identity_profile.current_identity, identity_profile.occupation, story_drive.immediate_goal, and story_drive.failure_stakes.",
                    *trope_validation_rules,
                ]

            validation_rules.append(financial_outline_rule)
            validation_rules.extend(power_contract_rules)
            if chapter_contracts_enabled:
                validation_rules.append(CHAPTER_CONTRACT_RULE)
            is_game_story = effective_novel_type_id == "game_webnovel"
            if is_game_story:
                validation_rules.extend(
                    [
                        "Every core arc must state a concrete game_line_payoff and reality_line_payoff.",
                        "Assign each core arc a pacing_stage_id from genre_outline_template.arc.pacing_stages, keep stage order, and cover all four stages across the core outline.",
                        "Treat pacing stage reference_range values as scalable references: compress or expand them to planned_length and planned_arc_count without padding repetitive progress.",
                    ]
                )
            if validated.continuation_start_chapter is not None and mode != "extend":
                validation_rules.extend(
                    [
                        "The overall outline must cover the whole book: imported history, the continuation point, future development, and the intended ending.",
                        "Provide evidence-backed historical arcs covering chapters 1 through continuation_start_chapter, plus future arcs after that boundary.",
                        "Detailed chapter outlines must contain only target_chapter_numbers after continuation_start_chapter.",
                        "core_ending_chapter and extension_ceiling_chapter describe the whole book and must not equal the end of the current detail batch merely because that batch ends there.",
                    ]
                )

            existing_outline = deepcopy(validated.existing_outline)
            existing_outline.pop("overall", None)
            if not chapter_contracts_enabled:
                _drop_chapter_contracts_from_outline(existing_outline)
            if mode == "regenerate" and validated.continuation_start_chapter is not None:
                boundary = int(validated.continuation_start_chapter)
                existing_outline["arcs"] = [
                    arc
                    for arc in existing_outline.get("arcs", [])
                    if isinstance(arc, dict)
                    and isinstance(arc.get("end_chapter"), int)
                    and not isinstance(arc.get("end_chapter"), bool)
                    and int(arc["end_chapter"]) <= boundary
                ]
                existing_outline["chapters"] = [
                    chapter
                    for chapter in existing_outline.get("chapters", [])
                    if isinstance(chapter, dict)
                    and isinstance(chapter.get("chapter_number"), int)
                    and not isinstance(chapter.get("chapter_number"), bool)
                    and int(chapter["chapter_number"]) <= boundary
                ]
            existing_outline_chapters = [
                chapter
                for chapter in validated.existing_outline.get("chapters", [])
                if isinstance(chapter, dict)
            ]
            previous_chapters = select_previous_chapter_titles(
                existing_outline_chapters,
                target_start=min(target_chapter_numbers),
            )
            existing_window_chapters = select_chapter_title_neighbors(
                existing_outline_chapters,
                generated_chapter_numbers=target_chapter_numbers,
            )
            adjacent_existing_chapters = select_adjacent_chapter_titles(
                existing_window_chapters,
                generated_chapter_numbers=target_chapter_numbers,
            )
            chapter_title_strategy = build_chapter_title_guidance(
                effective_novel_type_id
            )
            prompt_context = {
                "mode": mode,
                **genre_context,
                "title": validated.title,
                "overall_context": validated.overall_context,
                "opening_direction": validated.opening_direction.model_dump(mode="json"),
                "author_constraints": validated.author_constraints,
                "existing_outline": existing_outline,
                "existing_characters": validated.existing_characters,
                "existing_character_names": existing_character_names,
                "current_chapter": validated.current_chapter,
                "recent_chapter_summaries": validated.recent_chapter_summaries,
                "continuation_start_chapter": validated.continuation_start_chapter,
                "historical_chapter_summaries": _compact_historical_chapter_summaries(
                    validated.historical_chapter_summaries
                ),
                "chapter_title_strategy": chapter_title_strategy,
                "previous_chapter_titles": previous_chapters,
                "existing_window_chapter_titles": adjacent_existing_chapters,
                "target_chapter_numbers": target_chapter_numbers,
                "current_strategy": validated.existing_outline.get("overall", {}).get(
                    "current_strategy", "observe"
                ),
                "one_time_guidance": normalized_guidance,
                "output_schema": chapter_output_schema(
                    GeneratedOutlinePlan,
                    require_chapter_contracts=chapter_contracts_enabled,
                ),
                "validation_rules": validation_rules,
            }
            outline_skill_context = (
                skill_pack_prompt_context(
                    validated.enabled_skill_ids,
                    enabled_module_ids=validated.enabled_skill_module_ids,
                    purpose="outline",
                    include_examples=True,
                    genre_id=effective_novel_type_id,
                    max_chars_per_pack=3600,
                    compact=True,
                    max_serialized_chars=_OUTLINE_SKILL_LIST_MAX_CHARS,
                )
                if validated.enabled_skill_ids
                else []
            )
            chapter_skill_context = (
                skill_pack_prompt_context(
                    validated.enabled_skill_ids,
                    enabled_module_ids=validated.enabled_skill_module_ids,
                    purpose="chapter_plan",
                    include_examples=True,
                    genre_id=effective_novel_type_id,
                    max_chars_per_pack=_CHAPTER_SKILL_CONTEXT_MAX_CHARS,
                    compact=True,
                    max_serialized_chars=_CHAPTER_SKILL_LIST_MAX_CHARS,
                )
                if validated.enabled_skill_ids
                else []
            )
            skill_method_guard = ""
            stage_skill_context: dict[str, Any] = {}
            if outline_skill_context:
                stage_skill_context["outline"] = outline_skill_context
            if chapter_skill_context:
                stage_skill_context["chapter_plan"] = chapter_skill_context
            if stage_skill_context:
                prompt_context["skill_context"] = stage_skill_context
                skill_method_guard = _OUTLINE_SKILL_GUARD
            if power_system:
                prompt_context["power_system"] = power_system
            dual_line_prompt = (
                "Every core arc must state a concrete game_line_payoff and reality_line_payoff, "
                "and assign pacing_stage_id from prompt_context.genre_outline_template.arc.pacing_stages in stage order. "
                if is_game_story
                else "For non-game stories, leave game_line_payoff and reality_line_payoff empty. "
            )
            chapter_contract_prompt = (
                f"{CHAPTER_CONTRACT_RULE} "
                if chapter_contracts_enabled
                else ""
            )
            payload = {
                "model": runtime.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"{skill_method_guard}"
                            f"{chapter_contract_prompt}"
                            f"{financial_outline_rule} "
                            f"{' '.join(power_contract_rules)} "
                            "Follow prompt_context.output_schema exactly. Do not add fields, rename fields, "
                            "or use values outside the declared enums. Return every required field. "
                            "chapter_number values must exactly equal prompt_context.target_chapter_numbers in order. "
                            "Generate chapter.title from the concrete events in that chapter and follow prompt_context.chapter_title_strategy. "
                            "For initial/regenerate, provide the complete core arcs through core_ending_chapter, but only those detailed chapters. "
                            "For extend, continue from committed facts and the active arc; obey current_strategy. "
                            "For extend, characters must contain only newly introduced character cards, while chapter cast may also use names from prompt_context.existing_character_names. "
                            f"{dual_line_prompt}"
                            "observe follows the core route, expand uses only the next continue_route, and close uses the active close_route. "
                            "Choose one overall.primary_trope_id from prompt_context.genre_trope_templates and one arc.trope_id per arc. "
                            "Use chapter.trope_beat only on milestone chapters. Its value must exactly equal a beat from that arc's template. "
                            "Do not assign trope_beat to every chapter. Do not change trope_id inside an arc. "
                            "Use null for overall.primary_trope_id, arc.trope_id, and chapter.trope_beat when prompt_context.genre_trope_templates is empty. "
                            "必须按 prompt_context.genre_outline_template 的总纲、分卷、章节三层要求逐项填写对应输出字段；"
                            "该模板属于当前题材，不得套用其他题材的结构或术语。"
                            "你负责生成中文长篇网文的结构化开书计划，不写正文。只返回 JSON，根字段必须是 "
                            "outline 和 characters。initial/regenerate 模式必须给出完整总纲和全部核心卷，"
                            "总纲必须写清主题命题、前台故事、后台故事、可验证的全书目标和终局画面；"
                            "还要填写核心卖点、长期主线、规划卷数与章数、扩展路线和收束路线。"
                            "每卷必须写清情绪曲线、三个可验证结果、核心循环、三次升级、中段转折、"
                            "卷末高潮、关系变化、伏笔承接与新埋伏笔，以及卷尾不可逆变化。"
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
            split_full_plan = runtime.protocol.endswith("_cli") and (
                mode == "initial"
                or (
                    mode == "regenerate"
                    and (
                        validated.current_chapter == 0
                        or validated.continuation_start_chapter is not None
                    )
                )
            )
            if split_full_plan:
                cached_phases = phase_payloads or {}

                def run_phase(
                    phase: str,
                    schema: type[BaseModel],
                    request_payload: dict[str, Any],
                    error_prefix: str,
                    invalid_json_error: str,
                    result_validator: Callable[[BaseModel], None] | None = None,
                ) -> BaseModel:
                    cached = cached_phases.get(phase)
                    if isinstance(cached, dict):
                        try:
                            cached_result = schema.model_validate(cached)
                            if result_validator:
                                result_validator(cached_result)
                            return cached_result
                        except Exception as exc:
                            detail = re.sub(r"\s+", " ", str(exc)).strip()[:500]
                            error = (
                                f"invalid_cached_{phase}:{type(exc).__name__}:"
                                f"{detail or 'no_detail'}"
                            )
                            if phase_callback:
                                phase_callback(phase, "failed", None, error)
                            # Regenerate only this invalid cached phase.  A
                            # structurally valid placeholder is not reusable.

                    if phase_callback:
                        phase_callback(phase, "running", None, "")
                    try:
                        response = _complete_payload(
                            self._model_gateway,
                            request_payload,
                            operation=f"outline_planning_{phase}",
                        )
                        data = parse_json_message_content(response)
                        validation_error = ""
                        result: BaseModel | None = None
                        if data is None:
                            validation_error = invalid_json_error
                        else:
                            try:
                                result = schema.model_validate(data)
                                if result_validator:
                                    result_validator(result)
                            except Exception as exc:
                                validation_error = re.sub(
                                    r"\s+", " ", str(exc)
                                ).strip()[:1000]
                                result = None
                        if result is None:
                            retry_payload = {
                                **request_payload,
                                "messages": [
                                    *request_payload.get("messages", []),
                                    {
                                        "role": "system",
                                        "content": (
                                            "The previous JSON failed schema validation. Correct only the reported "
                                            "format or missing-field problems, then return the complete JSON object "
                                            "again without markdown or commentary. Validation error: "
                                            f"{validation_error}"
                                        ),
                                    },
                                ],
                            }
                            response = _complete_payload(
                                self._model_gateway,
                                retry_payload,
                                operation=f"outline_planning_{phase}_retry",
                            )
                            data = parse_json_message_content(response)
                            if data is None:
                                raise ValueError(invalid_json_error)
                            result = schema.model_validate(data)
                            if result_validator:
                                result_validator(result)
                        if phase_callback:
                            phase_callback(phase, "completed", result.model_dump(mode="json"), "")
                        return result
                    except Exception as exc:
                        detail = re.sub(r"\s+", " ", str(exc)).strip()[:500]
                        error = (
                            f"{error_prefix}:{type(exc).__name__}"
                            f":{detail or 'no_detail'}"
                        )
                        if phase_callback:
                            phase_callback(phase, "failed", None, error)
                        raise ValueError(error) from exc

                outline_context = {
                    **prompt_context,
                    "generation_phase": "outline",
                    "target_chapter_numbers": [],
                    "output_schema": chapter_output_schema(
                        GeneratedOutlineFoundation,
                        require_chapter_contracts=False,
                    ),
                    "validation_rules": [
                        rule
                        for rule in validation_rules
                        if rule != CHAPTER_CONTRACT_RULE
                    ],
                }
                outline_context.pop("chapter_title_strategy", None)
                outline_context.pop("previous_chapter_titles", None)
                outline_context.pop("existing_window_chapter_titles", None)
                if outline_skill_context:
                    outline_context["skill_context"] = {
                        "outline": outline_skill_context
                    }
                else:
                    outline_context.pop("skill_context", None)
                outline_payload = {
                    **payload,
                    "reasoning_effort": "low",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                f"{_OUTLINE_SKILL_GUARD if outline_skill_context else ''}"
                                "Generate only the story structure as JSON with the single root field outline. "
                                "Fill overall fields including theme_statement, foreground_story, background_story, "
                                "book_objective, ending_image, core_ending_chapter, extension_ceiling_chapter, "
                                "planned_length, and planned_arc_count. core_ending_chapter must equal the end_chapter "
                                "of the final core arc; extension_ceiling_chapter must be at least core_ending_chapter. "
                                "Each arc must contain exactly three key_results. "
                                "Every arc stage_antagonist must be a concrete personal name, never a role, occupation, "
                                "faction, or placeholder label; put that information in the character card later. "
                                "Provide the complete overall plan and all core arcs. Set outline.chapters to an empty array. "
                                "Follow prompt_context.output_schema exactly."
                            ),
                        },
                        {"role": "user", "content": json.dumps(outline_context, ensure_ascii=False)},
                    ],
                }

                def validate_foundation_detail(result: BaseModel) -> None:
                    if stop_after_phase != "outline_foundation":
                        return
                    outline = getattr(result, "outline", None)
                    arcs = getattr(outline, "arcs", [])
                    boundary = max(0, int(validated.current_chapter))
                    problems: list[str] = []
                    for arc in arcs:
                        if int(arc.end_chapter) <= boundary:
                            continue
                        missing = [
                            field
                            for field in (
                                "goal",
                                "obstacle",
                                "payoff",
                                "stage_antagonist",
                                "core_loop",
                                "midpoint_turn",
                                "climax",
                            )
                            if not str(getattr(arc, field, "") or "").strip()
                        ]
                        if len([item for item in arc.escalations if str(item).strip()]) < 2:
                            missing.append("escalations")
                        if not any(str(item).strip() for item in arc.active_long_term_lines):
                            missing.append("active_long_term_lines")
                        if missing:
                            problems.append(f"{arc.id}({','.join(missing)})")
                    if problems:
                        raise ValueError(
                            "incomplete_future_arc_detail:" + ";".join(problems)
                        )

                outline_foundation_model = run_phase(
                    "outline_foundation",
                    GeneratedOutlineFoundation,
                    outline_payload,
                    "outline_generation_failed",
                    "invalid_outline_json",
                    validate_foundation_detail,
                )
                outline_foundation = outline_foundation_model.model_dump(mode="json")
                outline_foundation["outline"]["chapters"] = []
                if stop_after_phase == "outline_foundation":
                    return GeneratedOutlinePlan.model_validate(
                        {
                            "outline": outline_foundation["outline"],
                            "characters": [],
                        }
                    )

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
                        "Every character name must be a concrete personal name, never a role, occupation, faction, or placeholder label.",
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
                                "Use concrete personal names; keep roles and occupations in their dedicated fields. "
                                "Follow prompt_context.output_schema exactly."
                            ),
                        },
                        {"role": "user", "content": json.dumps(character_context, ensure_ascii=False)},
                    ],
                }
                character_roster = run_phase(
                    "character_roster",
                    GeneratedCharacterRoster,
                    character_payload,
                    "character_generation_failed",
                    "invalid_character_json",
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
                        {"name": card["name"], "role": card["role"], "character_tier": card["character_tier"]}
                        for card in foundation_data["characters"]
                    ],
                    "genre_trope_templates": trope_candidates,
                    "chapter_outline_template": outline_template.get("chapter", {}),
                    "chapter_title_strategy": chapter_title_strategy,
                    "previous_chapter_titles": previous_chapters,
                    "existing_window_chapter_titles": adjacent_existing_chapters,
                    "target_chapter_numbers": target_chapter_numbers,
                    "output_schema": chapter_output_schema(
                        GeneratedChapterWindow,
                        require_chapter_contracts=chapter_contracts_enabled,
                    ),
                    "validation_rules": [
                        "Return exactly one chapter for every target_chapter_numbers value, in order.",
                        "Every cast name must exactly match one name in characters.",
                        "Use trope_beat only on a milestone that fits the active arc.",
                        financial_outline_rule,
                        *(
                            [CHAPTER_CONTRACT_RULE]
                            if chapter_contracts_enabled
                            else []
                        ),
                    ],
                }
                if chapter_skill_context:
                    chapter_context["skill_context"] = {
                        "chapter_plan": chapter_skill_context
                    }
                chapter_character_names = {
                    str(card["name"]).strip()
                    for card in foundation_data["characters"]
                    if str(card.get("name") or "").strip()
                }
                chapter_payload = {
                    **payload,
                    "reasoning_effort": "low",
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                f"{_OUTLINE_SKILL_GUARD if chapter_skill_context else ''}"
                                f"{chapter_contract_prompt}"
                                "Generate only the requested Chinese webnovel chapter outline window. "
                                "Fill each chapter using prompt_context.chapter_outline_template. "
                                "Generate chapter.title from the concrete events in that chapter and follow prompt_context.chapter_title_strategy. "
                                "Return JSON with the single root field chapters. Do not repeat overall, arcs, or character cards. "
                                "Follow prompt_context.output_schema and target_chapter_numbers exactly."
                            ),
                        },
                        {"role": "user", "content": json.dumps(chapter_context, ensure_ascii=False)},
                    ],
                }

                def validate_chapter_window_contracts(result: BaseModel) -> None:
                    chapters = getattr(result, "chapters", [])
                    for chapter in chapters:
                        for name in chapter.cast:
                            if name not in chapter_character_names:
                                raise ValueError(f"missing_character_card:{name}")
                    if chapter_contracts_enabled:
                        for chapter in chapters:
                            validate_concrete_chapter_contract(chapter)
                    validate_chapter_title_window(
                        [chapter.model_dump(mode="python") for chapter in chapters],
                        genre_id=effective_novel_type_id,
                        previous_chapters=previous_chapters,
                        known_chapters=existing_window_chapters,
                        generated_chapter_numbers=target_chapter_numbers,
                    )

                chapter_window = run_phase(
                    "chapter_window",
                    GeneratedChapterWindow,
                    chapter_payload,
                    "chapter_window_generation_failed",
                    "invalid_chapter_window_json",
                    validate_chapter_window_contracts,
                )
                # Plan rule: the rolling-only fields must not
                # enter the three-level outline schema. Project
                # the row back through ``ChapterPlan`` so the
                # generation-only keys are silently dropped. The
                # legacy ``ChapterPlan`` rejects ``extra="forbid"``
                # fields, so we explicitly strip the rolling keys
                # before re-validating.
                _ROLLING_CHAPTER_KEYS = (
                    "core_conflict",
                    "gain",
                    "cost",
                    "foreshadowing",
                    "state_delta_summary",
                    "scene_chain",
                )
                foundation_data["outline"]["chapters"] = [
                    ChapterPlan.model_validate(
                        {
                            key: value
                            for key, value in chapter.model_dump(mode="python").items()
                            if key not in _ROLLING_CHAPTER_KEYS
                        }
                    ).model_dump(mode="json")
                    for chapter in chapter_window.chapters
                ]
                parsed = foundation_data
                split_plan_completed = True
            else:
                def parse_direct_outline(response: dict[str, Any]) -> dict[str, Any]:
                    candidate = parse_json_message_content(response)
                    if candidate is None:
                        raise ValueError("invalid_json")
                    candidate_plan = GeneratedOutlinePlan.model_validate(candidate)
                    validate_chapter_title_window(
                        [
                            chapter.model_dump(mode="python")
                            for chapter in candidate_plan.outline.chapters
                        ],
                        genre_id=effective_novel_type_id,
                        previous_chapters=previous_chapters,
                        known_chapters=existing_window_chapters,
                        generated_chapter_numbers=target_chapter_numbers,
                    )
                    return candidate

                try:
                    response = _complete_payload(
                        self._model_gateway,
                        payload,
                        operation="outline_planning",
                    )
                    parsed = parse_direct_outline(response)
                except Exception as exc:
                    validation_error = re.sub(r"\s+", " ", str(exc)).strip()[:1000]
                    retry_payload = {
                        **payload,
                        "messages": [
                            *payload.get("messages", []),
                            {
                                "role": "system",
                                "content": (
                                    "The previous JSON failed schema or chapter-title validation. "
                                    "Correct only the reported problems, then return the complete JSON object "
                                    "again without markdown or commentary. Validation error: "
                                    f"{validation_error}"
                                ),
                            },
                        ],
                    }
                    response = _complete_payload(
                        self._model_gateway,
                        retry_payload,
                        operation="outline_planning_retry",
                    )
                    parsed = parse_direct_outline(response)
            if not chapter_contracts_enabled:
                _drop_disabled_chapter_contracts(parsed)
            parsed = sanitize_generated_outline_amounts(parsed)
            if preserve_unlocked_legacy_tropes:
                _preserve_unlocked_legacy_tropes(
                    parsed,
                    validated.existing_outline,
                )
            _drop_invalid_optional_trope_beats(
                parsed,
                trope_candidates,
                fallback_outline=(
                    validated.existing_outline if mode != "initial" else None
                ),
            )
            if is_game_story:
                _validate_game_dual_line_payoffs(GeneratedOutlinePlan.model_validate(parsed))
            else:
                _clear_non_game_dual_line_payoffs(parsed)
            if mode == "extend":
                return validate_generated_continuation_plan(
                    parsed,
                    expected_chapter_numbers=target_chapter_numbers,
                    existing_character_names=set(existing_character_names),
                    trope_templates=trope_candidates,
                    expected_primary_trope_id=expected_primary_trope_id,
                    fallback_outline=validated.existing_outline,
                    require_chapter_contracts=chapter_contracts_enabled,
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
                require_chapter_contracts=chapter_contracts_enabled,
            )
        except Exception as exc:
            if split_plan_completed and phase_callback:
                detail = re.sub(r"\s+", " ", str(exc)).strip()[:500]
                phase_callback(
                    "chapter_window",
                    "failed",
                    None,
                    f"combined_outline_validation_failed:{type(exc).__name__}:{detail or 'no_detail'}",
                )
            if isinstance(exc, ValueError):
                error = str(exc)
                if error in {
                    "regeneration_guidance_too_long",
                    "initial_outline_requires_unstarted_project",
                    "outline_window_already_full",
                }:
                    raise
            raise ValueError("outline_planning_generation_failed") from exc
