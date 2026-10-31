import json
from types import SimpleNamespace

import pytest

from packages.story_core import codex_cli_provider
from packages.story_core.model_gateway.contracts import ModelRequest
from packages.story_core.model_gateway.provider_adapters import CodexCLIAdapter
from packages.story_core.simplified_review import user_facing_generation_error


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (
            "cache warning " * 100
            + '\nERROR: {"type":"error","status":400,"error":{"code":"model_not_found",'
            '"message":"The model is not supported when using Codex with a ChatGPT account."}}',
            "model_not_found",
        ),
        ('ERROR: {"status":401,"error":{"message":"secret-token"}}', "authentication_failed"),
        ('ERROR: {"status":403,"error":{"code":"invalid_api_key"}}', "authentication_failed"),
        ('ERROR: {"status":429,"error":{"code":"insufficient_quota"}}', "quota_exhausted"),
        ('ERROR: {"status":429,"error":{"code":"rate_limit_exceeded"}}', "rate_limited"),
        ('ERROR: {"status":503,"error":{"message":"secret-token"}}', "provider_unavailable"),
        ('ERROR: failed to load models cache: missing field `base_instructions`', "cli_cache_incompatible"),
        ('ERROR: secret-token private prompt and https://private.example', "provider_unavailable"),
    ],
)
def test_cli_failure_reaches_adapter_without_raw_output(monkeypatch, tmp_path, stderr, expected):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(codex_cli_provider, "_codex_command_prefix", lambda _: ["fake-codex"])
    monkeypatch.setattr(
        codex_cli_provider.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=1, stdout="private prompt", stderr=stderr),
    )
    response = CodexCLIAdapter().complete(ModelRequest(
        prompt="private prompt", provider="codexcli", model="test-model", operation="writer",
    ))
    assert not response.ok
    assert response.error == expected
    assert response.raw is None
    assert "secret-token" not in json.dumps(response.__dict__)
    assert "private prompt" not in json.dumps(response.__dict__)


def test_missing_cli_is_distinct_from_service_outage(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(codex_cli_provider, "_codex_command_prefix", lambda _: ["missing-codex"])

    def missing(*a, **kw):
        raise FileNotFoundError("secret-path")

    monkeypatch.setattr(codex_cli_provider.subprocess, "run", missing)
    response = CodexCLIAdapter().complete(ModelRequest(
        prompt="test", provider="codexcli", model="test-model", operation="writer",
    ))
    assert response.error == "cli_not_found"
    assert response.raw is None


def test_cli_banner_is_not_a_successful_final_reply(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(codex_cli_provider, "_codex_command_prefix", lambda _: ["fake-codex"])
    monkeypatch.setattr(codex_cli_provider.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout="OpenAI Codex v0.166.0\nmodel: test-model", stderr="",
    ))
    response = CodexCLIAdapter().complete(ModelRequest(
        prompt="test", provider="codexcli", model="test-model", operation="writer",
    ))
    assert not response.ok
    assert response.error == "invalid_provider_response"


@pytest.mark.parametrize(
    ("code", "detail"),
    [
        ("model_not_found", "模型不支持"),
        ("authentication_failed", "登录"),
        ("quota_exhausted", "额度"),
        ("rate_limited", "频率"),
        ("cli_cache_incompatible", "缓存格式"),
        ("cli_not_found", "CLI 程序"),
        ("request_timed_out", "超时"),
        ("invalid_provider_response", "有效回复"),
        ("provider_unavailable", "服务暂时不可用"),
    ],
)
def test_review_repair_shows_model_failure_reason(code, detail):
    message = user_facing_generation_error(ValueError(
        f"review_repair_model_failed:codexcli/test-model/writer: {code}"
    ))
    assert detail in message
    assert "原稿未改动" in message
