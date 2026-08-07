"""Canonical entity registry.

The canon package owns the typed entity kinds, the alias /
display-name resolution, and the lifecycle rules the rest of
the codebase (writer context, entity preflight, fact extractor,
migration script) relies on. Once a project introduces an
entity, its ``entity_id`` is permanent; renaming the entity
never orphans references downstream code may have stored.
"""

from .contracts import ALLOWED_KINDS, CanonEntity, Lifecycle
from .entity_designer import EntityDesigner
from .registry import CanonRegistry
from .schemas import CharacterCard, EquipmentCard, TechniqueCard
from .service import CanonService, EntityPreflightFailed, preflight_requirements

__all__ = [
    "ALLOWED_KINDS",
    "CanonEntity",
    "CanonRegistry",
    "CanonService",
    "CharacterCard",
    "EntityDesigner",
    "EntityPreflightFailed",
    "EquipmentCard",
    "Lifecycle",
    "TechniqueCard",
    "preflight_requirements",
]
