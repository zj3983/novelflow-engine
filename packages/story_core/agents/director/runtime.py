"""Director runtime boundary.

The director agent is configured with a ``DirectorRuntime``
rather than a concrete provider. The gateway-backed
implementation routes through
``RuntimeModelGateway.complete_stage("director", ...)`` so the
same agent works for Codex CLI, Gemini CLI, and HTTP API
without any provider-specific branching.
"""

from __future__ import annotations

from typing import Any, Protocol


class DirectorRuntime(Protocol):
    """Anything that can fulfil one director model call."""

    def complete(self, request: Any) -> Any: ...


class GatewayDirectorRuntime:
    """Route director calls through the canonical model gateway."""

    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway

    def complete(self, request: Any) -> Any:
        return self._gateway.complete_stage("director", request)


__all__ = ["DirectorRuntime", "GatewayDirectorRuntime"]
