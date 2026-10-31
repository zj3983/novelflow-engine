import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from packages.story_core import runtime_config
from packages.story_core import gemini_cli_provider

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", tmp_path / "runtime.json")
    runtime_config.set_runtime_configuration(runtime_config.RuntimeConfiguration())


def candidate():
    value = runtime_config.RuntimeConfiguration().model_dump(mode="json")
    value["accounts"]["geminicli"]["codex_command"] = "gemini-test"
    for stage in ("planner", "writer"):
        value["stages"][stage] = {"provider_id": "geminicli", "model": "gemini-3.5-flash"}
    return value


def test_gemini_cli_account_can_be_saved_without_api_key():
    response = client.put("/runtime-settings", json=candidate())
    assert response.status_code == 200
    assert response.json()["stages"]["planner"]["provider_id"] == "geminicli"
    assert response.json()["accounts"]["geminicli"]["codex_command"] == "gemini-test"


@pytest.mark.parametrize("error,message", [
    ("gemini_cli_login_required", "Login with Google"),
    ("gemini_cli_account_unsupported", "迁移到 Antigravity"),
    ("gemini_cli_config_invalid", "配置无效"),
])
def test_gemini_cli_connection_reports_login_required(monkeypatch, error, message):
    def fail(*args, **kwargs):
        raise RuntimeError(error)
    monkeypatch.setattr(gemini_cli_provider, "post_json_via_gemini_cli", fail)
    response = client.post("/runtime-settings/test", json={"stage": "planner", "runtime_settings": candidate()})
    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert message in response.json()["message"]


def test_gemini_cli_discovery_returns_candidates_without_api_calls():
    response = client.post("/runtime-settings/discover-models", json={"provider_id": "geminicli", "runtime_settings": candidate()})
    assert response.status_code == 200
    models = response.json()["models"]
    assert models
    assert all(model["compatibility"] == "unknown" for model in models)
    assert all(model["endpoint"] == "gemini-cli" for model in models)
