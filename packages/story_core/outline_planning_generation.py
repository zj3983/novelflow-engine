from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from packages.story_core.agent_base import parse_json_message_content
from packages.story_core.attribute_allocation import normalize_attribute_allocation_rule
from packages.story_core.character_profiles import (
    character_profile_quality_issues,
    find_character_homogeneity_issues,
    normalize_speech_style_for_writing,
)
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
    get_outline_planning_settings,
    resolve_stage_runtime,
)
from packages.story_core.skill_packs import skill_pack_prompt_context
from packages.story_core.title_strategy import (
    build_chapter_title_guidance,
    select_adjacent_chapter_titles,
    select_all_existing_chapter_titles,
    select_chapter_title_neighbors,
    select_previous_chapter_titles,
    validate_chapter_title_window,
)
from packages.story_core.project_outline import (
    ArcOutline,
    ChapterPlan,
    ChapterScenePlan,
    ProjectOutline,
    select_outline_context,
)
from packages.story_core.volume_outline import (
    MIN_VOLUME_CHAPTERS,
    validate_volume_structure,
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
    include_attribute_allocation: bool = True,
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
    if not include_attribute_allocation:
        for definition in chapter_definitions:
            properties = definition.get("properties")
            if isinstance(properties, dict):
                properties.pop("attribute_allocation_decision", None)
            required = definition.get("required")
            if isinstance(required, list):
                definition["required"] = [
                    field_name
                    for field_name in required
                    if field_name != "attribute_allocation_decision"
                ]
        definitions.pop("AttributeAllocationDecision", None)
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


def _drop_disabled_attribute_allocations(payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    chapters = payload.get("chapters")
    if not isinstance(chapters, list):
        outline = payload.get("outline")
        chapters = outline.get("chapters") if isinstance(outline, dict) else None
    if not isinstance(chapters, list):
        return
    for chapter in chapters:
        if isinstance(chapter, dict):
            chapter.pop("attribute_allocation_decision", None)


def _drop_unknown_chapter_batch_fields(payload: Any) -> None:
    """Ignore planner notes that are not part of the persisted detail schema."""

    if not isinstance(payload, dict):
        return
    chapters = payload.get("chapters")
    if not isinstance(chapters, list):
        return
    chapter_fields = set(GeneratedDetailedChapter.model_fields)
    scene_fields = set(ChapterScenePlan.model_fields)
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        for key in list(chapter):
            if key not in chapter_fields:
                chapter.pop(key, None)
        scenes = chapter.get("scene_chain")
        if not isinstance(scenes, list):
            continue
        for scene in scenes:
            if not isinstance(scene, dict):
                continue
            for key in list(scene):
                if key not in scene_fields:
                    scene.pop(key, None)


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


def validate_next_volume(
    candidate: ArcOutline | dict[str, Any],
    *,
    previous_volume: ArcOutline | dict[str, Any] | None,
    allow_short_final: bool,
) -> ArcOutline:
    """Validate a single open-ended successor with the shared volume rules.

    ``previous_volume=None`` signals the project's first (bootstrap) volume.
    The validator then:
    * pins ``expected_start = 1`` instead of deriving from a prior arc,
    * drops the 50-chapter whole-book minimum so the user can pick a short
      bootstrap length for a brand-new project.
    """

    if previous_volume is not None:
        previous = (
            previous_volume
            if isinstance(previous_volume, ArcOutline)
            else ArcOutline.model_validate(previous_volume)
        )
        expected_start = previous.end_chapter + 1
        enforce_minimum_length = True
    else:
        previous = None
        expected_start = 1
        enforce_minimum_length = False
    volume = candidate if isinstance(candidate, ArcOutline) else ArcOutline.model_validate(candidate)
    if volume.start_chapter != expected_start:
        raise ValueError("next_volume_start_mismatch")
    if volume.is_final_arc and not allow_short_final:
        raise ValueError("unexpected_final_volume")
    if (
        enforce_minimum_length
        and not volume.is_final_arc
        and volume.end_chapter - volume.start_chapter + 1 < MIN_VOLUME_CHAPTERS
    ):
        raise ValueError(f"volume_too_short:{volume.id}")

    required_text = {
        "goal": volume.goal,
        "obstacle": volume.obstacle,
        "midpoint_turn": volume.midpoint_turn,
        "climax": volume.climax,
        "payoff": volume.payoff,
        "irreversible_change": volume.irreversible_change,
        "end_state": volume.end_state,
    }
    for field, value in required_text.items():
        if not value.strip():
            raise ValueError(f"next_volume_content_missing:{volume.id}:{field}")
    if not any(
        "cost" in str(item).lower() or "代价" in str(item)
        for item in volume.key_results
    ):
        raise ValueError(f"next_volume_content_missing:{volume.id}:cost")
    if not volume.is_final_arc and not volume.extension_gate.continue_route.strip():
        raise ValueError(f"next_volume_entry_missing:{volume.id}")

    # The shared validator models a closed whole-book outline. A newly designed
    # non-final volume is intentionally open-ended, so validate an offset copy as
    # the temporary last volume while preserving the real final marker above.
    offset = volume.start_chapter - 1
    projected = volume.model_dump(mode="json")
    projected["start_chapter"] = 1
    projected["end_chapter"] = volume.end_chapter - offset
    projected["is_final_arc"] = True
    projected["story_nodes"] = [
        {
            **node,
            "start_chapter": int(node["start_chapter"]) - offset,
            "end_chapter": int(node["end_chapter"]) - offset,
        }
        for node in projected["story_nodes"]
    ]
    validate_volume_structure(
        [projected],
        core_ending_chapter=int(projected["end_chapter"]),
    )
    return volume


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


def _outline_planning_timeout_seconds() -> int | None:
    """Per-call timeout for outline planning; big single-shot plans need it."""

    return get_outline_planning_settings().timeout_seconds


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
            timeout_seconds=_outline_planning_timeout_seconds(),
            metadata={"stream": get_outline_planning_settings().stream},
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
    world_facts: list[Any] = Field(default_factory=list)
    continuity_facts: list[Any] = Field(default_factory=list)
    committed_facts: list[Any] = Field(default_factory=list)
    unresolved_foreshadowing: list[Any] = Field(default_factory=list)
    character_current_states: list[dict[str, Any]] = Field(default_factory=list)
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

    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    obstacle: str = Field(min_length=1)
    action: str = Field(min_length=1)
    turn: str = Field(min_length=1)
    payoff: str = Field(min_length=1)
    ending_hook: str = Field(min_length=1)
    cast: list[str] = Field(min_length=1)
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


class PlanningRelationshipSeed(_PlanningInput):
    target: str = Field(min_length=1, max_length=80)
    relation_type: str = Field(min_length=1, max_length=80)
    history: str = Field(min_length=1, max_length=300)
    current_attitude: str = Field(min_length=1, max_length=300)
    shared_interest_or_conflict: str = Field(min_length=1, max_length=300)
    known_facts: list[str] = Field(default_factory=list, max_length=6)
    unknown_facts: list[str] = Field(default_factory=list, max_length=6)


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
    motivation: str = Field(min_length=1, max_length=300)
    long_term_goal: str = Field(default="", max_length=300)
    failure_stakes: str = Field(min_length=1, max_length=300)
    personality: str = Field(min_length=1, max_length=300)
    speech_style: str = Field(min_length=1, max_length=200)
    action_style: str = Field(min_length=1, max_length=200)
    emotional_trigger: str = Field(default="", max_length=200)
    decision_rule: str = Field(min_length=1, max_length=200)
    hidden_matter: str = Field(default="", max_length=300)
    dialogue_examples: list[str] = Field(min_length=2, max_length=2)
    relationship_notes: list[PlanningRelationshipSeed] = Field(min_length=1, max_length=6)


_CHINESE_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000}
_HISTORY_EVENT_WORDS = (
    "献祭", "失踪", "战争", "灭门", "事故", "灾难", "旧案", "血案", "入侵", "政变", "大劫",
)
_PERSONAL_HISTORY_MARKERS = (
    "亲历", "见证", "参与", "主导", "发动", "反对", "签署", "镇压", "主持", "策划",
)
_HISTORY_INHERITANCE_MARKERS = (
    "前世", "转世", "轮回", "重生", "分身", "后人", "后代", "先祖", "家族", "传闻", "记载", "记录",
)
_YEARS_AGO_PATTERN = re.compile(r"([0-9]{1,4}|[零〇一二两三四五六七八九十百千]{1,8})年前")


def _parse_year_count(raw: str) -> int | None:
    if raw.isdigit():
        return int(raw)
    total = 0
    pending = 0
    for char in raw:
        if char in _CHINESE_DIGITS:
            pending = _CHINESE_DIGITS[char]
            continue
        unit = _CHINESE_UNITS.get(char)
        if unit is None:
            return None
        total += (pending or 1) * unit
        pending = 0
    return total + pending


def _validate_character_seed_chronology(seed: PlanningCharacterSeed) -> None:
    """Reject obvious age/history contradictions before cards enter the outline."""

    fields = (
        seed.origin,
        seed.immediate_problem,
        seed.immediate_goal,
        seed.motivation,
        seed.long_term_goal,
        seed.hidden_matter,
        *(note.history for note in seed.relationship_notes),
    )
    clauses = [
        clause.strip()
        for value in fields
        for clause in re.split(r"[。！？；;!?]", str(value or ""))
        if clause.strip()
    ]
    event_dates: dict[str, set[int]] = {}
    for clause in clauses:
        offsets = {
            years
            for match in _YEARS_AGO_PATTERN.finditer(clause)
            if (years := _parse_year_count(match.group(1))) is not None
        }
        if not offsets:
            continue
        for event in _HISTORY_EVENT_WORDS:
            if event in clause:
                event_dates.setdefault(event, set()).update(offsets)
        if (
            seed.age is not None
            and any(marker in clause for marker in _PERSONAL_HISTORY_MARKERS)
            and not any(marker in clause for marker in _HISTORY_INHERITANCE_MARKERS)
            and any(years >= seed.age for years in offsets)
        ):
            raise ValueError(f"character_age_precedes_personal_history:{seed.name}")
    for event, offsets in event_dates.items():
        if len(offsets) > 1:
            raise ValueError(f"character_event_date_conflict:{seed.name}:{event}")


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
                "motivation": seed.motivation,
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
            "relationship_notes": [
                note.model_dump(mode="json") for note in seed.relationship_notes
            ],
        }
    )


def _character_card_roster_quality_issues(
    cards: list[Any],
    *,
    existing_names: set[str] | None = None,
) -> dict[str, list[str]]:
    payloads = [
        card.model_dump(mode="json") if isinstance(card, BaseModel) else deepcopy(card)
        for card in cards
        if isinstance(card, (BaseModel, dict))
    ]
    known_names = {
        str(name).strip() for name in (existing_names or set()) if str(name).strip()
    } | {
        str(card.get("name") or "").strip()
        for card in payloads
        if str(card.get("name") or "").strip()
    }
    issues: dict[str, list[str]] = {}
    for card in payloads:
        name = str(card.get("name") or "").strip() or "<unnamed>"
        current = list(character_profile_quality_issues(card))
        relations = [
            note
            for note in card.get("relationship_notes", [])
            if isinstance(note, dict)
        ]
        if not relations:
            current.append("missing:relationship_notes")
        else:
            links_roster = False
            for note in relations:
                target = str(note.get("target") or "").strip()
                if target == name:
                    current.append("relationship_targets_self")
                elif target in known_names:
                    links_roster = True
            if not links_roster:
                current.append("relationship_notes_missing_roster_link")
        if current:
            issues[name] = list(dict.fromkeys(current))

    for name, duplicate_issues in find_character_homogeneity_issues(payloads).items():
        issues.setdefault(name, []).extend(duplicate_issues)
        issues[name] = list(dict.fromkeys(issues[name]))
    return issues


def _validate_character_card_roster_quality(
    cards: list[Any],
    *,
    existing_names: set[str] | None = None,
) -> None:
    issues = _character_card_roster_quality_issues(
        cards,
        existing_names=existing_names,
    )
    if not issues:
        return
    detail = ";".join(
        f"{name}[{','.join(values)}]" for name, values in sorted(issues.items())
    )
    raise ValueError(f"character_profile_quality_failed:{detail}")


def _validate_character_seed_roster_quality(
    seeds: list[PlanningCharacterSeed],
    *,
    existing_names: set[str] | None = None,
) -> None:
    _validate_character_card_roster_quality(
        [_expand_character_seed(seed) for seed in seeds],
        existing_names=existing_names,
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


def _fill_equivalent_arc_handoffs(payload: dict[str, Any]) -> None:
    """Reuse an explicit next-volume entry when the duplicate hook field is blank."""

    outline = payload.get("outline")
    if not isinstance(outline, dict):
        return
    for arc in outline.get("arcs", []):
        if not isinstance(arc, dict) or str(arc.get("hook_plan") or "").strip():
            continue
        extension_gate = arc.get("extension_gate")
        continue_route = (
            str(extension_gate.get("continue_route") or "").strip()
            if isinstance(extension_gate, dict)
            else ""
        )
        replacement = str(arc.get("next_arc_entry") or "").strip() or continue_route
        if replacement:
            arc["hook_plan"] = replacement


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

    def generate_next_volume(
        self,
        brief: OutlinePlanningBrief,
        *,
        previous_volume: dict[str, Any] | None = None,
        guidance: str = "",
    ) -> ArcOutline:
        """Design one successor volume without generating chapter detail.

        ``previous_volume=None`` means the bootstrap volume for a brand-new
        project.  The model is told to start at chapter 1, no prior volume
        is referenced, and the 50-chapter whole-book length floor is
        dropped so the user can pick a short bootstrap length.
        """

        validated = OutlinePlanningBrief.model_validate(brief)
        normalized_guidance = str(guidance or "").strip()
        if len(normalized_guidance) > 1000:
            raise ValueError("regeneration_guidance_too_long")

        runtime = self._runtime_resolver("planner")
        if runtime.provider not in {"codexcli", "antigravity"} and not runtime.api_key:
            raise ValueError("runtime_unavailable")
        overall = deepcopy(validated.overall_context)
        strategy = str(overall.get("current_strategy") or "observe")
        allow_short_final = strategy == "close"
        if previous_volume is not None:
            previous = (
                previous_volume
                if isinstance(previous_volume, ArcOutline)
                else ArcOutline.model_validate(previous_volume)
            )
            required_start_chapter = previous.end_chapter + 1
            is_bootstrap = False
        else:
            previous = None
            required_start_chapter = 1
            is_bootstrap = True
        context = {
            "generation_phase": "next_volume",
            "title": validated.title,
            "novel_type_id": validated.novel_type_id,
            "overall": overall,
            "existing_volumes": deepcopy(
                validated.existing_outline.get("arcs", [])
                if isinstance(validated.existing_outline, dict)
                else []
            ),
            "committed_facts": deepcopy(validated.committed_facts),
            "world_facts": deepcopy(validated.world_facts),
            "continuity_facts": deepcopy(validated.continuity_facts),
            "recent_chapter_summaries": deepcopy(
                validated.recent_chapter_summaries
            ),
            "historical_chapter_summaries": deepcopy(
                validated.historical_chapter_summaries
            ),
            "power_system_spec": deepcopy(validated.power_system_spec),
            "opening_direction": validated.opening_direction.model_dump(mode="json"),
            "author_constraints": list(validated.author_constraints),
            "existing_characters": deepcopy(validated.existing_characters),
            "existing_character_names": list(validated.existing_character_names),
            "unresolved_foreshadowing": deepcopy(
                validated.unresolved_foreshadowing
            ),
            "character_current_states": deepcopy(
                validated.character_current_states
            ),
            "required_start_chapter": required_start_chapter,
            "allow_short_final_volume": allow_short_final,
            "is_bootstrap_volume": is_bootstrap,
            "guidance": normalized_guidance,
            "output_schema": ArcOutline.model_json_schema(),
            "validation_rules": [
                "Return exactly one volume object; do not return chapters or character cards.",
                "start_chapter must equal required_start_chapter.",
                "A non-bootstrap, non-final volume must cover at least 50 chapters; the bootstrap volume may be any length the user requested.",
                "story_nodes must cover the whole volume continuously in blocks of at most 15 chapters.",
                "The volume must provide goal, obstacle, midpoint turn, climax, payoff, explicit cost, irreversible change, and end_state.",
                "A non-final volume must leave a concrete extension_gate.continue_route and next-effect entry.",
                "Set is_final_arc only when allow_short_final_volume is true and the story is actually closing.",
            ],
        }
        if previous is not None:
            context["previous_volume"] = previous.model_dump(mode="json")
            context["previous_volume_end_state"] = previous.end_state
        payload = {
            "model": runtime.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Design exactly one successor volume for a Chinese long-form webnovel. "
                        "Use only the supplied canon and return one ArcOutline JSON object. "
                        "Do not generate chapter detail, prose, or character cards. "
                        "If is_bootstrap_volume is true, this is the first volume "
                        "of a brand-new project — start at required_start_chapter "
                        "(=1), invent a coherent opening arc, and do not invent "
                        "a prior volume."
                    ),
                },
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
                "max_tokens": 12000,
            "temperature": float(runtime.temperature),
        }
        response = _complete_payload(
            self._model_gateway,
            payload,
            operation="outline_planning_next_volume",
        )
        data = parse_json_message_content(response)
        if data is None:
            raise ValueError("invalid_next_volume_json")
        return validate_next_volume(
            data,
            previous_volume=previous,
            allow_short_final=allow_short_final,
        )

    def generate_volume_characters(
        self,
        brief: OutlinePlanningBrief,
        *,
        volume: dict[str, Any],
        guidance: str = "",
    ) -> list[PlanningCharacterCard]:
        """Create cards for important named characters introduced by one volume."""

        validated = OutlinePlanningBrief.model_validate(brief)
        arc = ArcOutline.model_validate(volume)
        normalized_guidance = str(guidance or "").strip()
        if len(normalized_guidance) > 1000:
            raise ValueError("regeneration_guidance_too_long")

        runtime = self._runtime_resolver("planner")
        if runtime.provider not in {"codexcli", "antigravity"} and not runtime.api_key:
            raise ValueError("runtime_unavailable")
        existing_names = {
            str(name).strip()
            for name in validated.existing_character_names
            if str(name).strip()
        }
        existing_volume_names = {
            str(card.get("name") or "").strip()
            for card in validated.existing_characters
            if isinstance(card, dict)
            and str(card.get("name") or "").strip()
            and isinstance(card.get("first_appearance"), int)
            and not isinstance(card.get("first_appearance"), bool)
            and arc.start_chapter
            <= int(card["first_appearance"])
            <= arc.end_chapter
        }
        existing_volume_character_count = len(existing_volume_names)
        max_new_characters = max(0, min(10, 15 - existing_volume_character_count))
        number_word = (
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
        )[max_new_characters]
        context = {
            "generation_phase": "volume_characters",
            "title": validated.title,
            "novel_type_id": validated.novel_type_id,
            "volume": arc.model_dump(mode="json"),
            "volume_range": [arc.start_chapter, arc.end_chapter],
            "story_nodes": [node.model_dump(mode="json") for node in arc.story_nodes],
            "existing_characters": deepcopy(validated.existing_characters),
            "existing_character_names": list(validated.existing_character_names),
            "existing_volume_character_count": existing_volume_character_count,
            "max_new_characters": max_new_characters,
            "world_facts": deepcopy(validated.world_facts),
            "continuity_facts": deepcopy(validated.continuity_facts),
            "author_constraints": list(validated.author_constraints),
            "guidance": normalized_guidance,
            "output_schema": GeneratedCharacterRoster.model_json_schema(),
            "validation_rules": [
                "Return only important named people who first appear in this volume and do not already have a card.",
                f"Return zero to {number_word} characters; do not pad the roster.",
                "A normal 50-chapter volume should have 10 to 15 active or newly introduced named people in total; generate only the missing people needed to reach a useful cast.",
                "Include a new stage antagonist or recurring ally when the fixed volume needs one.",
                "Every new card must attach to a concrete story node and have a recurring conflict, relationship, information, resource, or real-life function; do not create one-scene function labels.",
                "Names must be concrete personal names, never placeholders, occupations, factions, crowds, monsters, or generic labels such as commander, guard, elder, or manager.",
                "first_appearance must fall inside volume_range.",
                "Do not redesign the volume, story nodes, world, or existing characters.",
                "motivation must explain why immediate_goal matters and must not repeat or paraphrase immediate_goal.",
                "relationship_notes must contain at least one concrete tie to an existing or newly generated named character, including history, current attitude, and shared interest or conflict.",
                "For supporting characters, role should name the recurring narrative function such as ally, rival, mentor, resource contact, or relationship anchor instead of only saying supporting.",
                "Dialogue examples must be complete, natural Chinese utterances suited to the relationship and situation.",
            ],
        }
        payload = {
            "model": runtime.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Generate only the new named-character roster required by one fixed "
                        "Chinese webnovel volume. Return JSON with the single root field "
                        "characters. Do not generate chapters, prose, groups, unnamed roles, "
                        "or replacements for existing characters. Every character must have an independent "
                        "motivation that explains why the immediate goal matters, plus at least one concrete "
                        "relationship note linked to the existing or newly generated cast."
                    ),
                },
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
                "max_tokens": 12000,
            "temperature": float(runtime.temperature),
        }
        response = _complete_payload(
            self._model_gateway,
            payload,
            operation="outline_planning_volume_characters",
        )
        data = parse_json_message_content(response)
        if data is None:
            raise ValueError("invalid_volume_character_json")
        roster = GeneratedCharacterRoster.model_validate(data)
        new_seeds = [
            seed for seed in roster.characters if seed.name.strip() not in existing_names
        ]
        if len(new_seeds) > max_new_characters:
            raise ValueError("too_many_volume_characters")

        result: list[PlanningCharacterCard] = []
        generated_names: set[str] = set()
        for seed in new_seeds:
            name = seed.name.strip()
            _validate_character_seed_chronology(seed)
            if name in generated_names:
                raise ValueError(f"duplicate_volume_character:{name}")
            if not arc.start_chapter <= seed.first_appearance <= arc.end_chapter:
                raise ValueError(f"volume_character_first_appearance_out_of_range:{name}")
            generated_names.add(name)
            result.append(_expand_character_seed(seed))
        _validate_character_seed_roster_quality(
            new_seeds,
            existing_names=existing_names,
        )
        return result

    def generate_chapter_batch(
        self,
        brief: OutlinePlanningBrief,
        *,
        volume: dict[str, Any],
        chapter_numbers: list[int],
        previous_batches: list[dict[str, Any]],
        adjacent_chapters: list[dict[str, Any]] | None = None,
        committed_context: dict[str, Any] | None = None,
        guidance: str = "",
    ) -> GeneratedChapterWindow:
        """Generate one resumable chapter-detail batch inside a fixed volume."""

        validated = OutlinePlanningBrief.model_validate(brief)
        if not isinstance(volume, dict):
            raise ValueError("invalid_volume")
        volume_id = str(volume.get("id") or "").strip()
        start = volume.get("start_chapter")
        end = volume.get("end_chapter")
        if (
            not volume_id
            or not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 1
            or end < start
        ):
            raise ValueError("invalid_volume")
        if (
            not isinstance(chapter_numbers, list)
            or not chapter_numbers
            or len(chapter_numbers) > 15
            or any(
                not isinstance(number, int)
                or isinstance(number, bool)
                or number < start
                or number > end
                for number in chapter_numbers
            )
            or chapter_numbers != sorted(set(chapter_numbers))
        ):
            raise ValueError("invalid_chapter_batch")
        normalized_guidance = str(guidance or "").strip()
        if len(normalized_guidance) > 1000:
            raise ValueError("regeneration_guidance_too_long")

        runtime = self._runtime_resolver("planner")
        if runtime.provider not in {"codexcli", "antigravity"} and not runtime.api_key:
            raise ValueError("runtime_unavailable")
        genre = runtime_novel_type(validated.novel_type_id)
        if genre is None:
            raise ValueError("invalid_novel_type")
        genre_context = novel_type_prompt_context(genre)
        outline_template = genre_context.get("genre_outline_template")
        if not isinstance(outline_template, dict) or not outline_template:
            raise ValueError("outline_template_missing")
        genre_id = canonical_novel_type_id(
            getattr(genre, "id", None) or validated.novel_type_id
        )

        all_nodes = [
            dict(node)
            for node in volume.get("story_nodes", [])
            if isinstance(node, dict)
        ]
        current_nodes = [
            node
            for node in all_nodes
            if int(node.get("start_chapter") or 0) <= chapter_numbers[-1]
            and int(node.get("end_chapter") or 0) >= chapter_numbers[0]
        ]
        previous_endings: list[dict[str, Any]] = []
        for batch in previous_batches:
            chapters = batch.get("chapters") if isinstance(batch, dict) else None
            if not isinstance(chapters, list) or not chapters:
                continue
            last = chapters[-1]
            if not isinstance(last, dict):
                continue
            previous_endings.append(
                {
                    "chapter_number": last.get("chapter_number"),
                    "title": last.get("title"),
                    "ending_hook": last.get("ending_hook") or last.get("hook"),
                    "state_delta_summary": (
                        last.get("state_delta_summary") or last.get("state_delta")
                    ),
                }
            )
        existing_chapters = [
            dict(chapter)
            for chapter in validated.existing_outline.get("chapters", [])
            if isinstance(chapter, dict)
        ]
        previous_batch_chapters: list[dict[str, Any]] = []
        for batch in previous_batches:
            if isinstance(batch, dict) and isinstance(batch.get("chapters"), list):
                previous_batch_chapters.extend(
                    [c for c in batch["chapters"] if isinstance(c, dict)]
                )
        all_known_titles = select_all_existing_chapter_titles(
            existing_chapters,
            previous_batch_chapters,
            adjacent_chapters,
        )
        previous_titles = select_previous_chapter_titles(
            [*existing_chapters, *previous_endings],
            target_start=chapter_numbers[0],
        )
        known_titles = select_adjacent_chapter_titles(
            existing_chapters,
            generated_chapter_numbers=chapter_numbers,
        )
        contracts_enabled = (
            validated.enabled_skill_module_ids is None
            and CHAPTER_SOP_MODULE_ID.split("::", 1)[0]
            in validated.enabled_skill_ids
        ) or CHAPTER_SOP_MODULE_ID in {
            str(module_id).strip()
            for module_id in (validated.enabled_skill_module_ids or [])
        }
        attribute_allocation_enabled = bool(
            normalize_attribute_allocation_rule(
                validated.power_system_spec.get("attribute_allocation")
                if isinstance(validated.power_system_spec, dict)
                else None
            )
        )
        all_character_first_appearances = {
            str(card.get("name") or "").strip(): int(
                card.get("first_appearance") or 0
            )
            for card in validated.existing_characters
            if isinstance(card, dict) and str(card.get("name") or "").strip()
        }
        batch_end = chapter_numbers[-1]
        visible_characters = [
            deepcopy(card)
            for card in validated.existing_characters
            if isinstance(card, dict)
            and (
                int(card.get("first_appearance") or 0) <= 0
                or int(card.get("first_appearance") or 0) <= batch_end
            )
        ]
        visible_character_names = [
            name
            for name in validated.existing_character_names
            if int(all_character_first_appearances.get(str(name).strip()) or 0) <= 0
            or int(all_character_first_appearances.get(str(name).strip()) or 0)
            <= batch_end
        ]
        character_first_appearances = {
            name: first_appearance
            for name, first_appearance in all_character_first_appearances.items()
            if first_appearance <= 0 or first_appearance <= batch_end
        }
        context = {
            "generation_phase": "volume_chapter_batch",
            "title": validated.title,
            "novel_type_id": genre_id,
            "volume": deepcopy(volume),
            "target_chapter_numbers": list(chapter_numbers),
            "current_batch_story_nodes": current_nodes,
            "previous_batch_endings": previous_endings,
            "adjacent_chapters": deepcopy(adjacent_chapters or []),
            "committed_context": {
                "overall": deepcopy(validated.overall_context),
                "recent_chapter_summaries": deepcopy(
                    validated.recent_chapter_summaries
                ),
                "historical_chapter_summaries": deepcopy(
                    validated.historical_chapter_summaries
                ),
                "existing_characters": visible_characters,
                "known_character_names": visible_character_names,
                "character_first_appearances": character_first_appearances,
                "power_system": deepcopy(validated.power_system_spec),
                "world_facts": deepcopy(validated.world_facts),
                "continuity_facts": deepcopy(validated.continuity_facts),
                "committed_facts": deepcopy(validated.committed_facts),
                **deepcopy(committed_context or {}),
            },
            "required_volume_ending": str(
                volume.get("climax")
                or volume.get("end_state")
                or volume.get("payoff")
                or ""
            ).strip(),
            "guidance": normalized_guidance,
            "chapter_outline_template": outline_template.get("chapter", {}),
            "chapter_title_strategy": build_chapter_title_guidance(genre_id),
            "previous_chapter_titles": previous_titles,
            "existing_window_chapter_titles": known_titles,
            "existing_book_chapter_titles": all_known_titles,
            "output_schema": chapter_output_schema(
                GeneratedChapterWindow,
                require_chapter_contracts=contracts_enabled,
                include_attribute_allocation=attribute_allocation_enabled,
            ),
            "validation_rules": [
                "Return exactly the target_chapter_numbers in order.",
                "Use the fixed volume and story nodes; do not redesign arcs or volume boundaries.",
                "Every cast entry must use a name from committed_context.known_character_names; do not invent unnamed roles or new people here.",
                "Do not use a character before the chapter listed in committed_context.character_first_appearances.",
                "Carry forward previous_batch_endings and committed_context.",
                "Use adjacent_chapters as fixed handoff context for sparse gaps.",
                "The final batch must satisfy required_volume_ending.",
            ],
        }
        def complete_batch(
            prompt_context: dict[str, Any], *, operation: str
        ) -> GeneratedChapterWindow:
            payload = {
                "model": runtime.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Generate only one Chinese webnovel chapter-detail batch. "
                            "The supplied volume structure is fixed: you must not redesign, "
                            "replace, resize, or reorder the volume or its story nodes. "
                            "Every chapter title must sound like a natural Chinese novel "
                            "chapter title tied to a concrete event, choice, conflict, or "
                            "result. 禁止报告式标题，例如‘调查记录’‘阶段报告’‘线索预告’"
                            "‘任务总结’；不要把大纲字段名或工作说明当标题。"
                            "严禁与prompt_context.existing_book_chapter_titles中已有的任何全书章节标题重名。"
                            "Return JSON with the single root field chapters. Follow "
                            "prompt_context.output_schema and target_chapter_numbers exactly."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(prompt_context, ensure_ascii=False),
                    },
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 12000,
                "temperature": float(runtime.temperature),
            }
            response = _complete_payload(
                self._model_gateway,
                payload,
                operation=operation,
            )
            data = parse_json_message_content(response)
            if data is None:
                raise ValueError("invalid_chapter_batch_json")
            _drop_unknown_chapter_batch_fields(data)
            if not attribute_allocation_enabled:
                _drop_disabled_attribute_allocations(data)
            result = GeneratedChapterWindow.model_validate(data)
            actual = [chapter.chapter_number for chapter in result.chapters]
            if actual != chapter_numbers:
                raise ValueError("generated_chapters_do_not_match_target_batch")
            if contracts_enabled:
                for chapter in result.chapters:
                    validate_concrete_chapter_contract(chapter)
            return result

        def validate_titles(result: GeneratedChapterWindow) -> None:
            validate_chapter_title_window(
                [chapter.model_dump(mode="python") for chapter in result.chapters],
                genre_id=genre_id,
                previous_chapters=previous_titles,
                known_chapters=all_known_titles,
                generated_chapter_numbers=chapter_numbers,
            )

        def repair_rejected_titles(
            result: GeneratedChapterWindow,
            *,
            validation_error: str,
        ) -> GeneratedChapterWindow:
            matched_numbers = [
                int(value)
                for value in re.findall(r"\d+", validation_error)
                if int(value) in chapter_numbers
            ]
            target_numbers = sorted(set(matched_numbers)) or list(chapter_numbers)
            repair_rows = [
                {
                    "chapter_number": chapter.chapter_number,
                    "title": chapter.title,
                    "goal": chapter.goal,
                    "action": chapter.action,
                    "turn": chapter.turn,
                    "payoff": chapter.payoff,
                    "ending_hook": chapter.ending_hook,
                }
                for chapter in result.chapters
                if chapter.chapter_number in target_numbers
            ]
            forbidden_titles = [
                row["title"]
                for row in all_known_titles
                if isinstance(row, dict)
                and row.get("chapter_number") not in target_numbers
                and row.get("title")
            ] + [
                chapter.title
                for chapter in result.chapters
                if chapter.chapter_number not in target_numbers and chapter.title
            ]
            repair_context = {
                "validation_error": validation_error,
                "target_chapters": repair_rows,
                "chapter_title_strategy": build_chapter_title_guidance(genre_id),
                "neighbor_titles": [
                    {
                        "chapter_number": chapter.chapter_number,
                        "title": chapter.title,
                    }
                    for chapter in result.chapters
                    if chapter.chapter_number not in target_numbers
                ],
                "forbidden_existing_titles": forbidden_titles,
                "output_schema": {
                    "titles": [
                        {"chapter_number": number, "title": "自然中文章节名"}
                        for number in target_numbers
                    ]
                },
            }
            payload = {
                "model": runtime.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "只改标题，不改章节事件。根据每章已有的具体行动、选择、冲突、"
                            "结果和章末钩子，为指定章节重写自然中文章名。禁止‘调查记录’"
                            "‘阶段报告’‘线索预告’‘任务总结’‘情况说明’等报告式标题。"
                            "严禁使用forbidden_existing_titles中已有的任何章节标题（不得重名）。"
                            "只返回 JSON，根字段为 titles。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(repair_context, ensure_ascii=False),
                    },
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 12000,
                "temperature": float(runtime.temperature),
            }
            response = _complete_payload(
                self._model_gateway,
                payload,
                operation="outline_planning_chapter_title_repair",
            )
            data = parse_json_message_content(response)
            title_rows = data.get("titles") if isinstance(data, dict) else None
            if not isinstance(title_rows, list):
                raise ValueError("invalid_chapter_title_repair_json")
            repaired_titles: dict[int, str] = {}
            for row in title_rows:
                if not isinstance(row, dict):
                    continue
                number = row.get("chapter_number")
                title = str(row.get("title") or "").strip()
                if (
                    isinstance(number, int)
                    and not isinstance(number, bool)
                    and number in target_numbers
                    and title
                ):
                    repaired_titles[number] = title
            if sorted(repaired_titles) != target_numbers:
                raise ValueError("chapter_title_repair_numbers_mismatch")
            repaired = result.model_copy(
                update={
                    "chapters": [
                        chapter.model_copy(
                            update={"title": repaired_titles[chapter.chapter_number]}
                        )
                        if chapter.chapter_number in repaired_titles
                        else chapter
                        for chapter in result.chapters
                    ]
                }
            )
            validate_titles(repaired)
            return repaired

        try:
            result = complete_batch(
                context,
                operation="outline_planning_chapter_batch",
            )
        except ValidationError as exc:
            validation_error = str(exc).strip()
            retry_context = deepcopy(context)
            retry_context["correction_request"] = {
                "validation_error": validation_error,
                "instruction": (
                    "Regenerate the complete target batch once. Fill every required "
                    "chapter field with concrete content, especially cast, goal, "
                    "ending_hook, and state_delta_summary. Preserve the fixed volume, "
                    "chapter numbers, story-node events, and previous-batch handoff."
                ),
            }
            result = complete_batch(
                retry_context,
                operation="outline_planning_chapter_batch_retry",
            )

        try:
            validate_titles(result)
            return result
        except ValueError as exc:
            validation_error = str(exc).strip()
            retryable_title_errors = (
                "report_like_chapter_title:",
                "repeated_chapter_title_shape:",
                "repeated_chapter_title_pattern:",
                "duplicate_chapter_title:",
            )
            title_rejected = validation_error.startswith(retryable_title_errors)
            if not title_rejected:
                raise
            try:
                return repair_rejected_titles(
                    result,
                    validation_error=validation_error,
                )
            except ValueError as repair_exc:
                repaired_error = str(repair_exc).strip()
                if not repaired_error.startswith(retryable_title_errors):
                    raise
                return repair_rejected_titles(
                    result,
                    validation_error=(
                        f"{validation_error}; first title repair was also rejected: "
                        f"{repaired_error}"
                    ),
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
        attribute_allocation_enabled = bool(
            normalize_attribute_allocation_rule(
                validated.power_system_spec.get("attribute_allocation")
                if isinstance(validated.power_system_spec, dict)
                else None
            )
        )
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
                        else min(
                            validated.current_chapter
                            + INITIAL_OUTLINE_CHAPTER_COUNT,
                            window["target_last_chapter"],
                        )
                    )
                    target_chapter_numbers = list(
                        range(validated.current_chapter + 1, target_last_chapter + 1)
                    )
                if not target_chapter_numbers:
                    raise ValueError("outline_window_already_full")
            else:
                assert window is not None
                detail_batches = window.get("detail_batches") or []
                target_chapter_numbers = (
                    list(detail_batches[0]) if detail_batches else []
                )
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
                mode in {"extend", "regenerate"}
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
                    "Every new character must have non-empty identity_profile.origin, identity_profile.current_identity, identity_profile.occupation, story_drive.immediate_goal, story_drive.motivation, story_drive.failure_stakes, and at least one relationship_notes entry; motivation must explain why the goal matters and must not repeat immediate_goal.",
                    *trope_validation_rules,
                ]
            else:
                validation_rules = [
                    "For initial/regenerate, characters must contain 10 to 15 unique names for the first planned volume, with exactly one protagonist, at least one stage_antagonist, at least one long_term_antagonist, and at least five supporting characters.",
                    "The supporting cast must cover recurring cooperation, peer competition, information or resources, and a relationship or reality-line anchor when the premise has a reality line; every card needs a concrete recurring story function.",
                    "Every character name and every arc stage_antagonist must be a concrete personal name, never a role, occupation, faction, or placeholder label.",
                    "The opening arc must start at chapter 1, and its stage_antagonist must be exactly equal to the name of the character whose character_tier is stage_antagonist.",
                    "The opening arc must contain at least one long_term_antagonist_traces item.",
                    "chapter_number values must exactly equal prompt_context.target_chapter_numbers in order.",
                    "Every name in every chapter cast must exactly equal a name in characters.",
                    "Every character must have non-empty identity_profile.origin, identity_profile.current_identity, identity_profile.occupation, story_drive.immediate_goal, story_drive.motivation, story_drive.failure_stakes, and at least one relationship_notes entry; motivation must explain why the goal matters and must not repeat immediate_goal.",
                    *trope_validation_rules,
                ]

            validation_rules.append(financial_outline_rule)
            validation_rules.extend(power_contract_rules)
            validation_rules.extend(
                [
                    "Chapter fields must use neutral event planning, not finished prose, similes, camera directions, sensory-density instructions, or stock emotional gestures.",
                    "must_include may lock only plot facts, objects, actions, information, or results; it must not prescribe prose style, graphic injury detail, gore intensity, or repeated sensory description.",
                    "Arcs are complete book volumes, not short plot beats. Every non-final volume must span at least 50 chapters; only the actual closing volume may be shorter.",
                    "Use story_nodes for the smaller payoff cycles inside a volume. They must cover the volume continuously, and each story_node may span at most 15 chapters.",
                    "overall.planned_arc_count counts complete volumes, not story_nodes or pacing stages.",
                    "Every future volume must fill goal, obstacle, payoff, emotional_curve, hook_plan, irreversible_change, end_state, stage_antagonist, core_loop, escalations, midpoint_turn, climax, and active_long_term_lines.",
                ]
            )
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
                    include_attribute_allocation=attribute_allocation_enabled,
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
                            "但细纲只能覆盖目标章节，并给出10至15张具体角色卡。角色卡必须恰好1位主角，并包括阶段对手、长期反派和至少5位重要配角，"
                            "并写清年龄或身份、来历、职业、当前生活、即时目标、独立动机、失败代价、具体人物关系、可观察行为和两句自然对白。"
                            "immediate_goal 写角色现在要做什么，motivation 写为什么这件事对他重要，两者不得同义复述；每张新角色卡至少有一条 relationship_notes。"
                            "阶段对手要有现实利益和权力边界；长期反派只把允许露出的痕迹写进大纲。"
                            "章节字段为 chapter_number/title/goal/obstacle/action/turn/payoff/ending_hook/cast。"
                            "extend 模式只生成 target_chapter_numbers 指定的缺章，并只补充确实要出场的新角色卡。"
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt_context, ensure_ascii=False)},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": 12000,
                "temperature": float(runtime.temperature),
            }
            split_full_plan = (
                runtime.protocol.endswith("_cli")
                or get_outline_planning_settings().split_phases
            ) and (
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
                        if data is not None and not attribute_allocation_enabled:
                            _drop_disabled_attribute_allocations(data)
                        if isinstance(data, dict):
                            _fill_equivalent_arc_handoffs(data)
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
                            invalid_response = (
                                json.dumps(data, ensure_ascii=False, separators=(",", ":"))
                                if isinstance(data, dict)
                                else "{}"
                            )
                            retry_payload = {
                                **request_payload,
                                "messages": [
                                    *request_payload.get("messages", []),
                                    {
                                        "role": "assistant",
                                        "content": invalid_response,
                                    },
                                    {
                                        "role": "system",
                                        "content": (
                                            "The JSON immediately above failed schema validation. Edit that object "
                                            "to correct only the reported structural or missing-field problems, then return the complete JSON object "
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
                            if not attribute_allocation_enabled:
                                _drop_disabled_attribute_allocations(data)
                            _fill_equivalent_arc_handoffs(data)
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
                        include_attribute_allocation=attribute_allocation_enabled,
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
                                "Treat arcs as complete book volumes: every non-final arc spans at least 50 chapters, "
                                "and only the actual closing arc may be shorter. Put shorter plot beats in story_nodes, "
                                "cover the whole volume continuously, and keep every story_node within 15 chapters. "
                                "planned_arc_count counts volumes, not story_nodes or pacing stages. "
                                "Fill every arc's goal, obstacle, payoff, emotional_curve, hook_plan, "
                                "irreversible_change, end_state, stage_antagonist, core_loop, escalations, "
                                "midpoint_turn, climax, and active_long_term_lines with concrete content. "
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
                    outline = getattr(result, "outline", None)
                    arcs = getattr(outline, "arcs", [])
                    if validated.current_chapter == 0:
                        validate_volume_structure(
                            arcs,
                            core_ending_chapter=int(outline.overall.core_ending_chapter),
                        )
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
                                "emotional_curve",
                                "hook_plan",
                                "irreversible_change",
                                "end_state",
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
                    "world_facts": deepcopy(validated.world_facts),
                    "continuity_facts": deepcopy(validated.continuity_facts),
                    "target_chapter_numbers": [],
                    "output_schema": GeneratedCharacterRoster.model_json_schema(),
                    "validation_rules": [
                        "Return 10 to 15 unique complete character cards for the first planned volume.",
                        "Include protagonist, stage_antagonist, long_term_antagonist, and supporting tiers.",
                        "Return exactly one protagonist and at least five supporting characters.",
                        "The supporting cast must cover a recurring ally or partner, a peer rival or competitor, a resource or information contact, and a relationship or reality-line anchor when the premise has a reality line.",
                        "Each card must have a concrete first-volume story function and enough recurring pressure or relationship value to appear more than once; do not pad with one-scene function labels.",
                        "Every character name must be a concrete personal name, never a role, occupation, faction, or placeholder label.",
                        "The stage_antagonist name must match the opening arc stage_antagonist.",
                        "Personality describes decisions and behavior; it must not command clipped prose or emotionless dialogue.",
                        "speech_style and dialogue_examples must use complete natural Chinese speech. Do not use 简短、短句、惜字如金、毫无情绪 or similar labels as dialogue instructions.",
                        "Occupation defines what a character knows and does, not how every sentence sounds. speech_style must describe an everyday voice that changes with relationship, emotion, and situation; it is not a professional resume.",
                        "Dialogue examples must first respond to the other person and sound like ordinary conversation. Use professional terms only when the immediate topic requires them; do not turn every line into a report, policy statement, technical explanation, or interrogation.",
                        "Copy organization, faction, location, historical-event, and era names exactly from outline_foundation and world_facts; do not invent near-synonyms.",
                        "A character cannot personally witness, oppose, lead, or sign an event that happened before their current age unless reincarnation or inherited memory is explicitly established.",
                        "Do not assign two different dates to the same historical event inside one card.",
                        "motivation must explain the concrete history, pressure, desire, fear, obligation, or stake that makes immediate_goal matter; it must not copy immediate_goal.",
                        "Every card must include at least one relationship_notes entry linked to another character in this roster, with concrete history, current attitude, and shared interest or conflict.",
                        "Do not reuse the same motivation, long-term goal, speech style, or action style across multiple characters.",
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
                                "Create 10 to 15 complete Chinese webnovel character cards for the first planned volume that fit outline_foundation. "
                                "Use concrete personal names; keep roles and occupations in their dedicated fields. "
                                "Describe how each person decides, reacts, and speaks without turning restraint into clipped dialogue. "
                                "Treat occupation as a knowledge and action boundary, not a permanent speaking tone. "
                                "speech_style must describe everyday speech across different relationships and emotions, not a professional resume. "
                                "Dialogue examples must be complete natural Chinese utterances that answer the immediate conversation before adding needed reasons or attitude. "
                                "Professional terms belong only in scenes where the current topic requires them. "
                                "immediate_goal is what the character is trying to do now; motivation is why that goal matters to this person, and the two must not repeat each other. "
                                "Every card must include at least one concrete relationship note linked to another generated character, with history, current attitude, and a shared interest or conflict. "
                                "Do not give multiple characters identical motivation, long-term goal, speech style, or action style. "
                                "Follow prompt_context.output_schema exactly."
                            ),
                        },
                        {"role": "user", "content": json.dumps(character_context, ensure_ascii=False)},
                    ],
                }
                def validate_opening_character_roster(result: BaseModel) -> None:
                    characters = getattr(result, "characters", [])
                    if not 10 <= len(characters) <= 15:
                        raise ValueError("character_count_out_of_range")
                    tier_counts = {
                        tier: sum(
                            card.character_tier == tier for card in characters
                        )
                        for tier in (
                            "protagonist",
                            "stage_antagonist",
                            "long_term_antagonist",
                            "supporting",
                        )
                    }
                    if tier_counts["protagonist"] != 1:
                        raise ValueError("invalid_protagonist_count")
                    for tier in ("stage_antagonist", "long_term_antagonist"):
                        if tier_counts[tier] < 1:
                            raise ValueError(f"missing_character_tier:{tier}")
                    if tier_counts["supporting"] < 5:
                        raise ValueError("insufficient_supporting_characters")
                    for character in characters:
                        _validate_character_seed_chronology(character)
                    _validate_character_seed_roster_quality(list(characters))

                character_roster = run_phase(
                    "character_roster",
                    GeneratedCharacterRoster,
                    character_payload,
                    "character_generation_failed",
                    "invalid_character_json",
                    validate_opening_character_roster,
                )
                foundation_data = {
                    "outline": outline_foundation["outline"],
                    "characters": [
                        _expand_character_seed(seed).model_dump(mode="json")
                        for seed in character_roster.characters
                    ],
                }

                target_start = min(target_chapter_numbers)
                target_end = max(target_chapter_numbers)
                chapter_foundation = deepcopy(foundation_data["outline"])
                active_arcs: list[dict[str, Any]] = []
                active_story_nodes: list[dict[str, Any]] = []
                for raw_arc in chapter_foundation.get("arcs", []):
                    if not isinstance(raw_arc, dict):
                        continue
                    arc_start = int(raw_arc.get("start_chapter") or 0)
                    arc_end = int(raw_arc.get("end_chapter") or 0)
                    if arc_start > target_end or arc_end < target_start:
                        continue
                    active_arc = deepcopy(raw_arc)
                    current_nodes = [
                        deepcopy(node)
                        for node in raw_arc.get("story_nodes", [])
                        if isinstance(node, dict)
                        and int(node.get("start_chapter") or 0) <= target_end
                        and int(node.get("end_chapter") or 0) >= target_start
                    ]
                    active_arc["story_nodes"] = current_nodes
                    active_story_nodes.extend(current_nodes)
                    if arc_end > target_end:
                        for future_field in (
                            "midpoint_turn",
                            "climax",
                            "payoff",
                            "end_state",
                            "hook_plan",
                        ):
                            active_arc.pop(future_field, None)
                    active_arcs.append(active_arc)
                chapter_foundation["arcs"] = active_arcs
                chapter_foundation["chapters"] = []
                unfinished_active_node = any(
                    int(node.get("end_chapter") or 0) > target_end
                    for node in active_story_nodes
                )

                chapter_context = {
                    "generation_phase": "chapters",
                    "title": validated.title,
                    "novel_type_id": effective_novel_type_id,
                    "opening_direction": validated.opening_direction.model_dump(mode="json"),
                    "author_constraints": validated.author_constraints,
                    "outline_foundation": chapter_foundation,
                    "active_story_nodes": active_story_nodes,
                    "window_guard": {
                        "target_start_chapter": target_start,
                        "target_end_chapter": target_end,
                        "must_not_complete_active_node": unfinished_active_node,
                    },
                    "characters": [
                        {
                            "name": card["name"],
                            "role": card["role"],
                            "character_tier": card["character_tier"],
                            "first_appearance": int(card.get("first_appearance") or 0),
                        }
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
                        include_attribute_allocation=attribute_allocation_enabled,
                    ),
                    "validation_rules": [
                        "Return exactly one chapter for every target_chapter_numbers value, in order.",
                        "Chapter fields must use neutral event planning, not finished prose, similes, camera directions, sensory-density instructions, or stock emotional gestures.",
                        "must_include may lock only plot facts, objects, actions, information, or results; it must not prescribe prose style, graphic injury detail, gore intensity, or repeated sensory description.",
                        "Every cast name must exactly match one name in characters.",
                        "Do not use a character before that character's first_appearance chapter.",
                        "Use trope_beat only on a milestone that fits the active arc.",
                        "Plan only active_story_nodes. Do not pull any later story node, volume climax, volume payoff, or volume end_state into this chapter window.",
                        "When window_guard.must_not_complete_active_node is true, the final target chapter must leave the active node unresolved for its remaining chapters.",
                        financial_outline_rule,
                        *(
                            [
                                "Chapter 1 must stage the inciting incident and first discovery on page; do not write the protagonist as already experienced with a newly acquired ability.",
                                "If opening_direction.core_advantage.limits names a cost, chapter 1 must make that cost observable in an action, result, payoff, or ending hook instead of omitting it.",
                                "Deliver the strongest opening promise early enough to affect chapter 1 when it belongs to the inciting incident; do not postpone it only to preserve an outline beat.",
                            ]
                            if 1 in target_chapter_numbers
                            else []
                        ),
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
                chapter_character_first_appearances = {
                    str(card["name"]).strip(): int(
                        card.get("first_appearance") or 0
                    )
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
                                "For chapter 1, preserve the difference between first discovery and practiced mastery, and visibly apply any stated ability cost. "
                                "Return JSON with the single root field chapters. Do not repeat overall, arcs, or character cards. "
                                "Follow prompt_context.output_schema and target_chapter_numbers exactly."
                            ),
                        },
                        {"role": "user", "content": json.dumps(chapter_context, ensure_ascii=False)},
                    ],
                }

                def validate_chapter_window_contracts(result: BaseModel) -> None:
                    chapters = getattr(result, "chapters", [])
                    generated_chapter_numbers = [
                        int(chapter.chapter_number) for chapter in chapters
                    ]
                    if generated_chapter_numbers != target_chapter_numbers:
                        raise ValueError(
                            "generated_chapters_do_not_match_target_window:"
                            f"expected={target_chapter_numbers}:"
                            f"actual={generated_chapter_numbers}"
                        )
                    for chapter in chapters:
                        for name in chapter.cast:
                            if name not in chapter_character_names:
                                raise ValueError(f"missing_character_card:{name}")
                            planned_first = chapter_character_first_appearances.get(
                                name, 0
                            )
                            if planned_first > 0 and chapter.chapter_number < planned_first:
                                raise ValueError(
                                    f"character_appears_before_card:{name}:"
                                    f"{chapter.chapter_number}:{planned_first}"
                                )
                    if chapter_contracts_enabled:
                        for chapter in chapters:
                            validate_concrete_chapter_contract(chapter)
                    validate_chapter_title_window(
                        [chapter.model_dump(mode="python") for chapter in chapters],
                        genre_id=effective_novel_type_id,
                        previous_chapters=previous_chapters,
                        known_chapters=existing_outline_chapters,
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
                    if not attribute_allocation_enabled:
                        _drop_disabled_attribute_allocations(candidate)
                    candidate_plan = GeneratedOutlinePlan.model_validate(candidate)
                    if (
                        mode == "initial"
                        or mode == "extend"
                        or (mode == "regenerate" and validated.current_chapter == 0)
                    ):
                        _validate_character_card_roster_quality(
                            list(candidate_plan.characters),
                            existing_names=(
                                set(existing_character_names) if mode == "extend" else set()
                            ),
                        )
                    validate_chapter_title_window(
                        [
                            chapter.model_dump(mode="python")
                            for chapter in candidate_plan.outline.chapters
                        ],
                        genre_id=effective_novel_type_id,
                        previous_chapters=previous_chapters,
                        known_chapters=existing_outline_chapters,
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
                enforce_full_opening_roster=(
                    mode == "initial" and validated.current_chapter == 0
                ),
                allow_established_roster=(mode == "regenerate"),
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
