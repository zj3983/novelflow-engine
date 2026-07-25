from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.story_core.character_profiles import (
    BackgroundProfile,
    CurrentLifeProfile,
    IdentityProfile,
    RelationshipNote,
    StoryDriveProfile,
)
from packages.story_core.models import CharacterPerformanceProfile
from packages.story_core.project_outline import ProjectOutline, select_outline_context
from packages.story_core.trope_runtime import compact_trope_candidates


CharacterTier = Literal[
    "protagonist",
    "stage_antagonist",
    "long_term_antagonist",
    "supporting",
]


class _PlanningModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanningCharacterCard(_PlanningModel):
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=80)
    character_tier: CharacterTier
    first_appearance: int = Field(default=0, ge=0)
    identity_profile: IdentityProfile
    background_profile: BackgroundProfile
    current_life_profile: CurrentLifeProfile
    story_drive: StoryDriveProfile
    performance_profile: CharacterPerformanceProfile = Field(default_factory=CharacterPerformanceProfile)
    dialogue_examples: list[str] = Field(min_length=2, max_length=3)
    relationship_notes: list[RelationshipNote] = Field(default_factory=list)


class GeneratedOutlinePlan(_PlanningModel):
    outline: ProjectOutline
    characters: list[PlanningCharacterCard]


def _require_text(value: str, error: str) -> None:
    if not str(value or "").strip():
        raise ValueError(error)


def validate_generated_opening_plan(
    payload: Any,
    *,
    expected_chapter_numbers: list[int] | None = None,
    trope_templates: list[dict[str, Any]] | None = None,
    expected_primary_trope_id: str | None = None,
) -> GeneratedOutlinePlan:
    """Validate an AI-generated opening plan without constraining manual drafts."""

    plan = GeneratedOutlinePlan.model_validate(payload)
    overall = plan.outline.overall
    for field_name in (
        "story",
        "protagonist_goal",
        "main_conflict",
        "growth_path",
        "ending_direction",
    ):
        _require_text(getattr(overall, field_name), f"missing_overall_field:{field_name}")

    tiers = {card.character_tier for card in plan.characters}
    for tier in ("protagonist", "stage_antagonist", "long_term_antagonist"):
        if tier not in tiers:
            raise ValueError(f"missing_character_tier:{tier}")
    if not 4 <= len(plan.characters) <= 6:
        raise ValueError("character_count_out_of_range")

    names = [card.name.strip() for card in plan.characters]
    if len(names) != len(set(names)):
        raise ValueError("duplicate_character_name")

    opening_arcs = [arc for arc in plan.outline.arcs if arc.start_chapter == 1]
    if not opening_arcs:
        raise ValueError("opening_arc_required")
    opening_arc = opening_arcs[0]
    stage_names = {card.name for card in plan.characters if card.character_tier == "stage_antagonist"}
    if opening_arc.stage_antagonist not in stage_names:
        raise ValueError("stage_antagonist_card_mismatch")
    if not opening_arc.long_term_antagonist_traces:
        raise ValueError("long_term_antagonist_trace_required")

    expected = (
        list(range(1, 31))
        if expected_chapter_numbers is None
        else expected_chapter_numbers
    )
    chapter_numbers = [chapter.chapter_number for chapter in plan.outline.chapters]
    if chapter_numbers != expected:
        raise ValueError("generated_chapters_do_not_match_target_window")
    known_names = set(names)
    for chapter in plan.outline.chapters:
        for name in chapter.cast:
            if name not in known_names:
                raise ValueError(f"missing_character_card:{name}")

    for card in plan.characters:
        _require_text(card.identity_profile.origin, f"missing_character_origin:{card.name}")
        _require_text(card.identity_profile.current_identity, f"missing_character_identity:{card.name}")
        _require_text(card.identity_profile.occupation, f"missing_character_occupation:{card.name}")
        _require_text(card.story_drive.immediate_goal, f"missing_character_goal:{card.name}")
        _require_text(card.story_drive.failure_stakes, f"missing_character_stakes:{card.name}")
    if trope_templates is not None:
        validate_generated_trope_selection(
            plan,
            trope_templates,
            expected_primary_trope_id=expected_primary_trope_id,
        )
    return plan


def validate_generated_continuation_plan(
    payload: Any,
    *,
    expected_chapter_numbers: list[int],
    existing_character_names: set[str],
    trope_templates: list[dict[str, Any]] | None = None,
    expected_primary_trope_id: str | None = None,
) -> GeneratedOutlinePlan:
    """Validate an incremental plan without requiring opening-only structure."""

    plan = GeneratedOutlinePlan.model_validate(payload)
    chapter_numbers = [chapter.chapter_number for chapter in plan.outline.chapters]
    if chapter_numbers != expected_chapter_numbers:
        raise ValueError("generated_chapters_do_not_match_target_window")

    names = [card.name.strip() for card in plan.characters]
    if len(names) != len(set(names)):
        raise ValueError("duplicate_character_name")
    existing_names = {
        str(name).strip() for name in existing_character_names if str(name).strip()
    }
    repeated = next((name for name in names if name in existing_names), None)
    if repeated is not None:
        raise ValueError(f"duplicate_existing_character_card:{repeated}")

    known_names = {*existing_names, *names}
    for chapter in plan.outline.chapters:
        for name in chapter.cast:
            if name not in known_names:
                raise ValueError(f"missing_character_card:{name}")

    for card in plan.characters:
        _require_text(card.identity_profile.origin, f"missing_character_origin:{card.name}")
        _require_text(card.identity_profile.current_identity, f"missing_character_identity:{card.name}")
        _require_text(card.identity_profile.occupation, f"missing_character_occupation:{card.name}")
        _require_text(card.story_drive.immediate_goal, f"missing_character_goal:{card.name}")
        _require_text(card.story_drive.failure_stakes, f"missing_character_stakes:{card.name}")
    if trope_templates is not None:
        validate_generated_trope_selection(
            plan,
            trope_templates,
            expected_primary_trope_id=expected_primary_trope_id,
        )
    return plan


def validate_generated_trope_selection(
    plan: Any,
    trope_templates: list[dict[str, Any]],
    expected_primary_trope_id: str | None = None,
) -> GeneratedOutlinePlan:
    """Validate generated trope locks against the active project candidates."""

    validated = GeneratedOutlinePlan.model_validate(plan)
    candidates = compact_trope_candidates(trope_templates)
    candidates_by_id = {str(item["id"]): item for item in candidates}
    primary_trope_id = validated.outline.overall.primary_trope_id

    if not candidates_by_id:
        if primary_trope_id is not None:
            raise ValueError("unexpected_primary_trope_id")
        for arc in validated.outline.arcs:
            if arc.trope_id is not None:
                raise ValueError(f"unexpected_arc_trope_id:{arc.id}")
        for chapter in validated.outline.chapters:
            if chapter.trope_beat is not None:
                raise ValueError(f"unexpected_chapter_trope_beat:{chapter.chapter_number}")
        return validated

    if primary_trope_id not in candidates_by_id:
        raise ValueError("invalid_primary_trope_id")
    expected = str(expected_primary_trope_id or "").strip()
    if expected and primary_trope_id != expected:
        raise ValueError("unexpected_primary_trope_id")

    for arc in validated.outline.arcs:
        if arc.trope_id not in candidates_by_id:
            raise ValueError(f"invalid_arc_trope_id:{arc.id}")

    outline_payload = validated.outline.model_dump(mode="json")
    for chapter in validated.outline.chapters:
        beat = chapter.trope_beat
        if beat is None or beat == "":
            continue
        context = select_outline_context(outline_payload, chapter.chapter_number)
        active_arc = context.get("active_arc")
        active_trope_id = (
            active_arc.get("trope_id")
            if isinstance(active_arc, dict)
            else None
        )
        active_template = candidates_by_id.get(str(active_trope_id or ""))
        if active_template is None or beat not in active_template.get("beats", []):
            raise ValueError(f"invalid_chapter_trope_beat:{chapter.chapter_number}")
    return validated
