import json
import io
import socket
import urllib.error

import pytest

from packages.story_core.http_retry import RetryConfig
from packages.story_core.model_gateway import ModelRequest
from packages.story_core.model_gateway.provider_adapters import (
    AnthropicAdapter,
    CodexCLIAdapter,
    GeminiAdapter,
    OpenAICompatibleAdapter,
)
from packages.story_core.model_gateway.runtime_gateway import RuntimeModelGateway
from packages.story_core.runtime_config import StageRuntimeSettings


class RecordingTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, *, url, payload, headers, config):
        self.calls.append({"url": url, "payload": payload, "headers": headers, "config": config})
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


class FakeHTTPResponse:
    def __init__(self, payload, *, content_length=None):
        self._body = io.BytesIO(json.dumps(payload).encode("utf-8"))
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def read(self, size=-1):
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def request(**overrides):
    values = {
        "prompt": "Write it",
        "system_prompt": "Be precise",
        "provider": "provider",
        "model": "model-1",
        "operation": "writer",
        "temperature": 0.4,
        "max_tokens": 1200,
        "timeout_seconds": 19,
    }
    values.update(overrides)
    return ModelRequest(**values)


def test_openai_compatible_request_and_response_use_standard_chat_shape():
    transport = RecordingTransport(
        {"id": "req-1", "choices": [{"message": {"content": "chapter"}}], "usage": {"total_tokens": 9}}
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://api.example/v1", api_key="secret", transport=transport
    )

    response = adapter.complete(request(json_mode=True))

    call = transport.calls[0]
    assert call["url"] == "https://api.example/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer secret"
    assert call["payload"]["messages"] == [
        {"role": "system", "content": "Be precise"},
        {"role": "user", "content": "Write it"},
    ]
    assert call["payload"]["response_format"] == {"type": "json_object"}
    assert "parameters" not in call["payload"]
    assert call["config"].timeout == 19
    assert response.ok and response.text == "chapter" and response.request_id == "req-1"


def test_default_http_transport_retries_and_keeps_timeout_and_size_limit(monkeypatch):
    calls = []

    def fake_urlopen(http_request, timeout):
        calls.append((http_request, timeout))
        if len(calls) == 1:
            raise urllib.error.HTTPError(http_request.full_url, 429, "slow", {}, None)
        return FakeHTTPResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    adapter = OpenAICompatibleAdapter(
        base_url="https://model/v1",
        api_key="secret",
        retry_config=RetryConfig(
            max_retries=2,
            initial_delay=0,
            timeout=60,
            max_response_bytes=1024,
        ),
    )

    response = adapter.complete(request(timeout_seconds=7))

    assert response.ok and response.text == "ok"
    assert len(calls) == 2
    assert calls[1][1] == 7
    assert calls[1][0].full_url == "https://model/v1/chat/completions"


@pytest.mark.parametrize(
    ("retry_after", "expected_delay"),
    [("999", 2.0), ("-1", 0.5), ("not-a-number", 0.5)],
)
def test_retry_after_is_non_negative_and_clamped(monkeypatch, retry_after, expected_delay):
    sleeps = []
    calls = 0

    def fake_urlopen(http_request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                http_request.full_url,
                429,
                "slow",
                {"Retry-After": retry_after},
                None,
            )
        return FakeHTTPResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", sleeps.append)
    adapter = OpenAICompatibleAdapter(
        base_url="https://model/v1",
        api_key="secret",
        retry_config=RetryConfig(max_retries=2, initial_delay=0.5, max_delay=2.0),
    )

    assert adapter.complete(request()).ok is True
    assert sleeps == [expected_delay]


def test_default_http_transport_rejects_oversized_response(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeHTTPResponse({}, content_length=100),
    )
    adapter = OpenAICompatibleAdapter(
        base_url="https://model/v1",
        api_key="secret",
        retry_config=RetryConfig(max_retries=1, max_response_bytes=10),
    )

    response = adapter.complete(request())

    assert response.ok is False
    assert response.error == "invalid_provider_response"


def test_anthropic_uses_native_messages_and_splits_system_content():
    transport = RecordingTransport(
        {"id": "msg-1", "content": [{"type": "text", "text": "plan"}], "usage": {"input_tokens": 3}}
    )
    adapter = AnthropicAdapter(
        base_url="https://api.anthropic.com", api_key="anthropic-secret", transport=transport
    )

    response = adapter.complete(
        request(
            provider="anthropic",
            messages=(
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
            ),
        )
    )

    call = transport.calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"] == {
        "Content-Type": "application/json",
        "x-api-key": "anthropic-secret",
        "anthropic-version": "2023-06-01",
    }
    assert call["payload"]["system"] == "Be precise"
    assert call["payload"]["messages"] == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
    ]
    assert response.ok and response.text == "plan"


def test_gemini_uses_native_contents_and_json_response_mime_type():
    transport = RecordingTransport(
        {"candidates": [{"content": {"parts": [{"text": "{" + '\"ok\":true' + "}"}]}}], "usageMetadata": {"totalTokenCount": 4}}
    )
    adapter = GeminiAdapter(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="gemini-secret",
        transport=transport,
    )

    response = adapter.complete(request(provider="gemini", json_mode=True))

    call = transport.calls[0]
    assert call["url"].endswith("/models/model-1:generateContent")
    assert call["headers"]["x-goog-api-key"] == "gemini-secret"
    assert call["payload"]["systemInstruction"] == {"parts": [{"text": "Be precise"}]}
    assert call["payload"]["contents"] == [{"role": "user", "parts": [{"text": "Write it"}]}]
    assert call["payload"]["generationConfig"]["responseMimeType"] == "application/json"
    assert response.ok and response.text == '{"ok":true}'


def test_codex_cli_adapter_reuses_existing_provider(monkeypatch):
    captured = {}

    def fake_cli(payload, *, command, config):
        captured.update(payload=payload, command=command, config=config)
        return {
            "choices": [{"message": {"content": "from cli"}}],
            "Authorization": "must-not-survive",
        }

    monkeypatch.setattr(
        "packages.story_core.codex_cli_provider.post_json_via_codex_cli", fake_cli
    )
    adapter = CodexCLIAdapter(command="codex-custom")

    response = adapter.complete(request(provider="codexcli"))

    assert captured["command"] == "codex-custom"
    assert captured["payload"]["messages"][1]["content"] == "Write it"
    assert response.ok and response.text == "from cli"
    assert response.raw["Authorization"] == "[REDACTED]"


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (urllib.error.HTTPError("https://model", 401, "secret-token", {}, None), "authentication_failed"),
        (urllib.error.HTTPError("https://model", 403, "secret-token", {}, None), "authentication_failed"),
        (urllib.error.HTTPError("https://model", 404, "missing", {}, None), "model_not_found"),
        (urllib.error.HTTPError("https://model", 429, "slow", {}, None), "rate_limited"),
        (urllib.error.HTTPError("https://model", 503, "down", {}, None), "provider_unavailable"),
        (TimeoutError("secret-token"), "request_timed_out"),
        (socket.timeout("secret-token"), "request_timed_out"),
        (urllib.error.URLError("secret-token"), "provider_unavailable"),
    ],
)
def test_adapter_errors_are_stable_and_never_leak_secrets(exception, expected):
    adapter = OpenAICompatibleAdapter(
        base_url="https://model", api_key="secret-token", transport=RecordingTransport(exception)
    )

    response = adapter.complete(request())

    assert response.ok is False
    assert response.error == expected
    assert "secret-token" not in response.error
    assert "secret-token" not in json.dumps(response.raw)


def test_malformed_provider_response_has_stable_error():
    adapter = OpenAICompatibleAdapter(
        base_url="https://model", api_key="key", transport=RecordingTransport({"choices": []})
    )

    response = adapter.complete(request())

    assert response.ok is False
    assert response.error == "invalid_provider_response"


def test_success_raw_response_is_redacted_too():
    adapter = OpenAICompatibleAdapter(
        base_url="https://model",
        api_key="secret-token",
        transport=RecordingTransport(
            {
                "choices": [{"message": {"content": "ok"}}],
                "debug": "Bearer secret-token",
                "Authorization": "Bearer secret-token",
            }
        ),
    )

    response = adapter.complete(request())

    assert response.ok is True
    assert "secret-token" not in json.dumps(response.raw)
    assert response.raw["Authorization"] == "[REDACTED]"


def test_runtime_gateway_resolves_stage_and_selects_protocol_adapter():
    calls = []

    def resolver(stage):
        calls.append(stage)
        return StageRuntimeSettings(
            provider_id="anthropic",
            protocol="anthropic",
            model="claude-sonnet-4",
            api_key="key",
            base_url="https://anthropic.test",
            temperature=0.3,
        )

    transport = RecordingTransport(
        {"content": [{"type": "text", "text": "resolved"}], "usage": {}}
    )
    gateway = RuntimeModelGateway(runtime_resolver=resolver, transport=transport)

    response = gateway.complete_stage(
        "memory", request(provider="ignored", model="ignored", operation="memory")
    )

    assert calls == ["planner"]
    assert transport.calls[0]["url"] == "https://anthropic.test/v1/messages"
    assert transport.calls[0]["payload"]["model"] == "claude-sonnet-4"
    assert response.provider == "anthropic"
    assert response.model == "claude-sonnet-4"


def test_runtime_gateway_complete_keeps_constructor_bound_stage_compatibility():
    def resolver(stage):
        assert stage == "writer"
        return StageRuntimeSettings(
            provider_id="deepseek",
            protocol="openai_compatible",
            model="deepseek-chat",
            api_key="key",
            base_url="https://deepseek.test/v1",
        )

    transport = RecordingTransport(
        {"choices": [{"message": {"content": "written"}}]}
    )
    gateway = RuntimeModelGateway("writer", runtime_resolver=resolver, transport=transport)

    assert gateway.complete(request()).text == "written"


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        (
            StageRuntimeSettings(
                provider_id="deepseek",
                protocol="openai_compatible",
                model="deepseek-chat",
                api_key="",
                base_url="https://api.deepseek.com/v1",
            ),
            "missing_api_key",
        ),
        (
            StageRuntimeSettings(
                provider_id="ollama",
                protocol="openai_compatible",
                model="qwen3:8b",
                base_url="",
            ),
            "invalid_base_url",
        ),
        (
            StageRuntimeSettings(
                provider_id="ollama",
                protocol="openai_compatible",
                model="qwen3:8b",
                base_url="ftp://localhost/v1",
            ),
            "invalid_base_url",
        ),
        (
            StageRuntimeSettings(
                provider_id="unknown-provider",
                protocol="openai_compatible",
                model="unknown-model",
                api_key="secret-token",
                base_url="https://model.invalid/v1",
            ),
            "unsupported_protocol",
        ),
    ],
)
def test_runtime_gateway_returns_stable_configuration_errors(settings, expected):
    gateway = RuntimeModelGateway(runtime_resolver=lambda _stage: settings)

    response = gateway.complete_stage("writer", request())

    assert response.ok is False
    assert response.error == expected
    assert "secret-token" not in json.dumps(response.raw)


def test_runtime_gateway_contains_resolver_errors_without_leaking_details():
    def resolver(_stage):
        raise RuntimeError("secret-token from config")

    response = RuntimeModelGateway(runtime_resolver=resolver).complete_stage("planner", request())

    assert response.ok is False
    assert response.error == "unsupported_protocol"
    assert "secret-token" not in response.error
    assert "secret-token" not in json.dumps(response.raw)
