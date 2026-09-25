"""Shared helpers for the modular agent runtimes.

The gateway-backed runtimes (``GatewayDirectorRuntime``,
``GatewayWriterRuntime``, ``GatewayConsistencyRuntime``) used
to each re-implement the same lightweight-request
translation, the same stage-settings lookup, and the same
``PromptCallLog`` lifecycle. The duplication was the root
cause of two production failures:

* The lightweight request reached the gateway without
  ``provider`` / ``model`` / ``operation``, the gateway's
  :func:`dataclasses.replace` raised ``TypeError`` for the
  missing fields, and the gateway's broad ``except`` turned
  the call into a silent model-failure response — Round 5 /
  Round 6 had to teach every runtime the translation
  separately.
* None of the modular runs wrote to ``PromptCallLog``, so
  the workbench's stage evidence column stayed empty. The
  user feedback after Round 5 specifically called this out.

This module centralises the translation and the logging so
the three runtimes stay one-liners, the fix for one stage
is the fix for all three, and the prompt_call_log entry
records the same provider / model the gateway actually
answered with.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from packages.story_core.model_gateway.contracts import ModelRequest, ModelResponse
from packages.story_core.prompt_call_log import (
    finish_prompt_call,
    start_prompt_call,
)


def _settings_provider_model(settings: Any) -> tuple[str, str, str, float | None]:
    """Project a stage-settings object into the four fields
    the gateway and ``PromptCallLog`` both want to record.

    Returns ``(provider, model, protocol, temperature)``.
    ``provider`` is the catalog ``provider_id`` (e.g.
    ``"openai"``); ``model`` is the configured model name;
    ``protocol`` is the transport the provider uses; and
    ``temperature`` is the configured temperature. Missing
    or invalid values are normalised to empty strings /
    ``None`` so the rest of the pipeline never has to guard.
    """
    if settings is None:
        return "", "", "", None
    provider = str(
        getattr(settings, "provider_id", "") or getattr(settings, "provider", "")
    )
    model = str(getattr(settings, "model", "") or "")
    protocol = str(getattr(settings, "protocol", "") or "")
    raw_temperature = getattr(settings, "temperature", None)
    temperature: float | None = None
    if raw_temperature is not None:
        try:
            temperature = float(raw_temperature)
        except (TypeError, ValueError):
            temperature = None
    return provider, model, protocol, temperature


def _request_prompt_and_metadata(request: Any) -> tuple[str, dict[str, Any]]:
    """Pull the prompt and metadata off whatever the agent
    sent. The agent may hand the runtime a lightweight
    ``_ModelRequest`` (with ``prompt`` / ``stage`` /
    ``metadata``) or a fully-populated :class:`ModelRequest`;
    the helper only cares about the prompt and metadata.
    """
    prompt = getattr(request, "prompt", "") or ""
    metadata = getattr(request, "metadata", None) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return str(prompt), dict(metadata)


def _resolve_operation(metadata: dict[str, Any], stage: str) -> str:
    """Pick the operation name the gateway will see.

    The metadata the agents set always carries the agent
    name (``director`` / ``writer`` / ``consistency``); the
    stage is the gateway routing key (``director`` /
    ``writer`` / ``consistency``). They are equal today, but
    the ``agent`` key in metadata is the historical contract
    the orchestrator and CLI tools read, so we prefer it.
    """
    if isinstance(metadata, dict):
        candidate = metadata.get("agent") or metadata.get("stage")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return stage


@dataclass
class _ResolvedCall:
    """The internal envelope every modular runtime routes
    through. The fields are pre-populated with the stage
    settings so the gateway and the prompt_call_log both see
    the same provider / model / protocol / temperature.
    """

    request: ModelRequest
    protocol: str
    settings: Any | None = None


def _resolve_stage_settings(stage: str) -> Any | None:
    """Return the stage settings, or ``None`` when the
    runtime configuration is unavailable. The translator
    never raises so a missing config does not block the
    agent from at least attempting a call.

    The lookup uses a lazy import so tests can monkeypatch
    :func:`packages.story_core.runtime_config.resolve_stage_runtime`
    and see the patched value flow through to the
    ``PromptCallLog`` entry.
    """
    from packages.story_core import runtime_config

    resolver = getattr(runtime_config, "resolve_stage_runtime", None)
    if resolver is None:
        return None
    try:
        return resolver(stage)
    except Exception:
        return None


def translate_request(
    request: Any,
    *,
    stage: str,
    settings: Any | None = None,
) -> ModelRequest:
    """Translate a lightweight request into a real
    :class:`ModelRequest` addressed at ``stage``.

    Most modular agents send only ``prompt`` / ``stage`` /
    ``metadata``; Character sends a complete ``ModelRequest``.
    The gateway needs provider/model/operation fields populated
    for both forms.

    A complete :class:`ModelRequest` retains its prompt contract;
    stage settings remain authoritative for provider and model.
    """
    if settings is None:
        settings = _resolve_stage_settings(stage)
    provider, model, _protocol, temperature = _settings_provider_model(settings)
    if isinstance(request, ModelRequest):
        return ModelRequest(
            prompt=request.prompt,
            provider=provider or request.provider,
            model=model or request.model,
            operation=request.operation or stage,
            system_prompt=request.system_prompt,
            messages=request.messages,
            temperature=(
                request.temperature
                if request.temperature is not None
                else temperature
            ),
            metadata=dict(request.metadata or {}),
            max_tokens=request.max_tokens,
            output_limit_requirement=request.output_limit_requirement,
            json_mode=request.json_mode,
            timeout_seconds=request.timeout_seconds,
            optional_input_messages=request.optional_input_messages,
        )
    prompt, metadata = _request_prompt_and_metadata(request)
    operation = _resolve_operation(metadata, stage)
    return ModelRequest(
        prompt=prompt,
        provider=provider,
        model=model,
        operation=operation,
        temperature=temperature,
        metadata=metadata,
        output_limit_requirement=(
            "required"
            if metadata.get("output_limit_requirement") == "required"
            else "best_effort"
        ),
        optional_input_messages=tuple(
            metadata.get("preflight_optional_message_indexes", ())
            if isinstance(metadata.get("preflight_optional_message_indexes", ()), (list, tuple))
            else ()
        ),
    )


def resolve_call(request: Any, *, stage: str) -> _ResolvedCall:
    """Translate the request and capture the protocol in one
    call. The runtime returns the envelope to the caller so
    the same ``provider`` / ``model`` / ``protocol`` are
    used for the gateway call, the prompt_call_log entry,
    and the workflow artifact record.
    """
    settings = _resolve_stage_settings(stage)
    _provider, _model, protocol, _temperature = _settings_provider_model(settings)
    translated = translate_request(request, stage=stage, settings=settings)
    return _ResolvedCall(request=translated, protocol=protocol, settings=settings)


def _response_text(response: Any) -> str:
    """Best-effort: return the body of whatever the gateway
    returned, or an empty string if nothing useful is on the
    response. Used to populate ``PromptCallLog.output_chars``
    / ``output_summary``.
    """
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        try:
            return json.dumps(response, ensure_ascii=False)[:300]
        except (TypeError, ValueError):
            return ""
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    payload = getattr(response, "payload", None)
    if isinstance(payload, dict):
        try:
            return json.dumps(payload, ensure_ascii=False)[:300]
        except (TypeError, ValueError):
            return ""
    return ""


def call_with_logging(
    *,
    gateway: Any,
    stage: str,
    request: Any,
) -> tuple[Any, str, str, str]:
    """Call the gateway for ``stage`` and log the call.

    The function:

    1. Translates a lightweight request into a real
       :class:`ModelRequest` (filling ``provider`` /
       ``model`` / ``operation`` / ``temperature`` from the
       stage settings).
    2. Starts a ``PromptCallLog`` entry under the current
       context-local recorder (if any) so the workbench's
       stage evidence column shows the real provider /
       model.
    3. Calls :meth:`RuntimeModelGateway.complete_stage` and
       finishes the log entry as ``"succeeded"`` or
       ``"failed"`` based on the response.
    4. Returns ``(response, provider, model, protocol)`` so
       the runtime can pass the resolved metadata into the
       workflow artifact record.

    Errors raised by the gateway propagate after the log
    entry is closed as ``"failed"`` — the workbench never
    sees a hanging "running" row, and the next caller can
    still inspect what went wrong.
    """
    resolved = resolve_call(request, stage=stage)
    model_request = resolved.request
    protocol = resolved.protocol

    chapter_number = 0
    if isinstance(model_request.metadata, dict):
        try:
            chapter_number = int(model_request.metadata.get("chapter_number") or 0)
        except (TypeError, ValueError):
            chapter_number = 0

    call_id = start_prompt_call(
        chapter_number=chapter_number,
        stage=stage,
        agent=model_request.operation or stage,
        user_prompt=model_request.prompt or "",
        system_prompt=model_request.system_prompt,
        provider=model_request.provider,
        protocol=protocol,
        model=model_request.model,
        temperature=model_request.temperature,
        requested_max_tokens=model_request.max_tokens,
        json_mode=model_request.json_mode,
    )

    try:
        if resolved.settings is not None and callable(getattr(gateway, "complete_resolved", None)):
            response = gateway.complete_resolved(resolved.settings, model_request)
        else:
            response = gateway.complete_stage(stage, model_request)
    except Exception as exc:
        finish_prompt_call(
            call_id,
            status="failed",
            provider=model_request.provider,
            protocol=protocol,
            model=model_request.model,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise

    text = _response_text(response)
    status = "succeeded"
    error = ""
    if response is None:
        status = "failed"
        error = "no_response"
    elif isinstance(response, ModelResponse):
        if not response.ok:
            status = "failed"
            error = response.error or "model_call_failed"
    finish_prompt_call(
        call_id,
        status=status,
        provider=model_request.provider,
        protocol=protocol,
        model=model_request.model,
        resolved_model=str(getattr(response, "resolved_model", "") or ""),
        output=text,
        error=error,
        temperature_omitted=bool(getattr(response, "temperature_omitted", False)),
        raw=getattr(response, "raw", None),
        usage=getattr(response, "usage", None),
        preflight_report=getattr(response, "preflight_report", None),
    )
    return response, model_request.provider, model_request.model, protocol


__all__ = [
    "call_with_logging",
    "resolve_call",
    "translate_request",
]
