"""Entity preflight service.

The preflight sits between the director and the writer. It
takes the director's ``entity_requirements`` and ensures each
named one either resolves to an existing canonical entity or
has a freshly designed card before the writer ever sees the
chapter. Disposable inline roles stay out of the registry.
"""

from __future__ import annotations

from typing import Iterable, Optional

from pydantic import ValidationError

from ..agents.contracts import EntityRequirement
from .entity_designer import EntityDesigner
from .registry import CanonEntity, CanonRegistry
from .schemas import CharacterCard, EquipmentCard, TechniqueCard


class EntityPreflightFailed(RuntimeError):
    """Raised when the designer returns a card that fails
    validation or misses the required fields.

    The exception message always names the requirement that
    triggered the failure so the workbench can point at the
    exact entity instead of a generic "something went wrong".
    """


_KIND_VALIDATORS = {
    "character": CharacterCard,
    "equipment": EquipmentCard,
    "technique": TechniqueCard,
}

_PROMOTION_LIFECYCLE = "active"
_MIN_PROMOTION_IMPORTANCE = 5


class CanonService:
    """Resolve, design, and persist the director's entity needs.

    The service keeps the registry in a consistent state: every
    named requirement either resolves to an existing entity
    (possibly promoted to ``active``) or has a freshly designed
    card. Inline minor roles are silently skipped so the
    director can mention "the passerby" without polluting the
    canon.
    """

    def __init__(
        self,
        *,
        registry: CanonRegistry,
        designer: EntityDesigner,
    ) -> None:
        self._registry = registry
        self._designer = designer

    @property
    def registry(self) -> CanonRegistry:
        return self._registry

    def ensure_requirements(
        self,
        requirements: Iterable[EntityRequirement],
    ) -> list[CanonEntity]:
        """Resolve or design every named requirement.

        Returns the list of newly created entities. Existing
        entities that needed a lifecycle promotion are not in
        the returned list — the caller can read the registry
        to see the current state. Invalid designs raise
        ``EntityPreflightFailed`` so the chapter run aborts
        before the writer sees an incomplete canon.
        """
        created: list[CanonEntity] = []
        for requirement in requirements:
            if requirement.inline_minor:
                continue
            existing = self._registry.resolve(requirement.name, requirement.kind)
            if existing is not None:
                self._promote_if_needed(existing)
                continue
            card = self._designer.design(requirement, self._registry)
            self._validate_card(card, requirement)
            promoted = self._maybe_promote(card, requirement.importance)
            persisted = self._registry.add(
                kind=requirement.kind,  # type: ignore[arg-type]
                name=promoted.display_name,
                aliases=promoted.aliases,
                entity_id=promoted.entity_id,
                lifecycle=promoted.lifecycle,
                extensions=dict(promoted.extensions or {}),
            )
            created.append(persisted)
        return created

    # --- Internals -----------------------------------------------------------

    def _validate_card(
        self,
        card: CanonEntity,
        requirement: EntityRequirement,
    ) -> None:
        if not card.entity_id:
            raise EntityPreflightFailed(
                f"entity_card_missing_id: {requirement.kind}:{requirement.name}"
            )
        if not card.display_name:
            raise EntityPreflightFailed(
                f"entity_card_missing_display_name: {requirement.kind}:{requirement.name}"
            )
        if card.kind != requirement.kind:
            raise EntityPreflightFailed(
                f"entity_card_kind_mismatch: {requirement.kind} -> {card.kind}"
            )
        validator = _KIND_VALIDATORS.get(requirement.kind)
        if validator is None:
            return  # kind without a typed schema accepts what the designer returns
        try:
            validator.model_validate(card.extensions or {})
        except ValidationError as exc:
            raise EntityPreflightFailed(
                f"entity_card_validation_failed: {requirement.kind}:{requirement.name} -> {exc}"
            ) from exc

    def _promote_if_needed(self, entity: CanonEntity) -> None:
        if entity.lifecycle == "proposed":
            self._registry.approve(entity.entity_id)
        if entity.lifecycle == "approved":
            self._registry.activate(entity.entity_id)

    def _maybe_promote(
        self,
        card: CanonEntity,
        importance: int,
    ) -> CanonEntity:
        target = (
            _PROMOTION_LIFECYCLE
            if importance >= _MIN_PROMOTION_IMPORTANCE
            else card.lifecycle
        )
        if target == card.lifecycle:
            return card
        return card.model_copy(update={"lifecycle": target})


def preflight_requirements(
    requirements: Iterable[EntityRequirement],
    *,
    designer: EntityDesigner,
    registry: CanonRegistry | None = None,
) -> CanonRegistry:
    """Convenience entry point used by tests and the orchestrator.

    Builds a fresh ``CanonRegistry`` when one is not supplied
    so callers can scope the preflight to a single chapter
    without polluting the project's global registry.
    """
    target = registry if registry is not None else CanonRegistry.empty()
    service = CanonService(registry=target, designer=designer)
    service.ensure_requirements(requirements)
    return target


__all__ = [
    "CanonService",
    "EntityPreflightFailed",
    "preflight_requirements",
]
