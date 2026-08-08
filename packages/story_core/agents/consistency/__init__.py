"""Focused consistency agent.

The agent answers exactly one question: *does the draft
contradict the established facts or the approved director
plan?* It does not grade literary style; style findings stay
warnings the user can accept and ship with.

The agent is **fail-closed**: a runtime exception or a
malformed response becomes a blocking
``consistency.unavailable`` or ``consistency.invalid_response``
finding rather than a silent ``[]`` that lets a contradictory
draft reach the confirmation gate. Style findings keep the
original ``blocking=False`` downgrade; only the failure modes
are treated as blocking.

The runtime boundary lives in
:mod:`packages.story_core.agents.consistency.runtime` and the
shared prompt_call_log instrumentation in
:mod:`packages.story_core.agents._runtime_common`. The
consistency agent itself is a small, single-purpose wrapper
around the focused prompt builder.
"""

from .agent import (
    ConsistencyFinding,
    ConsistencyRuntime,
    FocusedConsistencyAgent,
    build_consistency_prompt,
    focused_consistency_review,
)
from .runtime import GatewayConsistencyRuntime

__all__ = [
    "ConsistencyFinding",
    "ConsistencyRuntime",
    "FocusedConsistencyAgent",
    "GatewayConsistencyRuntime",
    "build_consistency_prompt",
    "focused_consistency_review",
]
