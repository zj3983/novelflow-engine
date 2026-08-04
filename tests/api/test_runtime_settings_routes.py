import json

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from packages.story_core.model_gateway.contracts import ModelResponse


client = TestClient(app)


def runtime_configuration(*, planner="deepseek", writer="codexcli"):
    return {
        "schema_version": "runtime-config/v2",
        "accounts": {
            "deepseek": {
                "api_key": "deepseek-secret",
                "base_url": "https://api.deepseek.com/v1",
                "custom_models": [],
                "codex_command": "",
            },
            "codexcli": {
                "api_key": "",
                "base_url": "",
                "custom_models": [],
                "codex_command": "codex-test",
            },
        },
        "stages": {
            "planner": {"provider_id": planner, "model": "deepseek-reasoner"},
            "writer": {"provider_id": writer, "model": "gpt-5-codex"},
        },
        "image": {"enabled": False, "api_key": "", "base_url": "", "model": ""},
        "temperature": 0.7,
        "new_character_policy": "Director review",
    }


@pytest.fixture(autouse=True)
def isolate_runtime(monkeypatch, tmp_path):
    import packages.story_core.runtime_config as runtime_config

    monkeypatch.setattr(runtime_config, "CONFIG_FILE", tmp_path / "runtime-config.json")
    runtime_config.set_runtime_configuration(runtime_configuration())


def test_runtime_settings_uses_v2_accounts_and_only_public_stages():
    response = client.get("/runtime-settings")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "runtime-config/v2"
    assert set(payload["stages"]) == {"planner", "writer"}
    assert "memory" not in json.dumps(payload)
    assert payload["accounts"]["deepseek"]["api_key"] == "********"
    assert "deepseek-secret" not in response.text


def test_provider_catalog_exposes_public_metadata_without_secrets():
    response = client.get("/runtime-settings/providers")

    assert response.status_code == 200
    providers = {item["provider_id"]: item for item in response.json()["providers"]}
    assert providers["anthropic"]["protocol"] == "anthropic"
    assert providers["gemini"]["protocol"] == "gemini"
    assert providers["codexcli"]["requires_api_key"] is False
    assert providers["deepseek"]["default_base_url"] == "https://api.deepseek.com/v1"
    assert '"api_key":' not in response.text


def test_masked_update_preserves_stored_account_key_and_reveal_is_no_store():
    candidate = runtime_configuration()
    candidate["accounts"]["deepseek"]["api_key"] = "********"
    candidate["temperature"] = 0.4

    updated = client.put("/runtime-settings", json=candidate)
    reveal = client.post(
        "/runtime-settings/reveal-api-key", json={"provider_id": "deepseek"}
    )

    assert updated.status_code == 200
    assert updated.json()["accounts"]["deepseek"]["api_key"] == "********"
    assert reveal.status_code == 200
    assert reveal.json() == {"api_key": "deepseek-secret"}
    assert reveal.headers["cache-control"] == "no-store"
    assert reveal.headers["pragma"] == "no-cache"


def test_connection_test_uses_gateway_candidate_without_saving(monkeypatch):
    captured = {}

    def fake_complete(self, settings, request):
        captured["settings"] = settings
        captured["request"] = request
        return ModelResponse.success(
            request,
            text="pong",
            raw={"authorization": "deepseek-secret"},
        )

    monkeypatch.setattr(
        "apps.api.routes.runtime_settings.RuntimeModelGateway.complete_resolved",
        fake_complete,
    )
    persisted = client.get("/runtime-settings").json()
    candidate = runtime_configuration(writer="deepseek")
    candidate["stages"]["writer"]["model"] = "deepseek-chat"

    response = client.post(
        "/runtime-settings/test",
        json={"stage": "writer", "runtime_settings": candidate},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "provider": "deepseek",
        "stage": "writer",
        "model": "deepseek-chat",
        "protocol": "openai_compatible",
        "diagnosis": "",
        "message": "连接成功",
    }
    assert captured["settings"].protocol == "openai_compatible"
    assert captured["request"].operation == "runtime_connection_test"
    assert client.get("/runtime-settings").json() == persisted


def test_connection_test_gives_reasoning_models_enough_output_budget(monkeypatch):
    captured = {}

    def fake_complete(self, settings, request):
        captured["max_tokens"] = request.max_tokens
        return ModelResponse.success(request, text="pong")

    monkeypatch.setattr(
        "apps.api.routes.runtime_settings.RuntimeModelGateway.complete_resolved",
        fake_complete,
    )
    candidate = runtime_configuration(planner="deepseek")
    candidate["stages"]["planner"]["model"] = "deepseek-reasoner"

    response = client.post(
        "/runtime-settings/test",
        json={"stage": "planner", "runtime_settings": candidate},
    )

    assert response.status_code == 200
    assert captured["max_tokens"] >= 256


@pytest.mark.parametrize(
    ("error", "diagnosis", "message"),
    [
        ("authentication_failed", "authentication_failed", "API 密钥无效或没有访问权限"),
        ("model_not_found", "model_not_found", "模型不存在或当前账号无权使用"),
        ("rate_limited", "rate_limited", "请求受到限流，请稍后重试"),
        ("request_timed_out", "request_timed_out", "连接超时，请检查网络和 API 地址"),
        ("invalid_provider_response", "protocol_mismatch", "返回格式与所选协议不匹配"),
        ("provider_unavailable", "provider_unavailable", "服务暂时不可用"),
    ],
)
def test_connection_test_returns_actionable_diagnosis(monkeypatch, error, diagnosis, message):
    def fake_complete(self, settings, request):
        return ModelResponse.failure(request, error)

    monkeypatch.setattr(
        "apps.api.routes.runtime_settings.RuntimeModelGateway.complete_resolved",
        fake_complete,
    )

    response = client.post(
        "/runtime-settings/test",
        json={"stage": "planner", "runtime_settings": runtime_configuration()},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["diagnosis"] == diagnosis
    assert response.json()["message"] == message
    assert response.json()["protocol"] == "openai_compatible"


def test_model_discovery_uses_unsaved_candidate_credentials(monkeypatch):
    captured = {}

    def fake_discover(runtime):
        captured["runtime"] = runtime
        return [
            {
                "model_id": "deepseek-chat",
                "compatibility": "supported",
                "endpoint": "/chat/completions",
                "reason": "内置文本模型",
            }
        ]

    monkeypatch.setattr(
        "apps.api.routes.runtime_settings.discover_provider_models",
        fake_discover,
    )
    candidate = runtime_configuration()
    candidate["accounts"]["deepseek"]["api_key"] = "draft-key"

    response = client.post(
        "/runtime-settings/discover-models",
        json={"provider_id": "deepseek", "runtime_settings": candidate},
    )

    assert response.status_code == 200
    assert response.json() == {
        "provider": "deepseek",
        "protocol": "openai_compatible",
        "models": [
            {
                "model_id": "deepseek-chat",
                "compatibility": "supported",
                "endpoint": "/chat/completions",
                "reason": "内置文本模型",
            }
        ],
    }
    assert captured["runtime"].api_key == "draft-key"


@pytest.mark.parametrize(
    ("provider_id", "protocol", "base_url", "model", "api_key"),
    [
        ("anthropic", "anthropic", "https://api.anthropic.com", "claude-sonnet-4", "a-key"),
        (
            "gemini",
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            "gemini-2.5-pro",
            "g-key",
        ),
        ("codexcli", "codex_cli", "", "gpt-5-codex", ""),
        ("antigravity", "antigravity_cli", "", "gemini-3.6-flash-high", ""),
    ],
)
def test_connection_test_routes_native_protocols_through_gateway(
    monkeypatch, provider_id, protocol, base_url, model, api_key
):
    captured = {}

    def fake_complete(self, settings, request):
        captured["protocol"] = settings.protocol
        captured["provider_id"] = settings.provider_id
        return ModelResponse.success(request, text="pong")

    monkeypatch.setattr(
        "apps.api.routes.runtime_settings.RuntimeModelGateway.complete_resolved",
        fake_complete,
    )
    candidate = runtime_configuration()
    candidate["accounts"][provider_id] = {
        "api_key": api_key,
        "base_url": base_url,
        "custom_models": [],
        "codex_command": "codex-test" if provider_id == "codexcli" else "agy-test" if provider_id == "antigravity" else "",
    }
    candidate["stages"]["writer"] = {"provider_id": provider_id, "model": model}

    response = client.post(
        "/runtime-settings/test",
        json={"stage": "writer", "runtime_settings": candidate},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured == {"protocol": protocol, "provider_id": provider_id}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["stages"]["writer"].update(provider_id="unknown"),
        lambda value: value["stages"]["writer"].update(model=" "),
        lambda value: value["accounts"]["deepseek"].update(api_key=""),
        lambda value: value["accounts"]["deepseek"].update(base_url="ftp://bad.test"),
    ],
)
def test_invalid_selected_provider_configuration_is_rejected_without_secret_echo(mutate):
    candidate = runtime_configuration(writer="deepseek")
    candidate["accounts"]["deepseek"]["api_key"] = "do-not-echo"
    mutate(candidate)

    response = client.put("/runtime-settings", json=candidate)

    assert response.status_code == 422
    assert "do-not-echo" not in response.text


def test_image_key_reveal_compatibility_remains_explicit():
    candidate = runtime_configuration()
    candidate["image"] = {
        "enabled": True,
        "api_key": "image-secret",
        "base_url": "https://images.test/v1",
        "model": "cover-v1",
    }
    assert client.put("/runtime-settings", json=candidate).status_code == 200

    response = client.post(
        "/runtime-settings/reveal-api-key", json={"provider_id": "image"}
    )

    assert response.status_code == 200
    assert response.json() == {"api_key": "image-secret"}


def test_runtime_routes_are_registered_once():
    operations = [
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if route.path.startswith("/runtime-")
    ]
    assert len(operations) == len(set(operations))
