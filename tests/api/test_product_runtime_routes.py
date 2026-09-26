import json

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from packages.story_core.model_gateway.capability_refresh import refresh_capabilities
from packages.story_core.model_gateway.model_usability import test_model_usability as run_model_test
from packages.story_core.runtime_config import RuntimeConfiguration

client = TestClient(app)


@pytest.fixture
def settings(monkeypatch, tmp_path):
    import packages.story_core.runtime_config as config
    import packages.story_core.model_gateway.capabilities as capabilities
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(capabilities, "CAPABILITY_CACHE_FILE", tmp_path / "capabilities.json")
    configured = RuntimeConfiguration()
    for stage in ("planner", "writer"):
        getattr(configured.stages, stage).provider_id = "custom_openai"
        getattr(configured.stages, stage).model = "fake-model"
    configured.accounts["custom_openai"].api_key = "SYNTHETIC_SECRET"
    configured.accounts["custom_openai"].base_url = "https://fake.invalid/v1"
    configured.accounts["custom_openai"].model_capabilities = {"fake-model": {"streaming": "supported"}}
    config.set_runtime_configuration(configured)
    return client.get("/runtime-settings/product").json()


def test_product_config_and_catalog_omit_engineering_fields_and_save_preserves_them(settings, monkeypatch):
    from packages.story_core.runtime_config import get_runtime_configuration
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: pytest.fail("read probed provider"))
    catalog = client.get("/runtime-settings/product/providers").json()
    serialized = json.dumps([settings, catalog])
    for name in ("SYNTHETIC_SECRET", '"protocol"', '"model_capabilities"', '"temperature"', '"outline_planning"', "provenance", "verified_at", "schema_version"):
        assert name not in serialized
    settings["accounts"]["custom_openai"]["custom_models"] = ["fake-model", "another"]
    result = client.put("/runtime-settings/product", json=settings)
    assert result.status_code == 200
    assert get_runtime_configuration().accounts["custom_openai"].model_capabilities == {"fake-model": {"streaming": "supported"}}
    assert get_runtime_configuration().accounts["custom_openai"].api_key == "SYNTHETIC_SECRET"


def test_read_is_untested_and_detect_responds_only_with_backend_product_mapping(settings, monkeypatch):
    before = client.post("/runtime-settings/product/model-status", json={"stage": "planner", "settings": settings})
    assert before.json()["status"] == "untested"
    calls = []
    def transport(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": '{"ok":true}'}}], "capability_probe_sse": kwargs["payload"].get("stream", False)}
    def detect(runtime, **kwargs):
        return run_model_test(runtime, **kwargs, refresh=lambda selected, **kw: refresh_capabilities(selected, **kw, transport=transport, discovery=lambda _: []))
    monkeypatch.setattr("apps.api.routes.runtime_settings.test_model_usability", detect)
    result = client.post("/runtime-settings/product/test-model", json={"stage": "planner", "settings": settings})
    assert result.status_code == 200
    assert result.json()["status"] == "ready"
    assert len(calls) == 4
    assert set(result.json()) == {"status", "heading", "message", "tone", "can_continue", "actions"}
    assert "SYNTHETIC_SECRET" not in result.text
    assert client.post("/runtime-settings/product/model-status", json={"stage": "planner", "settings": settings}).json()["can_continue"] is True


def test_product_blockers_and_errors_are_safe_and_actionable(settings, monkeypatch, caplog):
    settings["accounts"]["custom_openai"]["api_key"] = ""
    result = client.post("/runtime-settings/product/test-model", json={"stage": "planner", "settings": settings})
    assert result.json()["status"] == "blocked"
    assert not result.json()["can_continue"]
    assert "edit_connection" in {action["id"] for action in result.json()["actions"]}
    settings["accounts"]["custom_openai"]["api_key"] = "SYNTHETIC_SECRET"
    monkeypatch.setattr("apps.api.routes.runtime_settings.test_model_usability", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("SYNTHETIC_SECRET https://secret.invalid/key")))
    failed = client.post("/runtime-settings/product/test-model", json={"stage": "planner", "settings": settings})
    assert failed.json()["status"] == "connection_error"
    assert "SYNTHETIC_SECRET" not in failed.text + caplog.text


def test_discovery_uses_product_model_choices_without_endpoint_or_protocol(settings, monkeypatch):
    monkeypatch.setattr("apps.api.routes.runtime_settings.discover_provider_models", lambda _: [
        {"model_id": "fake-model", "compatibility": "unknown", "endpoint": "SYNTHETIC_SECRET", "reason": "internal details"},
        {"model_id": "embedding", "compatibility": "unsupported", "endpoint": "/chat/completions", "reason": "internal details"},
    ])
    result = client.post("/runtime-settings/product/discover-models", json={"provider_id": "custom_openai", "settings": settings})
    assert result.status_code == 200
    assert result.json()["models"][0] == {"name": "fake-model", "selectable": True, "message": "请先测试模型", "can_test": True}
    assert result.json()["models"][1]["selectable"] is False
    for text in ("compatibility", "endpoint", "SYNTHETIC_SECRET", "internal details"):
        assert text not in result.text


def test_product_validation_response_contains_no_raw_input_or_internal_error(settings, caplog):
    settings["accounts"]["custom_openai"]["api_key"] = {"SYNTHETIC_SECRET": "https://secret.invalid/key"}
    response = client.post("/runtime-settings/product/test-model", json={"stage": "planner", "settings": settings})
    assert response.status_code == 422
    assert set(response.json()) == {"message"}
    assert "SYNTHETIC_SECRET" not in response.text + caplog.text


def test_product_connection_form_redacts_url_credentials_without_losing_saved_endpoint(settings):
    from packages.story_core.runtime_config import get_runtime_configuration, set_runtime_configuration
    stored = get_runtime_configuration()
    endpoint = "https://user:URL_SECRET@fake.invalid/v1?token=QUERY_SECRET"
    stored.accounts["custom_openai"].base_url = endpoint
    set_runtime_configuration(stored)
    visible = client.get("/runtime-settings/product")
    assert "URL_SECRET" not in visible.text and "QUERY_SECRET" not in visible.text
    assert visible.json()["accounts"]["custom_openai"]["base_url"] == "https://fake.invalid/v1"
    assert client.put("/runtime-settings/product", json=visible.json()).status_code == 200
    assert get_runtime_configuration().accounts["custom_openai"].base_url == endpoint
