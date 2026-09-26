import io
import json
import urllib.error

import pytest

from packages.story_core.model_gateway.capabilities import (
    CapabilityObservation, CapabilityProvenance, CapabilityRecord,
    ModelCapabilityResolver, ModelCapabilityStore,
)
from packages.story_core.model_gateway.capability_refresh import capability_snapshot, refresh_capabilities
from packages.story_core.model_gateway.contracts import ModelRequest
from packages.story_core.model_gateway.runtime_gateway import RuntimeModelGateway
from packages.story_core.runtime_config import StageRuntimeSettings


@pytest.fixture
def resolver(tmp_path):
    return ModelCapabilityResolver(store=ModelCapabilityStore(tmp_path / "cache.json"), catalog={})


@pytest.fixture
def runtime():
    return StageRuntimeSettings(provider_id="custom_openai", protocol="openai_compatible", model="fake-model", base_url="https://fake.invalid/private-secret?token=url-secret", api_key="TEST_KEY")


def success(**kwargs):
    return {"model": "backend", "choices": [{"message": {"content": '{"ok":true}'}}], "capability_probe_sse": kwargs["payload"].get("stream", False)}


def test_refresh_orders_small_probes_and_persists_expiring_runtime_evidence(runtime, resolver):
    calls = []
    def send(**kwargs):
        calls.append(kwargs)
        assert kwargs["payload"]["max_tokens"] == 64
        assert kwargs["config"].max_retries == 1
        assert kwargs["config"].timeout == 10
        assert kwargs["config"].max_response_bytes == 16384
        assert kwargs["config"].allow_compatibility_fallback is False
        assert kwargs["headers"]["Authorization"] == "Bearer TEST_KEY"
        return success(**kwargs)
    def discover(settings):
        assert len(calls) == 1
        assert settings is runtime
        return [{"model_id": runtime.model}]
    result = refresh_capabilities(runtime, resolver=resolver, transport=send, discovery=discover)
    assert result["ok"]
    assert len(calls) == 4
    assert [step["step"] for step in result["steps"]] == ["connectivity", "discovery", "temperature", "json_mode", "streaming"]
    for name in ("streaming", "temperature", "json_mode"):
        record = result["profile"]["records"][name]
        assert record["state"] == "supported"
        assert record["source"] == "runtime_observation"
        assert record["verified_at"] and record["expires_at"]
    assert result["profile"]["records"]["context_window"]["state"] == "unknown"
    assert result["profile"]["records"]["reasoning_effort"]["state"] == "unknown"
    serialized = json.dumps(result)
    for secret in (runtime.api_key, "url-secret", "private-secret", "Authorization"):
        assert secret not in serialized
    assert capability_snapshot(runtime, resolver)["records"]["json_mode"]["state"] == "supported"


def test_rejection_wins_over_declaration_and_runtime_falls_back_to_complete(runtime, resolver):
    runtime.user_declared_capabilities = {"streaming": "supported"}
    def send(**kwargs):
        if kwargs["payload"].get("stream"):
            raise urllib.error.HTTPError("https://fake.invalid", 400, "bad", {}, io.BytesIO(b'{"error":{"message":"stream is not supported"}}'))
        return success(**kwargs)
    result = refresh_capabilities(runtime, resolver=resolver, transport=send, discovery=lambda _: [])
    assert result["profile"]["records"]["streaming"]["state"] == "unsupported"
    sent = []
    gateway = RuntimeModelGateway(capability_resolver=resolver, transport=lambda **kw: (sent.append(kw["payload"]) or success(**kw)))
    response = gateway.complete_resolved(runtime, ModelRequest(prompt="short", provider="wrong", model="wrong", operation="test", max_tokens=64, metadata={"stream": True}))
    assert response.ok
    assert not sent[0].get("stream")
    assert sent[0]["model"] == "fake-model"


@pytest.mark.parametrize("status,message", [(401, "temperature not supported"), (429, "temperature not supported"), (400, "invalid request")])
def test_failure_is_not_unsupported_and_stops_without_retry(runtime, resolver, status, message):
    count = 0
    def send(**kwargs):
        nonlocal count
        count += 1
        if count > 1:
            raise urllib.error.HTTPError("https://fake.invalid", status, "bad", {}, io.BytesIO(json.dumps({"error": {"message": message}}).encode()))
        return success(**kwargs)
    result = refresh_capabilities(runtime, resolver=resolver, transport=send, discovery=lambda _: [])
    assert count == 2
    assert result["profile"]["records"]["temperature"]["state"] == "unknown"


def test_failed_connectivity_does_not_discover_or_probe(runtime, resolver):
    def fail(**kwargs):
        raise TimeoutError("TEST_KEY private-secret")
    result = refresh_capabilities(runtime, resolver=resolver, transport=fail, discovery=lambda _: pytest.fail("discovery after failure"))
    assert not result["ok"]
    assert len(result["steps"]) == 1
    assert "TEST_KEY" not in json.dumps(result)


def test_cli_skips_unbounded_probe(runtime, resolver):
    runtime.protocol = "codex_cli"
    runtime.provider_id = "codexcli"
    result = refresh_capabilities(runtime, resolver=resolver, transport=lambda **_: pytest.fail("CLI remote probe"), discovery=lambda _: pytest.fail("CLI discovery"))
    assert result["profile"]["output_budget"] == "best_effort"
    assert result["steps"][0]["reason"] == "cli_budget_best_effort"


def test_invalid_json_and_missing_sse_evidence_remain_unknown(runtime, resolver):
    def send(**kwargs):
        return {"choices": [{"message": {"content": "plain text"}}]}
    result = refresh_capabilities(runtime, resolver=resolver, transport=send, discovery=lambda _: [])
    assert result["profile"]["records"]["json_mode"]["state"] == "unknown"
    assert result["profile"]["records"]["streaming"]["state"] == "unknown"


def test_expiry_endpoint_isolation_and_invalidation(runtime, resolver):
    identity = resolver.identity(runtime.provider_id, runtime.base_url, runtime.model, runtime.protocol)
    resolver.store.record_runtime_observation(identity, "streaming", CapabilityRecord("supported", provenance=CapabilityProvenance.for_source("runtime_observation", expires_at="2000-01-01T00:00:00Z")))
    record = capability_snapshot(runtime, resolver)["records"]["streaming"]
    assert record["state"] == "unknown" and record["expires_at"]
    assert record["verification_status"] == "unknown"
    resolver.record_runtime_observation(CapabilityObservation(identity, "temperature", "unsupported"))
    other = runtime.model_copy(update={"base_url": "https://other.invalid/v1"})
    assert capability_snapshot(other, resolver)["records"]["temperature"]["state"] == "unknown"
    resolver.store.invalidate_identity(identity)
    assert capability_snapshot(runtime, resolver)["records"]["temperature"]["state"] == "unknown"


def test_discovery_failure_does_not_fabricate_capabilities(runtime, resolver):
    def discovery(_):
        raise ValueError("TEST_KEY")
    result = refresh_capabilities(runtime, resolver=resolver, transport=success, discovery=discovery)
    assert result["steps"][1]["status"] == "failed"
    assert result["profile"]["records"]["context_window"]["state"] == "unknown"
    assert "TEST_KEY" not in json.dumps(result)


@pytest.mark.parametrize("protocol,provider,expected_calls", [("anthropic", "anthropic", 2), ("gemini", "gemini", 3)])
def test_native_adapters_probe_only_parameters_they_send(runtime, resolver, protocol, provider, expected_calls):
    runtime.protocol, runtime.provider_id = protocol, provider
    calls = []
    def send(**kwargs):
        calls.append(kwargs["payload"])
        if protocol == "anthropic":
            assert kwargs["payload"]["max_tokens"] == 64
            return {"content": [{"text": '{"ok":true}'}]}
        assert kwargs["payload"]["generationConfig"]["maxOutputTokens"] == 64
        return {"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}]}
    result = refresh_capabilities(runtime, resolver=resolver, transport=send, discovery=lambda _: [])
    assert len(calls) == expected_calls
    assert result["profile"]["records"]["temperature"]["state"] == "supported"
    assert result["profile"]["records"]["streaming"]["state"] == "unknown"
    if protocol == "anthropic":
        assert result["profile"]["records"]["json_mode"]["state"] == "unknown"


def test_user_provenance_cannot_claim_runtime_verification(runtime, resolver):
    runtime.user_declared_capabilities = {"streaming": {
        "state": "supported", "provenance": {"source": "runtime_observation", "verification_status": "verified"},
    }}
    record = capability_snapshot(runtime, resolver)["records"]["streaming"]
    assert record["source"] == "user_declared"
    assert record["verification_status"] == "declared"
