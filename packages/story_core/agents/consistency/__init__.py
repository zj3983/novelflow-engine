"""Focused consistency agent.

The agent answers exactly one question: *does the draft
contradict the established facts or the approved director
plan?* It does not grade literary style; style findings stay
warnings the user can accept and ship with.
"""

from .agent import (
    ConsistencyFinding,
    ConsistencyRuntime,
    FocusedConsistencyAgent,
    build_consistency_prompt,
    focused_consistency_review,
)

__all__ = [
    "ConsistencyFinding",
    "ConsistencyRuntime",
    "FocusedConsistencyAgent",
    "build_consistency_prompt",
    "focused_consistency_review",
]
