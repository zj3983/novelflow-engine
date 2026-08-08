"""Entity preflight service.

The preflight sits between the director and the writer. It
takes the director's ``entity_requirements`` and ensures each
named one either resolves to an existing canonical entity or
has a freshly designed card before the writer ever sees the
chapter. Disposable inline roles stay out of the registry.

The same service is also responsible for committing a
confirmed candidate's :class:`ContinuityDelta` to the canon.
``apply_delta`` is the single entry point the candidate
confirmation path uses to translate a chapter's proposed
facts into real changes on the registry. Every operation
carries its own chapter / source-sentence provenance so the
workbench can show *why* a relationship flipped, an item
moved, or a marker landed on the timeline.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, TYPE_CHECKING

from pydantic import ValidationError

from ..agents.contracts import EntityRequirement
from .entity_designer import EntityDesigner
from .registry import CanonEntity, CanonRegistry
from .schemas import CharacterCard, EquipmentCard, TechniqueCard

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..continuity.delta import ContinuityDelta


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

    # --- Continuity delta --------------------------------------------------

    def apply_delta(self, delta: ContinuityDelta | None) -> dict[str, int]:
        """Commit a confirmed chapter's proposed facts to the canon.

        Every operation type on the :class:`ContinuityDelta` is
        applied to the registry:

        * ``entity_additions`` → new ``CanonEntity`` records;
        * ``entity_updates`` → shallow patches to the entity's
          ``extensions``;
        * ``relationship_changes`` → stored on the registry's
          relationship log (latest polarity wins per edge);
        * ``inventory_changes`` → patches the entity's
          ``extensions["inventory"]`` entry with the signed
          delta, writing the new quantity when stated;
        * ``task_progressions`` → patches the quest entity's
          ``extensions["status"]`` field with the new status;
        * ``location_movements`` → patches the entity's
          ``extensions["location"]`` to the destination;
        * ``timeline_advances`` → appended to the registry's
          append-only timeline log;
        * ``foreshadowing_changes`` → stored on the registry's
          foreshadowing log (latest action wins per id).

        The method is idempotent per chapter: re-applying the
        same delta overwrites the same edges / fields. Missing
        entities are silently skipped (the user sees the
        reference-validation list on the snapshot when a delta
        references a character that was never designed). The
        returned summary is the per-operation apply count so
        the workbench can render an "applied N facts" line
        without re-reading the delta.
        """
        # Lazy import: ``continuity.delta`` re-exports
        # ``agents.pipeline`` through the package init chain
        # and would otherwise create a circular import while
        # ``canon.service`` is still being initialised.
        from ..continuity.delta import ContinuityDelta as _ContinuityDelta

        if not isinstance(delta, _ContinuityDelta) and delta is not None:
            raise TypeError("apply_delta_expected_continuity_delta")
        if delta is None:
            return {
                "entity_additions": 0,
                "entity_updates": 0,
                "relationship_changes": 0,
                "inventory_changes": 0,
                "task_progressions": 0,
                "location_movements": 0,
                "timeline_advances": 0,
                "foreshadowing_changes": 0,
            }
        chapter = int(delta.chapter_number)
        counts = {
            "entity_additions": 0,
            "entity_updates": 0,
            "relationship_changes": 0,
            "inventory_changes": 0,
            "task_progressions": 0,
            "location_movements": 0,
            "timeline_advances": 0,
            "foreshadowing_changes": 0,
        }
        # Entity additions first so later updates can find the
        # newly created entity by id.
        for addition in delta.entity_additions:
            kind = str(addition.kind)
            existing = self._registry.get(addition.entity_id)
            if existing is not None:
                # Idempotent re-apply: an earlier chapter already
                # created this entity. Promote it to active so
                # the new chapter sees it.
                if existing.lifecycle == "proposed":
                    self._registry.approve(existing.entity_id)
                if existing.lifecycle == "approved":
                    self._registry.activate(existing.entity_id)
                counts["entity_additions"] += 1
                continue
            try:
                self._registry.add(
                    kind=kind,  # type: ignore[arg-type]
                    name=str(addition.canonical_name or addition.entity_id),
                    aliases=list(addition.aliases or []),
                    entity_id=str(addition.entity_id),
                    lifecycle="active",
                    extensions=dict(addition.attributes or {}),
                )
            except ValueError:
                # ``entity_id_conflict`` is fine on re-apply;
                # ``alias_conflict`` means another entity already
                # owns the canonical name, which is also fine —
                # we leave the registry alone and let the
                # workbench surface the reference-validation row.
                continue
            counts["entity_additions"] += 1
        for update in delta.entity_updates:
            try:
                self._registry.update_attributes(
                    update.entity_id, changes=dict(update.changes or {})
                )
            except ValueError:
                continue
            counts["entity_updates"] += 1
        for change in delta.relationship_changes:
            try:
                self._registry.add_relationship(
                    subject_id=change.subject_id,
                    predicate=change.predicate,
                    object_id=change.object_id,
                    polarity=change.polarity,
                    chapter_number=chapter,
                    source_sentence=change.source_sentence,
                    confidence=change.confidence,
                )
            except ValueError:
                continue
            counts["relationship_changes"] += 1
        for change in delta.inventory_changes:
            try:
                self._apply_inventory_change(change, chapter_number=chapter)
            except ValueError:
                continue
            counts["inventory_changes"] += 1
        for task in delta.task_progressions:
            try:
                self._registry.update_attributes(
                    task.task_id,
                    changes={
                        "status": task.status,
                        "notes": task.notes,
                        "last_chapter": chapter,
                    },
                )
            except ValueError:
                continue
            counts["task_progressions"] += 1
        for move in delta.location_movements:
            try:
                self._registry.update_attributes(
                    move.entity_id,
                    changes={
                        "location": move.to_location,
                        "previous_location": move.from_location,
                        "last_moved_chapter": chapter,
                    },
                )
            except ValueError:
                continue
            counts["location_movements"] += 1
        for marker in delta.timeline_advances:
            try:
                self._registry.add_timeline_marker(
                    marker=marker.marker,
                    chapter_number=chapter,
                    source_sentence=marker.source_sentence,
                )
            except ValueError:
                continue
            counts["timeline_advances"] += 1
        for change in delta.foreshadowing_changes:
            try:
                self._registry.add_foreshadowing_change(
                    foreshadowing_id=change.foreshadowing_id,
                    action=change.action,
                    detail=change.detail,
                    chapter_number=chapter,
                    source_sentence=change.source_sentence,
                )
            except ValueError:
                continue
            counts["foreshadowing_changes"] += 1
        return counts

    def _apply_inventory_change(
        self,
        change: Any,
        *,
        chapter_number: int,
    ) -> None:
        """Apply an ``InventoryChange`` to an entity's inventory extension."""
        entity = self._registry.get(change.entity_id)
        current: dict[str, dict[str, Any]] = {}
        if entity is not None and isinstance(entity.extensions, dict):
            existing = entity.extensions.get("inventory")
            if isinstance(existing, dict):
                current = {str(k): dict(v) for k, v in existing.items() if isinstance(v, dict)}
        slot = current.get(str(change.item), {"quantity": 0})
        try:
            quantity = int(slot.get("quantity", 0)) + int(change.delta)
        except (TypeError, ValueError):
            quantity = int(change.delta)
        if quantity < 0:
            quantity = 0
        if change.resulting_quantity is not None:
            quantity = int(change.resulting_quantity)
        current[str(change.item)] = {
            "quantity": quantity,
            "last_chapter": chapter_number,
        }
        self._registry.update_attributes(
            change.entity_id,
            changes={"inventory": current},
        )


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
