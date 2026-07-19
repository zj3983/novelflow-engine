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
from packages.story_core.project_outline import ProjectOutline


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

    expected = expected_chapter_numbers or list(range(1, 31))
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
    return plan
