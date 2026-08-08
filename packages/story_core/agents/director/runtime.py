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
    """Route director calls through the canonical model gateway.

    The agents ship a lightweight ``_ModelRequest`` (just
    ``prompt`` / ``stage`` / ``metadata``) so they do not have
    to know about the gateway's provider / model / operation
    contract. The gateway itself, however, needs a fully
    populated :class:`ModelRequest` — without ``provider`` and
    ``model`` the :func:`dataclasses.replace` call inside
    :meth:`RuntimeModelGateway.complete_resolved` raises
    :class:`TypeError`, the gateway's broad ``except`` swallows
    the failure, and the agent receives a model-failure
    response. That failure used to bubble up as an empty
    consistency finding (silently) and a writer ``empty_body``
    error (loudly). We now translate the lightweight request to
    a real :class:`ModelRequest` here so both paths get a
    properly addressed gateway call. The translation reads the
    stage-resolved runtime settings to fill ``provider`` /
    ``model`` / ``operation`` exactly the way
    :meth:`RuntimeModelGateway.complete_resolved` would have
    done internally — the only difference is that the missing
    fields never reach the dataclass in the first place.
    """

    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway

    def complete(self, request: Any) -> Any:
        from packages.story_core.model_gateway.contracts import ModelRequest
        from packages.story_core.runtime_config import resolve_stage_runtime

        if isinstance(request, ModelRequest):
            return self._gateway.complete_stage("director", request)
        stage = "director"
        operation = "director"
        prompt = getattr(request, "prompt", "") or ""
        metadata = getattr(request, "metadata", None) or {}
        if isinstance(metadata, dict):
            metadata_operation = metadata.get("agent") or metadata.get("stage")
            if isinstance(metadata_operation, str) and metadata_operation.strip():
                operation = metadata_operation.strip()
        try:
            settings = resolve_stage_runtime(stage)
        except Exception:
            settings = None
        provider = ""
        model = ""
        temperature: float | None = None
        if settings is not None:
            provider = str(
                getattr(settings, "provider_id", "") or getattr(settings, "provider", "")
            )
            model = str(getattr(settings, "model", "") or "")
            settings_temperature = getattr(settings, "temperature", None)
            if settings_temperature is not None:
                try:
                    temperature = float(settings_temperature)
                except (TypeError, ValueError):
                    temperature = None
        translated = ModelRequest(
            prompt=prompt,
            provider=provider,
            model=model,
            operation=operation,
            temperature=temperature,
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
        )
        return self._gateway.complete_stage(stage, translated)


__all__ = ["DirectorRuntime", "GatewayDirectorRuntime"]
