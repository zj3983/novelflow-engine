from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field


class _ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentityProfile(_ProfileModel):
    aliases: list[str] = Field(default_factory=list)
    gender: str = ""
    age: int | None = Field(default=None, ge=0)
    birthplace: str = ""
    origin: str = ""
    current_identity: str = ""
    occupation: str = ""
    affiliation: str = ""


class BackgroundProfile(_ProfileModel):
    family: str = ""
    upbringing: str = ""
    education_or_training: str = ""
    formative_events: list[str] = Field(default_factory=list)
    arrival_reason: str = ""


class CurrentLifeProfile(_ProfileModel):
    residence: str = ""
    livelihood: str = ""
    economic_state: str = ""
    resources_and_ability: str = ""
    authority_scope: str = ""
    immediate_problem: str = ""


class StoryDriveProfile(_ProfileModel):
    long_term_goal: str = ""
    immediate_goal: str = ""
    motivation: str = ""
    failure_stakes: str = ""
    hidden_matters: list[str] = Field(default_factory=list)
    main_conflict_reason: str = ""


class RelationshipNote(_ProfileModel):
    target: str
    relation_type: str = ""
    history: str = ""
    current_attitude: str = ""
    shared_interest_or_conflict: str = ""
    known_facts: list[str] = Field(default_factory=list)
    unknown_facts: list[str] = Field(default_factory=list)


_NESTED_MODELS: dict[str, type[BaseModel]] = {
    "identity_profile": IdentityProfile,
    "background_profile": BackgroundProfile,
    "current_life_profile": CurrentLifeProfile,
    "story_drive": StoryDriveProfile,
}


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _merge_prefer_existing(existing: Any, generated: Any) -> Any:
    if isinstance(existing, dict) and isinstance(generated, dict):
        keys = list(existing)
        keys.extend(key for key in generated if key not in existing)
        return {
            key: _merge_prefer_existing(existing.get(key), generated.get(key))
            for key in keys
        }
    return deepcopy(generated) if _is_empty(existing) else deepcopy(existing)


def merge_character_profile(existing: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
    """Fill blank character fields without replacing author-confirmed content."""

    return _merge_prefer_existing(dict(existing), dict(generated))


def normalize_character_profile(card: dict[str, Any]) -> dict[str, Any]:
    """Add concrete profile defaults while preserving legacy and extension fields."""

    normalized = deepcopy(dict(card))
    for field_name, model in _NESTED_MODELS.items():
        raw = normalized.get(field_name)
        raw = dict(raw) if isinstance(raw, dict) else {}
        if field_name == "story_drive" and not raw.get("motivation"):
            raw["motivation"] = str(normalized.get("motivation") or normalized.get("core_motivation") or "")
        normalized[field_name] = model.model_validate(raw).model_dump()

    performance = normalized.get("performance_profile")
    performance = dict(performance) if isinstance(performance, dict) else {}
    if not performance.get("speech_style") and normalized.get("speech_style"):
        performance["speech_style"] = str(normalized["speech_style"])
    normalized["performance_profile"] = performance
    normalized.setdefault("character_tier", str(normalized.get("role") or ""))
    normalized.setdefault("first_appearance", 0)
    normalized.setdefault("dialogue_examples", [])
    normalized.setdefault("relationship_notes", [])
    return normalized


def project_character_for_writer(
    card: dict[str, Any],
    *,
    allowed_reveals: Iterable[str] = (),
) -> dict[str, Any]:
    """Return a scene-safe copy of a card without unrevealed private facts."""

    projected = normalize_character_profile(card)
    allowed = {str(item).strip() for item in allowed_reveals if str(item).strip()}
    drive = dict(projected.get("story_drive") or {})
    drive["hidden_matters"] = [
        item for item in drive.get("hidden_matters", []) if str(item).strip() in allowed
    ]
    projected["story_drive"] = drive
    projected["secrets"] = [
        item for item in projected.get("secrets", []) if str(item).strip() in allowed
    ]
    return projected
