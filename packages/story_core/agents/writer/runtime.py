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
    The writer's lightweight ``_ModelRequest`` is translated to
    a fully populated :class:`ModelRequest` here so the
    gateway's :func:`dataclasses.replace` call does not raise
    on missing ``provider`` / ``model`` fields. Without this
    translation the gateway's broad ``except`` silently turns
    the call into a model-failure response and the writer
    surfaces ``writer_empty_body``.
    """

    def __init__(self, gateway: Any) -> None:
        self._gateway = gateway

    def complete(self, request: Any) -> Any:
        from packages.story_core.model_gateway.contracts import ModelRequest
        from packages.story_core.runtime_config import resolve_stage_runtime

        if isinstance(request, ModelRequest):
            return self._gateway.complete_stage("writer", request)
        stage = "writer"
        operation = "writer"
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


__all__ = ["WriterRuntime", "GatewayWriterRuntime"]
