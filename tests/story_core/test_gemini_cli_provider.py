import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.story_core import gemini_cli_provider as cli
from packages.story_core.model_gateway import provider_definition
from packages.story_core.model_gateway.contracts import ModelRequest
from packages.story_core.model_gateway.runtime_gateway import RuntimeModelGateway
from packages.story_core.runtime_config import StageRuntimeSettings


def test_gemini_cli_uses_google_login_stdin_and_isolated_workspace(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-use-api")
    monkeypatch.setenv("GOOGLE_API_KEY", "must-not-use-api")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setattr(cli, "_gemini_command_prefix", lambda command: [command])
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(args=args, **kwargs)
        settings = json.loads((Path(kwargs["cwd"]) / ".gemini/settings.json").read_text())
        assert settings["security"]["auth"]["selectedType"] == "oauth-personal"
        assert settings["tools"]["core"] == []
        assert settings["hooksConfig"]["enabled"] is False
        assert "hooks" not in settings
        return SimpleNamespace(returncode=0, stdout=json.dumps({"response": '{"ok":true}'}), stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    result = cli.post_json_via_gemini_cli({
        "model": "gemini-3.5-flash",
        "messages": [{"role": "system", "content": "只写小说"}, {"role": "user", "content": "中文灵感"}],
        "response_format": {"type": "json_object"},
    }, command="gemini-test")
    assert result["choices"][0]["message"]["content"] == '{"ok":true}'
    assert "中文灵感" in captured["input"]
    assert "合法 JSON" in captured["input"]
    assert "中文灵感" not in captured["args"]
    assert "--output-format" in captured["args"]
    assert "--yolo" not in captured["args"]
    assert "GEMINI_API_KEY" not in captured["env"]
    assert "GOOGLE_API_KEY" not in captured["env"]
    assert "GOOGLE_GENAI_USE_VERTEXAI" not in captured["env"]


@pytest.mark.parametrize("output,code,error", [
    ('{"error":{"type":"AuthError","message":"Please login"}}', 1, "gemini_cli_login_required"),
    ('{"response":""}', 0, "gemini_cli_empty"),
    ('not-json', 0, "gemini_cli_invalid_response"),
    ('{"error":{"message":"sensitive diagnostic"}}', 1, "gemini_cli_failed"),
])
def test_gemini_cli_reports_safe_errors(monkeypatch, output, code, error):
    monkeypatch.setattr(cli, "_gemini_command_prefix", lambda command: [command])
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=code, stdout=output, stderr=""))
    with pytest.raises((RuntimeError, ValueError), match=f"^{error}$"):
        cli.post_json_via_gemini_cli({"model": "gemini-3.5-flash", "messages": []})


def test_gemini_cli_gateway_requires_no_api_key(monkeypatch):
    definition = provider_definition("geminicli")
    assert definition.protocol == "gemini_cli"
    assert not definition.requires_api_key
    monkeypatch.setattr(cli, "post_json_via_gemini_cli", lambda *a, **k: {"choices": [{"message": {"content": "正文"}}]})
    runtime = StageRuntimeSettings(provider_id="geminicli", protocol="gemini_cli", model="gemini-3.5-flash", api_key="", base_url="", codex_command="gemini")
    result = RuntimeModelGateway(runtime_resolver=lambda stage: runtime).complete_stage("writer", ModelRequest(prompt="写正文", provider="", model="", operation="writer"))
    assert result.ok
    assert result.text == "正文"


@pytest.mark.parametrize("error", ["gemini_cli_login_required", "gemini_cli_account_unsupported", "gemini_cli_config_invalid"])
def test_missing_login_is_preserved_by_gateway(monkeypatch, error):
    def fail(*a, **k):
        raise RuntimeError(error)
    monkeypatch.setattr(cli, "post_json_via_gemini_cli", fail)
    runtime = StageRuntimeSettings(provider_id="geminicli", protocol="gemini_cli", model="gemini-3.5-flash", api_key="", base_url="", codex_command="gemini")
    result = RuntimeModelGateway(runtime_resolver=lambda stage: runtime).complete_stage("planner", ModelRequest(prompt="规划", provider="", model="", operation="planner"))
    assert result.error == error


@pytest.mark.parametrize("diagnostic,expected", [
    ("Error authenticating: IneligibleTierError: This client is no longer supported for Gemini Code Assist for individuals.", "gemini_cli_account_unsupported"),
    ("Invalid configuration: hooks.enabled Expected array, received boolean", "gemini_cli_config_invalid"),
    ("Loaded cached credentials. Service unavailable: HTTP 503", "gemini_cli_failed"),
])
def test_cli_does_not_report_provider_rejection_as_missing_login(monkeypatch, diagnostic, expected):
    monkeypatch.setattr(cli, "_gemini_command_prefix", lambda command: [command])
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr=diagnostic))
    with pytest.raises(RuntimeError, match=f"^{expected}$"):
        cli.post_json_via_gemini_cli({"model": "gemini-3.1-pro-preview"})


def test_antigravity_location_error_is_preserved(monkeypatch):
    from packages.story_core import antigravity_cli_provider
    monkeypatch.setattr(antigravity_cli_provider, "post_json_via_antigravity_cli", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("antigravity_cli_failed: User location is not supported for the API use")))
    runtime = StageRuntimeSettings(provider_id="antigravity", protocol="antigravity_cli", model="gemini-3.6-flash-low", api_key="", base_url="", codex_command="agy")
    result = RuntimeModelGateway(runtime_resolver=lambda stage: runtime).complete_stage("planner", ModelRequest(prompt="规划", provider="", model="", operation="planner"))
    assert result.error == "antigravity_cli_location_unsupported"


def test_legacy_provider_recognizes_google_account_login(monkeypatch):
    from packages.story_core.agent_base import BaseOpenAIProvider
    provider = BaseOpenAIProvider()
    monkeypatch.setattr(provider, "_runtime_settings", lambda: SimpleNamespace(provider="geminicli", api_key=""))
    assert provider.available()


def test_legacy_transport_dispatches_gemini_cli_without_http(monkeypatch):
    from packages.story_core.http_retry import post_json_with_retry
    captured = {}
    def fake(payload, **kwargs):
        captured.update(kwargs)
        return {"choices": [{"message": {"content": "计划"}}]}
    monkeypatch.setattr(cli, "post_json_via_gemini_cli", fake)
    result = post_json_with_retry("", "/chat/completions", {"model": "gemini-3.5-flash"}, "", provider="geminicli", codex_command="gemini-test")
    assert result["choices"][0]["message"]["content"] == "计划"
    assert captured["command"] == "gemini-test"
