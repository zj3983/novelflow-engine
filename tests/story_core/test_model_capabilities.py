import io
import json
import urllib.error

import pytest

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
    normalize_base_url,
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


@pytest.mark.parametrize(
    "base_url",
    [
        "https://demo:TEST_SECRET@example.invalid:bad/v1?token=QUERY_SECRET",
        "https://demo:TEST_SECRET@example.invalid:99999/v1?token=QUERY_SECRET",
        "https://demo:TEST_SECRET@[broken.example/v1?token=QUERY_SECRET",
    ],
)
def test_malformed_base_url_identity_never_keeps_credentials_or_query(base_url):
    normalized = normalize_base_url(base_url)

    assert "TEST_SECRET" not in normalized
    assert "demo:" not in normalized
    assert "QUERY_SECRET" not in normalized
    assert "token=" not in normalized
    assert normalized


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


def _preflight_settings(capabilities=None, *, model="alias-model", base_url="https://one.example/v1"):
    return StageRuntimeSettings(
        provider_id="custom_openai",
        protocol="openai_compatible",
        model=model,
        api_key="test-secret",
        base_url=base_url,
        temperature=0.7,
        user_declared_capabilities=dict(capabilities or {}),
    )


def test_gateway_preflights_the_actual_request_once_with_one_runtime_snapshot(tmp_path):
    settings = _preflight_settings({"limits": {
        "input_token_limit": 16_000,
        "context_window": 20_000,
        "max_output_tokens": 2_000,
    }})
    resolved_stages = []
    sent = []

    def transport(**call):
        sent.append(call)
        return {
            "choices": [{"message": {"content": "ok"}}],
            "model": "backend-model-v1",
        }

    gateway = RuntimeModelGateway(
        runtime_resolver=lambda stage: resolved_stages.append(stage) or settings,
        capability_resolver=ModelCapabilityResolver(
            store=ModelCapabilityStore(tmp_path / "capabilities.json")
        ),
        transport=transport,
    )
    response = gateway.complete_stage(
        "planner",
        ModelRequest(
            prompt="必要任务契约",
            provider="ignored-provider",
            model="ignored-model",
            operation="preflight-snapshot",
            max_tokens=512,
        ),
    )

    assert response.ok
    assert resolved_stages == ["planner"]
    assert sent[0]["payload"]["model"] == "alias-model"
    assert response.preflight_report["status"] == "READY"
    assert response.preflight_report["recheck_status"] is None
    assert response.preflight_report["provider"] == "custom_openai"
    assert response.preflight_report["requested_model"] == "alias-model"
    assert response.preflight_report["resolved_model"] == "backend-model-v1"
    assert response.preflight_report["resolved_model_changed"] is True
    assert response.preflight_report["estimate_method"] == "utf8_bytes_div3_v1"
    assert response.preflight_report["estimate_is_exact_tokenization"] is False
    assert sent[0]["payload"]["max_tokens"] == 512
    assert response.preflight_report["limits"]["context_window"]["source"] == "user_declared"


def test_known_unsupported_structured_output_blocks_before_provider_call(tmp_path):
    sent = []
    settings = _preflight_settings({
        "capabilities": {"json_mode": "unsupported"},
        "limits": {
            "input_token_limit": 16_000,
            "context_window": 20_000,
            "max_output_tokens": 2_000,
        },
    })
    gateway = RuntimeModelGateway(
        runtime_resolver=lambda _stage: settings,
        capability_resolver=ModelCapabilityResolver(
            store=ModelCapabilityStore(tmp_path / "capabilities.json")
        ),
        transport=lambda **call: sent.append(call) or {},
    )

    response = gateway.complete_stage(
        "planner",
        ModelRequest(
            prompt="只输出完整结构化结果",
            provider="",
            model="",
            operation="required-json",
            max_tokens=512,
            json_mode=True,
        ),
    )

    assert not response.ok
    assert response.error == "model_preflight_blocked"
    assert response.preflight_report["status"] == "BLOCKED"
    assert response.preflight_report["reason"] == "required_capability_unsupported"
    assert response.preflight_report["capabilities"]["json_mode"]["source"] == "user_declared"
    assert sent == []


def test_optional_messages_compact_and_recheck_without_removing_required_contract(tmp_path):
    sent = []
    settings = _preflight_settings({"limits": {
        "input_token_limit": 1_000,
        "context_window": 1_000,
        "max_output_tokens": 256,
    }})

    def transport(**call):
        sent.append(call)
        return {"choices": [{"message": {"content": "ok"}}], "model": "actual"}

    gateway = RuntimeModelGateway(
        runtime_resolver=lambda _stage: settings,
        capability_resolver=ModelCapabilityResolver(
            store=ModelCapabilityStore(tmp_path / "capabilities.json")
        ),
        transport=transport,
    )
    response = gateway.complete_stage(
        "planner",
        ModelRequest(
            prompt="该字段不会与 messages 重复发送",
            provider="",
            model="",
            operation="optional-compaction",
            system_prompt="must_not_write 是硬约束，必须保留。",
            messages=(
                {"role": "user", "content": "必要事实和完整执行契约"},
                {"role": "user", "content": "OPTIONAL_CONTEXT_SECRET " + "x" * 6_000},
            ),
            max_tokens=128,
            optional_input_messages=(1,),
        ),
    )

    assert response.ok
    actual_messages = sent[0]["payload"]["messages"]
    assert "must_not_write" in actual_messages[0]["content"]
    assert "必要事实和完整执行契约" in actual_messages[1]["content"]
    assert all("OPTIONAL_CONTEXT_SECRET" not in item["content"] for item in actual_messages)
    assert response.preflight_report["status"] == "COMPACT"
    assert response.preflight_report["recheck_status"] == "READY"
    assert response.preflight_report["compacted_optional_message_indexes"] == [1]
    assert response.preflight_report["estimates"]["optional_input_tokens"] == 0
    assert "该字段不会与 messages 重复发送" not in str(response.preflight_report)


def test_large_optional_message_recomputes_required_only_safety_margin(tmp_path):
    sent = []
    settings = _preflight_settings(
        {
            "limits": {
                "input_token_limit": 1_000,
                "context_window": 1_000,
                "max_output_tokens": 256,
            }
        }
    )
    gateway = RuntimeModelGateway(
        runtime_resolver=lambda _stage: settings,
        capability_resolver=ModelCapabilityResolver(
            store=ModelCapabilityStore(tmp_path / "capabilities.json")
        ),
        transport=lambda **call: sent.append(call)
        or {"choices": [{"message": {"content": "ok"}}]},
    )

    response = gateway.complete_stage(
        "planner",
        ModelRequest(
            prompt="unused legacy prompt",
            provider="",
            model="",
            operation="large-optional-compaction",
            messages=(
                {"role": "user", "content": "required contract and facts"},
                {"role": "user", "content": "x" * 30_000},
            ),
            max_tokens=128,
            optional_input_messages=(1,),
        ),
    )

    assert response.ok
    assert response.preflight_report["status"] == "COMPACT"
    assert response.preflight_report["recheck_status"] == "READY"
    assert response.preflight_report["estimates"]["safety_margin_tokens"] == 128
    assert response.preflight_report["estimates"]["optional_input_tokens"] == 0
    assert len(sent) == 1
    actual_messages = sent[0]["payload"]["messages"]
    assert len(actual_messages) == 1
    assert "required contract and facts" in actual_messages[0]["content"]
    assert all("x" * 100 not in item["content"] for item in actual_messages)


def test_unsupported_required_capability_does_not_trigger_optional_compaction(tmp_path):
    sent = []
    settings = _preflight_settings(
        {
            "capabilities": {"json_mode": "unsupported"},
            "limits": {
                "input_token_limit": 1_000,
                "context_window": 1_000,
                "max_output_tokens": 256,
            },
        }
    )
    gateway = RuntimeModelGateway(
        runtime_resolver=lambda _stage: settings,
        capability_resolver=ModelCapabilityResolver(
            store=ModelCapabilityStore(tmp_path / "capabilities.json")
        ),
        transport=lambda **call: sent.append(call) or {},
    )

    response = gateway.complete_stage(
        "planner",
        ModelRequest(
            prompt="unused legacy prompt",
            provider="",
            model="",
            operation="unsupported-with-optional-context",
            messages=(
                {"role": "user", "content": "required"},
                {"role": "user", "content": "x" * 30_000},
            ),
            max_tokens=128,
            json_mode=True,
            optional_input_messages=(1,),
        ),
    )

    assert not response.ok
    assert response.preflight_report["reason"] == "required_capability_unsupported"
    assert response.preflight_report["compacted_optional_message_indexes"] == []
    assert sent == []


@pytest.mark.parametrize(
    "base_url",
    [
        "https://demo:TEST_SECRET@example.invalid:bad/v1?token=QUERY_SECRET",
        "https://demo:TEST_SECRET@example.invalid:99999/v1?token=QUERY_SECRET",
        "https://demo:TEST_SECRET@[broken.example/v1?token=QUERY_SECRET",
    ],
)
def test_malformed_endpoint_is_safe_in_preview_execution_and_prompt_log(
    tmp_path, monkeypatch, base_url
):
    from packages.story_core.agents import _runtime_common
    from packages.story_core.agents._runtime_common import call_with_logging
    from packages.story_core.prompt_call_log import PromptCallLog, prompt_call_recording

    settings = _preflight_settings({}, base_url=base_url)
    settings.api_key = "AUTHORIZATION_SECRET"
    transport_calls = []

    def failing_transport(**call):
        transport_calls.append(call)
        raise ValueError("synthetic transport failure")

    gateway = RuntimeModelGateway(
        runtime_resolver=lambda _stage: settings,
        capability_resolver=ModelCapabilityResolver(
            store=ModelCapabilityStore(tmp_path / "capabilities.json")
        ),
        transport=failing_transport,
    )
    request = ModelRequest(
        prompt="short safe test prompt",
        provider="",
        model="",
        operation="malformed-endpoint-test",
        max_tokens=128,
    )

    preview = gateway.preflight_stage("planner", request)
    response = gateway.complete_stage("planner", request)
    log = PromptCallLog(tmp_path / "logs", project_id="file:malformed-endpoint")
    monkeypatch.setattr(
        _runtime_common, "_resolve_stage_settings", lambda _stage: settings
    )
    with prompt_call_recording(log):
        logged_response, *_ = call_with_logging(
            gateway=gateway, stage="planner", request=request
        )

    serialized = json.dumps(
        {
            "preview": preview.report,
            "response": response.__dict__,
            "logged_response": logged_response.__dict__,
            "prompt_log": log.get(log.list()[0]["call_id"]),
        },
        ensure_ascii=False,
        default=str,
    )
    for secret in ("demo:", "TEST_SECRET", "QUERY_SECRET", "AUTHORIZATION_SECRET", "Authorization"):
        assert secret not in serialized
    assert not response.ok
    assert not logged_response.ok
    assert transport_calls == []


def test_cli_output_limit_enforcement_is_reported_by_shared_preflight(tmp_path):
    from packages.story_core.runtime_config import StageRuntimeSettings

    codex = StageRuntimeSettings(
        provider_id="codexcli",
        protocol="codex_cli",
        model="gpt-5-codex",
        codex_command="codex",
    )
    antigravity = StageRuntimeSettings(
        provider_id="antigravity",
        protocol="antigravity_cli",
        model="gemini-3.1-pro-high",
        codex_command="agy",
    )
    resolver = ModelCapabilityResolver(
        store=ModelCapabilityStore(tmp_path / "capabilities.json")
    )

    codex_plan = RuntimeModelGateway(
        runtime_resolver=lambda _stage: codex,
        capability_resolver=resolver,
    ).preflight_stage(
        "planner",
        ModelRequest(prompt="bounded request", provider="", model="", operation="cli-test"),
    )
    antigravity_plan = RuntimeModelGateway(
        runtime_resolver=lambda _stage: antigravity,
        capability_resolver=resolver,
    ).preflight_stage(
        "planner",
        ModelRequest(prompt="bounded request", provider="", model="", operation="cli-test"),
    )

    assert codex_plan.report["status"] == "READY"
    assert codex_plan.report["reason"] == "within_context_limit"
    assert codex_plan.report["output_enforcement"]["state"] == "unsupported"
    assert codex_plan.report["output_budget"]["mode"] == "estimate_only"
    assert codex_plan.report["output_budget"]["enforced"] is False
    assert codex_plan.report["output_budget"]["estimated_tokens"] > 0
    assert antigravity_plan.report["status"] == "READY"
    assert antigravity_plan.report["reason"] == "within_context_limit"
    assert antigravity_plan.report["output_enforcement"]["state"] == "unsupported"
    assert antigravity_plan.report["output_budget"]["mode"] == "estimate_only"


@pytest.mark.parametrize(
    ("provider_id", "protocol", "model", "command", "provider_module"),
    [
        ("codexcli", "codex_cli", "gpt-5-codex", "codex-test", "codex_cli_provider"),
        ("antigravity", "antigravity_cli", "gemini-3.1-pro-high", "agy-test", "antigravity_cli_provider"),
    ],
)
def test_cli_gateway_executes_estimate_only_requests_without_sending_output_cap(
    tmp_path, monkeypatch, provider_id, protocol, model, command, provider_module
):
    from packages.story_core import codex_cli_provider, antigravity_cli_provider
    from packages.story_core.runtime_config import RuntimeConfiguration

    settings = StageRuntimeSettings(
        provider_id=provider_id,
        protocol=protocol,
        model=model,
        codex_command=command,
    )
    calls = []

    def fake_cli(payload, *, command, config):
        calls.append({"payload": payload, "command": command, "config": config})
        return {"choices": [{"message": {"content": "cli-result"}}], "model": model}

    module = codex_cli_provider if provider_module == "codex_cli_provider" else antigravity_cli_provider
    function_name = (
        "post_json_via_codex_cli"
        if provider_module == "codex_cli_provider"
        else "post_json_via_antigravity_cli"
    )
    monkeypatch.setattr(module, function_name, fake_cli)
    default_config = RuntimeConfiguration()
    assert default_config.stages.planner.provider_id == "codexcli"
    assert default_config.stages.writer.provider_id == "codexcli"

    gateway = RuntimeModelGateway(
        runtime_resolver=lambda _stage: settings,
        capability_resolver=ModelCapabilityResolver(
            store=ModelCapabilityStore(tmp_path / f"{provider_id}-capabilities.json")
        ),
    )
    response = gateway.complete_stage(
        "writer",
        ModelRequest(
            prompt="short request",
            provider="",
            model="",
            operation="writer",
            max_tokens=None,
        ),
    )

    assert response.ok
    assert calls[0]["command"] == command
    assert "max_tokens" not in calls[0]["payload"]
    assert response.preflight_report["status"] == "READY"
    assert response.preflight_report["output_enforcement"]["state"] == "unsupported"
    assert response.preflight_report["output_budget"]["mode"] == "estimate_only"
    assert response.preflight_report["output_budget"]["enforced"] is False
    assert response.preflight_report["output_budget"]["estimated_tokens"] > 0


@pytest.mark.parametrize(
    ("provider_id", "protocol", "model"),
    [
        ("codexcli", "codex_cli", "gpt-5-codex"),
        ("antigravity", "antigravity_cli", "gemini-3.1-pro-high"),
    ],
)
def test_cli_gateway_blocks_explicit_hard_output_limit_before_adapter(
    tmp_path, monkeypatch, provider_id, protocol, model
):
    settings = StageRuntimeSettings(
        provider_id=provider_id,
        protocol=protocol,
        model=model,
        codex_command="injected-cli",
    )
    calls = []
    monkeypatch.setattr(
        "packages.story_core.codex_cli_provider.post_json_via_codex_cli",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "packages.story_core.antigravity_cli_provider.post_json_via_antigravity_cli",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    gateway = RuntimeModelGateway(
        runtime_resolver=lambda _stage: settings,
        capability_resolver=ModelCapabilityResolver(
            store=ModelCapabilityStore(tmp_path / f"{provider_id}-capabilities.json")
        ),
    )

    response = gateway.complete_stage(
        "writer",
        ModelRequest(
            prompt="short request",
            provider="",
            model="",
            operation="writer",
            max_tokens=128,
            output_limit_requirement="required",
        ),
    )

    assert not response.ok
    assert response.preflight_report["status"] == "BLOCKED"
    assert response.preflight_report["reason"] == "max_output_limit_not_enforceable_by_adapter"
    assert response.preflight_report["output_enforcement"]["state"] == "unsupported"
    assert response.preflight_report["output_budget"]["policy"] == "required"
    assert response.preflight_report["output_budget"]["mode"] == "blocked_unenforceable"
    assert calls == []


@pytest.mark.parametrize(
    ("limits", "prompt", "max_tokens", "reason"),
    [
        (
            {"input_token_limit": 100, "context_window": 50_000, "max_output_tokens": 2_000},
            "required input " + "x" * 1_200,
            128,
            "required_input_over_limit",
        ),
        (
            {"input_token_limit": 50_000, "context_window": 500, "max_output_tokens": 2_000},
            "required context " + "x" * 1_200,
            128,
            "required_context_over_limit",
        ),
        (
            {"input_token_limit": 50_000, "context_window": 50_000, "max_output_tokens": 64},
            "small request",
            128,
            "max_output_limit_exceeded",
        ),
    ],
)
def test_preflight_checks_input_context_and_output_limits_separately(
    tmp_path, limits, prompt, max_tokens, reason
):
    sent = []
    settings = _preflight_settings({"limits": limits})
    gateway = RuntimeModelGateway(
        runtime_resolver=lambda _stage: settings,
        capability_resolver=ModelCapabilityResolver(
            store=ModelCapabilityStore(tmp_path / "capabilities.json")
        ),
        transport=lambda **call: sent.append(call) or {},
    )

    response = gateway.complete_stage(
        "planner",
        ModelRequest(
            prompt=prompt,
            provider="",
            model="",
            operation=reason,
            max_tokens=max_tokens,
        ),
    )

    assert response.preflight_report["status"] == "BLOCKED"
    assert response.preflight_report["reason"] == reason
    for name, value in limits.items():
        assert response.preflight_report["limits"][name]["value"] == value
    assert sent == []


def test_unknown_or_expired_evidence_is_visible_but_never_claimed_verified(tmp_path):
    sent = []
    settings = _preflight_settings(model="unknown-model")
    resolver = ModelCapabilityResolver(
        store=ModelCapabilityStore(tmp_path / "capabilities.json"),
        catalog={
            ("custom_openai", "openai_compatible", "unknown-model"): {
                "capabilities": {
                    "temperature": {
                        "state": "supported",
                        "provenance": {
                            "source": "official_catalog",
                            "expires_at": "2020-01-01T00:00:00+00:00",
                        },
                    }
                }
            }
        },
    )
    gateway = RuntimeModelGateway(
        runtime_resolver=lambda _stage: settings,
        capability_resolver=resolver,
        transport=lambda **call: sent.append(call) or {
            "choices": [{"message": {"content": "ok"}}],
            "model": "resolved-unknown-model",
        },
    )
    response = gateway.complete_stage(
        "planner",
        ModelRequest(prompt="small request", provider="", model="", operation="unknown"),
    )

    assert response.ok
    assert len(sent) == 1
    temperature = response.preflight_report["capabilities"]["temperature"]
    assert temperature["state"] == "unknown"
    assert temperature["source"] == "official_catalog"
    assert temperature["expired"] is True
    assert response.preflight_report["unknown_limit_policy"]["action"] == "bounded_legacy_compatibility_guard"
    assert response.preflight_report["resolved_model"] == "resolved-unknown-model"


def test_preflight_preview_is_local_and_does_not_call_provider(tmp_path):
    sent = []
    settings = _preflight_settings()
    gateway = RuntimeModelGateway(
        runtime_resolver=lambda _stage: settings,
        capability_resolver=ModelCapabilityResolver(
            store=ModelCapabilityStore(tmp_path / "capabilities.json")
        ),
        transport=lambda **call: sent.append(call) or {},
    )

    plan = gateway.preflight_stage(
        "writer",
        ModelRequest(prompt="preview only", provider="", model="", operation="preview"),
    )

    assert plan.report["status"] == "READY"
    assert plan.report["requested_model"] == "alias-model"
    assert sent == []


def test_character_director_writer_and_canon_review_share_runtime_preflight(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from packages.story_core import runtime_config
    from packages.story_core.agents.consistency.runtime import GatewayConsistencyRuntime
    from packages.story_core.agents.director.runtime import GatewayDirectorRuntime
    from packages.story_core.agents.writer.runtime import GatewayWriterRuntime
    from packages.story_core.character_agent import OpenAICharacterProposalProvider

    resolved_stages = []
    provider_calls = []
    settings_by_stage = {
        stage: StageRuntimeSettings(
            provider_id="openai",
            protocol="openai_compatible",
            model=f"{stage}-model",
            api_key="test-secret",
            base_url="https://api.example/v1",
            temperature=0,
            user_declared_capabilities={
                "limits": {
                    "input_token_limit": 32_000,
                    "context_window": 36_000,
                    "max_output_tokens": 4_000,
                }
            },
        )
        for stage in ("planner", "director", "writer", "consistency")
    }

    def resolve(stage):
        resolved_stages.append(stage)
        return settings_by_stage[stage]

    def transport(**call):
        provider_calls.append(call)
        return {
            "choices": [{"message": {"content": "ok"}}],
            "model": "resolved-body-model",
        }

    monkeypatch.setattr(runtime_config, "resolve_stage_runtime", resolve)
    gateway = RuntimeModelGateway(
        transport=transport,
        capability_resolver=ModelCapabilityResolver(
            store=ModelCapabilityStore(tmp_path / "capabilities.json")
        ),
    )
    requests = [
        OpenAICharacterProposalProvider(gateway).complete(
            ModelRequest(prompt="character request", provider="", model="", operation="character")
        ),
        GatewayDirectorRuntime(gateway).complete(
            SimpleNamespace(prompt="director request", stage="director", metadata={"agent": "director"})
        ),
        GatewayWriterRuntime(gateway).complete(
            SimpleNamespace(prompt="writer request", stage="writer", metadata={"agent": "writer"})
        ),
        GatewayConsistencyRuntime(gateway).complete(
            SimpleNamespace(prompt="canon review request", stage="consistency", metadata={"agent": "consistency"})
        ),
    ]

    assert all(response.ok for response in requests)
    assert all(response.preflight_report["status"] == "READY" for response in requests)
    assert [call["payload"]["model"] for call in provider_calls] == [
        "planner-model", "director-model", "writer-model", "consistency-model"
    ]
    assert resolved_stages == ["planner", "director", "writer", "consistency"]
    assert len(provider_calls) == 4
