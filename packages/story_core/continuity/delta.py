"""Structured proposal of facts a chapter introduces.

The ``ContinuityDelta`` is the bridge between the writer and the canon:
the writer (and the consistency agent) propose facts, the user reviews
them, and only confirmed facts reach the canonical entity registry and
the continuity ledger. Every operation carries ``source_sentence`` and
``confidence`` so the workbench can show *why* the proposal exists.

The schema is strict (``extra="forbid"`` on every model) so a
malformed writer output cannot leak into canon, and the
``schema_version`` constant keeps the on-disk format explicit.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FactSource(BaseModel):
    """Provenance for one extracted fact.

    ``chapter_number`` is the chapter that produced the fact (always
    available from the candidate context). ``source_sentence`` is the
    sentence in the chapter body that triggered the fact; the
    workbench highlights it. ``confidence`` is ``1.0`` for purely
    deterministic extraction and ``< 1.0`` for model-backed extraction.
    """

    model_config = ConfigDict(extra="forbid")

    chapter_number: int
    source_sentence: str
    confidence: float = 1.0


class EntityAddition(FactSource):
    """A new entity the chapter introduced (or made newly important)."""

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    kind: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class EntityUpdate(FactSource):
    """A change to an existing entity's attributes or state.

    ``changes`` is a shallow key→value patch; nested updates are not
    modeled because the registry records a single canonical record per
    entity, and deeper diffs belong in a separate versioned history.
    """

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    changes: dict[str, Any] = Field(default_factory=dict)


class RelationshipChange(FactSource):
    """An added / removed / intensified / weakened relationship."""

    model_config = ConfigDict(extra="forbid")

    subject_id: str
    predicate: str
    object_id: str
    polarity: Literal["added", "removed", "intensified", "weakened"] = "added"


class InventoryChange(FactSource):
    """A gain or loss of an item owned by an entity.

    ``delta`` is the signed change (``+N`` for acquisitions, ``-N`` for
    losses / consumption). ``resulting_quantity`` is optional and only
    set when the prose stated an exact count (e.g. "还剩三枚金币").
    """

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    item: str
    delta: int
    resulting_quantity: int | None = None


class TaskProgression(FactSource):
    """A quest / task / sub-objective progressed in this chapter."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: Literal["planted", "advanced", "resolved", "abandoned"]
    notes: str = ""


class LocationMovement(FactSource):
    """A character (or group) moved to a new place.

    ``from_location`` is optional because the source prose does not
    always state the starting point — only the destination.
    """

    model_config = ConfigDict(extra="forbid")

    entity_id: str
    from_location: str | None = None
    to_location: str


class TimelineAdvance(FactSource):
    """A marker the chapter placed on the story timeline.

    Examples: "入夜", "第三天清晨", "年关将近". The string is the
    human-readable marker; the orchestrator and the canon service
    decide how to interpret it.
    """

    model_config = ConfigDict(extra="forbid")

    marker: str


class ForeshadowingChange(FactSource):
    """A planted, advanced, or resolved foreshadowing note."""

    model_config = ConfigDict(extra="forbid")

    foreshadowing_id: str
    action: Literal["planted", "advanced", "resolved"]
    detail: str = ""


class ContinuityDelta(BaseModel):
    """All proposed facts from a single chapter's pipeline.

    Sections default to empty so a chapter that produced no detectable
    changes still serializes to a valid delta. ``reference_validation``
    is filled in by the extractor after building the rest of the
    delta: it records whether each referenced entity / task /
    foreshadowing id actually exists in the candidate canon view.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "continuity-delta/v1"
    chapter_number: int
    entity_additions: list[EntityAddition] = Field(default_factory=list)
    entity_updates: list[EntityUpdate] = Field(default_factory=list)
    relationship_changes: list[RelationshipChange] = Field(default_factory=list)
    inventory_changes: list[InventoryChange] = Field(default_factory=list)
    task_progressions: list[TaskProgression] = Field(default_factory=list)
    location_movements: list[LocationMovement] = Field(default_factory=list)
    timeline_advances: list[TimelineAdvance] = Field(default_factory=list)
    foreshadowing_changes: list[ForeshadowingChange] = Field(default_factory=list)
    reference_validation: list[dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "ContinuityDelta",
    "EntityAddition",
    "EntityUpdate",
    "FactSource",
    "ForeshadowingChange",
    "InventoryChange",
    "LocationMovement",
    "RelationshipChange",
    "TaskProgression",
    "TimelineAdvance",
]
