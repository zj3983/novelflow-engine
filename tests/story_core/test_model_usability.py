import json
from dataclasses import replace

import pytest

from packages.story_core.model_gateway.capabilities import ModelCapabilityResolver, ModelCapabilityStore
from packages.story_core.model_gateway.model_usability import read_model_usability, test_model_usability as run_model_test
from packages.story_core.runtime_config import StageRuntimeSettings


@pytest.fixture
def context(tmp_path):
    resolver = ModelCapabilityResolver(store=ModelCapabilityStore(tmp_path / "capabilities.json"))
    runtime = StageRuntimeSettings(provider_id="custom_openai", protocol="openai_compatible", model="fake", api_key="TEST_SECRET", base_url="https://fake.invalid/v1")
    return runtime, resolver


def passed(runtime, **kwargs):
    return {"steps": [{"step": "connectivity", "status": "success"}], "profile": {"secret": "TEST_SECRET"}}


def test_unknown_and_user_declared_capabilities_do_not_prove_model_is_usable(context):
    runtime, resolver = context
    runtime.user_declared_capabilities = {"text_generation": {"state": "supported", "provenance": {"source": "runtime_observation"}}}
    view = read_model_usability(runtime, resolver=resolver)
    assert view["status"] == "untested"
    assert view["can_continue"] is False
    assert view["actions"] == [{"id": "test", "label": "测试模型"}]


def test_verified_connection_is_product_ready_without_engineering_fields(context):
    runtime, resolver = context
    view = run_model_test(runtime, resolver=resolver, refresh=passed)
    assert view["can_continue"] and view["status"] == "ready"
    assert set(view) == {"status", "heading", "message", "tone", "can_continue", "actions"}
    for secret in ("TEST_SECRET", "profile", "streaming", "verified_at", "protocol", "expires_at", "best_effort"):
        assert secret not in json.dumps(view)
    assert read_model_usability(runtime, resolver=resolver) == view


@pytest.mark.parametrize("field,value", [("base_url", "https://new.invalid/v1"), ("model", "different"), ("api_key", "OTHER_SECRET"), ("codex_command", "other-command")])
def test_connection_identity_changes_require_a_new_test(context, field, value):
    runtime, resolver = context
    run_model_test(runtime, resolver=resolver, refresh=passed)
    setattr(runtime, field, value)
    assert read_model_usability(runtime, resolver=resolver)["status"] == "untested"


def test_failed_test_revokes_previous_usable_result_and_provides_repairs(context):
    runtime, resolver = context
    run_model_test(runtime, resolver=resolver, refresh=passed)
    view = run_model_test(runtime, resolver=resolver, refresh=lambda *_args, **_kwargs: {"steps": [{"step": "connectivity", "status": "failed"}]})
    assert view["status"] == "connection_error"
    assert not view["can_continue"]
    assert {action["id"] for action in view["actions"]} == {"test", "edit_connection", "choose_model"}
    assert read_model_usability(runtime, resolver=resolver)["status"] == "connection_error"


def test_expired_connection_is_untested(context):
    runtime, resolver = context
    run_model_test(runtime, resolver=resolver, refresh=passed)
    identity = resolver.identity(runtime.provider_id, runtime.base_url, runtime.model, runtime.protocol)
    record = resolver.store.get_profile(identity).verified_capabilities["text_generation"]
    resolver.store.record_runtime_observation(identity, "text_generation", replace(record, provenance=replace(record.provenance, expires_at="2000-01-01T00:00:00Z")))
    assert read_model_usability(runtime, resolver=resolver)["status"] == "untested"


def test_cli_explicit_test_uses_gateway_without_capability_probe(context):
    from packages.story_core.model_gateway.contracts import ModelResponse
    runtime, resolver = context
    runtime.protocol, runtime.provider_id = "codex_cli", "codexcli"
    class FakeGateway:
        def complete_resolved(self, settings, request):
            assert request.output_limit_requirement == "best_effort"
            assert request.operation == "model_usability_test"
            return ModelResponse.success(request, text="OK")
    assert run_model_test(runtime, resolver=resolver, gateway=FakeGateway(), refresh=lambda *_args, **_kwargs: pytest.fail("CLI probe"))["status"] == "ready"
