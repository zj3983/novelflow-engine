"""Consistency runtime boundary.

The focused consistency agent is configured with a
``ConsistencyRuntime`` rather than a concrete provider. The
gateway-backed implementation routes through
``RuntimeModelGateway.complete_stage("consistency", ...)`` so
the same agent works for Codex CLI, Gemini CLI, and HTTP API
without any provider-specific branching.

The runtime is its own class — separate from
``GatewayDirectorRuntime`` — because:

* The previous round reused ``GatewayDirectorRuntime`` for
  the consistency call and the workbench ended up listing
  two ``director`` rows per chapter run. The
  prompt_call_log entry also used the wrong stage key. A
  dedicated runtime routes the call through
  ``complete_stage("consistency", ...)`` so the workbench's
  stage evidence column shows three distinct rows
  (director / writer / consistency) per chapter.
* The agent boundary is per-stage: the consistency agent
  only needs the runtime to know about the consistency
  stage. Coupling the consistency agent to the director
  runtime meant swapping providers required touching the
  director wiring.
"""

from __future__ import annotations

from typing import Any, Protocol

from .._runtime_common import call_with_logging


class ConsistencyRuntime(Protocol):
    """Anything that can fulfil one consistency model call."""

    def complete(self, request: Any) -> Any: ...


class GatewayConsistencyRuntime:
    """Route consistency calls through the canonical model gateway.

    The shared :func:`call_with_logging` helper translates the
    lightweight ``_ModelRequest`` to a fully populated
    :class:`ModelRequest` (with ``operation="consistency"``,
    the provider / model the stage settings resolve to, and
    the configured temperature), opens and closes a
    ``PromptCallLog`` entry under the ``consistency`` stage,
    and returns the response plus the resolved metadata.
    """

    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway

    def complete(self, request: Any) -> Any:
        response, _provider, _model, _protocol = call_with_logging(
            gateway=self._gateway, stage="consistency", request=request
        )
        return response


__all__ = ["ConsistencyRuntime", "GatewayConsistencyRuntime"]
