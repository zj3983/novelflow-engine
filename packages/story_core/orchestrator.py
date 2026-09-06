from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from copy import deepcopy

import json
import inspect
import re
import subprocess
from time import perf_counter
from types import SimpleNamespace

from packages.story_core.agent_base import _parse_json_text, compact_list, compact_text
from packages.story_core.attribute_allocation import (
    apply_attribute_allocation,
    attribute_allocation_context,
    attribute_allocation_rule_from_story,
    award_attribute_points,
    current_protagonist_level,
    current_unallocated_attribute_points,
    parse_level,
    plan_handles_attribute_points,
    planned_level_target,
    validate_attribute_allocation_decision,
)
from packages.story_core.attribute_evidence import (
    character_evidence_names,
    character_aliases_by_name,
    character_update_names,
    protagonist_aliases_from_characters,
)
from packages.story_core.chapter_governance import build_chapter_governance, governance_quality_gate, review_chapter_governance
from packages.story_core.chapter_continuity import (
    departed_character_facts,
    has_return_transition,
    review_chinese_fragments,
    review_continuity_interface,
)
from packages.story_core.chapter_length_policy import (
    CHAPTER_HARD_MAX_CHARS,
    CHAPTER_HARD_MIN_CHARS as POLICY_HARD_MIN_CHARS,
    CHAPTER_TARGET_MAX_CHARS,
    CHAPTER_TARGET_MIN_CHARS,
    CHAPTER_TARGET_RANGE_TEXT,
)
from packages.story_core.chapter_planning import build_outline_chapter_plan
from packages.story_core.chapter_scope import first_chapter_trade_authorized
from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.chapter_plot_contract import build_chapter_plot_contract
from packages.story_core.craft import is_game_story
from packages.story_core.genre_stages.registry import genre_stage_profile_for
from packages.story_core.genre_stages.base import DirectorPlanReviewContext
from packages.story_core.genre_stages.common_writer import (
    WriterContext,
    _compact_world_context_for_prompt,
    _genre_context_for_prompt,
    _genre_context_summary_for_prompt,
    _skill_context_for_prompt,
    writer_skill_trace,
)
from packages.story_core.genre_stages.common_revision import RevisionContext, revision_char_ceiling
from packages.story_core.genre_stages.length_prompts import (
    LengthPromptContext,
    render_generic_polish_prompt,
)
from packages.story_core.genre_stages.postprocess import PostprocessContext
from packages.story_core.foreshadowing import select_unresolved_foreshadowing
from packages.story_core.generation_progress import report_generation_progress
from packages.story_core.pipeline.chapter_pipeline import ChapterPipeline, build_chapter_pipeline_event
from packages.story_core.pipeline.context_stage import (
    build_context_stage_events,
    planning_character_names as _pipeline_planning_character_names,
    prepare_chapter_context,
)
from packages.story_core.pipeline.planning_stage import resolve_chapter_plan
from packages.story_core.pipeline.simulation_stage import prepare_simulation_stage
from packages.story_core.pipeline.writing_stage import generate_chapter_body
from packages.story_core.pipeline.quality_stage import QualityStageCallbacks, run_quality_stage
from packages.story_core.pipeline.review_revision_stage import (
    ReviewRevisionCallbacks,
    ReviewRevisionResult,
    run_review_revision_stage,
)
from packages.story_core.review.contracts import ReviewResult
from packages.story_core.review.service import ReviewService
from packages.story_core.review.quality_gate import (
    ReviewDependencies,
    _build_world_state_review as _quality_build_world_state_review,
    _merge_world_state_reviews as _quality_merge_world_state_reviews,
    review_chapter_body as _run_review_quality_gate,
)
from packages.story_core.model_gateway import (
    ModelRequest,
    RuntimeModelGateway,
    normalize_model_error,
    provider_definition,
)
from packages.story_core.memory import (
    apply_post_chapter_updates,
    build_character_cards,
    build_foreshadowing,
    maybe_update_arc_recap,
    retrieve_relevant_memories,
)
from packages.story_core.models import DirectorDecision, StageRuntimeEntry, StoryState
from packages.story_core.novel_type_catalog import (
    normalize_novel_type_id,
    normalize_novel_type_ids,
    novel_type_prompt_context,
    runtime_novel_type,
)
from packages.story_core.planner import build_chapter_title, build_conflict_summary, build_event_beat, compute_chapter_cadence, plan_next_outline
from packages.story_core.post_draft_memory import (
    build_post_draft_memory_prompt,
    fallback_post_draft_memory,
    normalize_post_draft_memory,
)
from packages.story_core.adversarial_cut_review import build_expression_patch_suggestions, review_adversarial_cuts
from packages.story_core.ai_flavor_review import review_ai_flavor
from packages.story_core.cold_reader_review import review_cold_reader_experience
from packages.story_core.prose_quality_review import review_prose_quality
from packages.story_core.prose_rule_review import (
    CRITICAL_PROMPT_RULES,
    PROMPT_CRAFT_GUARDS,
    review_critical_prose_rules,
    review_director_result_leak,
)
from packages.story_core.prose_style_review import review_prose_style
from packages.story_core.character_portraits import build_scene_portrait_slice
from packages.story_core.reader_feel_review import review_reader_feel
from packages.story_core.plot_spine_review import review_plot_spine_completion
from packages.story_core.quality import validate_bundle
from packages.story_core.runtime import record_stage_runtime
from packages.story_core.runtime_config import resolve_stage_runtime
from packages.story_core.revision_safety import choose_best_revision
from packages.story_core.simplified_review import build_simplified_review
from packages.story_core.spot_fix_patch import apply_spot_fix_patches
from packages.story_core.style_coach import build_style_guidance
from packages.story_core.writing_learning import learning_snapshot, lessons_from_quality_report, merge_writing_lessons
from packages.story_core.writing_taskbook import (
    ensure_writing_taskbook,
    format_taskbook_brief_section,
    format_taskbook_prompt_section,
    writer_facing_text,
)
from packages.story_core.world_consistency_review import review_world_event_consistency
from packages.story_core.writing_packet import writing_power_system_context
from packages.story_core.world_pulse import advance_world_pulse
from packages.story_core.skill_packs import skill_pack_prompt_context
from packages.story_core.prompt_modules import replaceable_slots
from packages.story_core.prompt_templates import (
    get_effective_prompt_template,
    get_effective_prompt_template_source,
    render_prompt_template,
)
from packages.story_core.prompt_call_log import finish_prompt_call, start_prompt_call
from packages.story_core.dialogue_context import build_dialogue_context
from packages.story_core.memory import (
    apply_post_chapter_updates,
    build_character_cards,
    build_foreshadowing,
    maybe_update_arc_recap,
    retrieve_relevant_memories,
)
from packages.story_core.models import DirectorDecision, StageRuntimeEntry, StoryState
from packages.story_core.novel_type_catalog import (
    normalize_novel_type_id,
    normalize_novel_type_ids,
    novel_type_prompt_context,
    runtime_novel_type,
)
from packages.story_core.planner import build_chapter_title, build_conflict_summary, build_event_beat, compute_chapter_cadence, plan_next_outline
from packages.story_core.post_draft_memory import (
    build_post_draft_memory_prompt,
    fallback_post_draft_memory,
    normalize_post_draft_memory,
)
from packages.story_core.adversarial_cut_review import build_expression_patch_suggestions, review_adversarial_cuts
from packages.story_core.ai_flavor_review import review_ai_flavor
from packages.story_core.cold_reader_review import review_cold_reader_experience
from packages.story_core.prose_quality_review import review_prose_quality
from packages.story_core.prose_rule_review import (
    CRITICAL_PROMPT_RULES,
    PROMPT_CRAFT_GUARDS,
    review_critical_prose_rules,
    review_director_result_leak,
)
from packages.story_core.prose_style_review import review_prose_style
from packages.story_core.character_portraits import build_scene_portrait_slice
from packages.story_core.reader_feel_review import review_reader_feel
from packages.story_core.plot_spine_review import review_plot_spine_completion
from packages.story_core.quality import validate_bundle
from packages.story_core.runtime import record_stage_runtime
from packages.story_core.runtime_config import resolve_stage_runtime
from packages.story_core.revision_safety import choose_best_revision
from packages.story_core.simplified_review import build_simplified_review
from packages.story_core.spot_fix_patch import apply_spot_fix_patches
from packages.story_core.style_coach import build_style_guidance
from packages.story_core.writing_learning import learning_snapshot, lessons_from_quality_report, merge_writing_lessons
from packages.story_core.writing_taskbook import (
    ensure_writing_taskbook,
    format_taskbook_brief_section,
    format_taskbook_prompt_section,
    writer_facing_text,
)
from packages.story_core.world_consistency_review import review_world_event_consistency
from packages.story_core.writing_packet import writing_power_system_context
from packages.story_core.world_pulse import advance_world_pulse
from packages.story_core.skill_packs import skill_pack_prompt_context
from packages.story_core.prompt_modules import replaceable_slots
from packages.story_core.prompt_templates import (
    get_effective_prompt_template,
    get_effective_prompt_template_source,
    render_prompt_template,
)
from packages.story_core.prompt_call_log import finish_prompt_call, start_prompt_call
from packages.story_core.dialogue_context import build_dialogue_context
from packages.story_core.review_report import format_review_report
from packages.story_core.scene_contract_repair import build_scene_contract_repair_plan


_FORBIDDEN_REAL_CURRENCY_NAME = "\u4eba\u6c11\u5e01"
VALID_CADENCES = {"urgent", "measured", "breathing"}
MIN_CHAPTER_CHARS = CHAPTER_TARGET_MIN_CHARS
MAX_CHAPTER_CHARS = CHAPTER_TARGET_MAX_CHARS
CHAPTER_CHAR_TOLERANCE = 300
CHAPTER_MAX_CHAR_TOLERANCE = CHAPTER_HARD_MAX_CHARS - MAX_CHAPTER_CHARS
CHAPTER_HARD_MIN_CHARS = POLICY_HARD_MIN_CHARS
REGENERATION_MIN_CHARS = 3500
REGENERATION_FAST_MIN_CHARS = 3200
TARGET_CHAPTER_CHARS = CHAPTER_TARGET_RANGE_TEXT


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _expansion_timeout_seconds() -> int:
    return _env_int("NOVEL_EXPANSION_TIMEOUT_SECONDS", 720)


def _expansion_target_range(source_chars: int) -> tuple[int, int]:
    """Return ``(target_min, target_max)`` for an expansion pass on a chapter
    whose body is currently ``source_chars`` long.

    The expansion path is only invoked when the source body is too short
    (below :data:`MIN_CHAPTER_CHARS`), so ``target_min`` is the lower
    bound of the canonical chapter size (``CHAPTER_TARGET_MIN_CHARS``)
    and ``target_max`` is the upper bound (``CHAPTER_HARD_MAX_CHARS``).
    The pair is what the expansion prompt renders as
    "目标篇幅：{min}到{max}字（原文约{source_chars}字）", and
    the difference ``(target - source_chars)`` is the budget the model
    is asked to fill in.
    """
    try:
        current = int(source_chars)
    except (TypeError, ValueError):
        current = 0
    if current < 0:
        current = 0
    target_min = max(CHAPTER_TARGET_MIN_CHARS, current + 1)
    target_max = CHAPTER_HARD_MAX_CHARS
    return target_min, target_max


def _should_compress_chapter(body: str) -> bool:
    return _chapter_char_count(body) > MAX_CHAPTER_CHARS + CHAPTER_MAX_CHAR_TOLERANCE


def _chapter_body_is_hard_length_acceptable(body: str) -> bool:
    chars = _chapter_char_count(body)
    return CHAPTER_HARD_MIN_CHARS <= chars <= MAX_CHAPTER_CHARS + CHAPTER_MAX_CHAR_TOLERANCE


def _revision_char_ceiling(body: str) -> int:
    return revision_char_ceiling(body)


def _revision_max_tokens(body: str) -> int:
    return min(6200, _revision_char_ceiling(body) + 500)


def _expanded_body_is_acceptable(original_body: str, candidate_body: str) -> bool:
    original_chars = _chapter_char_count(original_body)
    candidate_chars = _chapter_char_count(candidate_body)
    return original_chars < candidate_chars and MIN_CHAPTER_CHARS - CHAPTER_CHAR_TOLERANCE <= candidate_chars <= MAX_CHAPTER_CHARS


def _expanded_body_is_progress(original_body: str, candidate_body: str) -> bool:
    original_chars = _chapter_char_count(original_body)
    candidate_chars = _chapter_char_count(candidate_body)
    return original_chars < candidate_chars


def _chapter_polish_mode(body: str) -> str:
    """Pick the adaptive length pass for a chapter body."""

    chars = _chapter_char_count(body)
    if chars < MIN_CHAPTER_CHARS:
        return "expand"
    if chars > MAX_CHAPTER_CHARS:
        return "shorten"
    return "polish"


def _compressed_body_is_acceptable(original_body: str, candidate_body: str) -> bool:
    original_chars = _chapter_char_count(original_body)
    candidate_chars = _chapter_char_count(candidate_body)
    return candidate_chars < original_chars and MIN_CHAPTER_CHARS - 10 <= candidate_chars <= MAX_CHAPTER_CHARS + CHAPTER_MAX_CHAR_TOLERANCE


def _compressed_body_is_progress(original_body: str, candidate_body: str) -> bool:
    original_chars = _chapter_char_count(original_body)
    candidate_chars = _chapter_char_count(candidate_body)
    return candidate_chars < original_chars and candidate_chars >= MIN_CHAPTER_CHARS - CHAPTER_CHAR_TOLERANCE


def _compression_candidate_action(original_body: str, candidate_body: str) -> str:
    if _compressed_body_is_acceptable(original_body, candidate_body):
        return "accept"
    candidate_chars = _chapter_char_count(candidate_body)
    original_chars = _chapter_char_count(original_body)
    if candidate_chars < original_chars and candidate_chars < MIN_CHAPTER_CHARS:
        return "retry"
    if _compressed_body_is_progress(original_body, candidate_body):
        return "continue"
    return "reject"


def _rebalanced_body_is_acceptable(short_body: str, candidate_body: str) -> bool:
    short_chars = _chapter_char_count(short_body)
    candidate_chars = _chapter_char_count(candidate_body)
    return (
        candidate_chars > short_chars
        and MIN_CHAPTER_CHARS - CHAPTER_CHAR_TOLERANCE <= candidate_chars <= MAX_CHAPTER_CHARS + CHAPTER_MAX_CHAR_TOLERANCE
    )


def _review_context_facts(story: StoryState) -> list[str]:
    outline_context = story.outline_context if isinstance(story.outline_context, dict) else {}
    outline_facts = [
        json.dumps(outline_context.get(key), ensure_ascii=False)
        for key in ("overall", "chapter")
        if isinstance(outline_context.get(key), dict)
    ]
    facts = [*story.world_facts, *story.author_constraints, *outline_facts]
    power_system = writing_power_system_context(story)
    if power_system:
        facts.extend(
            [
                f"力量体系审稿上下文：{json.dumps(power_system, ensure_ascii=False)}",
                "力量体系审稿检查：检查虚构技能或无依据能力、免费晋升和不可能的等级差；所有解锁与消耗必须能回写连续性记录。",
            ]
        )
    return list(dict.fromkeys(facts))


def _should_extract_final_memory(body: str, review_gate: dict[str, Any] | None) -> bool:
    chars = _chapter_char_count(body)
    gate = review_gate or {}
    status = str(gate.get("status") or "")
    if status == "blocked":
        review_blocks_memory = True
    elif "has_hard_errors" in gate:
        review_blocks_memory = bool(gate.get("has_hard_errors"))
    else:
        review_blocks_memory = bool(gate.get("needs_revision"))
    return MIN_CHAPTER_CHARS - CHAPTER_CHAR_TOLERANCE <= chars <= MAX_CHAPTER_CHARS + CHAPTER_MAX_CHAR_TOLERANCE and not review_blocks_memory


def _should_run_full_revision(review_gate: dict[str, Any] | None) -> bool:
    gate = review_gate or {}
    return bool(gate.get("needs_revision") and (gate.get("has_hard_errors") or gate.get("has_blocking_dialogue")))


def _compression_review_not_worse(
    before_review: dict[str, Any],
    candidate_review: dict[str, Any],
    *,
    before_body: str = "",
    candidate_body: str = "",
) -> bool:
    before_gate = build_simplified_review({"writing_review": before_review})
    candidate_gate = build_simplified_review({"writing_review": candidate_review})
    before_hard = int(before_gate.get("categories", {}).get("hard", {}).get("count") or 0)
    candidate_hard = int(candidate_gate.get("categories", {}).get("hard", {}).get("count") or 0)
    before_total = int(before_gate.get("total_issues") or 0)
    candidate_total = int(candidate_gate.get("total_issues") or 0)
    if before_body and _chapter_char_count(before_body) > MAX_CHAPTER_CHARS:
        before_hard += 1
        before_total += 1
    if candidate_body and _chapter_char_count(candidate_body) > MAX_CHAPTER_CHARS:
        candidate_hard += 1
        candidate_total += 1
    return candidate_hard <= before_hard and candidate_total <= before_total


def _review_reports_enabled() -> bool:
    value = os.getenv("NOVEL_AUTOGROWTH_REVIEW_REPORTS", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _review_report_output_dir() -> Path:
    configured = os.getenv("NOVEL_AUTOGROWTH_REVIEW_REPORTS_DIR", "").strip()
    return Path(configured) if configured else Path("chapter_exports")


def _persist_review_report(chapter_number: int, body: str, writing_review: dict[str, Any]) -> Path | None:
    if not _review_reports_enabled():
        return None
    try:
        output_dir = _review_report_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"review_ch{int(chapter_number):04d}.md"
        output_path.write_text(
            format_review_report(writing_review, chapter_number=chapter_number, body_chars=len(str(body or ""))),
            encoding="utf-8",
        )
        return output_path
    except Exception:
        return None


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


def _chapter_char_count(text: str) -> int:
    return len("".join(text.split()))


def _postprocess_chapter_output(
    story: StoryState,
    body: str,
    *,
    chapter_number: int,
    scene_cards: list[dict] | None = None,
    outline_anchor: Any = None,
) -> str:
    context = PostprocessContext(
        story=story,
        body=body,
        chapter_number=chapter_number,
        scene_cards=scene_cards or [],
        outline_anchor=outline_anchor,
    )
    return genre_stage_profile_for(story).postprocess_body(context=context)



def _priority_world_facts(facts: list[str], *, max_items: int, item_chars: int) -> list[str]:
    priority_tokens = (
        "人物关系",
        "世界规则",
        "时间线",
        "地点",
        "因果",
        "冲突",
        "连续性",
        "信息边界",
    )
    priority = [fact for fact in facts if any(token in fact for token in priority_tokens)]
    others = [fact for fact in facts if fact not in priority]
    return compact_list([*priority, *others], max_items=max_items, item_chars=item_chars)


def _compact_prompt_ledger(ledger: Any) -> dict[str, Any]:
    if not isinstance(ledger, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("protagonist", "economy", "equipment", "quests", "time", "simulation_variant"):
        value = ledger.get(key)
        if value not in (None, "", [], {}):
            result[key] = value
    world_pulse = ledger.get("world_pulse") if isinstance(ledger.get("world_pulse"), dict) else {}
    if world_pulse:
        result["world_pulse"] = _compact_world_pulse_for_prompt(world_pulse)
    inbox = ledger.get("visibility_inbox") if isinstance(ledger.get("visibility_inbox"), list) else []
    if inbox:
        result["visibility_inbox"] = inbox[-2:]
    return result


def _compact_character_cards_for_prompt(story: StoryState, *, max_items: int = 4) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for card in build_character_cards(story)[:max_items]:
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        profile = card.get("webnovel_profile") if isinstance(card.get("webnovel_profile"), dict) else {}
        usage = card.get("story_usage") if isinstance(card.get("story_usage"), dict) else {}
        voice = card.get("voice_and_action") if isinstance(card.get("voice_and_action"), dict) else {}
        locks = card.get("continuity_locks") if isinstance(card.get("continuity_locks"), dict) else {}
        relationships = locks.get("relationships") if isinstance(locks.get("relationships"), dict) else {}
        chapter_usage = usage.get("this_chapter_usage") if isinstance(usage.get("this_chapter_usage"), dict) else {}
        cards.append(
            {
                "identity": {
                    "name": identity.get("name", ""),
                    "role": identity.get("role", ""),
                    "location": compact_text(str(identity.get("location", "")), 60),
                },
                "webnovel_profile": {
                    "character_type": compact_text(str(profile.get("character_type", "")), 90),
                    "core_motivation": compact_text(str(profile.get("core_motivation", "")), 120),
                    "behavior_logic": compact_text(str(profile.get("behavior_logic", "")), 120),
                    "interaction_mode": compact_text(str(profile.get("interaction_mode", "")), 120),
                    "poison_points": compact_list(profile.get("poison_points", []), max_items=4, item_chars=80),
                },
                "this_chapter_usage": {
                    "speech_tendency": compact_text(str(chapter_usage.get("speech_tendency", "")), 100),
                    "action_tendency": compact_text(str(chapter_usage.get("action_tendency", "")), 100),
                },
                "voice_and_action": {
                    "risk_posture": compact_text(str(voice.get("risk_posture", "")), 100),
                    "speech_style": compact_text(str(voice.get("speech_style", "")), 100),
                    "action_style": compact_text(str(voice.get("action_style", "")), 100),
                },
            }
        )
    return cards


def _planned_character_names(plan: Any, known_names: tuple[str, ...] = ()) -> set[str]:
    if not isinstance(plan, dict):
        return set()
    names: set[str] = set()
    character_moves = plan.get("character_moves")
    if isinstance(character_moves, dict):
        for key, moves in character_moves.items():
            name = str(key or "").strip()
            if name:
                names.add(name)
            for item in moves if isinstance(moves, list) else [moves]:
                if isinstance(item, dict):
                    explicit_name = str(item.get("name") or "").strip()
                    if explicit_name:
                        names.add(explicit_name)
    for item in character_moves if isinstance(character_moves, list) else []:
        if isinstance(item, dict):
            for key in ("name",):
                value = str(item.get(key) or "").strip()
                if value:
                    names.add(value)
    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {}
    for item in event_plan.get("ordered_actions", []) if isinstance(event_plan.get("ordered_actions"), list) else []:
        if isinstance(item, dict):
            value = str(item.get("name") or "").strip()
            if value:
                names.add(value)
    for card in plan.get("scene_cards", []) if isinstance(plan.get("scene_cards"), list) else []:
        if isinstance(card, dict):
            for key in ("pov", "character", "name"):
                value = str(card.get(key) or "").strip()
                if value and value not in {"主角", "玩家", "NPC"}:
                    names.add(value)
    chapter_seed = plan.get("chapter_seed") if isinstance(plan.get("chapter_seed"), dict) else {}
    relevant_event_plan = {
        key: event_plan.get(key)
        for key in (
            "ordered_actions",
            "chapter_satisfaction",
            "chapter_end_hook",
            "world_reactions",
            "npc_beats",
            "next_focus",
        )
        if event_plan.get(key)
    }
    relevant_payload = {
        "character_moves": character_moves,
        "event_plan": relevant_event_plan,
        "scene_cards": plan.get("scene_cards"),
        "continuity": {
            key: chapter_seed.get(key)
            for key in ("must_carry", "continuity_facts", "opening_anchor", "chapter_facts")
            if chapter_seed.get(key)
        },
    }
    relevant_text = json.dumps(relevant_payload, ensure_ascii=False, default=str)
    for known_name in known_names:
        value = str(known_name or "").strip()
        if value and value in relevant_text:
            names.add(value)
    return names


def _approved_new_character_names(plan: Any) -> set[str]:
    if not isinstance(plan, dict):
        return set()
    intent = plan.get("chapter_intent") if isinstance(plan.get("chapter_intent"), dict) else {}
    governance = plan.get("governance") if isinstance(plan.get("governance"), dict) else {}
    governed_intent = governance.get("chapter_intent") if isinstance(governance.get("chapter_intent"), dict) else {}
    approved: set[str] = set()
    for source in (intent.get("approved_new_characters"), governed_intent.get("approved_new_characters")):
        for item in source if isinstance(source, list) else []:
            value = item.get("name") if isinstance(item, dict) else item
            name = str(value or "").strip()
            if name:
                approved.add(name)
    return approved


_GENERIC_CHARACTER_SIGNAL_MARKERS = (
    "围绕主线目标行动",
    "围绕当前目标行动",
    "推进当前主线",
    "根据行动结果调整",
    "推动剧情",
)


def _concrete_character_signal(*values: Any, limit: int) -> str:
    for value in values:
        text = compact_text(str(value or ""), limit)
        if text and not any(marker in text for marker in _GENERIC_CHARACTER_SIGNAL_MARKERS):
            return text
    return ""


def _character_context_for_prompt(
    story: StoryState,
    plan: Any | None = None,
    *,
    max_items: int = 4,
    include_memory: bool = False,
) -> dict[str, Any]:
    known_names = tuple(character.name for character in story.characters if character.name)
    requested = _planned_character_names(plan, known_names)
    approved_new = _approved_new_character_names(plan)
    cards = build_character_cards(story)
    raw_cards = {
        character.name: character.model_dump(mode="json")
        for character in story.characters
        if character.name
    }
    selected: list[dict[str, Any]] = []
    for card in cards:
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        name = str(identity.get("name") or "").strip()
        raw = raw_cards.get(name, {})
        if str(raw.get("lifecycle_state") or "active") == "proposed" and name not in approved_new:
            continue
        if requested and name not in requested:
            continue
        selected.append(card)
        if len(selected) >= max_items:
            break
    if not selected:
        selected = [
            card
            for card in cards
            if str(raw_cards.get(str((card.get("identity") or {}).get("name") or ""), {}).get("lifecycle_state") or "active")
            != "proposed"
        ][:max_items]

    compact_cards: list[dict[str, Any]] = []
    for card in selected:
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        name = str(identity.get("name") or "").strip()
        profile = card.get("webnovel_profile") if isinstance(card.get("webnovel_profile"), dict) else {}
        usage = card.get("story_usage") if isinstance(card.get("story_usage"), dict) else {}
        voice = card.get("voice_and_action") if isinstance(card.get("voice_and_action"), dict) else {}
        locks = card.get("continuity_locks") if isinstance(card.get("continuity_locks"), dict) else {}
        relationships = locks.get("relationships") if isinstance(locks.get("relationships"), dict) else {}
        chapter_usage = usage.get("this_chapter_usage") if isinstance(usage.get("this_chapter_usage"), dict) else {}
        raw = raw_cards.get(name, {})
        raw_identity = raw.get("identity_profile") if isinstance(raw.get("identity_profile"), dict) else {}
        raw_drive = raw.get("story_drive") if isinstance(raw.get("story_drive"), dict) else {}
        raw_performance = raw.get("performance_profile") if isinstance(raw.get("performance_profile"), dict) else {}
        compact_card = {
                "identity": {
                    "name": identity.get("name", ""),
                    "role": identity.get("role", ""),
                    "display_role": compact_text(
                        str(
                            raw_identity.get("current_identity")
                            or raw_identity.get("occupation")
                            or identity.get("role", "")
                        ),
                        100,
                    ),
                    "location": compact_text(str(identity.get("location", "")), 60),
                },
                "motivation": _concrete_character_signal(
                    profile.get("core_motivation"),
                    raw_drive.get("motivation"),
                    raw_drive.get("long_term_goal"),
                    limit=120,
                ),
                "behavior_logic": _concrete_character_signal(
                    profile.get("behavior_logic"),
                    raw_performance.get("action_style"),
                    limit=120,
                ),
                "interaction_mode": _concrete_character_signal(
                    profile.get("interaction_mode"),
                    limit=120,
                ),
                "goals": compact_list(raw.get("goals", []), max_items=2, item_chars=120),
                "speech_tendency": compact_text(str(chapter_usage.get("speech_tendency", "")), 100),
                "action_tendency": compact_text(str(chapter_usage.get("action_tendency", "")), 100),
                "risk_posture": compact_text(str(voice.get("risk_posture", "")), 100),
                "speech_style": compact_text(str(voice.get("speech_style", "")), 100),
                "poison_points": compact_list(profile.get("poison_points", []), max_items=4, item_chars=80),
                "relationship_context": [
                    {
                        "target": str(target),
                        "trust": relation.get("trust", 0),
                        "tension": relation.get("tension", 0),
                        "bond": str(relation.get("bond") or ""),
                    }
                    for target, relation in list(relationships.items())[:3]
                    if isinstance(relation, dict)
                ],
                "scene_portrait": build_scene_portrait_slice(card),
            }
        if include_memory:
            compact_card["memory"] = compact_list(raw.get("memory", []), max_items=2, item_chars=70)
        compact_cards.append(compact_card)
    return {
        "selection": "planned_characters" if requested else "fallback_active_characters",
        "requested_names": sorted(requested),
        "cards": compact_cards,
    }


def _character_context_summary_for_prompt(context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    cards = context.get("cards") if isinstance(context.get("cards"), list) else []
    brief_cards = []
    for card in cards[:2]:
        if not isinstance(card, dict):
            continue
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        brief_cards.append(
            {
                "name": identity.get("name"),
                "game_id": identity.get("game_id"),
                "role": identity.get("role"),
                "motivation": compact_text(str(card.get("motivation") or ""), 70),
                "speech": compact_text(str(card.get("speech_style") or card.get("speech_tendency") or ""), 70),
                "risk": compact_text(str(card.get("risk_posture") or ""), 70),
                "relationships": card.get("relationship_context", [])[:2],
                "scene_portrait": card.get("scene_portrait") if isinstance(card.get("scene_portrait"), dict) else {},
            }
        )
    return {"selection": context.get("selection"), "requested_names": context.get("requested_names", [])[:4], "cards": brief_cards}


def _progress_character_cards(story: StoryState, plan: dict[str, Any] | None = None, max_items: int = 3) -> dict[str, Any]:
    context = _character_context_for_prompt(story, plan, max_items=max_items)
    summary = _character_context_summary_for_prompt(context)
    return {
        "selection": summary.get("selection"),
        "requested_names": summary.get("requested_names", []),
        "cards": summary.get("cards", []),
    }


def _review_progress_snapshot(review: dict[str, Any] | None) -> dict[str, Any]:
    summary = _compact_review_summary(review)
    issues = summary.get("issues", [])
    revision_plan = summary.get("revision_plan", [])
    return {
        "issue_count": len(issues),
        "sample_issues": issues,
        "sample_revision_plan": revision_plan,
        "style_issues": summary.get("style_issues", []),
        "prose_issues": summary.get("prose_issues", []),
        "scene_contract_failures": summary.get("scene_contract_failures", []),
    }


def _slim_prompt_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return compact_text(str(value), 160)
    if isinstance(value, str):
        return compact_text(value, 180)
    if isinstance(value, list):
        return [_slim_prompt_value(item, depth=depth + 1) for item in value[:8]]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            result[str(key)] = _slim_prompt_value(item, depth=depth + 1)
        return result
    return value


def _compact_world_pulse_threads(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    compacted: list[Any] = []
    allowed_fields = (
        "id",
        "title",
        "summary",
        "status",
        "pressure",
        "next_step",
        "actors",
        "locations",
        "updated_chapter",
    )
    for item in value[:4]:
        if isinstance(item, str):
            compacted.append(compact_text(item, 140))
        elif isinstance(item, dict):
            thread = {
                key: _slim_prompt_value(item.get(key))
                for key in allowed_fields
                if item.get(key) not in (None, "", [], {})
            }
            if thread:
                compacted.append(thread)
    return compacted


def _compact_world_pulse_entry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result = {
        key: value.get(key)
        for key in ("pulse_index", "chapter_number", "visible_at_chapter")
        if value.get(key) is not None
    }
    summary = compact_text(
        str(
            value.get("reader_facing_summary")
            or value.get("summary")
            or value.get("id")
            or ""
        ),
        160,
    )
    if summary:
        result["summary"] = summary
    visible_traces = compact_list(value.get("visible_traces", []), max_items=3, item_chars=110)
    if visible_traces:
        result["visible_traces"] = visible_traces
    threads = _compact_world_pulse_threads(value.get("threads"))
    if threads:
        result["threads"] = threads
    return result


def _compact_world_pulse_for_prompt(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    latest = _compact_world_pulse_entry(value.get("latest"))
    if latest:
        result["latest"] = latest
    for key in ("threads", "active_threads"):
        threads = _compact_world_pulse_threads(value.get(key))
        if threads:
            result[key] = threads
    history = value.get("history")
    if isinstance(history, list):
        compacted_history = [
            entry
            for item in history[-2:]
            if (entry := _compact_world_pulse_entry(item))
        ]
        if compacted_history:
            result["history"] = compacted_history
    return result


def _compact_trope_contract_for_prompt(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        "template_id": compact_text(str(value.get("template_id") or ""), 180),
        "name": compact_text(str(value.get("name") or ""), 180),
        "trigger": compact_text(str(value.get("trigger") or ""), 180),
        "current_beat": compact_text(str(value.get("current_beat") or ""), 180),
        "payoff": compact_text(str(value.get("payoff") or ""), 180),
        "avoid": compact_list(value.get("avoid", []), max_items=8, item_chars=180),
    }


def _attach_trope_contract_to_simulation_plan(
    simulation_plan: dict[str, Any] | None,
    chapter_seed: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(simulation_plan, dict):
        return simulation_plan
    if not isinstance(chapter_seed, dict) or not isinstance(chapter_seed.get("trope_contract"), dict):
        return simulation_plan
    result = deepcopy(simulation_plan)
    result["trope_contract"] = deepcopy(chapter_seed["trope_contract"])
    return result


def _compact_chapter_seed_for_prompt(seed: Any) -> dict[str, Any]:
    if not isinstance(seed, dict):
        return {}
    keep_keys = (
        "schema_version",
        "chapter_number",
        "chapter_contract",
        "trope_contract",
        "outline_anchor",
        "writing_contract",
        "simulation_axes",
        "current_state",
        "continuity",
        "hard_locks",
        "must_show",
        "must_not_write",
    )
    compacted = {key: _slim_prompt_value(seed.get(key)) for key in keep_keys if seed.get(key) not in (None, "", [], {})}
    if seed.get("trope_contract") not in (None, "", [], {}):
        compacted["trope_contract"] = _compact_trope_contract_for_prompt(seed.get("trope_contract"))
    current_state = compacted.get("current_state")
    if isinstance(current_state, dict):
        slim_state: dict[str, Any] = {}
        for key in ("real", "panel", "equipment", "economy", "quests", "risk", "skills", "protagonist", "pressure", "market", "systems", "clock"):
            if current_state.get(key) not in (None, "", [], {}):
                slim_state[key] = current_state[key]
        inbox = current_state.get("visibility_inbox")
        if isinstance(inbox, list) and inbox:
            slim_state["visibility_inbox"] = inbox[:3]
        compacted["current_state"] = slim_state
    if "writing_contract" in compacted and isinstance(compacted["writing_contract"], dict):
        contract = compacted["writing_contract"]
        for key in ("scene_plan", "allowed_progress", "forbidden_unlocks"):
            if isinstance(contract.get(key), list):
                contract[key] = contract[key][:6]
    return compacted


def _compact_writer_plan_for_prompt(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {}
    chapter_intent = plan.get("chapter_intent") if isinstance(plan.get("chapter_intent"), dict) else {}
    result: dict[str, Any] = {}
    if chapter_intent:
        compact_intent = {
            key: _slim_prompt_value(chapter_intent.get(key))
            for key in (
                "chapter_title",
                "next_focus",
                "primary_conflict",
                "secondary_conflict",
            )
            if chapter_intent.get(key) not in (None, "", [], {})
        }
        if compact_intent:
            result["chapter_intent"] = compact_intent
    if event_plan:
        compact_event = {
            key: _slim_prompt_value(event_plan.get(key))
            for key in (
                "chapter_title",
                "chapter_satisfaction",
                "ordered_actions",
                "chapter_end_hook",
                "must_include",
                "must_not_write",
                "numeric_plan",
            )
            if event_plan.get(key) not in (None, "", [], {})
        }
        if compact_event:
            result["event_plan"] = compact_event
    scene_cards = plan.get("scene_cards")
    if isinstance(scene_cards, list) and scene_cards:
        compact_cards: list[dict[str, Any]] = []
        for card in scene_cards[:6]:
            if not isinstance(card, dict):
                continue
            compact_cards.append(
                {
                    "scene_id": card.get("scene_id"),
                    "location": card.get("location"),
                    "pov": card.get("pov"),
                    "purpose": compact_text(str(card.get("purpose") or ""), 120),
                    "conflict": compact_text(str(card.get("conflict") or ""), 120),
                    "must_show": compact_list(card.get("must_show", []), max_items=4, item_chars=80),
                    "ending_pressure": compact_text(str(card.get("ending_pressure") or ""), 100),
                }
            )
        result["scene_cards"] = compact_cards
    character_moves = plan.get("character_moves")
    if isinstance(character_moves, list) and character_moves:
        result["character_moves"] = _slim_prompt_value(character_moves[:6])
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}


def _trope_contract_guidance(contract: Any) -> list[str]:
    if not isinstance(contract, dict) or not contract:
        return []
    current_beat = str(contract.get("current_beat") or "").strip()
    progress_rule = (
        "本章产生可观察推进，不能只提到节点，必须让当前节点在行动、反馈或关系变化中落地。"
        if current_beat
        else "只保持阶段承诺，不强行完成整套节点，也不得自行换套路。"
    )
    return [progress_rule, "始终保守遵守 avoid 规则。"]


def _writer_seed_summary(seed: Any) -> dict[str, Any]:
    compacted = _compact_chapter_seed_for_prompt(seed)
    if not compacted:
        return {}
    writing_contract = compacted.get("writing_contract") if isinstance(compacted.get("writing_contract"), dict) else {}
    chapter_contract = compacted.get("chapter_contract") if isinstance(compacted.get("chapter_contract"), dict) else {}
    trope_contract = compacted.get("trope_contract") if isinstance(compacted.get("trope_contract"), dict) else {}
    continuity = compacted.get("continuity") if isinstance(compacted.get("continuity"), dict) else {}
    summary = {
        "章节": compacted.get("chapter_number"),
        "本章硬锚点": compacted.get("outline_anchor", {}),
        "上一章": compact_text(str(continuity.get("latest_summary") or ""), 160),
        "必须承接": compact_list(continuity.get("must_keep_facts", []), max_items=4, item_chars=90),
        "未解线索": compact_list(continuity.get("unresolved_threads", []), max_items=4, item_chars=90),
        "下一步": compact_text(str(continuity.get("next_focus") or ""), 100),
        "当前状态": compact_list(
            [
                str(chapter_contract.get("current_level") or "").strip(),
                str(chapter_contract.get("progression_stage") or "").strip(),
            ],
            max_items=2,
            item_chars=40,
        ),
        "本章目标": compact_text(str(chapter_contract.get("goal") or chapter_contract.get("chapter_goal") or ""), 90),
        "本章要兑现": compact_text(str(chapter_contract.get("payoff") or chapter_contract.get("visible_payoff") or ""), 90),
        "这章可以兑现的小进展": compact_list(writing_contract.get("allowed_progress", []), max_items=3, item_chars=70),
        "这章不能提前写": compact_list(writing_contract.get("forbidden_unlocks", []), max_items=3, item_chars=70),
        "情绪走向": compact_list(writing_contract.get("emotional_arc", []), max_items=3, item_chars=70),
        "行动顺序": compact_list((writing_contract.get("genre_craft") or {}).get("action_chain", []), max_items=3, item_chars=70)
        if isinstance(writing_contract.get("genre_craft"), dict)
        else [],
        "正文要露出": compact_list(compacted.get("must_show", []), max_items=3, item_chars=70),
        "正文别写": compact_list(compacted.get("must_not_write", []), max_items=3, item_chars=70),
    }
    if trope_contract:
        summary["当前阶段套路"] = trope_contract
        summary["套路写作提醒"] = _trope_contract_guidance(trope_contract)
    return summary


def _director_characters(story: StoryState, *, limit: int = 4) -> list[Any]:
    latest = story.chapter_summaries[-1] if story.chapter_summaries else None
    relevance_text = " ".join(
        [
            story.outline,
            latest.summary if latest else "",
            " ".join(latest.unresolved_threads) if latest else "",
            latest.next_focus if latest else "",
        ]
    )
    ranked: list[tuple[int, int, Any]] = []
    for index, character in enumerate(story.characters):
        if character.lifecycle_state != "active" or character.frozen:
            continue
        score = 0
        if character.role in {"protagonist", "主角"}:
            score += 100
        if character.chapter_role:
            score += 25
        if character.name and character.name in relevance_text:
            score += 40
        if character.game_id and character.game_id in relevance_text:
            score += 35
        if any(token in character.role for token in ("本章", "相关", "核心")):
            score += 15
        ranked.append((score, -index, character))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in ranked[:limit]]


def _story_snapshot(story: StoryState) -> dict:
    latest = story.chapter_summaries[-1] if story.chapter_summaries else None
    memory_query = " ".join(
        [
            story.outline,
            latest.next_focus if latest else "",
            latest.summary if latest else "",
            " ".join(story.world_facts[:8]),
        ]
    )
    relevant_memories = retrieve_relevant_memories(story, memory_query, limit=6)
    prompt_ledger = _compact_prompt_ledger(story.progression_ledger)
    snapshot = {
        "outline": compact_text(story.outline, 1600),
        "outline_context": story.outline_context,
        "genre": story.genre,
        "style": story.style,
        "current_chapter": story.current_chapter,
        "author_constraints": compact_list(story.author_constraints, max_items=6, item_chars=130),
        "world_facts": _priority_world_facts(story.world_facts, max_items=12, item_chars=140),
        "world_context": _compact_world_context_for_prompt(
            story.world_context,
            "\n".join((story.outline, json.dumps(story.outline_context, ensure_ascii=False))),
            max_rules=8,
        ),
        "progression_ledger": prompt_ledger,
        "relevant_memories": [
            {
                "chapter_number": entry.chapter_number,
                "chapter_title": entry.chapter_title,
                "summary": compact_text(entry.summary, 160),
                "tags": entry.tags[:8],
                "characters": entry.characters[:6],
                "locations": entry.locations[:6],
                "factions": entry.factions[:6],
                "quests": entry.quests[:6],
                "items": entry.items[:6],
                "unresolved_threads": compact_list(entry.unresolved_threads, max_items=3, item_chars=90),
            }
            for entry in relevant_memories
        ],
        "arc_recaps": [
            {
                "range": f"{recap.start_chapter}-{recap.end_chapter}",
                "recap": compact_text(recap.recap, 220),
                "key_threads": compact_list(recap.key_threads, max_items=6, item_chars=90),
                "open_threads": compact_list(recap.open_threads, max_items=6, item_chars=90),
                "character_changes": compact_list(recap.character_changes, max_items=6, item_chars=90),
                "ledger_snapshot": recap.ledger_snapshot,
            }
            for recap in story.arc_recaps[-3:]
        ],
        "latest_summary": compact_text(latest.summary if latest else "", 200),
        "latest_facts": compact_list(latest.facts if latest else [], max_items=8, item_chars=130),
        "latest_threads": compact_list(latest.unresolved_threads if latest else [], max_items=3, item_chars=70),
        "current_focus": compact_text(latest.next_focus if latest else "", 120),
        "world_pulse": prompt_ledger.get("world_pulse", {}),
        "visibility_inbox": prompt_ledger.get("visibility_inbox", []),
        "characters": [
            {
                "name": c.name,
                "game_id": c.game_id,
                "game_panel": c.game_panel.model_dump(),
                "role": c.role,
                "goals": compact_list(c.goals, max_items=3, item_chars=90),
                "emotion": c.current_emotion,
                "location": compact_text(c.location, 80),
                "secrets": compact_list(c.secrets, max_items=3, item_chars=80),
                "memory": compact_list(c.memory, max_items=3, item_chars=90),
                "relationships": [
                    {
                        "target": relation.target,
                        "bond": compact_text(relation.bond, 80),
                        "trust": relation.trust,
                        "tension": relation.tension,
                    }
                    for relation in list(c.relationships.values())[:4]
                ],
            }
            for c in _director_characters(story)
        ],
    }
    power_system = writing_power_system_context(story)
    if power_system:
        snapshot["power_system"] = power_system
    return snapshot


def _director_snapshot_summary(snapshot: dict) -> dict:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    characters = snapshot.get("characters") if isinstance(snapshot.get("characters"), list) else []
    result = {
        "outline": compact_text(str(snapshot.get("outline") or ""), 1200),
        "outline_context": snapshot.get("outline_context") if isinstance(snapshot.get("outline_context"), dict) else {},
        "genre": snapshot.get("genre"),
        "style": compact_text(str(snapshot.get("style") or ""), 120),
        "current_chapter": snapshot.get("current_chapter"),
        "author_constraints": compact_list(snapshot.get("author_constraints", []), max_items=4, item_chars=90),
        "world_facts": compact_list(snapshot.get("world_facts", []), max_items=6, item_chars=90),
        "world_context": _slim_prompt_value(snapshot.get("world_context", {})),
        "latest_summary": compact_text(str(snapshot.get("latest_summary") or ""), 160),
        "latest_facts": compact_list(snapshot.get("latest_facts", []), max_items=4, item_chars=80),
        "latest_threads": compact_list(snapshot.get("latest_threads", []), max_items=4, item_chars=80),
        "current_focus": compact_text(str(snapshot.get("current_focus") or ""), 120),
        "relevant_memories": [
            _slim_prompt_value(item)
            for item in snapshot.get("relevant_memories", [])[:4]
            if isinstance(item, dict)
        ],
        "arc_recaps": [
            _slim_prompt_value(item)
            for item in snapshot.get("arc_recaps", [])[-2:]
            if isinstance(item, dict)
        ],
        "characters": [
            {
                "name": item.get("name"),
                "role": item.get("role"),
                "goals": compact_list(item.get("goals", []), max_items=2, item_chars=60),
                "emotion": compact_text(str(item.get("emotion") or ""), 40),
                "location": compact_text(str(item.get("location") or ""), 60),
                "memory": compact_list(item.get("memory", []), max_items=2, item_chars=70),
                "secrets": compact_list(item.get("secrets", []), max_items=2, item_chars=70),
                "relationships": item.get("relationships", [])[:3]
                if isinstance(item.get("relationships"), list)
                else [],
            }
            for item in characters[:4]
            if isinstance(item, dict)
        ],
    }
    world_pulse = _compact_world_pulse_for_prompt(snapshot.get("world_pulse"))
    if world_pulse:
        result["world_pulse"] = world_pulse
    if isinstance(snapshot.get("power_system"), dict) and snapshot["power_system"]:
        result["power_system"] = _slim_prompt_value(snapshot["power_system"])
    return result


def _load_canon_registry_for_project_root(project_root: Any) -> Any:
    """Read the on-disk canon registry for ``project_root``.

    The orchestrator's modular pipeline previously started every
    chapter with a fresh, in-memory :class:`CanonRegistry`. The
    user's confirmation step writes the registry back to disk
    under ``.story-system/canon/registry.json``; the next chapter
    needs to read that file so its ``FactExtractor`` can anchor
    new facts to the world the user actually has. We reuse the
    same loader the file project store uses — keeping the
    read/write formats in one place — and fall back to an empty
    registry when the project is brand new.
    """
    from pathlib import Path

    from packages.story_core.canon.registry import CanonRegistry

    if project_root is None:
        return CanonRegistry()
    try:
        root_path = Path(project_root)
    except TypeError:
        return CanonRegistry()
    target = root_path / ".story-system" / "canon" / "registry.json"
    if not target.is_file():
        return CanonRegistry()
    try:
        text = target.read_text(encoding="utf-8-sig")
        import json

        payload = json.loads(text)
    except (OSError, ValueError, json.JSONDecodeError):
        return CanonRegistry()
    if not isinstance(payload, dict):
        return CanonRegistry()
    try:
        from packages.story_core.file_project_store import _registry_from_payload

        return _registry_from_payload(payload)
    except Exception:
        return CanonRegistry()


def _director_context_payload(story: StoryState, chapter_number: int) -> dict[str, Any]:
    chapter_context = (
        story.outline_context.get("chapter")
        if isinstance(story.outline_context, dict)
        and isinstance(story.outline_context.get("chapter"), dict)
        else {}
    )
    cast = {
        str(item or "").strip()
        for item in chapter_context.get("cast", [])
        if str(item or "").strip()
    }
    active_characters = [
        character
        for character in story.characters
        if character.lifecycle_state == "active" and not character.frozen
    ]
    relevant_characters = [character for character in active_characters if character.name in cast]
    if not relevant_characters:
        relevant_characters = _director_characters(story, limit=4)
    protagonist = next(
        (character for character in active_characters if character.role in {"protagonist", "主角"}),
        None,
    )
    if protagonist is not None and protagonist not in relevant_characters:
        relevant_characters.insert(0, protagonist)
    relevant_characters = relevant_characters[:4]
    selector_plan = {
        "character_moves": [{"name": character.name} for character in relevant_characters]
    }
    raw_project_snapshot = _story_snapshot(story)
    relevant_names = {character.name for character in relevant_characters}
    if relevant_names and isinstance(raw_project_snapshot.get("characters"), list):
        raw_project_snapshot["characters"] = [
            item
            for item in raw_project_snapshot["characters"]
            if isinstance(item, dict) and str(item.get("name") or "").strip() in relevant_names
        ]
    raw_character_cards = _character_context_for_prompt(
        story,
        selector_plan,
        max_items=4,
        include_memory=True,
    )
    raw_chapter_seed = build_chapter_seed(story, chapter_number)
    return {
        "project_snapshot": _director_snapshot_summary(raw_project_snapshot),
        "chapter_seed": _writer_seed_summary(
            _compact_chapter_seed_for_prompt(raw_chapter_seed)
        ),
        "character_cards": raw_character_cards,
        "raw_project_snapshot": raw_project_snapshot,
        "raw_outline_context": story.outline_context,
        "raw_character_cards": raw_character_cards,
    }


def _planning_character_names(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    names: list[str] = []
    cards = payload.get("cards")
    if isinstance(cards, list):
        for card in cards:
            identity = card.get("identity") if isinstance(card, dict) else None
            name = str(identity.get("name") or "").strip() if isinstance(identity, dict) else ""
            if name and name not in names:
                names.append(name)
    if names:
        return names
    envelope_keys = {"selection", "requested_names", "cards"}
    direct_names = [str(name).strip() for name in payload if name not in envelope_keys]
    if direct_names:
        return sorted(name for name in direct_names if name)
    requested = payload.get("requested_names")
    if isinstance(requested, list):
        return [str(name).strip() for name in requested if str(name).strip()]
    return []


def _director_prompt_outline_context(value: Any) -> dict[str, Any]:
    context = value if isinstance(value, dict) else {}
    field_limits = {
        "overall": ("protagonist_goal", "main_conflict", "current_strategy"),
        "active_arc": (
            "id",
            "title",
            "start_chapter",
            "end_chapter",
            "goal",
            "obstacle",
            "payoff",
            "end_state",
            "stage_antagonist",
        ),
        "chapter": ("chapter_number", "title", "goal", "obstacle", "action", "turn", "payoff", "ending_hook", "cast"),
        "continuity_interface": (
            "previous_chapter_number",
            "previous_tail",
            "previous_facts",
            "previous_threads",
            "next_chapter_number",
            "next_opening",
            "fact_priority",
        ),
    }
    result: dict[str, Any] = {}
    for section, keys in field_limits.items():
        source = context.get(section) if isinstance(context.get(section), dict) else {}
        selected: dict[str, Any] = {}
        for key in keys:
            item = source.get(key)
            if item in (None, "", [], {}):
                continue
            if isinstance(item, list):
                selected[key] = compact_list(item, max_items=3, item_chars=60)
            elif isinstance(item, (bool, int, float)):
                selected[key] = item
            else:
                selected[key] = compact_text(str(item), 120)
        if selected:
            result[section] = selected
    return result


def _director_prompt_snapshot(snapshot: Any) -> dict[str, Any]:
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    latest_recap = next((item for item in reversed(snapshot.get("arc_recaps", [])) if isinstance(item, dict)), {})
    result = {
        "outline": compact_text(str(snapshot.get("outline") or ""), 180),
        "outline_context": _director_prompt_outline_context(snapshot.get("outline_context")),
        "genre": snapshot.get("genre"),
        "style": compact_text(str(snapshot.get("style") or ""), 80),
        "author_constraints": compact_list(snapshot.get("author_constraints", []), max_items=3, item_chars=75),
        "world_facts": compact_list(snapshot.get("world_facts", []), max_items=3, item_chars=75),
        "previous": {
            "summary": compact_text(str(snapshot.get("latest_summary") or ""), 150),
            "facts": compact_list(snapshot.get("latest_facts", []), max_items=2, item_chars=70),
            "threads": compact_list(snapshot.get("latest_threads", []), max_items=3, item_chars=70),
            "next_focus": compact_text(str(snapshot.get("current_focus") or ""), 100),
        },
        "relevant_memories": [
            {
                "summary": compact_text(str(item.get("summary") or ""), 100),
                "facts": compact_list(item.get("facts", []), max_items=2, item_chars=60),
            }
            for item in snapshot.get("relevant_memories", [])[:1]
            if isinstance(item, dict)
        ],
        "arc_recap": {
            "range": latest_recap.get("range"),
            "recap": compact_text(str(latest_recap.get("recap") or ""), 120),
            "open_threads": compact_list(latest_recap.get("open_threads", []), max_items=3, item_chars=60),
        }
        if latest_recap
        else {},
        "world_pulse": _slim_prompt_value(snapshot.get("world_pulse", {})),
        "visibility": _slim_prompt_value(snapshot.get("visibility_inbox", {})),
    }
    if isinstance(snapshot.get("power_system"), dict) and snapshot["power_system"]:
        result["power_system"] = _slim_prompt_value(snapshot["power_system"])
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}


def _director_prompt_chapter_seed(value: Any) -> dict[str, Any]:
    seed = value if isinstance(value, dict) else {}
    keys = (
        "章节",
        "未解线索",
        "下一步",
        "本章目标",
        "本章要兑现",
        "当前阶段套路",
        "套路写作提醒",
        "这章可以兑现的小进展",
        "这章不能提前写",
        "情绪走向",
        "行动顺序",
    )
    result: dict[str, Any] = {}
    for key in keys:
        item = seed.get(key)
        if item in (None, "", [], {}):
            continue
        if isinstance(item, list):
            max_items = 3 if key == "行动顺序" else 2
            result[key] = compact_list(item, max_items=max_items, item_chars=80)
        elif isinstance(item, dict):
            result[key] = _compact_trope_contract_for_prompt(item) if key == "当前阶段套路" else _slim_prompt_value(item)
        else:
            result[key] = compact_text(str(item), 130)
    return result


def _director_prompt_character_cards(value: Any) -> dict[str, Any]:
    context = value if isinstance(value, dict) else {}
    cards = context.get("cards") if isinstance(context.get("cards"), list) else []
    compact_cards: list[dict[str, Any]] = []
    for card in cards[:4]:
        if not isinstance(card, dict):
            continue
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        relationships = card.get("relationship_context") if isinstance(card.get("relationship_context"), list) else []
        portrait = card.get("scene_portrait") if isinstance(card.get("scene_portrait"), dict) else {}
        compact_cards.append(
            {
                "identity": {
                    key: identity.get(key)
                    for key in ("name", "role")
                    if identity.get(key) not in (None, "")
                },
                "motivation": compact_text(str(card.get("motivation") or ""), 100),
                "emotion": compact_text(str(portrait.get("current_emotion") or ""), 40),
                "behavior": compact_text(str(card.get("behavior_logic") or ""), 110),
                "interaction": compact_text(str(card.get("interaction_mode") or ""), 90),
                "speech": compact_text(str(card.get("speech_style") or card.get("speech_tendency") or ""), 80),
                "risk": compact_text(str(card.get("risk_posture") or ""), 70),
                "memory": compact_list(card.get("memory", []), max_items=2, item_chars=70),
                "relationships": [
                    {
                        "target": item.get("target"),
                        "bond": compact_text(str(item.get("bond") or ""), 60),
                        "trust": item.get("trust"),
                        "tension": item.get("tension"),
                    }
                    for item in relationships[:2]
                    if isinstance(item, dict)
                ],
            }
        )
    return {"cards": compact_cards}


def _normalize_moves(
    raw_moves: object,
    *,
    require_action: bool = False,
    allow_text_items: bool = False,
    require_name: bool = True,
) -> list[dict]:
    moves: list[dict] = []
    candidates: list[tuple[dict | str, object]] = []
    if isinstance(raw_moves, list):
        candidates.extend(
            (item, None)
            for item in raw_moves
            if isinstance(item, dict) or (allow_text_items and isinstance(item, str))
        )
    elif isinstance(raw_moves, dict):
        if "name" in raw_moves or "action" in raw_moves:
            candidates.append((raw_moves, None))
        else:
            for grouped_name, grouped_moves in raw_moves.items():
                if isinstance(grouped_moves, dict):
                    candidates.append((grouped_moves, grouped_name))
                elif isinstance(grouped_moves, list):
                    candidates.extend(
                        (item, grouped_name)
                        for item in grouped_moves
                        if isinstance(item, dict) or (allow_text_items and isinstance(item, str))
                    )
                elif allow_text_items and isinstance(grouped_moves, str):
                    candidates.append((grouped_moves, grouped_name))
    else:
        return moves
    for item, grouped_name in candidates:
        item_data = item if isinstance(item, dict) else {}
        raw_action = str(item if isinstance(item, str) else item_data.get("action") or "").strip()
        if isinstance(item, str) and not raw_action:
            continue
        explicit_name = str(item_data.get("name") or "").strip()
        name = explicit_name or str(grouped_name or "").strip()
        if require_name and not name:
            continue
        if require_action and not raw_action:
            continue
        moves.append(
            {
                "name": name,
                "goal": compact_text(str(item_data.get("goal") or "").strip() or "推进当前主线", 80),
                "emotion": str(item_data.get("emotion") or "").strip() or "alert",
                "action": compact_text(raw_action or "继续推进当前主线", 120),
                "priority": _normalize_priority(item_data.get("priority")),
                "new_character_candidates": compact_list(
                    item_data.get("new_character_candidates", []),
                    max_items=4,
                    item_chars=60,
                ),
            }
        )
        if len(moves) == 6:
            break
    return moves


def _story_character_names(story: StoryState) -> list[str]:
    return list(
        dict.fromkeys(
            name
            for character in story.characters
            for name in (str(character.name or "").strip(), str(character.game_id or "").strip())
            if name
        )
    )


def _normalize_ordered_actions(
    raw_actions: object,
    *,
    story: StoryState,
    require_action: bool = False,
) -> list[dict]:
    moves = _normalize_moves(
        raw_actions,
        require_action=require_action,
        allow_text_items=True,
        require_name=False,
    )
    known_names = _story_character_names(story)
    for move in moves:
        if str(move.get("name") or "").strip():
            continue
        action = str(move.get("action") or "").lstrip()
        matches = [
            (-len(name), order, name)
            for order, name in enumerate(known_names)
            if action.startswith(name)
        ]
        if matches:
            move["name"] = min(matches)[2]
    return moves


def _normalize_priority(raw: object) -> int:
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, (int, float)):
        return max(0, min(10, int(raw)))
    cleaned = str(raw or "").strip().lower()
    if not cleaned:
        return 0
    if cleaned in {"最高", "高", "紧急", "关键", "highest", "high", "critical"}:
        return 3
    if cleaned in {"中", "一般", "普通", "medium", "normal"}:
        return 2
    if cleaned in {"低", "最低", "low", "lowest"}:
        return 1
    match = re.search(r"-?\d+", cleaned)
    return max(0, min(10, int(match.group(0)))) if match else 0


def _normalize_cadence(raw: object) -> str:
    cleaned = str(raw).strip().lower()
    if cleaned in VALID_CADENCES:
        return cleaned
    if any(word in cleaned for word in ("快", "急", "紧迫", "紧张", "urgent")):
        return "urgent"
    if any(word in cleaned for word in ("缓", "慢", "平稳", "从容", "breathing")):
        return "breathing"
    return "measured"


def _normalize_intent(raw_intent: object) -> dict:
    if not isinstance(raw_intent, dict):
        return {}

    def _normalize_conflict(value: object) -> dict:
        if isinstance(value, dict):
            return value
        text = compact_text(str(value or "").strip(), 180)
        return {"summary": text} if text else {}

    return {
        "chapter_title": compact_text(str(raw_intent.get("chapter_title", "")).strip(), 60),
        "cadence": _normalize_cadence(raw_intent.get("cadence", "measured")),
        "next_focus": compact_text(str(raw_intent.get("next_focus", "")).strip(), 160),
        "primary_conflict": _normalize_conflict(raw_intent.get("primary_conflict")),
        "secondary_conflict": _normalize_conflict(raw_intent.get("secondary_conflict")),
        "approved_new_characters": raw_intent.get("approved_new_characters", [])
        if isinstance(raw_intent.get("approved_new_characters", []), list)
        else [],
        "deferred_characters": raw_intent.get("deferred_characters", [])
        if isinstance(raw_intent.get("deferred_characters", []), list)
        else [],
        "rejected_characters": raw_intent.get("rejected_characters", [])
        if isinstance(raw_intent.get("rejected_characters", []), list)
        else [],
    }


def _ensure_director_scene_chain(story: StoryState, plan: object) -> dict[str, Any]:
    """Upgrade legacy director actions into the executable three-scene contract."""

    prepared = deepcopy(plan) if isinstance(plan, dict) else {}
    event_plan = prepared.get("event_plan")
    event_plan = deepcopy(event_plan) if isinstance(event_plan, dict) else {}
    chapter_context = (
        story.outline_context.get("chapter")
        if isinstance(story.outline_context, dict)
        and isinstance(story.outline_context.get("chapter"), dict)
        else {}
    )
    outline_decision = chapter_context.get("attribute_allocation_decision")
    if isinstance(outline_decision, dict):
        event_plan["attribute_allocation_decision"] = deepcopy(outline_decision)
    for field in ("must_include", "must_not_write"):
        values = chapter_context.get(field)
        if isinstance(values, list):
            cleaned = list(
                dict.fromkeys(
                    text for item in values if (text := str(item or "").strip())
                )
            )
            if cleaned:
                event_plan[field] = cleaned

    cast = {
        str(item or "").strip()
        for item in chapter_context.get("cast", [])
        if str(item or "").strip()
    }
    if cast and isinstance(prepared.get("character_moves"), list):
        allowed_names = set(cast)
        for character in story.characters:
            if character.name in cast or (character.game_id and character.game_id in cast):
                allowed_names.add(character.name)
                if character.game_id:
                    allowed_names.add(character.game_id)
        filtered_moves = [
            move
            for move in prepared["character_moves"]
            if isinstance(move, dict) and str(move.get("name") or "").strip() in allowed_names
        ]
        if filtered_moves:
            prepared["character_moves"] = filtered_moves

    existing = event_plan.get("scene_chain")
    required = ("location", "pov", "goal", "obstacle", "action", "change", "next")
    if isinstance(existing, list) and len(existing) >= 3 and all(
        isinstance(scene, dict) and all(str(scene.get(field) or "").strip() for field in required)
        for scene in existing
    ):
        prepared["event_plan"] = event_plan
        return prepared

    actions = _normalize_ordered_actions(
        event_plan.get("ordered_actions"), story=story, require_action=True
    )
    if not actions:
        actions = _normalize_moves(
            prepared.get("character_moves"), require_action=True, allow_text_items=True
        )
    satisfaction = (
        event_plan.get("chapter_satisfaction")
        if isinstance(event_plan.get("chapter_satisfaction"), dict)
        else {}
    )
    protagonist = next(
        (character for character in story.characters if character.role in {"主角", "protagonist"}),
        None,
    )
    pov = str(
        (protagonist.game_id if protagonist and is_game_story(story) else protagonist.name if protagonist else "主角")
        or "主角"
    )
    action_texts = [str(item.get("action") or item.get("goal") or "").strip() for item in actions]
    action_texts = [item for item in action_texts if item]
    while len(action_texts) < 3:
        action_texts.append(
            str(
                satisfaction.get(
                    ("core_event", "visible_payoff", "next_hook")[len(action_texts)]
                )
                or ("推进当前行动", "处理行动结果", "追查下一条线索")[len(action_texts)]
            )
        )
    event_plan["scene_chain"] = [
        {
            "location": f"本章场景{index + 1}",
            "pov": pov,
            "goal": str(satisfaction.get("core_event") or action_texts[index]),
            "obstacle": str(satisfaction.get("obstacle") or "行动受到具体阻碍"),
            "action": action_texts[index],
            "change": str(satisfaction.get("state_change") or satisfaction.get("visible_payoff") or "局面发生变化"),
            "next": str(satisfaction.get("next_hook") or "转入下一步行动"),
        }
        for index in range(3)
    ]
    prepared["event_plan"] = event_plan
    return prepared


def _director_plan_quality_issues(story: StoryState, plan: object) -> list[str]:
    if not isinstance(plan, dict):
        return ["导演产物不是JSON对象。"]
    issues: list[str] = []
    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {}
    satisfaction = event_plan.get("chapter_satisfaction") if isinstance(event_plan.get("chapter_satisfaction"), dict) else {}
    required_satisfaction = ("core_event", "obstacle", "visible_payoff", "cost", "state_change", "next_hook")
    missing = [key for key in required_satisfaction if not str(satisfaction.get(key) or "").strip()]
    if missing:
        issues.append(f"event_plan.chapter_satisfaction 缺少：{', '.join(missing)}。")
    hook = event_plan.get("chapter_end_hook") if isinstance(event_plan.get("chapter_end_hook"), dict) else {}
    if not str(hook.get("content") or "").strip():
        issues.append("event_plan.chapter_end_hook 缺少具体 content。")

    attribute_rule = attribute_allocation_rule_from_story(story)
    if attribute_rule:
        current_level = current_protagonist_level(story.progression_ledger, attribute_rule["starting_level"])
        target_level = planned_level_target(plan)
        current_points = current_unallocated_attribute_points(story.progression_ledger)
        expected_points = current_points + max(0, (target_level or current_level) - current_level) * attribute_rule["points_per_level"]
        raw_decision = event_plan.get("attribute_allocation_decision")
        requires_decision = (
            (target_level is not None and target_level > current_level)
            or (current_points > 0 and plan_handles_attribute_points(plan))
            or raw_decision is not None
        )
        if requires_decision and not validate_attribute_allocation_decision(raw_decision, attribute_rule, expected_points):
            if not isinstance(raw_decision, dict):
                issues.append("event_plan.attribute_allocation_decision 缺失：本章明确升级时必须 allocate 或 carry。")
            elif str(raw_decision.get("mode") or "").strip().lower() == "carry" and not attribute_rule["allow_carry"]:
                issues.append("event_plan.attribute_allocation_decision 使用 carry，但当前规则禁止保留属性点。")
            elif str(raw_decision.get("mode") or "").strip().lower() == "carry":
                if not str(raw_decision.get("reason") or "").strip():
                    issues.append("event_plan.attribute_allocation_decision 保留属性点必须填写理由。")
                else:
                    issues.append("event_plan.attribute_allocation_decision 的 remaining 必须等于预计剩余点数。")
            elif str(raw_decision.get("mode") or "").strip().lower() == "allocate":
                allocations = raw_decision.get("allocations")
                allocation_items_invalid = (
                    not isinstance(allocations, dict)
                    or not allocations
                    or any(
                        not isinstance(name, str)
                        or name not in attribute_rule["base_attributes"]
                        or isinstance(points, bool)
                        or not isinstance(points, int)
                        or points <= 0
                        for name, points in allocations.items()
                    )
                )
                if allocation_items_invalid:
                    issues.append("event_plan.attribute_allocation_decision 分配项/属性非法。")
                elif sum(allocations.values()) > expected_points:
                    issues.append("event_plan.attribute_allocation_decision 分配点数超过本章预计可用点数。")
                else:
                    issues.append("event_plan.attribute_allocation_decision 的 remaining 必须等于预计剩余点数。")
            else:
                issues.append("event_plan.attribute_allocation_decision 必须是合法的 allocate 或 carry。")
    placeholder_phrases = {
        "完成本章推进",
        "推进当前目标",
        "出现可见阻力",
        "获得阶段收益",
        "付出可见代价",
        "状态发生变化",
        "形成下一场压力",
        "留下下一步",
    }
    satisfaction_values = [str(satisfaction.get(key) or "").strip() for key in required_satisfaction]
    if any(value in placeholder_phrases for value in [*satisfaction_values, str(hook.get("content") or "").strip()]):
        issues.append("章节规划仍含空泛占位语，必须改成能直接写成场景的具体行动、阻力、结果和章末事件。")

    character_moves = _normalize_moves(plan.get("character_moves"), require_action=True, allow_text_items=True)
    ordered_moves = _normalize_ordered_actions(event_plan.get("ordered_actions"), story=story, require_action=True)
    moves = [*character_moves, *ordered_moves]
    if not moves:
        issues.append("导演计划缺少可执行动作。")

    scene_chain = event_plan.get("scene_chain") if isinstance(event_plan.get("scene_chain"), list) else []
    required_scene_fields = ("location", "pov", "goal", "obstacle", "action", "change", "next")
    if not 3 <= len(scene_chain) <= 5 or any(
        not isinstance(scene, dict)
        or any(not str(scene.get(field) or "").strip() for field in required_scene_fields)
        for scene in scene_chain
    ):
        issues.append("event_plan.scene_chain 必须包含3至5个完整场景，每个场景写清地点、视角、目标、阻力、行动、变化和下一步。")

    interface = story.outline_context.get("continuity_interface") if isinstance(story.outline_context, dict) else {}
    departed = departed_character_facts(interface)
    for name in departed:
        actions = " ".join(
            " ".join(str(move.get(key) or "") for key in ("name", "goal", "action"))
            for move in moves
            if name in " ".join(str(move.get(key) or "") for key in ("name", "goal", "action"))
        )
        if actions and not has_return_transition(name, actions):
            issues.append(f"连续性冲突：{name}上一章已经离场，本章计划没有交代返场过程。")

    profile = genre_stage_profile_for(story, plan)
    issues.extend(
        profile.review_director_plan(
            context=DirectorPlanReviewContext(story=story, moves=moves, plan=plan)
        )
    )
    return list(dict.fromkeys(issues))


def _director_revision_prompt(base_prompt: str, plan: dict, issues: list[str]) -> str:
    return "\n".join(
        [
            base_prompt,
            "",
            "上一次章节规划未通过硬性验收，请完整重做JSON。",
            f"必须修复：{'；'.join(issues)}",
            "不得保留错误材料名、占位人物或空的章节收益/钩子；不要输出解释。",
            f"上一次JSON：{_plain_prompt_json(plan)}",
        ]
    )


def _normalize_event_plan(raw_event_plan: object, chapter_number: int, story: StoryState) -> dict:
    def _normalize_chapter_end_hook(raw_hook: object) -> dict[str, str | None] | None:
        if not isinstance(raw_hook, dict):
            return None
        hook_type = str(raw_hook.get("type", "")).strip() or None
        strength = str(raw_hook.get("strength", "")).strip().lower() or None
        content = compact_text(str(raw_hook.get("content", "")).strip(), 180)
        return {"type": hook_type, "strength": strength, "content": content}

    def _normalize_chapter_satisfaction(raw_satisfaction: object) -> dict[str, str]:
        if not isinstance(raw_satisfaction, dict):
            return {}
        fields = (
            "emotion_target",
            "core_event",
            "obstacle",
            "visible_payoff",
            "cost",
            "outsider_misread",
            "state_change",
            "next_hook",
        )
        return {
            field: compact_text(str(raw_satisfaction.get(field, "")).strip(), 180)
            for field in fields
            if str(raw_satisfaction.get(field, "")).strip()
        }

    if not isinstance(raw_event_plan, dict):
        return {
            "chapter_number": chapter_number,
            "ordered_actions": [],
            "world_reactions": [],
            "exposition_beats": [],
            "npc_beats": [],
            "quest_beats": [],
            "location_beats": [],
            "explicit_chapter_end_hook": "",
            "chapter_end_hook": None,
            "chapter_satisfaction": {},
            "author_constraints": list(story.author_constraints),
        }
    result = {
        "chapter_number": chapter_number,
        "chapter_title": compact_text(str(raw_event_plan.get("chapter_title", "")).strip(), 60),
        "turn": compact_text(str(raw_event_plan.get("turn", "")).strip(), 120),
        "pivot": compact_text(str(raw_event_plan.get("pivot", "")).strip(), 160),
        "collision": compact_text(str(raw_event_plan.get("collision", "")).strip(), 160),
        "ordered_actions": _normalize_ordered_actions(
            raw_event_plan.get("ordered_actions"),
            story=story,
            require_action=True,
        ),
        "exposition_beats": compact_list(raw_event_plan.get("exposition_beats", []), max_items=8, item_chars=180),
        "npc_beats": compact_list(raw_event_plan.get("npc_beats", []), max_items=6, item_chars=180),
        "quest_beats": compact_list(raw_event_plan.get("quest_beats", []), max_items=6, item_chars=180),
        "location_beats": compact_list(raw_event_plan.get("location_beats", []), max_items=6, item_chars=180),
        "world_reactions": compact_list(raw_event_plan.get("world_reactions", []), max_items=6, item_chars=160),
        "stakes": compact_text(str(raw_event_plan.get("stakes", "")).strip(), 140),
        "next_focus": compact_text(str(raw_event_plan.get("next_focus", "")).strip(), 160),
        "explicit_chapter_end_hook": compact_text(str(raw_event_plan.get("explicit_chapter_end_hook", "")).strip(), 180),
        "chapter_end_hook": _normalize_chapter_end_hook(raw_event_plan.get("chapter_end_hook")),
        "chapter_satisfaction": _normalize_chapter_satisfaction(raw_event_plan.get("chapter_satisfaction")),
        "author_constraints": list(story.author_constraints),
    }
    numeric_plan = raw_event_plan.get("numeric_plan")
    if isinstance(numeric_plan, dict) and numeric_plan:
        result["numeric_plan"] = deepcopy(numeric_plan)
    raw_scene_chain = raw_event_plan.get("scene_chain")
    if isinstance(raw_scene_chain, list):
        scene_fields = ("location", "pov", "goal", "obstacle", "action", "change", "next")
        result["scene_chain"] = [
            {
                field: compact_text(str(scene.get(field) or "").strip(), 220)
                for field in scene_fields
                if str(scene.get(field) or "").strip()
            }
            for scene in raw_scene_chain[:5]
            if isinstance(scene, dict)
        ]
    if (level_target := planned_level_target({"event_plan": raw_event_plan})) is not None:
        result["attribute_allocation_level_target"] = level_target
    decision = attribute_allocation_context(story, {"event_plan": raw_event_plan}).get("chapter_decision")
    if decision:
        result["attribute_allocation_decision"] = decision
    return result


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
            "ledger_updates": {},
        }
    return {
        "must_keep_facts": compact_list(raw_memory.get("must_keep_facts", []), max_items=8, item_chars=140),
        "unresolved_threads": compact_list(raw_memory.get("unresolved_threads", []), max_items=4, item_chars=90),
        "protected_characters": [str(v).strip() for v in raw_memory.get("protected_characters", []) if str(v).strip()][:4],
        "protected_foreshadowing": raw_memory.get("protected_foreshadowing", [])[:3] if isinstance(raw_memory.get("protected_foreshadowing"), list) else [],
        "author_constraints": compact_list(raw_memory.get("author_constraints", []), max_items=16, item_chars=180) or list(story.author_constraints),
        "current_focus": compact_text(str(raw_memory.get("current_focus", "")).strip(), 160),
        "conflict_anchor": compact_text(str(raw_memory.get("conflict_anchor", "")).strip(), 160),
        "event_guardrail": compact_text(str(raw_memory.get("event_guardrail", "")).strip(), 160),
        "ledger_updates": raw_memory.get("ledger_updates", {}) if isinstance(raw_memory.get("ledger_updates"), dict) else {},
    }


def _merge_ledger_dict(base: dict, updates: dict) -> dict:
    result = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_ledger_dict(result[key], value)
        elif value not in (None, "", [], {}):
            result[key] = value
    return result


def _apply_ledger_updates(
    story: StoryState,
    ledger_updates: dict,
    *,
    chapter_number: int | None = None,
) -> None:
    if not isinstance(ledger_updates, dict) or not ledger_updates:
        return
    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    previous_protagonist = _clean_mapping(ledger.get("protagonist"))
    previous_level = parse_level(previous_protagonist.get("level"))
    if previous_level is None:
        previous_level = parse_level(ledger.get("level"))
    rule = attribute_allocation_rule_from_story(story)
    updates = deepcopy(ledger_updates)
    directive = None
    updates_protagonist = updates.get("protagonist")
    nested_level_update = None
    if isinstance(updates_protagonist, dict) and updates_protagonist.get("level") not in (None, "", [], {}):
        nested_level_update = updates_protagonist["level"]
    if rule and isinstance(updates_protagonist, dict):
        directive = updates_protagonist.pop("attribute_allocation", None)
        if isinstance(directive, dict) and isinstance(directive.get("allocations"), dict):
            direct_attributes = updates_protagonist.get("attributes")
            if isinstance(direct_attributes, dict):
                for attribute in directive["allocations"]:
                    direct_attributes.pop(attribute, None)
                if not direct_attributes:
                    updates_protagonist.pop("attributes", None)
            updates_protagonist.pop("unallocated_attribute_points", None)
        if not updates_protagonist:
            updates.pop("protagonist", None)

    story.progression_ledger = _merge_ledger_dict(ledger, updates)
    if nested_level_update is not None:
        story.progression_ledger.pop("level", None)
    _normalize_progression_ledger(story.progression_ledger)
    sync_chapter = chapter_number if chapter_number is not None else int(story.current_chapter or 0) or None
    if rule:
        current_protagonist = _clean_mapping(story.progression_ledger.get("protagonist"))
        award_attribute_points(
            story.progression_ledger,
            rule,
            previous_level,
            current_protagonist.get("level"),
            sync_chapter,
        )
        if directive is not None:
            apply_attribute_allocation(story.progression_ledger, directive, rule, sync_chapter)
    _sync_character_game_panels(
        story,
        sync_chapter,
        authoritative_updates=updates,
    )


def _collect_state_deltas(items: list[dict] | None) -> list[dict]:
    deltas: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        delta = item.get("state_delta")
        if isinstance(delta, dict) and delta:
            deltas.append(delta)
    return deltas


def _add_int(base: object, delta: object) -> int:
    try:
        return int(base or 0) + int(delta or 0)
    except (TypeError, ValueError):
        return int(delta or 0) if isinstance(delta, int) else 0


def _parse_copper(value: object) -> int:
    match = re.search(r"-?\d+", str(value or "0"))
    return int(match.group(0)) if match else 0


def _add_mapping_counts(base: dict, updates: dict) -> dict:
    result = dict(base)
    for key, value in updates.items():
        if isinstance(value, (int, float)) or str(value).lstrip("-").isdigit():
            result[key] = _add_int(result.get(key), value)
        elif value not in (None, "", [], {}):
            result[key] = value
    return result


def _systemic_ledger_delta(delta: dict) -> dict:
    game_world = delta.get("game_world_simulation") if isinstance(delta, dict) else None
    if not isinstance(game_world, dict):
        return {}
    ledger_delta = game_world.get("ledger_delta")
    return ledger_delta if isinstance(ledger_delta, dict) else {}


def _apply_systemic_ledger_delta(story: StoryState, ledger_delta: dict) -> None:
    if not isinstance(ledger_delta, dict) or not ledger_delta:
        return
    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}

    inventory_delta = ledger_delta.get("inventory_delta")
    if isinstance(inventory_delta, dict) and inventory_delta:
        economy = ledger.setdefault("economy", {})
        inventory = economy.get("inventory") if isinstance(economy.get("inventory"), dict) else {}
        economy["inventory"] = _add_mapping_counts(inventory, inventory_delta)

    currency_delta = ledger_delta.get("currency_delta")
    if isinstance(currency_delta, dict) and currency_delta:
        economy = ledger.setdefault("economy", {})
        copper_delta = currency_delta.get("铜")
        if copper_delta not in (None, "", [], {}):
            economy["game_currency"] = f"{_add_int(_parse_copper(economy.get('game_currency')), copper_delta)}铜"

    cost_delta = ledger_delta.get("cost_delta")
    if isinstance(cost_delta, dict) and cost_delta:
        protagonist = ledger.setdefault("protagonist", {})
        protagonist["cost_delta"] = dict(cost_delta)

    market_delta = ledger_delta.get("market_delta")
    if isinstance(market_delta, dict) and market_delta:
        market_root = ledger.get("market") if isinstance(ledger.get("market"), dict) else {}
        ledger["market"] = market_root
        market = market_root.get("newbie_materials") if isinstance(market_root.get("newbie_materials"), dict) else {}
        market_root["newbie_materials"] = market
        if "material_supply" in market_delta:
            market["supply"] = _add_int(market.get("supply"), market_delta.get("material_supply"))
        if market_delta.get("price_copper") not in (None, "", [], {}):
            market["price_copper"] = market_delta["price_copper"]

    hidden_delta = ledger_delta.get("hidden_system_delta")
    if isinstance(hidden_delta, dict) and hidden_delta:
        systems = ledger.get("systems") if isinstance(ledger.get("systems"), dict) else {}
        ledger["systems"] = systems
        chaos = systems.get("chaos_seed") if isinstance(systems.get("chaos_seed"), dict) else {}
        systems["chaos_seed"] = chaos
        if hidden_delta.get("chaos_seed_anomaly_score") not in (None, "", [], {}):
            chaos["anomaly_score"] = _add_int(chaos.get("anomaly_score"), hidden_delta["chaos_seed_anomaly_score"])

    if ledger_delta.get("clock_minutes") not in (None, "", [], {}):
        clock = ledger.setdefault("clock", {})
        clock["elapsed_minutes"] = _add_int(clock.get("elapsed_minutes"), ledger_delta["clock_minutes"])

    next_pressure = ledger_delta.get("next_pressure")
    if isinstance(next_pressure, list) and next_pressure:
        pressure = ledger.setdefault("pressure", {})
        pressure["next"] = [str(item) for item in next_pressure if str(item).strip()]

    set_delta = ledger_delta.get("set_delta")
    if isinstance(set_delta, dict) and set_delta:
        story.progression_ledger = _merge_ledger_dict(ledger, set_delta)
        ledger = story.progression_ledger

    story.progression_ledger = ledger
    _normalize_progression_ledger(story.progression_ledger)


def apply_simulated_state_deltas(
    story: StoryState,
    *,
    world_events: list[dict] | None = None,
    scene_cards: list[dict] | None = None,
    chapter_number: int | None = None,
) -> None:
    """Persist state changes created by the simulation layer."""

    for delta in [*_collect_state_deltas(world_events), *_collect_state_deltas(scene_cards)]:
        ledger_update = {key: value for key, value in delta.items() if key != "game_world_simulation"}
        _apply_ledger_updates(story, ledger_update, chapter_number=chapter_number)
        _apply_systemic_ledger_delta(story, _systemic_ledger_delta(delta))
    _sync_character_game_panels(story, chapter_number)


def _pick_protagonist(story: StoryState):
    return next(
        (
            character
            for character in story.characters
            if character.role in ("protagonist", "主角") or character.name in ("苏叶", "夜烬")
        ),
        story.characters[0] if story.characters else None,
    )


def _clean_mapping(value) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _clean_identity_placeholder(value: object) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or set(cleaned) <= {"?", "？", "�"}:
        return ""
    return cleaned


def _clean_game_id(value: object, character_name: str) -> str:
    cleaned = _clean_identity_placeholder(value)
    if cleaned and (cleaned == character_name or cleaned == "苏叶"):
        return ""
    return cleaned


def _sync_character_game_panels(
    story: StoryState,
    chapter_number: int | None = None,
    *,
    authoritative_updates: dict | None = None,
) -> None:
    """Mirror the persistent progression ledger into the protagonist character card."""
    genre = str(getattr(story, "genre", "") or "").strip().lower()
    game_sync_enabled = is_game_story(story) or genre in {"网游", "web game", "game fantasy", "game_webnovel"}
    if not story.characters or not isinstance(story.progression_ledger, dict) or not game_sync_enabled:
        return
    character = _pick_protagonist(story)
    if character is None:
        return

    ledger = story.progression_ledger
    attribute_rule = attribute_allocation_rule_from_story(story)
    protagonist = _clean_mapping(ledger.get("protagonist"))
    economy = _clean_mapping(ledger.get("economy"))
    equipment = _clean_mapping(ledger.get("equipment"))
    skills = ledger.get("skills")
    quests = ledger.get("quests")
    pressure = _clean_mapping(ledger.get("pressure"))
    panel = character.game_panel
    game_state = dict(character.game_state) if isinstance(character.game_state, dict) else {}
    current = deepcopy(game_state.get("current")) if isinstance(game_state.get("current"), dict) else {}
    previous_current = deepcopy(current)

    def present(value: object) -> bool:
        return value not in (None, "", [], {})

    def fill(field: str, *values: object) -> None:
        if present(current.get(field)):
            return
        for value in values:
            if present(value):
                current[field] = deepcopy(value)
                return

    legacy = panel.model_dump(mode="json")
    ledger_skills: list[str] = []
    if isinstance(skills, dict):
        for value in skills.values():
            ledger_skills.extend(
                str(item) for item in (value if isinstance(value, list) else [value]) if str(item).strip()
            )
    elif isinstance(skills, list):
        ledger_skills = [str(item) for item in skills if str(item).strip()]

    def ledger_values_from(source: dict) -> dict:
        source_protagonist = _clean_mapping(source.get("protagonist"))
        source_economy = _clean_mapping(source.get("economy"))
        source_equipment = _clean_mapping(source.get("equipment"))
        source_quests = source.get("quests")
        source_pressure = _clean_mapping(source.get("pressure"))
        source_skills = source.get("skills")
        if isinstance(source_skills, dict):
            source_skill_values = [
                str(item)
                for value in source_skills.values()
                for item in (value if isinstance(value, list) else [value])
                if str(item).strip()
            ]
        elif isinstance(source_skills, list):
            source_skill_values = [str(item) for item in source_skills if str(item).strip()]
        else:
            source_skill_values = []
        values = {
            "level": source_protagonist.get("level", source.get("level")),
            "class_path": source_protagonist.get("class_path", source.get("class_path")),
            "exp": source_protagonist.get("exp", source.get("exp")),
            "hp": source_protagonist.get("hp", source.get("hp")),
            "mp": source_protagonist.get("mp", source.get("mp")),
            "attributes": source_protagonist.get("attributes", source.get("attributes")),
            "skills": source_skill_values or source.get("skills"),
            "equipment": source_equipment or source.get("equipment"),
            "inventory": source_economy.get("inventory", source.get("inventory")),
            "currency": source_economy.get("game_currency") or source_economy.get("currency") or source.get("game_currency") or source.get("currency"),
            "quests": source_quests if isinstance(source_quests, (dict, list)) else None,
            "risk": source_pressure or source.get("risk"),
        }
        if attribute_rule:
            values.update(
                {
                    "unallocated_attribute_points": source_protagonist.get("unallocated_attribute_points"),
                    "attribute_point_awards": source_protagonist.get("attribute_point_awards"),
                    "attribute_allocations": source_protagonist.get("attribute_allocations"),
                }
            )
        return values

    ledger_values = ledger_values_from(ledger)
    for field, value in ledger_values.items():
        fill(field, value, legacy.get(field))
    if isinstance(authoritative_updates, dict):
        for field, value in ledger_values_from(authoritative_updates).items():
            if present(value):
                current[field] = deepcopy(value)
    if attribute_rule:
        for field in ("attributes", "unallocated_attribute_points", "attribute_point_awards", "attribute_allocations"):
            if field in protagonist:
                current[field] = deepcopy(protagonist[field])

    game_id = _clean_game_id(current.get("game_id"), character.name)
    if not game_id:
        game_id = (
            _clean_game_id(protagonist.get("game_id"), character.name)
            or _clean_game_id(legacy.get("game_id"), character.name)
            or _clean_game_id(character.game_id, character.name)
        )
    if not game_id and character.name == "苏叶":
        game_id = "夜烬"
    fill("game_id", game_id)

    if character.name == "苏叶" and (present(current.get("class_path")) or game_sync_enabled):
        fill("hp", "92/100" if str(current.get("exp") or "") not in {"", "0/100"} else "100/100")
        fill("mp", "61/80" if str(current.get("exp") or "") not in {"", "0/100"} else "80/80")
        if not attribute_rule:
            fill("attributes", {"力量": 3, "敏捷": 4, "智力": 9, "体质": 5})
    if character.name == "苏叶" and not present(current.get("inventory")) and str(current.get("exp") or "") not in {"", "0/100"}:
        fill("inventory", {"灰鼠毒腺": "18份", "灰鼠皮": "3张"})
    if character.name == "苏叶" and isinstance(current.get("equipment"), dict):
        equipment_values = current["equipment"]
        if any("补给前置" in str(value) or "补给门槛" in str(value) for value in equipment_values.values()):
            durability = str(equipment_values.get("durability") or equipment_values.get("耐久") or "94/100")
            current["equipment"] = {"主武器": "新手法杖", "护甲": "粗布衣", "耐久": durability}

    panel.game_id = str(current.get("game_id") or "")
    panel.level = current.get("level")
    panel.class_path = str(current.get("class_path") or "")
    panel.exp = str(current.get("exp") or "")
    panel.hp = str(current.get("hp") or "")
    panel.mp = str(current.get("mp") or "")
    panel.attributes = deepcopy(current.get("attributes")) if isinstance(current.get("attributes"), dict) else {}
    panel.unallocated_attribute_points = (
        current.get("unallocated_attribute_points")
        if isinstance(current.get("unallocated_attribute_points"), int)
        and not isinstance(current.get("unallocated_attribute_points"), bool)
        else 0
    )
    panel.attribute_point_awards = (
        deepcopy(current.get("attribute_point_awards"))
        if isinstance(current.get("attribute_point_awards"), list)
        else []
    )
    panel.attribute_allocations = (
        deepcopy(current.get("attribute_allocations"))
        if isinstance(current.get("attribute_allocations"), list)
        else []
    )
    panel.skills = list(current.get("skills") or []) if isinstance(current.get("skills"), list) else []
    panel.equipment = deepcopy(current.get("equipment")) if isinstance(current.get("equipment"), dict) else {}
    panel.inventory = deepcopy(current.get("inventory")) if isinstance(current.get("inventory"), dict) else {}
    panel.currency = str(current.get("currency") or "")
    if isinstance(current.get("quests"), dict):
        panel.quests = deepcopy(current["quests"])
    elif isinstance(current.get("quests"), list):
        panel.quests = {"active": deepcopy(current["quests"])}
    else:
        panel.quests = {}
    panel.risk = deepcopy(current.get("risk")) if isinstance(current.get("risk"), dict) else {}
    if chapter_number is not None:
        panel.updated_chapter = chapter_number
    character.game_id = panel.game_id or character.game_id

    game_state["current"] = current
    game_state.setdefault("recent_changes", [])
    changed_fields = [field for field in ledger_values if previous_current.get(field) != current.get(field)]
    if chapter_number is not None and changed_fields:
        fact = f"游戏账本更新：{', '.join(changed_fields[:5])}"
        if not any(
            isinstance(item, dict)
            and item.get("chapter") == int(chapter_number)
            and item.get("fact") == fact
            for item in game_state["recent_changes"]
        ):
            game_state["recent_changes"].append({"chapter": int(chapter_number), "fact": fact})
    character.game_state = game_state

    summary_parts = [
        f"ID {panel.game_id}" if panel.game_id else "",
        f"Lv.{panel.level}" if panel.level not in (None, "") else "",
        panel.class_path,
        f"经验{panel.exp}" if panel.exp else "",
        panel.currency,
    ]
    summary = " / ".join(part for part in summary_parts if part)
    if summary:
        memory = f"角色面板：{summary}"
        character.memory = [memory, *[item for item in character.memory if not item.startswith("角色面板：")]][:12]


def _normalize_progression_ledger(ledger: dict) -> None:
    """Keep legacy flat ledger keys mirrored into the structured game ledger."""
    if not isinstance(ledger, dict):
        return
    protagonist = ledger.setdefault("protagonist", {})
    economy = ledger.setdefault("economy", {})
    equipment = ledger.setdefault("equipment", {})
    pressure = ledger.setdefault("pressure", {})
    if isinstance(protagonist, dict):
        for key in ("level", "exp", "class_path", "location"):
            if key in ledger and ledger[key] not in (None, "", [], {}):
                protagonist[key] = ledger[key]
    if isinstance(economy, dict):
        for key in ("currency", "inventory", "market_anomaly"):
            value = ledger.get(key)
            if value in (None, "", [], {}):
                continue
            if key == "currency" and economy.get("game_currency") not in (None, "", [], {}):
                continue
            if key == "inventory" and isinstance(economy.get("inventory"), dict) and not isinstance(value, dict):
                continue
            economy[key] = value
        if economy.get("game_currency") not in (None, "", [], {}) and economy.get("currency") not in (None, "", [], {}):
            economy.pop("currency", None)
    if isinstance(equipment, dict):
        for key in ("weapon", "armor", "durability"):
            if key in ledger and ledger[key] not in (None, "", [], {}):
                equipment[key] = ledger[key]
    if isinstance(pressure, dict):
        for key in ("guild_attention", "goldfinger_exposure", "system_risk"):
            if key in ledger and ledger[key] not in (None, "", [], {}):
                pressure[key] = ledger[key]
        next_pressure = pressure.get("next")
        if isinstance(next_pressure, list):
            pressure["next"] = [
                "后坡探路前置已满足，但等级和补给仍压着风险"
                if "熟练度" in str(item)
                else item
                for item in next_pressure
            ]
    if isinstance(economy.get("inventory"), dict):
        ledger.pop("inventory", None)
    if economy.get("game_currency") not in (None, "", [], {}):
        ledger.pop("currency", None)
    if isinstance(ledger.get("skills"), list):
        ledger["skills"] = [item for item in ledger["skills"] if "熟练度" not in str(item)]
        if not ledger["skills"]:
            ledger.pop("skills", None)


def _merge_unique_compact(existing: object, additions: object, *, max_items: int = 8, item_chars: int = 140) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for source in (existing, additions):
        if isinstance(source, str):
            values = [source]
        elif isinstance(source, list):
            values = source
        else:
            values = []
        for value in values:
            clean = compact_text(str(value).strip(), item_chars)
            if not clean:
                continue
            key = re.sub(r"\s+", "", clean)
            if key in seen:
                continue
            seen.add(key)
            merged.append(clean)
            if len(merged) >= max_items:
                return merged
    return merged


def _economy_anchor_rank(text: str) -> int:
    if any(token in text for token in ("市场价", "均价", "挂牌均价", "回收单价", "定价", "单价", "价格")):
        return 0
    if any(token in text for token in ("手续费", "单笔上架上限", "单笔寄售上限", "流水风控", "风控阈值")):
        return 1
    if any(token in text for token in ("到账", "当前余额", "账户余额", "铜币余额", "货币：", "货币:")):
        return 2
    if any(token in text for token in ("掉落判定", "获得：", "背包：", "库存", "数量：")):
        return 3
    return 4


def _extract_economy_anchors(body: str, *, max_items: int = 8) -> list[str]:
    """Extract concrete price/currency anchors that must survive into later chapters."""
    if not body:
        return []
    economy_terms = (
        "市场价",
        "均价",
        "挂牌均价",
        "回收单价",
        "定价",
        "单价",
        "价格",
        "手续费",
        "到账",
        "当前余额",
        "账户余额",
        "铜币余额",
        "货币：",
        "货币:",
        "单笔上架上限",
        "单笔寄售上限",
        "流水风控",
        "风控阈值",
        "掉落判定",
        "获得：",
        "背包：",
    )
    value_terms = ("金币", "银币", "铜币", "毒腺", "狼牙", "狼皮", "材料", "交易行", "寄售", "上架", "回收")
    normalized = body.replace("\r", "\n").replace("`", "")
    candidates: list[tuple[int, int, str]] = []
    order = 0
    for line in normalized.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        for chunk in re.split(r"(?<=[。！？；])\s*", line):
            chunk = chunk.strip(" ，,")
            if not chunk:
                continue
            if any(term in chunk for term in economy_terms) and any(term in chunk for term in value_terms):
                candidates.append((_economy_anchor_rank(chunk), order, f"经济锚点：{compact_text(chunk, 130)}"))
                order += 1
    candidates.sort(key=lambda item: (item[0], item[1]))
    return _merge_unique_compact([], [candidate for _, _, candidate in candidates], max_items=max_items, item_chars=150)


def _extract_system_anchors(body: str, *, max_items: int = 10) -> list[str]:
    """Extract class, equipment and NPC service facts for long-form continuity."""
    if not body:
        return []
    normalized = body.replace("\r", "\n").replace("`", "")
    anchor_terms = (
        "初始身份",
        "身份栏",
        "身份：",
        "职业倾向",
        "职业：",
        "元素法师",
        "法师",
        "见习冒险者",
        "未转职",
        "基础火球术",
        "技能栏",
        "武器栏",
        "装备栏",
        "装备",
        "法杖",
        "短剑",
        "布衣",
        "护甲",
        "耐久",
        "修理",
        "购买",
        "药剂师洛婶",
        "职业导师艾伦",
        "仓库管理员铁栓",
        "修理匠老葛",
        "灰烬村村长",
    )
    candidates: list[tuple[int, int, str]] = []
    order = 0
    for line in normalized.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        for chunk in re.split(r"(?<=[。！？；])\s*", line):
            chunk = chunk.strip(" ，,")
            if not chunk or not any(term in chunk for term in anchor_terms):
                continue
            if any(term in chunk for term in ("职业倾向", "职业：", "元素法师", "法师")):
                label = "职业锚点"
                rank = 0
            elif any(term in chunk for term in ("初始身份", "身份栏", "身份：", "见习冒险者", "未转职", "基础火球术", "新手法杖")):
                label = "身份锚点"
                rank = 0
            elif any(term in chunk for term in ("武器栏", "装备栏", "装备", "法杖", "短剑", "布衣", "护甲", "耐久", "修理", "购买")):
                label = "装备锚点"
                rank = 1
            else:
                label = "NPC锚点"
                rank = 2
            candidates.append((rank, order, f"{label}：{compact_text(chunk, 130)}"))
            order += 1
    candidates.sort(key=lambda item: (item[0], item[1]))
    return _merge_unique_compact([], [candidate for _, _, candidate in candidates], max_items=max_items, item_chars=150)


def _extract_equipment_ledger_updates(body: str) -> dict:
    updates: dict[str, dict] = {}
    if not body:
        return updates
    protagonist: dict[str, str | int] = {}
    economy: dict[str, object] = {}
    equipment: dict[str, str] = {}
    if any(token in body for token in ("见习冒险者", "未转职", "基础火球术", "新手法杖")):
        protagonist["class_path"] = "见习冒险者（未转职）"
    level_matches = re.findall(r"(?:当前等级|等级)[：:]\s*(\d{1,3})", body)
    if level_matches:
        protagonist["level"] = int(level_matches[-1])
    exp_matches = re.findall(r"(?:经验|当前经验)[：:]\s*(\d+\s*/\s*\d+)", body)
    if exp_matches:
        protagonist["exp"] = re.sub(r"\s+", "", exp_matches[-1])
    currency_matches = re.findall(
        r"(?:当前资产|当前余额|账户余额|余额栏跳动|余额跳动|余额|货币)[：:]\s*([^\n。】]*(?:金币|银币|铜币)[^\n。】]*)",
        body,
    )
    if currency_matches:
        currency_text = currency_matches[-1]
        money = re.search(r"(?:(\d+)\s*金币)?\s*(?:(\d+)\s*银币)?\s*(?:(\d+)\s*铜币)?", currency_text)
        if money:
            gold = int(money.group(1) or 0)
            silver = int(money.group(2) or 0)
            copper = int(money.group(3) or 0)
            economy["currency"] = f"{gold}金币{silver}银币{copper}铜币"
    weapon_matches = re.findall(r"【([^】]*(?:法杖|短剑|剑|杖)[^】]*)】", body)
    if weapon_matches:
        preferred = next((item for item in reversed(weapon_matches) if "法杖" in item or "杖" in item), weapon_matches[-1])
        equipment["weapon"] = compact_text(preferred, 60)
    durability_matches = re.findall(r"(?:耐久度?[:：]\s*|耐久(?:恢复至|已降至|降至|：|:)?\s*)(\d{1,3}%|\d+/\d+|正常)", body)
    if durability_matches:
        equipment["durability"] = durability_matches[-1]
    if "布衣" in body and "armor" not in equipment:
        equipment["armor"] = "布衣"
    inventory_matches = re.findall(r"背包[：:]\s*([^\n】]+)", body)
    if inventory_matches:
        inventory: dict[str, str | int] = {}
        latest_inventory = inventory_matches[-1]
        for item, count in re.findall(r"([\u4e00-\u9fa5A-Za-z0-9·]+)\s*[×xX*＊]\s*(\d+)", latest_inventory):
            inventory[item] = int(count)
        if (
            inventory.get("灰狼毒腺") == 5
            and re.search(r"(?:递过去的五份毒腺|提交[^。]{0,12}五份毒腺|已提交5/5)", body)
        ):
            inventory["灰狼毒腺"] = 0
        if inventory:
            economy["inventory"] = inventory
    skill_matches = re.findall(r"(?:基础技能|技能)[：:]\s*([^\n】]+)", body)
    if skill_matches:
        updates["skills"] = [compact_text(skill_matches[-1], 80)]
    if protagonist:
        updates["protagonist"] = protagonist
    if economy:
        updates["economy"] = economy
        if "currency" in economy:
            updates["currency"] = economy["currency"]
    if equipment:
        updates["equipment"] = equipment
    return updates


def _inject_continuity_anchors(memory_constraints: dict, chapter_summary_data: dict, body: str) -> list[str]:
    anchors = _merge_unique_compact(
        _extract_economy_anchors(body, max_items=8),
        _extract_system_anchors(body, max_items=10),
        max_items=14,
        item_chars=150,
    )
    if not anchors:
        return []
    memory_constraints["must_keep_facts"] = _merge_unique_compact(
        memory_constraints.get("must_keep_facts", []),
        anchors,
        max_items=14,
        item_chars=150,
    )
    chapter_summary_data["facts"] = _merge_unique_compact(
        chapter_summary_data.get("facts", []),
        anchors,
        max_items=14,
        item_chars=150,
    )
    equipment_updates = _extract_equipment_ledger_updates(body)
    if equipment_updates:
        current_updates = memory_constraints.get("ledger_updates", {})
        memory_constraints["ledger_updates"] = _merge_ledger_dict(
            current_updates if isinstance(current_updates, dict) else {},
            equipment_updates,
        )
    return anchors


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
        "summary": compact_text(str(raw_summary.get("summary", "")).strip(), 260),
        "facts": compact_list(raw_summary.get("facts", []), max_items=8, item_chars=120),
        "unresolved_threads": compact_list(raw_summary.get("unresolved_threads", []), max_items=5, item_chars=90),
        "next_focus": compact_text(str(raw_summary.get("next_focus", "")).strip(), 160),
        "chapter_title": compact_text(str(raw_summary.get("chapter_title", "")).strip(), 60),
    }


def _opening_phase_name(chapter_number: int, *, is_game: bool = True) -> str:
    if not is_game:
        if chapter_number <= 3:
            return f"黄金三章第{chapter_number}章：推进当前核心矛盾，兑现一个具体进展，并留下下一步行动"
        return "常规连载章节：目标、行动、结果、代价和章末钩子"
    if chapter_number == 1:
        return "黄金三章第1章：立世界、立主角、立核心能力、完成第一次有效验证"
    if chapter_number == 2:
        return "黄金三章第2章：把本书核心优势转成任务、装备、关系或路线上的具体领先"
    if chapter_number == 3:
        return "黄金三章第3章：第一个小高潮、明确敌对压力、确立长期成长路线"
    return "常规连载章节：目标、行动、收益、压力、钩子循环"


def _review_protagonist_names(event_plan: dict[str, Any], simulation_plan: dict[str, Any] | None = None) -> tuple[str, ...]:
    """Extract likely protagonist names for local prose reviewers.

    The prose-rule reviewer can only detect "the protagonist never speaks" if
    it knows which names belong to the lead. Director plans already carry this
    in ordered_actions; keep the extraction narrow so NPC names do not flood
    the speech gate.
    """

    names: list[str] = []

    def add(value: object) -> None:
        name = str(value or "").strip()
        if not name or len(name) > 12:
            return
        if name in {"主角", "玩家", "散人", "NPC", "系统", "旁人", "众人"}:
            return
        if name not in names:
            names.append(name)

    def scan_plan(plan: dict[str, Any]) -> None:
        primary = plan.get("primary_conflict")
        if isinstance(primary, dict):
            add(primary.get("lead"))
        for action in plan.get("ordered_actions") or []:
            if isinstance(action, dict):
                add(action.get("name"))

    if isinstance(event_plan, dict):
        scan_plan(event_plan)
    if isinstance(simulation_plan, dict):
        nested_event_plan = simulation_plan.get("event_plan")
        if isinstance(nested_event_plan, dict):
            scan_plan(nested_event_plan)
        performance = simulation_plan.get("character_performance")
        if isinstance(performance, dict):
            for name in performance.keys():
                add(name)

    return tuple(names[:4])


def _story_review_genre_context(story: StoryState) -> dict[str, Any]:
    return {
        "genre": story.genre,
        "genre_plugin_ids": list(story.genre_plugin_ids),
    }


def _review_character_names(story: StoryState) -> tuple[str, ...]:
    """Names and game IDs available to evidence-based chapter review."""

    names = character_evidence_names(
        character
        for character in story.characters
        if character.lifecycle_state in {"active", "approved"} and not character.frozen
    )
    return tuple(sorted(names, key=lambda value: (-len(value), value)))


def _review_chapter_body(
    chapter_number: int,
    body: str,
    event_plan: dict,
    world_facts: list[str] | None = None,
    simulation_plan: dict | None = None,
    world_events: list[dict] | None = None,
    scene_cards: list[dict] | None = None,
    genre_context: Any = None,
    protagonist_aliases: tuple[str, ...] | None = None,
    character_names: tuple[str, ...] | None = None,
) -> dict:
    return _run_review_quality_gate(
        chapter_number=chapter_number,
        body=body,
        event_plan=event_plan,
        world_facts=world_facts,
        simulation_plan=simulation_plan,
        world_events=world_events,
        scene_cards=scene_cards,
        genre_context=genre_context,
        protagonist_aliases=protagonist_aliases,
        character_names=character_names,
        dependencies=ReviewDependencies(
            profile_for=genre_stage_profile_for,
            review_continuity=review_continuity_interface,
            review_fragments=review_chinese_fragments,
            review_consistency=review_world_event_consistency,
            review_style=review_prose_style,
            review_prose_quality=review_prose_quality,
            review_adversarial_cuts=review_adversarial_cuts,
            review_ai_flavor=review_ai_flavor,
            review_reader_feel=review_reader_feel,
            review_cold_reader=review_cold_reader_experience,
            review_plot_spine=review_plot_spine_completion,
            review_critical_rules=review_critical_prose_rules,
            build_scene_repair=build_scene_contract_repair_plan,
            report_progress=report_generation_progress,
        ),
        min_chapter_chars=_chapter_review_min_chars(simulation_plan),
        target_chapter_chars=TARGET_CHAPTER_CHARS,
        chapter_char_tolerance=CHAPTER_CHAR_TOLERANCE,
    )


def _merge_writing_review_quality(quality: dict, writing_review: dict) -> dict:
    merged = dict(quality)
    issues = list(merged.get("issues") or [])
    scores = writing_review.get("scores", {}) if isinstance(writing_review.get("scores"), dict) else {}
    hard_review_prefixes = ("web_game_", "prose_style_", "prose_quality_")
    writing_review_failed = not bool(writing_review.get("pass", True)) or bool(writing_review.get("issues")) or any(
        str(key).startswith(hard_review_prefixes) and int(value or 0) < 8 for key, value in scores.items()
    )
    if writing_review_failed:
        merged["ok"] = False
        if "writing_review" not in issues:
            issues.append("writing_review")
    merged["issues"] = issues
    merged["writing_review"] = writing_review
    for key in (
        "critical_review",
        "web_game_review",
        "consistency_review",
        "prose_style_review",
        "hook_review",
        "pacing_review",
        "beats_review",
        "reader_agent_review",
        "editor_agent_review",
        "reviewer_agent_review",
        "ai_flavor_review",
        "reader_feel_review",
        "cold_reader_review",
        "progression_lead_review",
    ):
        if isinstance(writing_review.get(key), dict):
            merged[key] = writing_review[key]
    merged["simplified_review"] = build_simplified_review(merged)
    return merged


def apply_expression_patches_from_review(body: str, writing_review: dict) -> tuple[str, dict[str, Any]]:
    """Apply expression-only patch suggestions from adversarial cut review."""

    cut_review = writing_review.get("adversarial_cut_review", {}) if isinstance(writing_review, dict) else {}
    patches = build_expression_patch_suggestions(cut_review if isinstance(cut_review, dict) else {})
    result = apply_spot_fix_patches(body, patches)
    return str(result.get("revised_content", body)), {
        "reviewer": "expression_patch/v1",
        "patches": patches,
        **result,
    }


def _render_expansion_length_prompt(
    story: StoryState,
    *,
    source_body: str,
    chapter_number: int,
    event_plan: dict[str, Any] | None = None,
    world_facts: list[str] | None = None,
    source_chars_override: int | None = None,
) -> str:
    target_chars: str = TARGET_CHAPTER_CHARS
    if source_chars_override is not None:
        source_chars = int(source_chars_override)
        target_min, target_max = _expansion_target_range(source_chars)
        target_chars = (
            f"{target_min}到{target_max}字（原文约{source_chars}字）"
            f"\n新增字数预算：共补约{target_min - source_chars}到{target_max - source_chars}字"
        )
    context = LengthPromptContext(
        story=story,
        chapter_number=chapter_number,
        source_body=source_body,
        event_plan=event_plan or {},
        world_facts=world_facts or [],
        target_chars=target_chars,
        max_chapter_chars=MAX_CHAPTER_CHARS,
        outline_anchor={},
    )
    return genre_stage_profile_for(story, event_plan).render_expansion_prompt(context=context)


def _render_compression_length_prompt(
    story: StoryState,
    *,
    source_body: str,
    chapter_number: int,
    event_plan: dict[str, Any] | None = None,
    world_facts: list[str] | None = None,
    outline_anchor: dict[str, Any] | None = None,
    target_chars: str | None = None,
    feedback: str = "",
) -> str:
    """Render the compression prompt for the given chapter body.

    The bounded flow no longer invokes this prompt automatically
    (over-length is reported as a ``length.out_of_range`` blocking
    finding and handed to the same revise pass), but the helper is
    kept so the file-project store's prompt preview, the
    ``compression`` prompt-template override, and any future manual
    compression path can still render the prompt.
    """
    context = LengthPromptContext(
        story=story,
        chapter_number=chapter_number,
        source_body=source_body,
        event_plan=event_plan or {},
        world_facts=world_facts or [],
        target_chars=TARGET_CHAPTER_CHARS,
        max_chapter_chars=MAX_CHAPTER_CHARS,
        outline_anchor=outline_anchor if isinstance(outline_anchor, dict) else {},
        compression_target_chars=target_chars,
        feedback=feedback,
    )
    return genre_stage_profile_for(story, event_plan).render_compression_prompt(context=context)


def _render_polish_length_prompt(
    story: StoryState,
    *,
    source_body: str,
    chapter_number: int,
    event_plan: dict[str, Any] | None = None,
    world_facts: list[str] | None = None,
    outline_anchor: dict[str, Any] | None = None,
    target_chars: str | None = None,
) -> str:
    """Render the expression-only polish prompt for an in-range chapter body."""

    context = LengthPromptContext(
        story=story,
        chapter_number=chapter_number,
        source_body=source_body,
        event_plan=event_plan or {},
        world_facts=world_facts or [],
        target_chars=target_chars or TARGET_CHAPTER_CHARS,
        max_chapter_chars=MAX_CHAPTER_CHARS,
        outline_anchor=outline_anchor if isinstance(outline_anchor, dict) else {},
    )
    rendered = None
    profile = genre_stage_profile_for(story, event_plan)
    if profile.render_polish_prompt is not None:
        rendered = profile.render_polish_prompt(context=context)
    else:
        rendered = render_generic_polish_prompt(context=context)
    return rendered


def _repair_generic_chapter_title(
    title: str,
    *,
    chapter_number: int,
    next_focus: str,
    conflict_summary: dict[str, Any],
    genre: str,
) -> str:
    generic_titles = {"真相道韵", "真相交锋", "真相异兆", "真相疑云", "真相剑影", "真相风声"}
    clean = str(title or "").strip()
    if clean and clean not in generic_titles:
        return clean
    concrete_title_rules = (
        (("黑痕", "掌"), "掌心黑痕"),
        (("供桌", "刻"), "供桌藏字"),
        (("供桌", "字"), "供桌藏字"),
        (("青砖",), "青砖之下"),
        (("旧香", "回应"), "残香回应"),
    )
    for required_terms, concrete_title in concrete_title_rules:
        if all(term in next_focus for term in required_terms):
            return concrete_title
    return build_chapter_title(
        chapter_number,
        conflict_summary=conflict_summary,
        next_focus=next_focus,
        genre=genre,
    )


def _planned_chapter_title(
    *,
    event_plan: dict[str, Any] | None,
    chapter_intent: dict[str, Any] | None,
    chapter_summary: dict[str, Any] | None,
) -> str:
    """Keep the current chapter plan authoritative over stale memory output."""

    for source in (event_plan, chapter_intent, chapter_summary):
        if not isinstance(source, dict):
            continue
        title = compact_text(str(source.get("chapter_title") or "").strip(), 60)
        if title:
            return title
    return ""


def _compact_review_summary(review: dict[str, Any] | None) -> dict[str, Any]:
    review = review if isinstance(review, dict) else {}
    style_review = review.get("style_review") if isinstance(review.get("style_review"), dict) else {}
    prose_review = review.get("prose_quality_review") if isinstance(review.get("prose_quality_review"), dict) else {}
    summary: dict[str, Any] = {
        "issues": compact_list(review.get("issues", []), max_items=6, item_chars=90),
        "revision_plan": compact_list(review.get("revision_plan", []), max_items=6, item_chars=90),
    }
    scene_failures = compact_list(review.get("scene_contract_failures", []), max_items=6, item_chars=180)
    scene_repair_plan = review.get("scene_repair_plan") if isinstance(review.get("scene_repair_plan"), dict) else {}
    if scene_failures:
        summary["scene_contract_failures"] = scene_failures
    if scene_repair_plan:
        summary["scene_repair_plan"] = scene_repair_plan
    style_issues = compact_list(style_review.get("issues", []), max_items=4, item_chars=90)
    prose_issues = compact_list(prose_review.get("issues", []), max_items=4, item_chars=90)
    if style_issues:
        summary["style_issues"] = style_issues
    if prose_issues:
        summary["prose_issues"] = prose_issues
    return summary


def _plain_prompt_payload(value: Any) -> Any:
    """Remove writer-dangerous backend wording from structured prompt payloads."""

    if isinstance(value, str):
        return writer_facing_text(value)
    if isinstance(value, list):
        return [_plain_prompt_payload(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain_prompt_payload(item) for key, item in value.items()}
    return value


def _plain_prompt_json(value: Any) -> str:
    return json.dumps(_plain_prompt_payload(value), ensure_ascii=False)






def _simulation_variant_from_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
    plan = plan if isinstance(plan, dict) else {}
    simulation_plan = plan.get("simulation_plan") if isinstance(plan.get("simulation_plan"), dict) else {}
    simulation_variant = (
        simulation_plan.get("simulation_variant") if isinstance(simulation_plan.get("simulation_variant"), dict) else {}
    )
    return simulation_variant


def _simulation_variant_from_simulation_plan(simulation_plan: dict[str, Any] | None) -> dict[str, Any]:
    simulation_plan = simulation_plan if isinstance(simulation_plan, dict) else {}
    simulation_variant = (
        simulation_plan.get("simulation_variant") if isinstance(simulation_plan.get("simulation_variant"), dict) else {}
    )
    return simulation_variant


def _should_expand_chapter(body: str, plan: dict[str, Any] | None) -> bool:
    if _simulation_variant_from_plan(plan).get("skip_expansion"):
        return False
    return _chapter_char_count(body) < MIN_CHAPTER_CHARS


def _chapter_review_min_chars(simulation_plan: dict[str, Any] | None) -> int:
    variant = _simulation_variant_from_simulation_plan(simulation_plan)
    if variant.get("skip_expansion"):
        return REGENERATION_FAST_MIN_CHARS
    if variant:
        return REGENERATION_MIN_CHARS
    return MIN_CHAPTER_CHARS






def _governance_prompt_section(governance: dict[str, Any] | None) -> str:
    if not isinstance(governance, dict) or not governance:
        return "## 本章事实边界\n按已有事实写，不输出工作流字段或说明文字。"
    chapter_intent = governance.get("chapter_intent", {}) if isinstance(governance.get("chapter_intent"), dict) else {}
    rule_stack = governance.get("rule_stack", {}) if isinstance(governance.get("rule_stack"), dict) else {}
    governance_review = governance.get("governance_review")
    if not isinstance(governance_review, dict):
        governance_review = review_chapter_governance(governance)
    governance_gate = governance_quality_gate(governance)
    lines = ["## 本章事实边界"]
    if governance_gate.get("blocking"):
        lines.append("当前事实边界有冲突；只按下面能确认的事实写，冲突项不要写进正文。")
    lines.append("把事实写成场景、动作、对话、物件反馈或界面反馈，不写成规则解释。")
    include = compact_list(chapter_intent.get("must_include", []), max_items=8, item_chars=90)
    avoid = compact_list(chapter_intent.get("must_avoid", []), max_items=8, item_chars=90)
    hard_facts = compact_list(rule_stack.get("hard_facts", []), max_items=8, item_chars=100)
    soft_guidance = compact_list(rule_stack.get("soft_guidance", []), max_items=4, item_chars=100)
    if include:
        lines.append("本章要出现：")
        lines.extend(f"- {item}" for item in include)
    if avoid:
        lines.append("不要提前写：")
        lines.extend(f"- {item}" for item in avoid)
    ending_change = str(chapter_intent.get("ending_change") or "").strip()
    if ending_change:
        lines.append(f"章尾变化：{ending_change}")
    if hard_facts and not governance_gate.get("blocking"):
        lines.append("不能改的事实：")
        lines.extend(f"- {item}" for item in hard_facts)
    if soft_guidance:
        lines.append("写法提醒：")
        lines.extend(f"- {item}" for item in soft_guidance)
    return "\n".join(lines)


def _governance_bundle_view(chapter_number: int, plan: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        chapter_number=chapter_number,
        chapter_title=str(plan.get("event_plan", {}).get("chapter_title", "")) if isinstance(plan.get("event_plan"), dict) else "",
        event_plan=plan.get("event_plan", {}) if isinstance(plan.get("event_plan"), dict) else {},
        next_outline=str(plan.get("event_plan", {}).get("next_focus", "")) if isinstance(plan.get("event_plan"), dict) else "",
        body="",
        chapter_summary={},
    )


def _build_world_state_review(issues: list[str], revision_plan: list[str]) -> dict[str, Any]:
    """Compatibility wrapper for callers that inspect the legacy module."""
    return _quality_build_world_state_review(issues, revision_plan)


def _merge_world_state_reviews(*reviews: Any) -> dict[str, Any]:
    """Compatibility wrapper for callers that inspect the legacy module."""
    return _quality_merge_world_state_reviews(*reviews)


def _build_simulation_status(story: StoryState) -> dict:
    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    agent_entries = {
        "planner": story.agent_runtime.planner.model_dump(),
        "writer": story.agent_runtime.writer.model_dump(),
        "memory": story.agent_runtime.memory.model_dump(),
    }
    fallback_agents = [name for name, entry in agent_entries.items() if entry.get("source") == "fallback"]
    return {
        "ok": not fallback_agents,
        "mode": "full" if not fallback_agents else "degraded",
        "fallback_agents": fallback_agents,
        "recent_events": list(story.agent_runtime.recent_events),
        "agents": agent_entries,
        "world_pulse": ledger.get("world_pulse", {}),
        "visibility_inbox": ledger.get("visibility_inbox", [])[-12:]
        if isinstance(ledger.get("visibility_inbox"), list)
        else [],
    }


def _failed_bundle(story: StoryState, chapter_number: int, reason: str = ""):
    from packages.story_core.engine import ChapterBundle

    bundle = ChapterBundle(
        chapter_number=chapter_number,
        body=f"生成失败：{reason}" if reason else "",
        chapter_title=f"第{chapter_number}章生成失败" if reason else "",
        cadence="measured",
        chapter_intent={},
        character_moves=[],
        memory_constraints={},
        event_plan={},
        chapter_seed=build_chapter_seed(story, chapter_number),
        simulation_plan={},
        world_events=[],
        scene_cards=[],
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
    if reason:
        bundle.quality_report["ok"] = False
        bundle.quality_report["failure_reason"] = reason
        issues = list(bundle.quality_report.get("issues") or [])
        issues.append(reason)
        bundle.quality_report["issues"] = issues
    return bundle


class StoryOrchestrator:
    def __init__(
        self,
        model_gateway: Any | None = None,
        *,
        use_modular_agents: bool = False,
        project_root: Any | None = None,
    ) -> None:
        self.model_gateway = model_gateway or RuntimeModelGateway()
        # ``use_modular_agents`` flags the new pipeline as the
        # preferred body-generation path. When True, the public
        # ``generate_next_chapter`` entry routes through the
        # Director / Writer / FactExtractor agents instead of
        # the legacy ``resolve_chapter_plan`` /
        # ``generate_chapter_body`` path. ``project_root`` carries
        # the on-disk project the new pipeline reads from; it
        # is ignored on the legacy path which only needs the
        # ``StoryState``. Production callers
        # (``FileProjectStore``) flip both flags on so the
        # workbench drives the new pipeline end-to-end.
        self._use_modular_agents = bool(use_modular_agents)
        self._project_root = project_root
        # The fact extractor is shared between the orchestrator and
        # the candidate-save path so both see the same shape. The
        # default factory produces a model-less extractor; callers
        # that want the model-backed path swap in a runtime-bearing
        # instance via ``set_fact_extractor``. This is the seam Task
        # 14 will tighten when the orchestrator owns the canon
        # registry and can pass a real view to the extractor.
        self._fact_extractor: Any | None = None

    @property
    def use_modular_agents(self) -> bool:
        """Whether the orchestrator routes through the new modular pipeline."""
        return self._use_modular_agents

    def fact_extractor(self) -> Any:
        """Return the active ``FactExtractor`` instance.

        Lazy-constructs the default on first use so importing this
        module does not eagerly pull the fact-extractor package (the
        extractor is only relevant for the candidate-save path).
        """
        if self._fact_extractor is None:
            from packages.story_core.agents.fact_extractor import (
                build_default_extractor,
            )

            self._fact_extractor = build_default_extractor()
        return self._fact_extractor

    def set_fact_extractor(self, extractor: Any) -> None:
        """Install a custom ``FactExtractor`` (used by tests and CLI)."""
        self._fact_extractor = extractor

    def generate_next_chapter_via_modular_pipeline(
        self,
        *,
        project_root: Any,
        chapter_number: int,
        director_runtime: Any | None = None,
        writer_runtime: Any | None = None,
        fact_extractor: Any | None = None,
        consistency_runtime: Any | None = None,
        canon_registry: Any | None = None,
        workflow_store: Any | None = None,
        job_id: str | None = None,
        rewrite_guidance: str = "",
    ) -> Any:
        """Run the new modular agent pipeline end-to-end.

        This is the wiring the Tasks 10-14 infrastructure prepared
        for. The orchestrator calls ``plan_director_artifact`` (new
        :class:`DirectorAgent`), then ``run_writer`` (new
        :class:`WriterAgent` with the side-effect-free canon
        preflight), then ``run_fact_extractor`` (the deterministic
        :class:`FactExtractor`) — the three modules the user
        flagged as missing from the main flow. The returned
        :class:`ModularChapterBundle` carries the
        :class:`DirectorArtifact`, the body, the
        :class:`ContinuityDelta`, and per-stage trace ids so the
        workbench can render each agent's output.

        When ``workflow_store`` is omitted the orchestrator
        instantiates a :class:`WorkflowArtifactStore` rooted at
        ``project_root`` so each stage lands an artifact under
        ``.story-system/workflow/{job_id}/`` for the workbench to
        re-render. ``job_id`` defaults to
        ``chapter-{N}-{timestamp}`` so parallel runs of the same
        chapter do not collide.

        Tests call this directly to assert the three modules were
        called exactly once. The legacy
        ``generate_next_chapter_bundle`` is unchanged so the
        existing test suite keeps working.
        """
        from packages.story_core.agents.fact_extractor import FactExtractor
        from packages.story_core.agents.pipeline import run_modular_pipeline
        from packages.story_core.persistence.workflow_artifact_store import (
            WorkflowArtifactStore,
        )

        if fact_extractor is None:
            fact_extractor = self.fact_extractor() or FactExtractor()
        if workflow_store is None:
            workflow_store = WorkflowArtifactStore(project_root)
        if job_id is None:
            from datetime import datetime, timezone

            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            job_id = f"chapter-{chapter_number}-{stamp}"
        # The pipeline accepts an explicit ``canon_registry`` so the
        # caller can decide which canon the new Director / Writer /
        # FactExtractor stages should see. The previous round
        # defaulted to a fresh in-memory registry, which meant a
        # long-running project silently lost every character, item,
        # and relationship the user had confirmed — the
        # ``FactExtractor`` would re-extract against an empty world
        # and the resulting ``ContinuityDelta`` could not anchor
        # back to anything. When the caller did not pass a
        # registry, we now read the project's on-disk canon via
        # the same helper ``_apply_candidate_canon_delta`` writes
        # back on confirmation, so the next chapter's pipeline
        # sees the world the user actually has.
        if canon_registry is None:
            try:
                canon_registry = _load_canon_registry_for_project_root(project_root)
            except Exception:
                canon_registry = None
        return run_modular_pipeline(
            project_root=project_root,
            chapter_number=chapter_number,
            director_runtime=director_runtime,
            writer_runtime=writer_runtime,
            fact_extractor=fact_extractor,
            consistency_runtime=consistency_runtime,
            canon_registry=canon_registry,
            workflow_store=workflow_store,
            job_id=job_id,
            rewrite_guidance=rewrite_guidance,
        )

    def _emit_workflow_step(
        self,
        step_id: str,
        label: str,
        *,
        status: str = "running",
        source: str = "orchestrator",
        used_modules: list[str] | None = None,
        reads: list[str] | None = None,
        outputs: dict[str, Any] | None = None,
    ) -> None:
        report_generation_progress(
            build_chapter_pipeline_event(
                step_id,
                label,
                status=status,
                source=source,
                used_modules=used_modules,
                reads=reads,
                outputs=outputs,
            )
        )

    def _emit_progress_with_artifact(
        self,
        message: str,
        stage: str,
        *,
        source: str = "orchestrator",
        used_modules: list[str] | None = None,
        reason: str | None = None,
        inputs: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        keep_legacy_text: bool = True,
    ) -> None:
        if keep_legacy_text:
            report_generation_progress(message)
        if source and (used_modules or reason or inputs or outputs):
            artifact: dict[str, Any] = {}
            if used_modules:
                artifact["used_modules"] = used_modules
            if reason:
                artifact["reason"] = reason
            if inputs:
                artifact["inputs"] = inputs
            if outputs:
                artifact["outputs"] = outputs
            report_generation_progress(
                {
                    "message": message,
                    "stage": stage,
                    "source": source,
                    "artifact": artifact,
                }
            )

    @staticmethod
    def _model_system_prompt(json_mode: bool, agent: str = "") -> str:
        if json_mode:
            return "You are a novel planning and state engine. Respond in json format only."
        if agent == "writer":
            return "你是中文网文写手。只输出正在发生的小说正文，不解释创作规则、剧情作用或输入要求；已经通过人物行动表现的信息不要再总结一遍。"
        return "你是中文网文作者。只把给定剧情写成正在发生的场景，不解释创作规则，不总结已经通过动作表现出的信息。"

    def _chat(
        self,
        story: StoryState,
        prompt: str,
        *,
        max_tokens: int,
        json_mode: bool,
        agent: str = "planner",
        stage: str = "",
        timeout_seconds: int | None = None,
    ) -> tuple[str, str]:
        runtime_stage = "writer" if agent == "writer" else "planner"
        prepared_runtime = getattr(self, "_prepared_runtime_request", None)
        if prepared_runtime is not None and prepared_runtime[0] == runtime_stage:
            settings = prepared_runtime[1]
            self._prepared_runtime_request = None
        else:
            settings = resolve_stage_runtime(runtime_stage)
        self._last_runtime_request = (runtime_stage, settings)
        model = settings.model
        temperature = float(settings.temperature)
        if json_mode and max_tokens < 2000:
            max_tokens = 2000

        system_msg = self._model_system_prompt(json_mode, agent=agent)
        request = ModelRequest(
            prompt=prompt,
            system_prompt=system_msg,
            provider=settings.provider,
            model=model,
            operation=agent,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
        )

        if stage:
            timeout_label = timeout_seconds if timeout_seconds is not None else "default"
            report_generation_progress(f"{stage}：模型请求中（超时 {timeout_label} 秒）")

        complete_resolved = getattr(self.model_gateway, "complete_resolved", None)
        if callable(complete_resolved):
            response = complete_resolved(settings, request)
        else:
            response = self.model_gateway.complete_stage(runtime_stage, request)
        self._last_model_response = response
        if not response.ok:
            error = normalize_model_error(response)
            if stage:
                error = f"{stage} model_request_failed:{error}"
                report_generation_progress(f"模型请求失败：{error}")
            return "", error
        if json_mode:
            parsed = _parse_json_text(response.text)
            if parsed is None:
                return "", "invalid_json_response"
            if stage:
                report_generation_progress(f"{stage}：模型返回完成")
            return json.dumps(parsed, ensure_ascii=False), ""
        text = str(response.text or "")
        if stage and text:
            report_generation_progress(f"{stage}：模型返回完成")
        return text, "" if text else "empty_model_response"

    def _timed_chat(
        self,
        story: StoryState,
        prompt: str,
        *,
        max_tokens: int,
        json_mode: bool,
        agent: str = "planner",
        stage: str,
        timeout_seconds: int | None = None,
    ) -> tuple[str, str]:
        runtime_stage = "writer" if agent == "writer" else "planner"
        self._last_runtime_request = None
        self._last_model_response = None
        template_key = ""
        module_keys: list[str] = []
        if runtime_stage == "planner":
            template_key = genre_stage_profile_for(story).director_template_key
            module_keys = ["core_context", "outline_context", "character_context"]
        elif runtime_stage == "writer":
            if "扩写" in stage:
                template_key = "expansion"
            elif "压缩" in stage:
                template_key = "compression"
            elif any(marker in stage for marker in ("改稿", "修订", "重写")):
                template_key = "revision"
            else:
                template_key = "writer"
            module_keys = [
                "core_context",
                "outline_context",
                "chapter_plan",
                "character_context",
                "dialogue_context",
                "genre_context",
                "writing_taskbook",
                "style_context",
            ]
        genre_stage = {
            "director": "director",
            "director_generic": "director",
            "writer": "writer",
            "revision": "revision",
            "expansion": "length",
            "compression": "length",
        }.get(template_key, "")
        template_source = ""
        template_version = ""
        if template_key:
            try:
                template = get_effective_prompt_template(template_key)
                template_version = template.version
                template_source = get_effective_prompt_template_source(template_key)
            except KeyError:
                template_key = ""
        initial_settings = resolve_stage_runtime(runtime_stage)
        self._prepared_runtime_request = (runtime_stage, initial_settings)
        call_id = start_prompt_call(
            chapter_number=story.current_chapter,
            stage=stage,
            agent=runtime_stage,
            user_prompt=prompt,
            system_prompt=self._model_system_prompt(json_mode),
            module_keys=module_keys,
            template_key=template_key,
            template_source=template_source,
            template_version=template_version,
            provider=initial_settings.provider,
            protocol=str(getattr(initial_settings, "protocol", "")),
            model=initial_settings.model,
            temperature=float(getattr(initial_settings, "temperature", 0.2)),
            genre_stage=genre_stage,
        )
        started = perf_counter()
        chat_kwargs: dict[str, Any] = {
            "max_tokens": max_tokens,
            "json_mode": json_mode,
            "agent": agent,
        }
        if timeout_seconds is not None:
            chat_kwargs["timeout_seconds"] = timeout_seconds
        try:
            try:
                text, error = self._chat(story, prompt, **chat_kwargs)
            except TypeError as exc:
                if timeout_seconds is None or "timeout_seconds" not in str(exc):
                    raise
                chat_kwargs.pop("timeout_seconds", None)
                text, error = self._chat(story, prompt, **chat_kwargs)
        except Exception as exc:
            elapsed = perf_counter() - started
            self._prepared_runtime_request = None
            finish_prompt_call(
                call_id,
                status="failed",
                provider=initial_settings.provider,
                protocol=str(getattr(initial_settings, "protocol", "")),
                model=initial_settings.model,
                elapsed_seconds=elapsed,
                error=str(exc),
            )
            raise
        self._prepared_runtime_request = None
        elapsed = perf_counter() - started
        suffix = "失败" if error else "完成"
        report_generation_progress(f"{stage}耗时 {elapsed:.1f}s：{suffix}")
        runtime_request = self._last_runtime_request
        settings = (
            runtime_request[1]
            if runtime_request is not None and runtime_request[0] == runtime_stage
            else initial_settings
        )
        model_response = self._last_model_response
        actual_provider = str(getattr(model_response, "provider", "") or settings.provider)
        actual_model = str(getattr(model_response, "model", "") or settings.model)
        actual_protocol = str(getattr(settings, "protocol", ""))
        if actual_provider != settings.provider:
            try:
                actual_protocol = provider_definition(actual_provider).protocol
            except (KeyError, ValueError):
                pass
        record_stage_runtime(
            story,
            runtime_stage,
            "fallback" if error else "llm",
            actual_provider,
            actual_model,
            story.current_chapter,
            fallback_reason=error,
        )
        finish_prompt_call(
            call_id,
            status="failed" if error else "succeeded",
            provider=actual_provider,
            protocol=actual_protocol,
            model=actual_model,
            elapsed_seconds=elapsed,
            output=text,
            error=error,
        )
        return text, error

    def _plan_prompt(
        self,
        story: StoryState,
        chapter_number: int,
        director_context: dict[str, Any] | None = None,
    ) -> str:
        return self._render_plan_prompt(story, chapter_number, director_context)

    def _render_plan_prompt(
        self,
        story: StoryState,
        chapter_number: int,
        director_context: dict[str, Any] | None = None,
    ) -> str:
        director_context = director_context or _director_context_payload(story, chapter_number)
        snapshot = _director_prompt_snapshot(director_context.get("project_snapshot", {}))
        chapter_seed = _director_prompt_chapter_seed(director_context.get("chapter_seed", {}))
        character_cards = _director_prompt_character_cards(director_context.get("character_cards", {}))
        if "raw_project_snapshot" in director_context:
            raw_project_snapshot = director_context["raw_project_snapshot"]
        else:
            raw_project_snapshot = _story_snapshot(story)
        if "raw_outline_context" in director_context:
            raw_outline_context = director_context["raw_outline_context"]
        else:
            raw_outline_context = story.outline_context
        if "raw_character_cards" in director_context:
            raw_character_cards = director_context["raw_character_cards"]
        else:
            relevant_characters = _director_characters(story, limit=4)
            selector_plan = {
                "character_moves": [
                    {"name": character.name}
                    for character in relevant_characters
                ]
            }
            raw_character_cards = _character_context_for_prompt(
                story,
                selector_plan,
                max_items=4,
                include_memory=True,
            )
        values = {
            "project_snapshot": _plain_prompt_json(snapshot),
            "raw_project_snapshot": raw_project_snapshot,
            "raw_outline_context": raw_outline_context,
            "chapter_seed": _plain_prompt_json(chapter_seed),
            "character_cards": _plain_prompt_json(character_cards),
            "raw_character_cards": raw_character_cards,
        }
        profile = genre_stage_profile_for(story, director_context)
        return profile.render_director_prompt(
            story=story,
            chapter_number=chapter_number,
            plan=director_context,
            values=values,
        )

    def _body_prompt(self, story: StoryState, chapter_number: int, plan: dict) -> str:
        return self._render_body_prompt(story, chapter_number, plan)

    def _build_writer_context(self, story: StoryState, chapter_number: int, plan: dict) -> WriterContext:
        plan = plan if isinstance(plan, dict) else {}
        plan = {**plan, "writing_taskbook": ensure_writing_taskbook(chapter_number, plan, genre=story.genre, style=story.style)}
        style_guidance = plan.get("style_guidance") if isinstance(plan.get("style_guidance"), dict) else {}
        if not style_guidance:
            style_guidance = build_style_guidance(
                genre=story.genre,
                style=story.style,
                chapter_number=chapter_number,
            )
        character_context = _character_context_for_prompt(story, plan, max_items=4)
        dialogue_context = build_dialogue_context(character_context, plan)
        skill_context = _skill_context_for_prompt(story, ("writer", "dialogue", "style", "genre"))
        replaced_defaults = set(skill_context.get("_replaced_defaults", []))
        skill_context_for_prompt = {key: value for key, value in skill_context.items() if key != "_replaced_defaults"}
        include_genre_method = "genre_context" not in replaced_defaults
        plan_seed = plan.get("chapter_seed")
        chapter_seed = deepcopy(plan_seed) if isinstance(plan_seed, dict) and plan_seed else build_chapter_seed(story, chapter_number)
        chapter_seed_for_prompt = _writer_seed_summary(_plain_prompt_payload(chapter_seed))
        trope_contract = (
            chapter_seed_for_prompt.get("当前阶段套路")
            if isinstance(chapter_seed_for_prompt.get("当前阶段套路"), dict)
            else chapter_seed_for_prompt.get("trope_contract")
            if isinstance(chapter_seed_for_prompt.get("trope_contract"), dict)
            else {}
        )
        writer_context = WriterContext(
            story=story,
            chapter_number=chapter_number,
            plan=plan,
            style_guidance=style_guidance,
            character_context=character_context,
            dialogue_context=dialogue_context,
            chapter_seed=chapter_seed_for_prompt,
            skill_context=skill_context_for_prompt,
            include_genre_method=include_genre_method,
            writer_plan_for_prompt=_compact_writer_plan_for_prompt(plan),
            world_facts_for_prompt=_priority_world_facts(story.world_facts, max_items=6, item_chars=100),
            trope_guidance=_trope_contract_guidance(trope_contract),
            trope_contract_for_prompt=_compact_trope_contract_for_prompt(trope_contract),
        )
        return writer_context

    def _render_body_prompt(self, story: StoryState, chapter_number: int, plan: dict) -> str:
        writer_context = self._build_writer_context(story, chapter_number, plan)
        profile = genre_stage_profile_for(story, plan)
        return profile.render_writer_prompt(context=writer_context)

    def _revision_prompt(self, story: StoryState, chapter_number: int, body: str, plan: dict, review: dict) -> str:
        return self._render_revision_prompt(story, chapter_number, body, plan, review)

    def _render_revision_prompt(self, story: StoryState, chapter_number: int, body: str, plan: dict, review: dict) -> str:
        writer_context = self._build_writer_context(story, chapter_number, plan)
        context = RevisionContext(
            story=story,
            chapter_number=chapter_number,
            body=body,
            plan=plan,
            review=review,
            writer_context=writer_context,
        )
        return genre_stage_profile_for(story, plan).render_revision_prompt(context=context)

    def _extract_final_body_memory(
        self,
        story: StoryState,
        body: str,
        chapter_number: int,
        *,
        fact_locks: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        previous_summary = story.chapter_summaries[-1] if story.chapter_summaries else None
        open_foreshadowing = [
            item.text
            for item in select_unresolved_foreshadowing(
                story.foreshadowing,
                chapter_number=chapter_number,
                limit=8,
            )
        ]
        memory_fact_locks = dict(fact_locks or {})
        memory_fact_locks["open_foreshadowing"] = open_foreshadowing
        prompt = build_post_draft_memory_prompt(
            body,
            previous_summary=previous_summary.summary if previous_summary else "",
            existing_character_names=character_update_names(story.characters),
            character_aliases_by_name=character_aliases_by_name(story.characters),
            genre=story.genre,
            fact_locks=memory_fact_locks,
        )
        self._emit_progress_with_artifact(
            "最终正文记忆提取中...",
            "memory_post_draft",
            source="memory",
            used_modules=["memory_agent", "post_draft_memory", "writer_agent"],
            reason="将正文压缩为下一章状态摘要和账本变动",
            inputs={
                "story_id": story.story_id,
                "chapter_number": chapter_number,
                "body_chars": len(body),
                "prompt_chars": len(prompt),
            },
        )
        memory_text, memory_error = self._timed_chat(
            story,
            prompt,
            max_tokens=2200,
            json_mode=True,
            agent="memory",
            stage=f"最终正文记忆 第{chapter_number}章",
        )
        if memory_error:
            self._emit_progress_with_artifact(
                "最终正文记忆提取失败",
                "memory_post_draft",
                source="memory",
                used_modules=["memory_agent", "post_draft_memory"],
                reason="模型未返回可解析记忆，fallback",
                inputs={"chapter_number": chapter_number},
                outputs={"error": memory_error},
            )
            return fallback_post_draft_memory(body), {
                "status": "fallback",
                "rejected_count": 0,
                "reason": compact_text(memory_error, 120),
            }
        try:
            payload = json.loads(memory_text)
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            current = story.agent_runtime.memory
            record_stage_runtime(
                story,
                "memory",
                "fallback",
                current.provider,
                current.model,
                chapter_number,
                fallback_reason="memory_invalid_json",
            )
            self._emit_progress_with_artifact(
                "最终正文记忆JSON解析失败",
                "memory_post_draft",
                source="memory",
                used_modules=["memory_agent", "post_draft_memory"],
                reason="返回内容不是字典，改用安全后备逻辑",
                inputs={"chapter_number": chapter_number},
                outputs={"raw_payload_type": type(memory_text).__name__},
            )
            return fallback_post_draft_memory(body), {
                "status": "fallback",
                "rejected_count": 0,
                "reason": "memory_invalid_json",
            }
        normalizer_kwargs = {
            "body": body,
            "existing_character_names": character_update_names(story.characters),
            "evidence_character_names": character_evidence_names(story.characters),
            "character_aliases_by_name": character_aliases_by_name(story.characters),
            "protagonist_aliases": protagonist_aliases_from_characters(story.characters),
        }
        if "chapter_number" in inspect.signature(normalize_post_draft_memory).parameters:
            normalizer_kwargs["chapter_number"] = chapter_number
        if "open_foreshadowing_texts" in inspect.signature(normalize_post_draft_memory).parameters:
            normalizer_kwargs["open_foreshadowing_texts"] = open_foreshadowing
        memory = normalize_post_draft_memory(payload, **normalizer_kwargs)
        has_grounded_memory = any(
            memory.get(key)
            for key in (
                "summary",
                "facts",
                "unresolved_threads",
                "resolved_threads",
                "character_updates",
                "equipment_updates",
                "ledger_updates",
            )
        )
        if not has_grounded_memory:
            current = story.agent_runtime.memory
            record_stage_runtime(
                story,
                "memory",
                "fallback",
                current.provider,
                current.model,
                chapter_number,
                fallback_reason="memory_has_no_grounded_updates",
            )
            self._emit_progress_with_artifact(
                "最终正文记忆无有效事实",
                "memory_post_draft",
                source="memory",
                used_modules=["memory_agent", "post_draft_memory"],
                reason="记忆缺失关键字段，改走后备记忆抽取",
                inputs={"chapter_number": chapter_number},
                outputs={"rejected_updates": len(memory.get("rejected_updates", []))},
            )
            return fallback_post_draft_memory(body), {
                "status": "fallback",
                "rejected_count": len(memory.get("rejected_updates", [])),
                "reason": "memory_has_no_grounded_updates",
            }
        self._emit_progress_with_artifact(
            "最终正文记忆提取完成",
            "memory_post_draft",
            source="memory",
            used_modules=["memory_agent", "post_draft_memory"],
            reason="记忆落盘成功，可用于下一章状态更新",
            inputs={"chapter_number": chapter_number},
            outputs={
                "summary": bool(memory.get("summary")),
                "facts": len(memory.get("facts", [])),
                "unresolved_threads": len(memory.get("unresolved_threads", [])),
                "rejected_updates": len(memory.get("rejected_updates", [])),
            },
        )
        return memory, {
            "status": "ok",
            "rejected_count": len(memory.get("rejected_updates", [])),
        }

    def refresh_revised_bundle_metadata(self, base_story: StoryState, bundle: Any) -> Any:
        """Rebuild summary, ledger and memory surfaces after latest-chapter revision."""
        refreshed_bundle = bundle.model_copy(deep=True)
        refreshed_bundle.body = _postprocess_chapter_output(
            base_story,
            refreshed_bundle.body,
            chapter_number=refreshed_bundle.chapter_number,
            scene_cards=refreshed_bundle.scene_cards,
        )
        chapter_number = refreshed_bundle.chapter_number
        working_story = base_story.model_copy(deep=True)
        working_story.current_chapter = chapter_number

        memory_constraints = _normalize_memory_constraints(refreshed_bundle.memory_constraints, working_story)
        memory_constraints["must_keep_facts"] = []
        memory_constraints["ledger_updates"] = {}
        conflict_summary = refreshed_bundle.conflict_summary if isinstance(refreshed_bundle.conflict_summary, dict) else {}
        event_beat = refreshed_bundle.event_beat if isinstance(refreshed_bundle.event_beat, dict) else {}
        post_draft_memory, memory_sync = self._extract_final_body_memory(
            working_story,
            refreshed_bundle.body,
            chapter_number,
            fact_locks={"previous_chapter_summary": refreshed_bundle.chapter_summary},
        )
        memory_is_verified = memory_sync.get("status") == "ok"
        persisted_conflict: dict[str, Any] = {}
        persisted_event_beat: dict[str, Any] = {}

        updated_story = working_story.model_copy(deep=True)
        apply_post_chapter_updates(
            updated_story,
            refreshed_bundle.body,
            chapter_number,
            conflict_summary=persisted_conflict,
            event_beat=persisted_event_beat,
            post_draft_memory=post_draft_memory,
        )
        _apply_ledger_updates(
            updated_story,
            post_draft_memory.get("ledger_updates", {}),
            chapter_number=chapter_number,
        )
        _sync_character_game_panels(updated_story, chapter_number)
        if is_game_story(updated_story):
            advance_world_pulse(updated_story, chapter_number=chapter_number)
        maybe_update_arc_recap(updated_story, chapter_number)

        if updated_story.chapter_summaries:
            latest_summary = updated_story.chapter_summaries[-1]
            revised_title_focus = (
                f"{working_story.outline} {refreshed_bundle.body} {latest_summary.next_focus}"
            )
            latest_summary.chapter_title = _planned_chapter_title(
                event_plan=refreshed_bundle.event_plan,
                chapter_intent=None,
                chapter_summary=None,
            ) or latest_summary.chapter_title
            latest_summary.chapter_title = _repair_generic_chapter_title(
                latest_summary.chapter_title,
                chapter_number=chapter_number,
                next_focus=revised_title_focus,
                conflict_summary=persisted_conflict,
                genre=working_story.genre,
            )
            latest_summary.cadence = refreshed_bundle.cadence  # type: ignore[assignment]
            refreshed_bundle.chapter_title = latest_summary.chapter_title
            refreshed_bundle.chapter_summary = latest_summary.model_dump()

        refreshed_bundle.memory_constraints = memory_constraints
        refreshed_bundle.simulation_plan = (
            dict(refreshed_bundle.simulation_plan)
            if isinstance(refreshed_bundle.simulation_plan, dict)
            else {}
        )
        refreshed_bundle.simulation_plan["memory_sync"] = memory_sync
        refreshed_bundle.quality_report = (
            dict(refreshed_bundle.quality_report)
            if isinstance(refreshed_bundle.quality_report, dict)
            else {}
        )
        refreshed_bundle.quality_report["memory_sync"] = memory_sync
        refreshed_bundle.updated_story = updated_story
        refreshed_bundle.simulation_status = _build_simulation_status(updated_story)
        refreshed_bundle.character_cards = build_character_cards(updated_story)
        refreshed_bundle.foreshadowing = build_foreshadowing(updated_story, chapter_number)
        refreshed_bundle.next_outline = plan_next_outline(
            updated_story,
            chapter_number,
            conflict_summary=persisted_conflict,
            cadence=refreshed_bundle.cadence,
        )
        return refreshed_bundle

    def revise_chapter_body(
        self,
        story: StoryState,
        bundle,
        review: dict,
        instructions: list[str] | None = None,
    ) -> tuple[str, dict, str]:
        revision_review = dict(review or {})
        manual_instructions = [str(instruction).strip() for instruction in (instructions or []) if str(instruction).strip()]
        revision_review["manual_instructions"] = manual_instructions
        original_quality_seed = bundle.model_dump()
        original_quality_seed["manual_instructions"] = manual_instructions
        original_quality = _merge_writing_review_quality(validate_bundle(original_quality_seed), revision_review)
        original_quality["has_hard_errors"] = bool(
            build_simplified_review(original_quality).get("has_hard_errors")
        )
        plan = {
            "character_moves": bundle.character_moves,
            "chapter_intent": bundle.chapter_intent,
            "event_plan": bundle.event_plan,
            "memory_constraints": bundle.memory_constraints,
            "chapter_seed": getattr(bundle, "chapter_seed", {}),
            "governance": build_chapter_governance(story, bundle, chapter_number=bundle.chapter_number),
        }
        patched_body, patch_report = apply_expression_patches_from_review(bundle.body, revision_review)
        if patch_report.get("applied"):
            patched_body = _postprocess_chapter_output(
                story,
                patched_body,
                chapter_number=bundle.chapter_number,
                scene_cards=bundle.scene_cards,
            )
            quality_seed = bundle.model_dump()
            quality_seed["body"] = patched_body
            quality_seed["manual_instructions"] = manual_instructions
            patched_review = _review_chapter_body(
                bundle.chapter_number,
                patched_body,
                bundle.event_plan,
                _review_context_facts(story),
                getattr(bundle, "simulation_plan", {}),
                getattr(bundle, "world_events", []),
                getattr(bundle, "scene_cards", []),
                genre_context=_story_review_genre_context(story),
                protagonist_aliases=tuple(protagonist_aliases_from_characters(story.characters)),
                character_names=_review_character_names(story),
            )
            patched_review["expression_patch_report"] = patch_report
            patched_quality = _merge_writing_review_quality(validate_bundle(quality_seed), patched_review)
            patched_quality["has_hard_errors"] = bool(
                build_simplified_review(patched_quality).get("has_hard_errors")
            )
            patch_safety = choose_best_revision(
                original_body=bundle.body,
                original_quality=original_quality,
                candidate_body=patched_body,
                candidate_quality=patched_quality,
            )
            selected_patch_quality = dict(patch_safety["quality"])
            selected_patch_quality["revision_safety"] = patch_safety["report"]
            patched_body = str(patch_safety["body"])
            patched_quality = selected_patch_quality
            cut_review = patched_review.get("adversarial_cut_review", {})
            if not manual_instructions and patch_safety.get("accepted") and (
                patched_review.get("pass") or (isinstance(cut_review, dict) and cut_review.get("pass"))
            ):
                record_stage_runtime(
                    story,
                    "writer",
                    "fallback",
                    "",
                    "",
                    story.current_chapter,
                    fallback_reason="本地表达修补",
                )
                return patched_body, patched_quality, ""

        revised_body, error = self._timed_chat(
            story,
            self._revision_prompt(story, bundle.chapter_number, bundle.body, plan, revision_review),
            max_tokens=7000,
            json_mode=False,
            agent="writer",
            stage=f"自动改稿 第{bundle.chapter_number}章",
        )
        if error or not revised_body.strip():
            return "", {}, error or "revision_empty"

        revised_body = _postprocess_chapter_output(
            story,
            revised_body,
            chapter_number=bundle.chapter_number,
            scene_cards=bundle.scene_cards,
        )
        quality_seed = bundle.model_dump()
        quality_seed["body"] = revised_body
        quality_seed["manual_instructions"] = manual_instructions
        writing_review = _review_chapter_body(
            bundle.chapter_number,
            revised_body,
            bundle.event_plan,
            _review_context_facts(story),
            getattr(bundle, "simulation_plan", {}),
            getattr(bundle, "world_events", []),
            getattr(bundle, "scene_cards", []),
            genre_context=_story_review_genre_context(story),
            protagonist_aliases=tuple(protagonist_aliases_from_characters(story.characters)),
            character_names=_review_character_names(story),
        )
        quality_report = _merge_writing_review_quality(validate_bundle(quality_seed), writing_review)
        quality_report["has_hard_errors"] = bool(
            build_simplified_review(quality_report).get("has_hard_errors")
        )
        safety = choose_best_revision(
            original_body=bundle.body,
            original_quality=original_quality,
            candidate_body=revised_body,
            candidate_quality=quality_report,
        )
        selected_quality = dict(safety["quality"])
        selected_quality["revision_safety"] = safety["report"]
        revised_body = str(safety["body"])
        quality_report = selected_quality
        return revised_body, quality_report, ""

    def generate_next_chapter(
        self,
        story: StoryState,
        *,
        project_root: Any | None = None,
        director_runtime: Any | None = None,
        writer_runtime: Any | None = None,
        fact_extractor: Any | None = None,
    ):
        # The workbench path: route through the new modular
        # pipeline. The new Director → CanonService preflight →
        # Writer → FactExtractor flow produces a body + a
        # ``DirectorArtifact`` + a ``ContinuityDelta``; we
        # build a minimal ``ChapterBundle`` so the existing
        # save / confirm / persist flow keeps working. The
        # bounded review and the revision controller are
        # intentionally not re-run here: the new pipeline's
        # ``FocusedConsistencyAgent`` already surfaces
        # deterministic contradictions during the writer
        # stage, and the user's confirmation gate is the
        # final safety net.
        if self._use_modular_agents:
            effective_root = project_root or self._project_root
            if effective_root is not None:
                return self._generate_next_chapter_bundle_via_modular_agents(
                    story,
                    project_root=effective_root,
                    director_runtime=director_runtime,
                    writer_runtime=writer_runtime,
                    fact_extractor=fact_extractor,
                )
        return ChapterPipeline().run(
            story,
            generate_bundle=self._generate_next_chapter_bundle,
        )

    def _generate_next_chapter_bundle_via_modular_agents(
        self,
        story: StoryState,
        *,
        project_root: Any,
        director_runtime: Any | None = None,
        writer_runtime: Any | None = None,
        fact_extractor: Any | None = None,
        consistency_runtime: Any | None = None,
    ) -> Any:
        """Produce a legacy ``ChapterBundle`` from the modular pipeline.

        The new pipeline returns a :class:`ModularChapterBundle`
        with the body, the director's artifact, and the
        fact-extractor's ``ContinuityDelta``. The legacy
        :class:`ChapterBundle` the workbench and the
        file-project store consume has 24 typed fields; the
        synthesis here is deliberately lossy — the new
        pipeline's body and trace ids are the real signal,
        and the rest of the bundle is filled with the minimum
        the downstream save / confirm / persist flow needs.
        """
        chapter_number = int(story.current_chapter or 0) + 1
        rewrite_guidance = ""
        progression_ledger = getattr(story, "progression_ledger", None)
        if isinstance(progression_ledger, dict):
            simulation_variant = progression_ledger.get("simulation_variant")
            if isinstance(simulation_variant, dict):
                guidance_payload = simulation_variant.get("rewrite_guidance")
                if isinstance(guidance_payload, dict):
                    rewrite_guidance = str(guidance_payload.get("text") or "").strip()
        bundle = self.generate_next_chapter_via_modular_pipeline(
            project_root=project_root,
            chapter_number=chapter_number,
            director_runtime=director_runtime,
            writer_runtime=writer_runtime,
            fact_extractor=fact_extractor,
            consistency_runtime=consistency_runtime,
            rewrite_guidance=rewrite_guidance,
        )
        from packages.story_core.modular_bundle_adapter import (
            adapt_modular_bundle_to_legacy,
        )

        legacy_bundle = adapt_modular_bundle_to_legacy(
            story=story,
            modular_bundle=bundle,
            chapter_number=chapter_number,
        )
        director_review = review_director_result_leak(
            legacy_bundle.body,
            director_results=[
                str(beat.result or "")
                for beat in (bundle.director_artifact.scene_beats or [])
            ],
        )
        quality_report = dict(legacy_bundle.quality_report or {})
        existing_review = dict(quality_report.get("writing_review") or {})
        existing_issues = [str(item) for item in (existing_review.get("issues") or [])]
        director_issues = [str(item) for item in director_review.get("issues") or []]
        existing_hard = [str(item) for item in (existing_review.get("hard_issues") or [])]
        existing_plan = [str(item) for item in (existing_review.get("revision_plan") or [])]
        combined_review = {
            **existing_review,
            "pass": bool(existing_review.get("pass", True))
            and bool(director_review.get("pass", True)),
            "issues": list(dict.fromkeys([*existing_issues, *director_issues])),
            "hard_issues": list(dict.fromkeys([*existing_hard, *director_issues])),
            "soft_issues": list(existing_review.get("soft_issues") or []),
            "revision_plan": list(
                dict.fromkeys(
                    [*existing_plan, *[str(item) for item in director_review.get("revision_plan") or []]]
                )
            ),
            "scores": {
                **dict(existing_review.get("scores") or {}),
                **dict(director_review.get("scores") or {}),
            },
            "requires_revision": (
                not bool(existing_review.get("pass", True))
                or not bool(director_review.get("pass", True))
            ),
            "severity_summary": {
                "has_hard_violation": bool(director_issues),
                "soft_violation_count": 0,
                "soft_threshold": 3,
            },
        }
        legacy_bundle.quality_report = _merge_writing_review_quality(
            quality_report,
            combined_review,
        )
        return legacy_bundle

    def _generate_next_chapter_bundle(self, story: StoryState):
        from packages.story_core.engine import ChapterBundle

        chapter_number = story.current_chapter + 1
        working_story = story.model_copy(deep=True)
        working_story.current_chapter = chapter_number
        for runtime_stage in ("planner", "writer", "memory"):
            setattr(working_story.agent_runtime, runtime_stage, StageRuntimeEntry())
        director_context = _director_context_payload(working_story, chapter_number)
        prepared_context = prepare_chapter_context(working_story, chapter_number, director_context)
        planning_character_cards = prepared_context.planning_character_cards
        outline_snapshot = prepared_context.outline_snapshot
        context_package = prepared_context.context_package

        report_generation_progress("剧情计划生成中...")
        for context_event in build_context_stage_events(prepared_context):
            report_generation_progress(context_event)
        outline_plan = build_outline_chapter_plan(director_context, chapter_number)
        initial_planning_source = "outline" if outline_plan is not None else "model_fallback"
        initial_planning_modules = ["chapter_planning"] if outline_plan is not None else ["chapter_planning", "planner_model"]
        self._emit_workflow_step(
            "director_plan",
            "章节规划",
            status="running",
            source="chapter_planning",
            used_modules=initial_planning_modules,
            reads=["大纲读取结果", "本章角色卡", "世界观与连续性"],
        )

        planning_profile = genre_stage_profile_for(working_story, director_context)
        self._emit_progress_with_artifact(
            "剧情计划生成中...",
            "outline_plan",
            source="chapter_planning",
            used_modules=[*initial_planning_modules, "outline_agent", "character_agent", "memory_retrieval"],
            reason="读取相关大纲、连续性、长期记忆、世界状态和角色卡，生成本章剧情计划",
            inputs={
                "chapter_number": chapter_number,
                "story_outline": outline_snapshot,
                "character_cards": planning_character_cards,
                "project_snapshot": director_context.get("project_snapshot", {}),
                "chapter_seed": director_context.get("chapter_seed", {}),
                "genre_stage_profile": planning_profile.profile_id,
                "opening_phase": planning_profile.chapter_phase(chapter_number),
                "characters": [character.name for character in working_story.characters],
                "world_facts_count": len(working_story.world_facts),
            },
        )

        def report_planning_event(name: str, payload: dict[str, Any]) -> None:
            if name == "format_retry":
                self._emit_progress_with_artifact(
                    "章节规划补全返回格式错误，正在重试...",
                    "outline_plan_retry",
                    source="director",
                    used_modules=["director_agent", "json_contract"],
                    reason="第一次导演输出不是有效JSON，使用同一上下文做一次严格格式重试",
                    inputs={"chapter_number": chapter_number, **payload},
                )
            elif name == "quality_retry":
                self._emit_progress_with_artifact(
                    "章节规划未通过，定向重做中...",
                    "director_quality_gate",
                    source="director",
                    used_modules=["director_agent", "continuity_gate"],
                    reason="章节规划存在硬性结构或连续性错误，禁止交给写手",
                    inputs=payload,
                )
            elif name == "quality_failed":
                self._emit_progress_with_artifact(
                    "章节规划重做后仍未通过",
                    "director_quality_gate",
                    source="director",
                    used_modules=["director_agent", "continuity_gate"],
                    reason="第二次章节规划仍有硬性错误，本轮生成终止",
                    outputs=payload,
                )

        planning_result = resolve_chapter_plan(
            outline_plan=outline_plan,
            build_prompt=lambda: self._plan_prompt(working_story, chapter_number, director_context),
            call_model=lambda prompt, stage: self._timed_chat(
                working_story,
                prompt,
                max_tokens=8000,
                json_mode=True,
                agent="planner",
                stage=stage,
            ),
            review_plan=lambda candidate: _director_plan_quality_issues(working_story, candidate),
            build_revision_prompt=_director_revision_prompt,
            prepare_plan=lambda candidate: _ensure_director_scene_chain(working_story, candidate),
            on_event=report_planning_event,
        )
        planning_source = planning_result.planning_source
        planning_modules = planning_result.planning_modules
        if not planning_result.ok:
            planning_error = planning_result.error or "plan_empty"
            self._emit_workflow_step(
                "director_plan",
                "章节规划",
                status="error",
                source="chapter_planning",
                used_modules=planning_modules,
                reads=["大纲读取结果", "本章角色卡", "世界观与连续性"],
                outputs={"error": planning_error},
            )
            if planning_error.startswith("outline_plan_parse_failed"):
                self._emit_progress_with_artifact(
                    "剧情计划解析失败",
                    "outline_plan",
                    source="director",
                    used_modules=["director_agent", "outline_agent", "character_agent", "memory_retrieval"],
                    reason="规划返回内容不是合法JSON，无法进入正文阶段",
                    inputs={"chapter_number": chapter_number, "story_outline": outline_snapshot},
                    outputs={"error": planning_error},
                )
            elif not planning_error.startswith("director_plan_quality_failed"):
                self._emit_progress_with_artifact(
                    "剧情计划生成失败",
                    "outline_plan",
                    source="chapter_planning",
                    used_modules=[*planning_modules, "outline_agent", "character_agent", "memory_retrieval"],
                    reason="规划模型返回异常，中断本轮写作",
                    inputs={"chapter_number": chapter_number, "story_outline": outline_snapshot},
                    outputs={"error": planning_error},
                )
            return _failed_bundle(working_story, chapter_number, planning_error)

        plan = planning_result.plan
        plan_summary = {key: len(plan.get(key, [])) if isinstance(plan.get(key, []), list) else None for key in ("character_moves", "chapter_summary")}
        action_briefs = _normalize_moves(
            plan.get("character_moves"),
            require_action=True,
            allow_text_items=True,
        )
        chapter_intent = _normalize_intent(plan.get("chapter_intent"))
        event_plan = _normalize_event_plan(plan.get("event_plan"), chapter_number, working_story)
        outline_chapter = (
            working_story.outline_context.get("chapter")
            if isinstance(working_story.outline_context, dict)
            and isinstance(working_story.outline_context.get("chapter"), dict)
            else {}
        )
        outline_trade_contract = {
            "chapter_number": chapter_number,
            **outline_chapter,
        }
        event_plan["first_chapter_trade_authorized"] = bool(
            chapter_number == 1
            and first_chapter_trade_authorized(outline_trade_contract, working_story.world_facts)
        )
        memory_constraints = _normalize_memory_constraints(plan.get("memory_constraints"), working_story)
        memory_constraints["ledger_updates"] = {}
        chapter_summary_data: dict[str, Any] = {}
        self._emit_progress_with_artifact(
            "剧情计划生成完成",
            "outline_plan",
            source="chapter_planning",
            used_modules=[*planning_modules, "outline_agent", "character_agent", "memory_retrieval"],
            reason="章节规划已完成字段规范化，写前准备只校验规则并组装上下文",
            inputs={
                "chapter_number": chapter_number,
                "planning_source": planning_source,
                "project_snapshot": director_context.get("project_snapshot", {}),
                "chapter_seed": director_context.get("chapter_seed", {}),
                "character_cards": planning_character_cards,
            },
            outputs={
                "character_moves": action_briefs,
                "chapter_intent": chapter_intent,
                "event_plan": event_plan,
                "memory_constraints": memory_constraints,
            },
        )
        self._emit_workflow_step(
            "director_plan",
            "章节规划",
            status="done",
            source="chapter_planning",
            used_modules=planning_modules,
            reads=["大纲读取结果", "本章角色卡", "世界观与连续性"],
            outputs={
                "chapter_title": chapter_intent.get("chapter_title", ""),
                "planning_source": planning_source,
                "character_moves": len(action_briefs),
                "event_plan_keys": sorted(event_plan.keys()),
                "next_focus": chapter_intent.get("next_focus", ""),
            },
        )
        self._emit_workflow_step(
            "prepare_writing_context",
            "准备写作上下文",
            status="running",
            source="context_builder",
            used_modules=["director_projection", "world_rules", "scene_cards"],
            reads=["章节规划", "世界状态", "信息边界"],
        )
        simulation_result = prepare_simulation_stage(
            working_story,
            chapter_number,
            event_plan=event_plan,
            memory_constraints=memory_constraints,
            planning_profile=planning_profile,
            attach_trope_contract=_attach_trope_contract_to_simulation_plan,
        )
        chapter_seed = simulation_result.chapter_seed
        simulation_plan = simulation_result.simulation_plan
        run_world_simulation = simulation_result.run_world_simulation
        world_events = simulation_result.world_events
        scene_cards = simulation_result.scene_cards
        style_guidance = simulation_result.style_guidance
        self._emit_workflow_step(
            "prepare_writing_context",
            "准备写作上下文",
            status="done",
            source="context_builder",
            used_modules=["director_projection", "world_rules", "scene_cards", "style_guidance"],
            reads=["章节规划", "世界状态", "信息边界"],
            outputs={
                "director_scene_cards": len(scene_cards),
                "world_update_deferred": bool(simulation_plan.get("world_update_deferred")),
                "world_update_reason": simulation_plan.get("world_update_reason", ""),
                "scene_cards": len(scene_cards),
            },
        )
        conflict_summary = build_conflict_summary(working_story, action_briefs)
        cadence = chapter_intent.get("cadence") or compute_chapter_cadence(working_story, action_briefs, conflict_summary)
        event_beat = build_event_beat(conflict_summary)

        writer_plan = {
            "character_moves": action_briefs,
            "chapter_intent": chapter_intent,
            "event_plan": event_plan,
            "memory_constraints": memory_constraints,
            "chapter_seed": chapter_seed,
            "simulation_plan": simulation_plan,
            "world_events": world_events,
            "scene_cards": scene_cards,
            "style_guidance": style_guidance,
        }
        for contract_key in ("payoff_contract", "chapter_sop"):
            contract = outline_chapter.get(contract_key)
            if isinstance(contract, dict) and contract:
                writer_plan[contract_key] = deepcopy(contract)
        writer_plan["governance"] = build_chapter_governance(
            working_story,
            _governance_bundle_view(chapter_number, writer_plan),
            chapter_number=chapter_number,
        )
        writer_plan["writing_taskbook"] = ensure_writing_taskbook(
            chapter_number,
            writer_plan,
            genre=working_story.genre,
            style=working_story.style,
        )
        writer_plan_snapshot = _compact_writer_plan_for_prompt(writer_plan)

        self._emit_workflow_step(
            "write_body",
            "写手生成正文",
            status="running",
            source="writer",
            used_modules=["writer_agent", "plot_contract", "writing_taskbook"],
            reads=["章节规划", "场景卡", "本章角色卡", "相关世界规则", "连续性事实"],
        )

        self._emit_progress_with_artifact(
            "正文生成中...",
            "body_generate",
            source="writer",
            used_modules=["writer_agent", "plot_contract"],
            reason="基于计划生成正文主文，控制现实压迫与世界连续性",
            inputs={
                "chapter_number": chapter_number,
                "target_chars": TARGET_CHAPTER_CHARS,
                "scene_cards": len(scene_cards),
                "outline_title": compact_text(str(event_plan.get("chapter_title") or ""), 80),
                "character_cards": planning_character_cards,
                "writer_plan": writer_plan_snapshot,
                "writer_taskbook": len(writer_plan.get("writing_taskbook", [])),
            },
            outputs={"plan_valid": bool(plan)},
        )
        body_prompt = self._body_prompt(
            working_story,
            chapter_number,
            writer_plan,
        )
        writer_skill_context = _skill_context_for_prompt(
            working_story,
            ("writer", "dialogue", "style", "genre"),
        )
        injected_skill_modules = writer_skill_trace(
            {
                key: value
                for key, value in writer_skill_context.items()
                if key != "_replaced_defaults"
            }
        )
        enabled_skill_ids = [
            str(item).strip()
            for item in getattr(working_story, "enabled_skill_ids", [])
            if str(item).strip()
        ]
        enabled_skill_module_ids = [
            str(item).strip()
            for item in (getattr(working_story, "enabled_skill_module_ids", None) or [])
            if str(item).strip()
        ]
        if injected_skill_modules:
            self._emit_workflow_step(
                "load_writer_skills",
                "加载写手 Skill",
                status="done",
                source="writer",
                used_modules=["skill_packs"],
                reads=["已启用的 Skill", "Skill 模块规则", "项目作者约束"],
                outputs={
                    "enabled_skill_ids": enabled_skill_ids,
                    "enabled_skill_module_ids": enabled_skill_module_ids,
                    "injected_modules": injected_skill_modules,
                    "prompt_chars": len(body_prompt),
                },
            )
            self._emit_progress_with_artifact(
                "写手已加载 Skill",
                "writer_skill_context",
                source="writer",
                used_modules=["writer_agent", "skill_packs"],
                reason="记录实际进入写手提示词的技能模块，避免只显示启用状态",
                inputs={
                    "chapter_number": chapter_number,
                    "enabled_skill_ids": enabled_skill_ids,
                    "enabled_skill_module_ids": enabled_skill_module_ids,
                },
                outputs={
                    "injected_modules": injected_skill_modules,
                    "prompt_chars": len(body_prompt),
                    "skill_rule_markers": body_prompt.count("Skill"),
                },
            )

        def report_writing_event(name: str, payload: dict[str, Any]) -> None:
            if name == "empty_retry":
                self._emit_progress_with_artifact(
                    "写手返回空正文，正在重试...",
                    "body_generate_retry",
                    source="writer",
                    used_modules=["writer_agent", "output_contract"],
                    reason="第一次写手调用未返回正文，复用同一写作包重试一次",
                    inputs={"chapter_number": chapter_number, **payload},
                )
            elif name == "expansion_start":
                self._emit_progress_with_artifact(
                    "章节扩写中...",
                    "body_expand",
                    source="writer",
                    used_modules=["writer_agent", "writing_taskbook", "plot_contract"],
                    reason="正文字数不足时进行事件与对话扩充",
                    inputs={
                        "chapter_number": chapter_number,
                        "current_chars": _chapter_char_count(str(payload.get("body") or "")),
                        "plan_snapshot": {"target_chars": TARGET_CHAPTER_CHARS, "outline": outline_snapshot},
                    },
                )
            elif name == "expansion_complete":
                self._emit_progress_with_artifact(
                    "章节扩写完成",
                    "body_expand",
                    source="writer",
                    used_modules=["writer_agent", "writing_taskbook"],
                    reason="扩写后长度和细节有实质补充",
                    inputs={"chapter_number": chapter_number},
                    outputs={
                        "before_chars": _chapter_char_count(str(payload.get("before") or "")),
                        "after_chars": _chapter_char_count(str(payload.get("after") or "")),
                    },
                )

        writing_result = generate_chapter_body(
            body_prompt=body_prompt,
            chapter_number=chapter_number,
            writer_plan=writer_plan,
            call_model=lambda prompt, stage, timeout: self._timed_chat(
                working_story,
                prompt,
                max_tokens=7000,
                json_mode=False,
                agent="writer",
                stage=stage,
                timeout_seconds=int(timeout) if timeout is not None else None,
            ),
            postprocess=lambda candidate: _postprocess_chapter_output(
                working_story,
                candidate,
                chapter_number=chapter_number,
                scene_cards=scene_cards,
                outline_anchor=chapter_seed.get("outline_anchor"),
            ),
            should_expand=_should_expand_chapter,
            build_expansion_prompt=lambda source_body: _render_expansion_length_prompt(
                working_story,
                source_body=source_body,
                chapter_number=chapter_number,
                event_plan=event_plan,
                world_facts=_review_context_facts(story),
            ),
            expansion_is_acceptable=_expanded_body_is_acceptable,
            expansion_timeout_seconds=_expansion_timeout_seconds(),
            on_event=report_writing_event,
        )
        if not writing_result.ok:
            body_error = writing_result.error or "body_empty"
            if body_error.startswith("章节扩写失败："):
                return _failed_bundle(working_story, chapter_number, body_error)
            self._emit_workflow_step(
                "write_body",
                "写手生成正文",
                status="error",
                source="writer",
                used_modules=["writer_agent"],
                outputs={"error": body_error},
            )
            if body_error == "body_empty":
                current = working_story.agent_runtime.writer
                record_stage_runtime(
                    working_story,
                    "writer",
                    "fallback",
                    current.provider,
                    current.model,
                    chapter_number,
                    fallback_reason="正文为空",
                )
            self._emit_progress_with_artifact(
                "正文生成失败",
                "body_generate",
                source="writer",
                used_modules=["writer_agent", "plot_contract"],
                reason="正文写作未返回有效文本，章节中止",
                inputs={"chapter_number": chapter_number, "writer_plan": writer_plan_snapshot},
                outputs={"error": body_error},
            )
            return _failed_bundle(working_story, chapter_number, body_error)
        body = writing_result.body

        self._emit_workflow_step(
            "write_body",
            "写手生成正文",
            status="done",
            source="writer",
            used_modules=["writer_agent", "plot_contract", "writing_taskbook"],
            reads=["章节规划", "场景卡", "本章角色卡", "相关世界规则", "连续性事实"],
            outputs={"body_chars": _chapter_char_count(body), "chapter_number": chapter_number},
        )
        self._emit_workflow_step(
            "review_body",
            "综合审稿",
            status="running",
            source="reviewer",
            used_modules=["reviewer_agent", "editor_agent"],
            reads=["正文", "章节规划", "连续性事实", "角色卡"],
        )
        review_world_facts = _review_context_facts(story)
        review_genre_context = _story_review_genre_context(story)
        review_protagonist_aliases = tuple(protagonist_aliases_from_characters(story.characters))
        review_character_names = _review_character_names(story)
        outline_anchor = chapter_seed.get("outline_anchor") if isinstance(chapter_seed, dict) else {}

        def revise_body(candidate_body: str, candidate_review: dict[str, Any], round_number: int) -> tuple[str, str]:
            return self._timed_chat(
                working_story,
                self._revision_prompt(
                    working_story,
                    chapter_number,
                    candidate_body,
                    writer_plan,
                    candidate_review,
                ),
                max_tokens=_revision_max_tokens(candidate_body),
                json_mode=False,
                agent="writer",
                stage=f"审稿改稿 第{chapter_number}章（第{round_number}轮）",
            )

        # Bounded review flow. The hard gate and soft review are
        # thin callbacks over a single canonical `ReviewService`
        # instance so each reviewer source runs at most once per
        # gate call. The controller below enforces "hard gate ≤ 2,
        # soft review = 1, model revision ≤ 1" at the algorithm
        # level, replacing the previous free-form while loop.
        # Over-length bodies are reported as
        # ``length.out_of_range`` blocking findings and handed to
        # the same revise pass — the plan forbids a second
        # model body modification after the bounded controller
        # has produced its final body, so the historical
        # compression stage is gone.

        review_service = ReviewService(
            review_continuity=review_continuity_interface,
            review_fragments=review_chinese_fragments,
            review_consistency=review_world_event_consistency,
            review_critical_rules=review_critical_prose_rules,
            profile_for=genre_stage_profile_for,
            review_style=review_prose_style,
            review_prose_quality=review_prose_quality,
            review_adversarial_cuts=review_adversarial_cuts,
            review_ai_flavor=review_ai_flavor,
            review_reader_feel=review_reader_feel,
            review_cold_reader=review_cold_reader_experience,
            review_plot_spine=review_plot_spine_completion,
            min_chars=_chapter_review_min_chars(simulation_plan),
            char_tolerance=CHAPTER_CHAR_TOLERANCE,
            # Over-length bodies are blocking findings inside the same
            # revise pass. ``hard_max_chars`` is the strict ceiling the
            # length check enforces; ``_should_compress_chapter`` uses
            # ``MAX_CHAPTER_CHARS + CHAPTER_MAX_CHAR_TOLERANCE`` as a
            # softer "no compression needed" threshold and only fires
            # for the dead-letter path where the gate is misconfigured
            # (e.g. ``hard_max_chars=0``).
            hard_max_chars=CHAPTER_HARD_MAX_CHARS,
        )
        review_hard_context: dict[str, Any] = {
            "continuity_interface": (
                simulation_plan.get("continuity_interface")
                if isinstance(simulation_plan, dict)
                and isinstance(simulation_plan.get("continuity_interface"), dict)
                else {}
            ),
            "world_events": list(world_events or []),
            "scene_cards": list(scene_cards or []),
            "chapter_number": chapter_number,
            "genre_context": review_genre_context,
            "event_plan": event_plan,
            "world_facts": list(review_world_facts or []),
            "simulation_plan": simulation_plan,
            "protagonist_aliases": review_protagonist_aliases,
            "character_names": review_character_names,
        }
        review_soft_context = dict(review_hard_context)
        review_soft_context["previous_summary"] = str(
            (simulation_plan or {}).get("previous_summary")
            or event_plan.get("previous_summary")
            or event_plan.get("summary")
            or ""
        )

        def _hard_review(candidate: str) -> ReviewResult:
            return review_service.run_hard_gate(
                body=candidate, context=review_hard_context
            )

        def _soft_review(candidate: str) -> ReviewResult:
            return review_service.run_soft_review(
                body=candidate, context=review_soft_context
            )

        def _postprocess_revision(text: str) -> str:
            return _postprocess_chapter_output(
                working_story,
                text,
                chapter_number=chapter_number,
                scene_cards=scene_cards,
                outline_anchor=outline_anchor,
            )

        def _choose_revision(
            *,
            original_body: str,
            candidate_body: str,
            original_hard: ReviewResult,
            candidate_hard: ReviewResult,
        ) -> dict[str, Any]:
            original_quality = {
                "pass": not original_hard.has_hard_errors,
                "issues": [item.message for item in original_hard.findings],
                "has_hard_errors": original_hard.has_hard_errors,
                "review_result": original_hard.to_dict(),
            }
            candidate_quality = {
                "pass": not candidate_hard.has_hard_errors,
                "issues": [item.message for item in candidate_hard.findings],
                "has_hard_errors": candidate_hard.has_hard_errors,
                "review_result": candidate_hard.to_dict(),
            }
            return choose_best_revision(
                original_body=original_body,
                original_quality=original_quality,
                candidate_body=candidate_body,
                candidate_quality=candidate_quality,
                min_delta=0.01,
            )

        def _revise(candidate: str, hard_result: ReviewResult) -> tuple[str, str]:
            review_for_prompt = hard_result.to_dict()
            return self._timed_chat(
                working_story,
                self._revision_prompt(
                    working_story,
                    chapter_number,
                    candidate,
                    writer_plan,
                    review_for_prompt,
                ),
                max_tokens=_revision_max_tokens(candidate),
                json_mode=False,
                agent="writer",
                stage=f"审稿改稿 第{chapter_number}章（第1轮）",
            )

        def _report_quality_event(event: str, payload: dict[str, Any]) -> None:
            if event == "revision_start":
                round_number = int(payload.get("round") or 1)
                self._emit_progress_with_artifact(
                    f"审稿改稿中...（第{round_number}/1轮）",
                    "revision",
                    source="reviewer",
                    used_modules=["reviewer_agent", "writer_agent", "editor_agent"],
                    reason=f"写稿审查后触发第{round_number}轮修订",
                    inputs={
                        "chapter_number": chapter_number,
                        "round": round_number,
                        "max_rounds": 1,
                        "issue_count": len(payload.get("review", {}).get("issues", [])),
                        "character_cards": planning_character_cards,
                        "outline": outline_snapshot,
                        "writer_plan": writer_plan_snapshot,
                        "review_snapshot": _review_progress_snapshot(payload.get("review", {})),
                        "chapter_title": compact_text(str(event_plan.get("chapter_title") or ""), 100),
                    },
                )
            elif event == "revision_complete":
                safety = payload.get("safety_report") or {}
                gate = payload.get("gate") or {}
                candidate_review = payload.get("review") or {}
                self._emit_progress_with_artifact(
                    "审稿改稿完成",
                    "revision",
                    source="reviewer",
                    used_modules=["reviewer_agent", "writer_agent", "editor_agent"],
                    reason=f"改稿完成，共执行{payload.get('round', 1)}轮修订，回填安全评估与剩余问题记录",
                    inputs={"chapter_number": chapter_number, "rounds_done": payload.get("round", 1)},
                    outputs={
                        "accepted": bool(safety.get("accepted")),
                        "rounds_done": payload.get("round", 1),
                        "passed": not gate.get("needs_revision"),
                        "issues_remaining": len(candidate_review.get("issues", [])),
                        **{key: safety.get(key) for key in (
                            "reason", "original_score", "candidate_score", "original_issue_count",
                            "candidate_issue_count", "original_chars", "candidate_chars",
                        )},
                    },
                )

        review_revision_result = run_review_revision_stage(
            body=body,
            callbacks=ReviewRevisionCallbacks(
                hard_review=_hard_review,
                soft_review=_soft_review,
                revise=_revise,
                postprocess=_postprocess_revision,
                choose_revision=_choose_revision,
            ),
            on_event=_report_quality_event,
        )

        # The bounded controller already returned the final body and
        # the canonical review. The plan forbids any further model
        # body modifications after this point: over-length bodies
        # were reported as ``length.out_of_range`` blocking findings
        # inside the controller's hard gate and handed to the same
        # revise pass. We accept whatever the controller produced and
        # surface ``body_chars`` / the gate's status so downstream
        # callers (memory gate, file-project save) can see when the
        # length window is still violated.
        body = review_revision_result.body
        if _should_compress_chapter(body) and review_revision_result.hard_result.status != "blocked":
            # Over-length but no blocking finding is reported (e.g.
            # the bounded controller downgraded the length issue).
            # Surface a warning so the front-end and the file-project
            # save can flag the over-length body without invoking
            # another model call.
            self._emit_progress_with_artifact(
                "正文仍超长，未触发额外压缩",
                "length_warning",
                source="reviewer",
                used_modules=["quality_gate"],
                reason="bounded flow 完成后正文仍超过章节硬上限，需用户或后续流程处理",
                inputs={"chapter_number": chapter_number, "current_chars": _chapter_char_count(body)},
            )

        quality_result = review_revision_result
        writing_review = quality_result.review_result.to_dict()
        review_gate = {
            "status": quality_result.hard_result.status,
            "needs_revision": quality_result.hard_result.needs_revision,
            "has_hard_errors": quality_result.hard_result.has_hard_errors,
            "issues": [item.message for item in quality_result.hard_result.findings],
            "revision_plan": quality_result.hard_result.revision_plan,
            "categories": writing_review.get("categories", {}),
        }
        revision_rounds_done = quality_result.revision_rounds
        revision_safety_report = quality_result.revision_safety_report
        accepted_revision_actions: list[str] = []
        body_chars = _chapter_char_count(body)
        self._emit_workflow_step(
            "review_body",
            "综合审稿",
            status="done",
            source="reviewer",
            used_modules=["reviewer_agent", "editor_agent", "quality_gate"],
            reads=["正文", "章节规划", "连续性事实", "角色卡"],
            outputs={
                "body_chars": body_chars,
                "needs_revision": bool(review_gate.get("needs_revision")),
                "issue_count": len((writing_review or {}).get("issues", [])),
                "revision_rounds": revision_rounds_done,
            },
        )
        self._emit_workflow_step(
            "write_memory",
            "记忆与状态回写",
            status="running",
            source="memory",
            used_modules=["memory_agent", "project_state"],
            reads=["最终正文", "本章事实锁", "当前任务与资源账本"],
        )
        memory_input_is_usable = _should_extract_final_memory(body, review_gate)
        if memory_input_is_usable:
            post_draft_memory, memory_sync = self._extract_final_body_memory(
                working_story,
                body,
                chapter_number,
                fact_locks={
                    "must_keep_facts": memory_constraints.get("must_keep_facts", []),
                },
            )
        else:
            post_draft_memory = {}
            memory_sync = {
                "status": "skipped",
                "reason": "final_body_not_accepted",
                "body_chars": body_chars,
                "needs_revision": bool(review_gate.get("needs_revision")),
            }
            self._emit_progress_with_artifact(
                "最终正文未通过，跳过记忆提取",
                "memory_sync",
                source="memory",
                used_modules=["memory_agent", "quality_gate"],
                reason="未通过篇幅或审稿门禁的正文不会写入长期记忆",
                inputs={"chapter_number": chapter_number},
                outputs=memory_sync,
            )
        simulation_plan["memory_sync"] = memory_sync

        decision = DirectorDecision(
            primary_conflict=chapter_intent.get("primary_conflict", {}) or conflict_summary.get("primary_conflict", {}),
            secondary_conflict=chapter_intent.get("secondary_conflict", {}) or conflict_summary.get("secondary_conflict", {}),
            event_beat=event_beat,
            cadence=cadence,  # type: ignore[arg-type]
            chapter_title=_planned_chapter_title(
                event_plan=event_plan,
                chapter_intent=chapter_intent,
                chapter_summary=chapter_summary_data,
            ),
            next_focus=chapter_intent.get("next_focus", "") or chapter_summary_data.get("next_focus", ""),
            approved_new_characters=[
                str(item.get("name", item)).strip() if isinstance(item, dict) else str(item).strip()
                for item in chapter_intent.get("approved_new_characters", [])
                if (str(item.get("name", item)).strip() if isinstance(item, dict) else str(item).strip())
            ],
            deferred_characters=[
                str(item.get("name", item)).strip() if isinstance(item, dict) else str(item).strip()
                for item in chapter_intent.get("deferred_characters", [])
                if (str(item.get("name", item)).strip() if isinstance(item, dict) else str(item).strip())
            ],
            rejected_characters=[
                str(item.get("name", item)).strip() if isinstance(item, dict) else str(item).strip()
                for item in chapter_intent.get("rejected_characters", [])
                if (str(item.get("name", item)).strip() if isinstance(item, dict) else str(item).strip())
            ],
        )

        updated_story = working_story.model_copy(deep=True)
        effective_conflict_summary = {
            **conflict_summary,
            "primary_conflict": decision.primary_conflict,
            "secondary_conflict": decision.secondary_conflict,
        }

        self._emit_progress_with_artifact(
            "记忆回写中...",
            "memory_sync",
            source="memory",
            used_modules=["memory_agent", "world_simulation", "project_state"],
            reason="写入章节摘要、账本与世界脉络推进状态",
            inputs={"chapter_number": chapter_number, "writer_plan_key_count": len(writer_plan)},
        )
        memory_is_verified = memory_sync.get("status") == "ok"
        apply_post_chapter_updates(
            updated_story,
            body,
            chapter_number,
            conflict_summary={},
            event_beat={},
            post_draft_memory=post_draft_memory,
        )
        _apply_ledger_updates(
            updated_story,
            post_draft_memory.get("ledger_updates", {}),
            chapter_number=chapter_number,
        )
        _sync_character_game_panels(updated_story, chapter_number)
        if is_game_story(updated_story):
            advance_world_pulse(updated_story, chapter_number=chapter_number)
        maybe_update_arc_recap(updated_story, chapter_number)
        self._emit_workflow_step(
            "write_memory",
            "记忆与状态回写",
            status="done",
            source="memory",
            used_modules=["memory_agent", "project_state", "progression_ledger"],
            reads=["最终正文", "本章事实锁", "当前任务与资源账本"],
            outputs={
                "memory_status": memory_sync.get("status", "unknown"),
                "chapter_summaries": len(updated_story.chapter_summaries),
                "world_facts": len(updated_story.world_facts),
            },
        )

        latest_summary = updated_story.chapter_summaries[-1]
        title_conflict: dict[str, Any] = {}
        title_next_focus = (
            f"{updated_story.outline} {body} "
            f"{latest_summary.next_focus if memory_is_verified else ''}"
        )
        latest_summary.chapter_title = _planned_chapter_title(
            event_plan=event_plan,
            chapter_intent=None,
            chapter_summary=None,
        ) or latest_summary.chapter_title
        latest_summary.chapter_title = _repair_generic_chapter_title(
            latest_summary.chapter_title,
            chapter_number=chapter_number,
            next_focus=title_next_focus,
            conflict_summary=title_conflict,
            genre=updated_story.genre,
        )
        latest_summary.primary_conflict = {}
        latest_summary.secondary_conflict = {}
        latest_summary.event_beat = {}
        latest_summary.cadence = cadence  # type: ignore[assignment]

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
                "approved_new_characters": decision.approved_new_characters,
                "deferred_characters": decision.deferred_characters,
                "rejected_characters": decision.rejected_characters,
            },
            character_moves=action_briefs,
            memory_constraints=memory_constraints,
            event_plan=event_plan,
            chapter_seed=chapter_seed,
            simulation_plan=simulation_plan,
            world_events=world_events,
            scene_cards=scene_cards,
            simulation_status=_build_simulation_status(updated_story),
            action_briefs=action_briefs,
            conflict_summary={
                **effective_conflict_summary,
                "approved_new_characters": decision.approved_new_characters,
                "deferred_characters": decision.deferred_characters,
                "rejected_characters": decision.rejected_characters,
            },
            event_beat=event_beat,
            character_cards=build_character_cards(updated_story),
            foreshadowing=build_foreshadowing(updated_story, chapter_number),
            next_outline=plan_next_outline(
                updated_story,
                chapter_number,
                conflict_summary={},
                cadence=cadence,
            ),
            updated_story=updated_story,
            chapter_summary=latest_summary.model_dump(),
            context_snapshot_id=context_package.snapshot_id,
        )
        self._emit_progress_with_artifact(
            "质量检查中...",
            "quality_gate",
            source="reviewer",
            used_modules=["prose_quality_review", "world_consistency_review", "writer_agent"],
            reason="执行最终质量评估并合并审查报告",
            inputs={"chapter_number": chapter_number, "writing_review_issue_count": len(writing_review.get("issues", []))},
            outputs={"memory_sync_status": memory_sync.get("status", "unknown")},
            keep_legacy_text=False,
        )
        report_generation_progress("质量检查中...")
        bundle.quality_report = _merge_writing_review_quality(validate_bundle(bundle.model_dump()), writing_review)
        bundle.quality_report["memory_sync"] = memory_sync
        if revision_safety_report:
            bundle.quality_report["revision_safety"] = revision_safety_report
        if accepted_revision_actions:
            bundle.quality_report["accepted_revision_actions"] = accepted_revision_actions
        updated_story.writing_lessons = merge_writing_lessons(
            updated_story.writing_lessons,
            lessons_from_quality_report(bundle.quality_report),
        )
        bundle.updated_story = updated_story
        return bundle
