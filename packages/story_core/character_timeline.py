"""Compatibility import surface for the character inspection read model."""

from packages.story_core.character_inspection import (
    CharacterPlanContext,
    CharacterTimelineEvent,
    ConsistencyWarning,
    check_character_consistency,
    get_character_timeline,
)

__all__ = [
    "CharacterPlanContext",
    "CharacterTimelineEvent",
    "ConsistencyWarning",
    "check_character_consistency",
    "get_character_timeline",
]
