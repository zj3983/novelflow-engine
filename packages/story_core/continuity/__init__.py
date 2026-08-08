"""Continuity primitives shared by the writer, the director,
and the focused consistency agent.

The ``checks`` module owns the pure-function deterministic
findings; the ``delta`` module owns the structured proposal
of facts a chapter introduces that should reach canon once
confirmed. Higher-level callers (the orchestrator's
confirmation path, the workbench) read the structured
``CheckFinding`` and ``ContinuityDelta`` records to decide
whether a chapter can ship and what state should change.
"""

from .checks import (
    CheckContext,
    CheckFinding,
    DeterministicChecks,
    check_body_not_empty,
    check_chapter_number_contract,
    check_inventory_changes,
    check_knowledge_boundaries,
    check_length_window,
    check_outline_must_haves,
    run_deterministic_checks,
)
from .delta import (
    ContinuityDelta,
    EntityAddition,
    EntityUpdate,
    FactSource,
    ForeshadowingChange,
    InventoryChange,
    LocationMovement,
    RelationshipChange,
    TaskProgression,
    TimelineAdvance,
)
from .snapshot import ChapterSnapshot, SNAPSHOT_SCHEMA_VERSION
from .store import ContinuityStore

__all__ = [
    "ChapterSnapshot",
    "CheckContext",
    "CheckFinding",
    "ContinuityDelta",
    "ContinuityStore",
    "DeterministicChecks",
    "EntityAddition",
    "EntityUpdate",
    "FactSource",
    "ForeshadowingChange",
    "InventoryChange",
    "LocationMovement",
    "RelationshipChange",
    "SNAPSHOT_SCHEMA_VERSION",
    "TaskProgression",
    "TimelineAdvance",
    "check_body_not_empty",
    "check_chapter_number_contract",
    "check_inventory_changes",
    "check_knowledge_boundaries",
    "check_length_window",
    "check_outline_must_haves",
    "run_deterministic_checks",
]
