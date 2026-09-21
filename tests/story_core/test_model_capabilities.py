import io
import json
import urllib.error

from packages.story_core.model_gateway import (
    CapabilityObservation,
    CapabilityProvenance,
    CapabilityRecord,
    ModelCapabilityResolver,
    ModelCapabilityStore,
    ModelIdentity,
    ModelProfile,
    ModelRequest,
    RuntimeModelGateway,
    effective_streaming,
    preflight_context,
)
from packages.story_core.runtime_config import StageRuntimeSettings, load_runtime_configuration


def _identity(
    resolver: ModelCapabilityResolver,
    *,
    provider: str = "custom_openai",
    base_url: str = "https://one.example/v1",
    model: str = "k3",
    resolved_model: str | None = None,
) -> ModelIdentity:
    return resolver.identity(
        provider,
        base_url,
        model,
        "openai_compatible",
        resolved_model=resolved_model,
    )


def test_same_model_on_different_base_urls_has_different_identity_and_profile(tmp_path):
    resolver = ModelCapabilityResolver(store=ModelCapabilityStore(tmp_path / "capabilities.json"))

    first = resolver.resolve_model_profile(
        "custom_openai", "https://one.example/v1/", "k3", "openai_compatible"
    )
    second = resolver.resolve_model_profile(
        "custom_openai", "https://two.example/v1", "k3", "openai_compatible"
    )

    assert first.identity.normalized_base_url == "https://one.example/v1"
    assert second.identity.normalized_base_url == "https://two.example/v1"
    assert first.identity.cache_key != second.identity.cache_key
    assert first.identity != second.identity


def test_capability_states_and_profile_round_trip():
    profile = ModelProfile(
        identity=ModelIdentity(
            "provider",
            "openai_compatible",
            "https://model.example/v1",
            "model",
        ),
        effective_capabilities={
            "streaming": CapabilityRecord(
                "supported",
                provenance=CapabilityProvenance.for_source(
                    "provider_metadata", now="2026-09-21T00:00:00+00:00"
                ),
            ),
            "temperature": CapabilityRecord(
                "unsupported",
                provenance=CapabilityProvenance.for_source(
                    "runtime_observation", now="2026-09-21T00:00:00+00:00"
                ),
            ),
            "thinking": CapabilityRecord("unknown"),
        },
    )

    restored = ModelProfile.from_dict(profile.to_dict())

    assert restored.identity == profile.identity
    assert restored.effective_capabilities["streaming"].state == "supported"
    assert restored.effective_capabilities["temperature"].state == "unsupported"
    assert restored.effective_capabilities["thinking"].state == "unknown"
    assert restored.effective_capabilities["temperature"].provenance.source == "runtime_observation"


def test_runtime_observation_beats_provider_catalog_and_user_declaration(tmp_path):
    store = ModelCapabilityStore(tmp_path / "capabilities.json")
    resolver = ModelCapabilityResolver(
        store=store,
        catalog={
            ("custom_openai", "openai_compatible", "k3"): {
                "temperature": "supported"
            }
        },
        clock=lambda: "2026-09-21T00:00:00+00:00",
    )
    identity = _identity(resolver)
    resolver.record_runtime_observation(
        CapabilityObservation(identity=identity, capability="temperature", state="unsupported")
    )

    profile = resolver.resolve_model_profile(
        "custom_openai",
        "https://one.example/v1",
        "k3",
        "openai_compatible",
        user_declared={"temperature": "supported"},
    )

    temperature = profile.effective_capability("temperature")
    assert temperature.state == "unsupported"
    assert temperature.provenance.source == "runtime_observation"

    provider_metadata_profile = resolver.resolve_model_profile(
        "custom_openai",
        "https://two.example/v1",
        "k3",
        "openai_compatible",
        provider_metadata={"temperature": "unsupported"},
        user_declared={"temperature": "supported"},
    )
    provider_temperature = provider_metadata_profile.effective_capability("temperature")
    assert provider_temperature.state == "unsupported"
    assert provider_temperature.provenance.source == "provider_metadata"


def test_temperature_rejection_records_runtime_observation_after_successful_fallback(tmp_path):
    store = ModelCapabilityStore(tmp_path / "capabilities.json")
    resolver = ModelCapabilityResolver(store=store)

    class Transport:
        def __init__(self):
            self.payloads = []

        def __call__(self, *, url, payload, headers, config):
            self.payloads.append(dict(payload))
            if len(self.payloads) == 1:
                raise urllib.error.HTTPError(
                    url,
                    400,
                    "Bad Request",
                    {},
                    io.BytesIO(
                        json.dumps(
                            {"error": {"message": "temperature not supported"}}
                        ).encode()
                    ),
                )
            return {
                "model": "k3-runtime",
                "choices": [{"message": {"content": "ok"}}],
            }

    from packages.story_core.model_gateway.provider_adapters import OpenAICompatibleAdapter

    transport = Transport()
    response = OpenAICompatibleAdapter(
        base_url="https://one.example/v1",
        api_key="secret-key",
        transport=transport,
        capability_observer=resolver.record_runtime_observation,
    ).complete(
        ModelRequest(
            prompt="write",
            provider="custom_openai",
            model="k3",
            operation="writer",
            temperature=0.4,
        )
    )

    assert response.ok is True
    assert response.temperature_omitted is True
    assert response.resolved_model == "k3-runtime"
    assert len(transport.payloads) == 2
    assert "temperature" not in transport.payloads[1]
    profile = resolver.resolve_model_profile(
        "custom_openai", "https://one.example/v1", "k3", "openai_compatible"
    )
    assert profile.effective_capability("temperature").state == "unsupported"
    assert profile.effective_capability("temperature").provenance.source == "runtime_observation"


def test_successful_response_resolved_snapshot_change_invalidates_alias_observation(tmp_path):
    store = ModelCapabilityStore(tmp_path / "capabilities.json")
    resolver = ModelCapabilityResolver(store=store)
    identity_a = _identity(resolver, resolved_model="backend-a")
    store.record_runtime_observation(
        identity_a,
        "temperature",
        CapabilityRecord(
            "unsupported",
            provenance=CapabilityProvenance.for_source(
                "runtime_observation", now="2026-09-21T00:00:00+00:00"
            ),
        ),
    )

    before = resolver.resolve_model_profile(
        "custom_openai", "https://one.example/v1", "k3", "openai_compatible"
    )
    assert before.effective_capability("temperature").state == "unsupported"

    settings = StageRuntimeSettings(
        provider_id="custom_openai",
        protocol="openai_compatible",
        model="k3",
        api_key="secret-key",
        base_url="https://one.example/v1",
    )
    calls = []

    def transport(*, url, payload, headers, config):
        calls.append(payload)
        return {
            "model": "backend-b",
            "choices": [{"message": {"content": "ok"}}],
        }

    response = RuntimeModelGateway(
        runtime_resolver=lambda _stage: settings,
        transport=transport,
        capability_resolver=resolver,
    ).complete_stage(
        "writer",
        ModelRequest(
            prompt="write",
            provider="ignored",
            model="ignored",
            operation="writer",
            temperature=0.4,
        ),
    )

    assert response.ok is True
    assert response.resolved_model == "backend-b"
    # The first request after an unknown alias switch may still use the old
    # evidence. It must not poison the next resolution after backend-b is seen.
    assert "temperature" not in calls[0]
    after = resolver.resolve_model_profile(
        "custom_openai", "https://one.example/v1", "k3", "openai_compatible"
    )
    assert after.effective_capability("temperature").state == "unknown"
    assert (
        store.get_profile(identity_a)
        .verified_capabilities["temperature"]
        .state
        == "unsupported"
    )


def test_streaming_response_resolved_snapshot_change_invalidates_alias_observation(
    tmp_path, monkeypatch
):
    store = ModelCapabilityStore(tmp_path / "capabilities.json")
    resolver = ModelCapabilityResolver(store=store)
    identity_a = _identity(resolver, resolved_model="backend-a")
    store.record_runtime_observation(
        identity_a,
        "temperature",
        CapabilityRecord(
            "unsupported",
            provenance=CapabilityProvenance.for_source(
                "runtime_observation", now="2026-09-21T00:00:00+00:00"
            ),
        ),
    )

    class StreamingResponse:
        def __iter__(self):
            return iter(
                [
                    b'data: {"id":"req-1","model":"backend-b","choices":[{"delta":{"content":"a"}}]}\n',
                    b'data: {"choices":[{"delta":{"content":"b"}}]}\n',
                    b"data: [DONE]\n",
                ]
            )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda request, timeout: StreamingResponse(),
    )
    settings = StageRuntimeSettings(
        provider_id="custom_openai",
        protocol="openai_compatible",
        model="k3",
        api_key="secret-key",
        base_url="https://one.example/v1",
    )

    response = RuntimeModelGateway(
        runtime_resolver=lambda _stage: settings,
        capability_resolver=resolver,
    ).complete_stage(
        "writer",
        ModelRequest(
            prompt="write",
            provider="ignored",
            model="ignored",
            operation="writer",
            temperature=0.4,
            metadata={"stream": True},
        ),
    )

    assert response.ok is True
    assert response.text == "ab"
    assert response.resolved_model == "backend-b"
    after = resolver.resolve_model_profile(
        "custom_openai", "https://one.example/v1", "k3", "openai_compatible"
    )
    assert after.effective_capability("temperature").state == "unknown"
    assert (
        store.get_profile(identity_a)
        .verified_capabilities["temperature"]
        .state
        == "unsupported"
    )


def _gateway_with_observed_streaming(tmp_path, state: str):
    store = ModelCapabilityStore(tmp_path / f"{state}.json")
    resolver = ModelCapabilityResolver(store=store)
    identity = _identity(resolver)
    resolver.record_runtime_observation(
        CapabilityObservation(identity=identity, capability="streaming", state=state)
    )
    settings = StageRuntimeSettings(
        provider_id="custom_openai",
        protocol="openai_compatible",
        model="k3",
        api_key="secret-key",
        base_url="https://one.example/v1",
    )
    calls = []

    def transport(*, url, payload, headers, config):
        calls.append(payload)
        return {"choices": [{"message": {"content": "ok"}}]}

    gateway = RuntimeModelGateway(
        runtime_resolver=lambda _stage: settings,
        transport=transport,
        capability_resolver=resolver,
    )
    response = gateway.complete_stage(
        "writer",
        ModelRequest(
            prompt="write",
            provider="ignored",
            model="ignored",
            operation="writer",
            temperature=0.4,
            metadata={"stream": True},
        ),
    )
    return response, calls


def test_stream_requested_with_unsupported_capability_downgrades_to_complete(tmp_path):
    response, calls = _gateway_with_observed_streaming(tmp_path, "unsupported")

    assert response.ok is True
    assert "stream" not in calls[0]
    assert effective_streaming(True, "unsupported") is False


def test_stream_requested_with_supported_capability_remains_streaming(tmp_path):
    response, calls = _gateway_with_observed_streaming(tmp_path, "supported")

    assert response.ok is True
    assert calls[0]["stream"] is True
    assert effective_streaming(True, "supported") is True


def test_stream_requested_with_unknown_capability_preserves_existing_request(tmp_path):
    response, calls = _gateway_with_observed_streaming(tmp_path, "unknown")

    assert response.ok is True
    assert calls[0]["stream"] is True
    # The general runtime wiring preserves compatibility while discovery is
    # absent; the standalone decision primitive remains conservative.
    assert effective_streaming(True, "unknown") is False


def test_unknown_context_limit_is_not_reported_as_ready():
    result = preflight_context(
        estimated_required_input=1000,
        estimated_optional_input=1000,
        reserved_output=500,
        safety_margin=100,
        model_effective_limit=None,
    )

    assert result.status == "COMPACT"
    assert result.safe is False
    assert result.context_limit is None
    assert "unknown" in result.reason


def test_known_safe_context_is_ready():
    result = preflight_context(
        estimated_required_input=1000,
        estimated_optional_input=1000,
        reserved_output=500,
        safety_margin=100,
        model_effective_limit=3000,
    )

    assert result.status == "READY"
    assert result.safe is True


def test_known_over_budget_context_is_compacted_or_split_before_blocking():
    compact = preflight_context(
        estimated_required_input=1000,
        estimated_optional_input=1000,
        reserved_output=500,
        safety_margin=100,
        model_effective_limit=1700,
    )
    split = preflight_context(
        estimated_required_input=1000,
        estimated_optional_input=0,
        reserved_output=500,
        safety_margin=300,
        model_effective_limit=1600,
    )
    blocked = preflight_context(
        estimated_required_input=1000,
        estimated_optional_input=0,
        reserved_output=500,
        safety_margin=100,
        model_effective_limit=1400,
    )

    assert compact.status == "COMPACT"
    assert split.status == "SPLIT"
    assert blocked.status == "BLOCKED"


def test_provider_base_url_model_and_resolved_snapshot_changes_do_not_reuse_cache(tmp_path):
    store = ModelCapabilityStore(tmp_path / "capabilities.json")
    resolver = ModelCapabilityResolver(store=store)
    original = _identity(resolver, resolved_model="backend-a")
    store.record_runtime_observation(
        original,
        "temperature",
        CapabilityRecord(
            "unsupported",
            provenance=CapabilityProvenance.for_source(
                "runtime_observation", now="2026-09-21T00:00:00+00:00"
            ),
        ),
    )

    assert store.get_profile(original) is not None
    assert store.get_profile(original.with_resolved_model("backend-b")) is None
    assert store.get_profile(_identity(resolver, provider="other-provider", resolved_model="backend-a")) is None
    assert store.get_profile(_identity(resolver, base_url="https://two.example/v1", resolved_model="backend-a")) is None
    assert store.get_profile(_identity(resolver, model="k4", resolved_model="backend-a")) is None


def test_legacy_runtime_config_v2_loads_without_capability_schema_changes(tmp_path):
    path = tmp_path / "runtime-config.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "runtime-config/v2",
                "accounts": {
                    "codexcli": {
                        "api_key": "",
                        "base_url": "",
                        "custom_models": [],
                        "codex_command": "codex",
                    }
                },
                "stages": {
                    "planner": {"provider_id": "codexcli", "model": "gpt-5-codex"},
                    "writer": {"provider_id": "codexcli", "model": "gpt-5-codex"},
                },
                "temperature": 0.7,
            }
        ),
        encoding="utf-8",
    )

    loaded = load_runtime_configuration(path)

    assert loaded.schema_version == "runtime-config/v2"
    assert loaded.stages.planner.model == "gpt-5-codex"
    assert loaded.stages.writer.provider_id == "codexcli"


def test_capability_cache_does_not_persist_secret_url_query_or_authorization(tmp_path):
    path = tmp_path / "capabilities.json"
    store = ModelCapabilityStore(path)
    identity = ModelIdentity(
        "custom_openai",
        "openai_compatible",
        "https://model.example/v1?api_key=super-secret&token=another-secret",
        "k3",
    )
    store.record_runtime_observation(
        identity,
        "temperature",
        CapabilityRecord(
            "unsupported",
            provenance=CapabilityProvenance.for_source(
                "runtime_observation", now="2026-09-21T00:00:00+00:00"
            ),
        ),
    )

    persisted = path.read_text(encoding="utf-8")
    assert identity.normalized_base_url == "https://model.example/v1"
    assert "super-secret" not in persisted
    assert "another-secret" not in persisted
    assert "Authorization" not in persisted
    assert "api_key" not in persisted
