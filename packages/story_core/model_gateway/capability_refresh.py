"""Explicit, bounded capability refresh using the existing adapters and cache.

Reading a profile never calls this service. A refresh sends at most four small
generation requests and one discovery request; limits are never probed.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import io
import json
from typing import Any
import urllib.error
import urllib.request

from .capabilities import (
    CapabilityProvenance, CapabilityRecord, KNOWN_CAPABILITIES, KNOWN_LIMITS,
    ModelCapabilityResolver,
)
from .contracts import ModelRequest
from .model_discovery import discover_provider_models
from .provider_adapters import (
    AnthropicAdapter, GeminiAdapter, OpenAICompatibleAdapter,
    _post_json_with_retry, _read_sse_json_stream,
)


def _transport(**kwargs):
    if not kwargs["payload"].get("stream"):
        return _post_json_with_retry(**kwargs)
    request = urllib.request.Request(
        kwargs["url"], data=json.dumps(kwargs["payload"]).encode(),
        headers=kwargs["headers"], method="POST",
    )
    with urllib.request.urlopen(request, timeout=kwargs["config"].timeout) as response:
        if "text/event-stream" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("stream_not_observed")
        result = _read_sse_json_stream(response, kwargs["config"].max_response_bytes)
        result["capability_probe_sse"] = True
        return result


def capability_snapshot(runtime: Any, resolver: ModelCapabilityResolver) -> dict:
    """Allowlisted projection; never return URLs, notes, credentials or raw data."""
    profile = resolver.resolve_model_profile(
        runtime.provider_id, runtime.base_url, runtime.model, runtime.protocol,
        user_declared=runtime.user_declared_capabilities,
    )
    records = {}
    for name in (*KNOWN_CAPABILITIES, *KNOWN_LIMITS):
        record = profile.effective_capability(name)
        provenance = record.provenance
        records[name] = {
            "state": record.state,
            "value": record.value if record.state == "supported" and name in KNOWN_LIMITS and isinstance(record.value, (int, float)) and not isinstance(record.value, bool) else None,
            "source": provenance.source,
            "verification_status": provenance.verification_status if record.state != "unknown" else "unknown",
            "verified_at": provenance.verified_at,
            "expires_at": provenance.expires_at,
        }
    return {
        "provider": runtime.provider_id, "model": runtime.model,
        "protocol": runtime.protocol, "identity_key": profile.identity.cache_key,
        "records": records,
        "output_budget": "best_effort" if runtime.protocol.endswith("_cli") else "provider_parameter",
    }


def refresh_capabilities(runtime: Any, *, resolver=None, transport=None, discovery=None) -> dict:
    resolver = resolver or ModelCapabilityResolver()
    stages: list[dict] = []
    result = {"ok": False, "steps": stages}
    if runtime.protocol.endswith("_cli"):
        # CLI budgets cannot provide the hard cap required for cheap probes.
        stages.append({"step": "connectivity", "status": "skipped", "reason": "cli_budget_best_effort"})
        return {**result, "profile": capability_snapshot(runtime, resolver)}
    send = transport or _transport
    rejected = False
    feature = ""

    def observed_transport(**kwargs):
        nonlocal rejected
        try:
            return send(**kwargs)
        except urllib.error.HTTPError as exc:
            body = exc.read(8192)
            exc.fp = io.BytesIO(body)
            try:
                error = json.loads(body).get("error", {})
                message = str(error.get("message", "")).lower()
                parameter = {"streaming": "stream", "json_mode": "response_format", "temperature": "temperature"}.get(feature, "")
                rejected = bool(parameter) and exc.code == 400 and (
                    parameter in message or error.get("param") == parameter
                ) and any(phrase in message for phrase in ("not supported", "unsupported", "only default", "only the default", "only 1 is allowed"))
            except (ValueError, AttributeError, TypeError):
                pass
            raise

    adapter_cls = {"openai_compatible": OpenAICompatibleAdapter, "anthropic": AnthropicAdapter, "gemini": GeminiAdapter}[runtime.protocol]
    adapter = adapter_cls(base_url=runtime.base_url, api_key=runtime.api_key, transport=observed_transport)
    request = ModelRequest(
        prompt='Return only {"ok":true}.', provider=runtime.provider_id,
        model=runtime.model, operation="capability_refresh", max_tokens=64,
        timeout_seconds=10, output_limit_requirement="required",
        metadata={"max_retries": 1, "max_response_bytes": 16384, "allow_compatibility_fallback": False},
    )
    connected = adapter.complete(request)
    stages.append({"step": "connectivity", "status": "success" if connected.ok else "failed"})
    if not connected.ok:
        return {**result, "profile": capability_snapshot(runtime, resolver)}
    identity = resolver.identity(runtime.provider_id, runtime.base_url, runtime.model, runtime.protocol, resolved_model=connected.resolved_model or None)
    resolver.record_resolved_model(identity)
    try:
        models = (discovery or discover_provider_models)(runtime)
        stages.append({"step": "discovery", "status": "success", "model_count": len(models), "selected_model_found": any(item["model_id"] == runtime.model for item in models)})
    except Exception:
        stages.append({"step": "discovery", "status": "failed", "reason": "discovery_unavailable"})
    probes = ["temperature"]
    if runtime.protocol in {"openai_compatible", "gemini"}:
        probes.append("json_mode")
    if runtime.protocol == "openai_compatible":
        probes.append("streaming")
    for feature in probes:
        rejected = False
        probe = replace(request, temperature=0.2 if feature == "temperature" else None,
                        json_mode=feature == "json_mode",
                        metadata={**request.metadata, "stream": feature == "streaming"})
        response = adapter.complete(probe)
        if response.ok and response.resolved_model:
            identity = identity.with_resolved_model(response.resolved_model)
            resolver.record_resolved_model(identity)
        state = "unknown"
        if rejected:
            state = "unsupported"
        elif response.ok:
            if feature == "temperature":
                state = "supported"
            elif feature == "json_mode":
                try:
                    if isinstance(json.loads(response.text), dict):
                        state = "supported"
                except ValueError:
                    pass
            elif feature == "streaming" and (response.raw or {}).get("capability_probe_sse") is True:
                state = "supported"
        # Unknown results are diagnostic, never overwrite still valid evidence.
        if state != "unknown":
            observed_identity = identity.with_resolved_model(response.resolved_model or identity.resolved_model)
            resolver.store.record_runtime_observation(observed_identity, feature, CapabilityRecord(
                state=state,
                provenance=CapabilityProvenance.for_source(
                    "runtime_observation", expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
                    note="explicit_small_probe",
                ),
            ))
        stages.append({"step": feature, "status": state})
        if not response.ok and not rejected:
            # Auth/rate/transport failures are not capability rejections; stop.
            break
    return {"ok": True, "steps": stages, "profile": capability_snapshot(runtime, resolver)}
