"""Director runtime boundary.

The director agent is configured with a ``DirectorRuntime``
rather than a concrete provider. The gateway-backed
implementation routes through
``RuntimeModelGateway.complete_stage("director", ...)`` so the
same agent works for Codex CLI, Gemini CLI, and HTTP API
without any provider-specific branching.

The runtime delegates the lightweight-request translation and
the ``PromptCallLog`` lifecycle to the shared
:mod:`packages.story_core.agents._runtime_common` module. The
director agent never has to know which provider / model the
gateway addressed — the resolved values are surfaced back
through the runtime so the workflow artifact record can carry
the same metadata.
"""

from __future__ import annotations

from typing import Any, Protocol

from .._runtime_common import call_with_logging


class DirectorRuntime(Protocol):
    """Anything that can fulfil one director model call."""

    def complete(self, request: Any) -> Any: ...


class GatewayDirectorRuntime:
    """Route director calls through the canonical model gateway.

    The agents ship a lightweight ``_ModelRequest`` (just
    ``prompt`` / ``stage`` / ``metadata``) so they do not have
    to know about the gateway's provider / model / operation
    contract. The shared :func:`call_with_logging` helper
    translates the lightweight request to a real
    :class:`ModelRequest` (filling ``provider`` / ``model`` /
    ``operation`` / ``temperature`` from the stage settings),
    starts and finishes a ``PromptCallLog`` entry, and
    returns the response plus the resolved metadata. The
    runtime itself is therefore a one-liner around the helper.
    """

    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway

    def complete(self, request: Any) -> Any:
        response, _provider, _model, _protocol = call_with_logging(
            gateway=self._gateway, stage="director", request=request
        )
        return response


__all__ = ["DirectorRuntime", "GatewayDirectorRuntime"]
