"""Focused consistency agent.

The agent answers exactly one question: *does the draft
contradict the established Canon facts?* Director plans and
context summaries remain advisory. It does not grade literary style; style findings stay
warnings the user can accept and ship with.

An unavailable review stays visible: a runtime exception or a
malformed response becomes an advisory
``consistency.unavailable`` or ``consistency.invalid_response``
finding rather than a silent ``[]``. This is not evidence of a factual
contradiction. Model findings may block only when backed by established
snapshot evidence; deterministic contract gates keep their own disposition.

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
