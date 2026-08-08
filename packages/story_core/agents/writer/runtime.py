"""Writer runtime boundary.

The writer agent is configured with a ``WriterRuntime`` rather
than a concrete provider. The gateway-backed implementation
routes through ``RuntimeModelGateway.complete_stage("writer",
...)`` so the same agent works for Codex CLI, Gemini CLI, and
HTTP API without any provider-specific branching.

The runtime delegates the lightweight-request translation and
the ``PromptCallLog`` lifecycle to the shared
:mod:`packages.story_core.agents._runtime_common` module. The
writer agent never has to know which provider / model the
gateway addressed — the resolved values are surfaced back
through the runtime so the workflow artifact record can carry
the same metadata.
"""

from __future__ import annotations

from typing import Any, Protocol

from .._runtime_common import call_with_logging


class WriterRuntime(Protocol):
    """Anything that can fulfil one writer model call.

    ``complete`` is intentionally a small, stable surface. A
    test double can return a canned response; a gateway-backed
    implementation can route through the canonical model
    gateway; a future offline implementation can return a
    fixture. The writer agent treats them all the same.
    """

    def complete(self, request: Any) -> Any: ...


class GatewayWriterRuntime:
    """Route writer calls through the canonical model gateway.

    The agent never sees the underlying transport; it only
    knows that a ``complete(request)`` call returns a model
    response. The shared :func:`call_with_logging` helper
    translates the lightweight ``_ModelRequest`` to a fully
    populated :class:`ModelRequest`, opens and closes a
    ``PromptCallLog`` entry, and returns the response plus the
    resolved metadata.
    """

    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway

    def complete(self, request: Any) -> Any:
        response, _provider, _model, _protocol = call_with_logging(
            gateway=self._gateway, stage="writer", request=request
        )
        return response


__all__ = ["WriterRuntime", "GatewayWriterRuntime"]
