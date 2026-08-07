"""Writer runtime boundary.

The writer agent is configured with a ``WriterRuntime`` rather
than a concrete provider. The gateway-backed implementation
routes through ``RuntimeModelGateway.complete_stage("writer",
...)`` so the same agent works for Codex CLI, Gemini CLI, and
HTTP API without any provider-specific branching.
"""

from __future__ import annotations

from typing import Any, Protocol


class WriterRuntime(Protocol):
    """Anything that can fulfil one writer model call.

    ``complete`` is intentionally a small, stable surface. A test
    double can return a canned response; a gateway-backed
    implementation can route through the canonical model
    gateway; a future offline implementation can return a
    fixture. The writer agent treats them all the same.
    """

    def complete(self, request: Any) -> Any: ...


class GatewayWriterRuntime:
    """Route writer calls through the canonical model gateway.

    The agent never sees the underlying transport; it only knows
    that a ``complete(request)`` call returns a model response.
    """

    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway

    def complete(self, request: Any) -> Any:
        return self._gateway.complete_stage("writer", request)


__all__ = ["WriterRuntime", "GatewayWriterRuntime"]
