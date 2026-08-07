"""Continuity primitives shared by the writer, the director,
and the focused consistency agent.

The ``checks`` module owns the pure-function deterministic
findings; higher-level callers (the orchestrator's
confirmation path, the workbench) read the structured
``CheckFinding`` records to decide whether a chapter can
ship.
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

__all__ = [
    "CheckContext",
    "CheckFinding",
    "DeterministicChecks",
    "check_body_not_empty",
    "check_chapter_number_contract",
    "check_inventory_changes",
    "check_knowledge_boundaries",
    "check_length_window",
    "check_outline_must_haves",
    "run_deterministic_checks",
]
