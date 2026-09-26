import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from packages.story_core.model_gateway.capabilities import CapabilityObservation, ModelCapabilityResolver
from packages.story_core.model_gateway.capability_refresh import refresh_capabilities
from packages.story_core.runtime_config import RuntimeConfiguration


@pytest.fixture
def candidate(monkeypatch, tmp_path):
    import packages.story_core.runtime_config as config
    import packages.story_core.model_gateway.capabilities as capabilities
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(capabilities, "CAPABILITY_CACHE_FILE", tmp_path / "capabilities.json")
    candidate = RuntimeConfiguration().model_dump(mode="json")
    candidate["stages"] = {stage: {"provider_id": "custom_openai", "model": "fake-model"} for stage in ("planner", "writer")}
    candidate["accounts"]["custom_openai"].update(api_key="TEST_ONLY_SECRET", base_url="https://fake.invalid/v1")
    config.set_runtime_configuration(candidate)
    return candidate


client = TestClient(app)


def test_read_capabilities_never_calls_provider_and_hides_urls(candidate, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: pytest.fail("network on read"))
    candidate["accounts"]["custom_openai"].update(api_key="", base_url="https://user:secret@fake.invalid/private-secret?token=query-secret")
    candidate["accounts"]["custom_openai"]["model_capabilities"] = {"fake-model": {"json_mode": "supported", "limits": {"context_window": 8192}}}
    response = client.post("/runtime-settings/capabilities", json={"stage": "planner", "runtime_settings": candidate})
    assert response.status_code == 200
    assert response.json()["records"]["json_mode"]["source"] == "user_declared"
    assert response.json()["records"]["context_window"]["value"] == 8192
    assert "secret" not in response.text and "base_url" not in response.text


def test_refresh_uses_candidate_selected_stage_and_masked_secret_without_saving(candidate, monkeypatch):
    candidate["accounts"]["custom_openai"]["api_key"] = "********"
    candidate["accounts"]["custom_openai"]["base_url"] = "https://candidate.invalid/v1"
    candidate["stages"]["planner"]["model"] = "candidate-model"
    candidate["stages"]["writer"] = {"provider_id": "openai", "model": "unconfigured-other-model"}
    calls = []
    def transport(**kwargs):
        calls.append(kwargs)
        assert kwargs["url"] == "https://candidate.invalid/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer TEST_ONLY_SECRET"
        assert kwargs["payload"]["model"] == "candidate-model"
        return {"choices": [{"message": {"content": '{"ok":true}'}}], "capability_probe_sse": kwargs["payload"].get("stream", False)}
    monkeypatch.setattr("apps.api.routes.runtime_settings.refresh_capabilities", lambda runtime: refresh_capabilities(runtime, transport=transport, discovery=lambda _: []))
    response = client.post("/runtime-settings/refresh-capabilities", json={"stage": "planner", "runtime_settings": candidate})
    assert response.status_code == 200 and response.json()["ok"]
    assert len(calls) == 4
    assert "TEST_ONLY_SECRET" not in response.text
    assert client.get("/runtime-settings").json()["stages"]["planner"]["model"] == "fake-model"


def test_save_invalidates_removed_binding_but_preserves_shared_binding(candidate):
    resolver = ModelCapabilityResolver()
    identity = resolver.identity("custom_openai", "https://fake.invalid/v1", "fake-model", "openai_compatible")
    resolver.record_runtime_observation(CapabilityObservation(identity, "temperature", "unsupported"))
    candidate["stages"]["planner"]["model"] = "new-model"
    assert client.put("/runtime-settings", json=candidate).status_code == 200
    assert resolver.store.get_profile(identity) is not None  # still used by writer
    candidate["stages"]["writer"]["model"] = "new-model"
    assert client.put("/runtime-settings", json=candidate).status_code == 200
    assert resolver.store.get_profile(identity) is None
    assert client.post("/runtime-settings/capabilities", json={"stage": "planner", "runtime_settings": candidate}).json()["records"]["temperature"]["state"] == "unknown"


def test_endpoint_change_invalidates_old_profile(candidate):
    resolver = ModelCapabilityResolver()
    identity = resolver.identity("custom_openai", "https://fake.invalid/v1", "fake-model", "openai_compatible", resolved_model="snapshot")
    resolver.record_runtime_observation(CapabilityObservation(identity, "streaming", "supported"))
    candidate["accounts"]["custom_openai"]["base_url"] = "https://new.invalid/v1"
    assert client.put("/runtime-settings", json=candidate).status_code == 200
    assert resolver.store.get_profile(identity) is None
    assert resolver.store.get_profile(identity.with_resolved_model(None)) is None


def test_invalid_preview_provider_returns_safe_validation_error(candidate, caplog):
    candidate["stages"]["planner"]["provider_id"] = "unknown"
    response = client.post("/runtime-settings/capabilities", json={"stage": "planner", "runtime_settings": candidate})
    assert response.status_code == 422
    assert "TEST_ONLY_SECRET" not in response.text
    assert "TEST_ONLY_SECRET" not in caplog.text
    assert response.json()["detail"][0]["type"] == "value_error"
    assert "runtime_settings" in response.json()["detail"][0]["loc"]


@pytest.mark.parametrize("path", ["/runtime-settings/capabilities", "/runtime-settings/refresh-capabilities", "/runtime-settings/test", "/runtime-settings/discover-models"])
def test_malformed_input_redacts_validation_context_and_logs(candidate, caplog, path):
    candidate["accounts"]["custom_openai"]["model_capabilities"] = "TEST_ONLY_SECRET https://secret-url.invalid/key"
    response = client.post(path, json={"stage": "planner", "runtime_settings": candidate})
    assert response.status_code == 422
    serialized = response.text + caplog.text
    for secret in ("TEST_ONLY_SECRET", "secret-url", '"input"', '"ctx"'):
        assert secret not in serialized
    assert any("model_capabilities" in error["loc"] for error in response.json()["detail"])
