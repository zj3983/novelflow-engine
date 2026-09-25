import json
import io
import socket
import urllib.error
from pathlib import Path

import pytest

from packages.story_core.http_retry import ResponseTooLargeError, RetryConfig
from packages.story_core.model_gateway import ModelRequest
from packages.story_core.model_gateway.provider_adapters import (
    AntigravityCLIAdapter,
    AnthropicAdapter,
    CodexCLIAdapter,
    GeminiAdapter,
    OpenAICompatibleAdapter,
    _read_sse_json_stream,
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


def test_sse_aggregation_preserves_resolved_model_and_content():
    chunks = [
        b'data: {"id":"req-1","model":"backend-b","choices":[{"delta":{"content":"a"}}]}\n',
        b'data: {"choices":[{"delta":{"content":"b"}}]}\n',
        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n',
        b'data: {"usage":{"total_tokens":2}}\n',
        b"data: [DONE]\n",
    ]

    result = _read_sse_json_stream(chunks, max_response_bytes=4096)

    assert result["id"] == "req-1"
    assert result["model"] == "backend-b"
    assert result["choices"][0]["message"]["content"] == "ab"
    assert result["choices"][0]["finish_reason"] == "stop"
    assert result["usage"] == {"total_tokens": 2}


def test_provider_adapter_preserves_response_too_large_error_code() -> None:
    adapter = OpenAICompatibleAdapter(
        base_url="https://api.example.test/v1",
        api_key="secret",
        transport=RecordingTransport(ResponseTooLargeError("response_too_large")),
    )

    response = adapter.complete(request())

    assert response.ok is False
    assert response.error == "response_too_large"


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
    assert call["payload"]["temperature"] == 0.4
    assert len(transport.calls) == 1
    assert "parameters" not in call["payload"]
    assert call["config"].timeout == 19
    assert response.ok and response.text == "chapter" and response.request_id == "req-1"


def test_openai_compatible_response_keeps_allowlisted_completion_metadata():
    transport = RecordingTransport(
        {
            "id": "req-1",
            "model": "resolved-k3",
            "choices": [{"finish_reason": "length", "message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 2600, "total_tokens": 2700},
            "Authorization": "Bearer secret",
        }
    )
    response = OpenAICompatibleAdapter(
        base_url="https://api.example/v1", api_key="secret", transport=transport
    ).complete(request(json_mode=True))

    assert response.ok
    assert response.resolved_model == "resolved-k3"
    assert response.usage == {"prompt_tokens": 100, "completion_tokens": 2600, "total_tokens": 2700}
    assert response.raw["choices"][0]["finish_reason"] == "length"
    assert response.raw["Authorization"] == "[REDACTED]"


def test_openai_compatible_retries_once_without_temperature_only_on_explicit_rejection():
    class Transport:
        def __init__(self):
            self.payloads = []

        def __call__(self, *, url, payload, headers, config):
            self.payloads.append(dict(payload))
            if len(self.payloads) == 1:
                raise urllib.error.HTTPError(
                    url, 400, "Bad Request", {},
                    io.BytesIO(json.dumps({"error": {"message": "invalid temperature: only 1 is allowed for this model", "type": "invalid_request_error"}}).encode()),
                )
            return {"choices": [{"message": {"content": "ok"}}]}

    transport = Transport()
    response = OpenAICompatibleAdapter(base_url="https://api.example/v1", api_key="secret", transport=transport).complete(request(json_mode=True))
    assert response.ok and response.temperature_omitted
    assert len(transport.payloads) == 2
    assert transport.payloads[0]["temperature"] == 0.4
    assert transport.payloads[1] == {k: v for k, v in transport.payloads[0].items() if k != "temperature"}


def test_openai_compatible_temperature_compatibility_retry_is_bounded_to_two_calls():
    # A fresh response body is needed on each call to simulate a rejecting server.
    calls = []

    def reject(*, url, payload, headers, config):
        calls.append(dict(payload))
        raise urllib.error.HTTPError(
            url, 400, "Bad Request", {},
            io.BytesIO(json.dumps({"error": {"message": "temperature not supported"}}).encode()),
        )

    response = OpenAICompatibleAdapter(base_url="https://api.example/v1", api_key="secret", transport=reject).complete(request())
    assert not response.ok and response.temperature_omitted
    assert len(calls) == 2


@pytest.mark.parametrize("status,message", [
    (400, "invalid request"), (400, "temperature out of range"),
    (401, "temperature not supported"), (403, "temperature not supported"),
    (404, "temperature not supported"), (429, "temperature not supported"),
    (500, "temperature not supported"),
])
def test_openai_compatible_does_not_retry_unrelated_errors(status, message):
    calls = []

    def transport(*, url, payload, headers, config):
        calls.append(payload)
        raise urllib.error.HTTPError(url, status, "error", {}, io.BytesIO(json.dumps({"error": {"message": message}}).encode()))

    response = OpenAICompatibleAdapter(base_url="https://api.example/v1", api_key="secret", transport=transport).complete(request())
    assert not response.ok
    assert len(calls) == 1


def test_openai_compatible_does_not_retry_timeout_as_temperature_failure():
    transport = RecordingTransport(TimeoutError("timed out"))
    response = OpenAICompatibleAdapter(base_url="https://api.example/v1", api_key="secret", transport=transport).complete(request())
    assert not response.ok and response.error == "request_timed_out"
    assert len(transport.calls) == 1


def test_openai_compatible_respects_explicit_compatibility_opt_out():
    calls = []

    def reject(*, url, payload, headers, config):
        calls.append(dict(payload))
        raise urllib.error.HTTPError(
            url, 400, "Bad Request", {},
            io.BytesIO(json.dumps({"error": {"message": "temperature not supported"}}).encode()),
        )

    response = OpenAICompatibleAdapter(base_url="https://api.example/v1", api_key="secret", transport=reject).complete(
        request(metadata={"allow_compatibility_fallback": False})
    )
    assert not response.ok and len(calls) == 1


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
    assert response.error == "response_too_large"


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

    response = adapter.complete(request(provider="codexcli", max_tokens=None))

    assert captured["command"] == "codex-custom"
    assert captured["payload"]["messages"][1]["content"] == "Write it"
    assert "max_tokens" not in captured["payload"]
    assert response.ok and response.text == "from cli"
    assert response.raw["Authorization"] == "[REDACTED]"


def test_codex_cli_adapter_fails_closed_when_output_limit_is_requested(monkeypatch):
    calls = []

    def unexpected_call(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Codex CLI must not run without an enforceable output limit")

    monkeypatch.setattr(
        "packages.story_core.codex_cli_provider.post_json_via_codex_cli",
        unexpected_call,
    )

    response = CodexCLIAdapter().complete(
        request(
            provider="codexcli",
            max_tokens=128,
            output_limit_requirement="required",
        )
    )

    assert not response.ok
    assert response.error == "max_output_limit_not_enforceable"
    assert calls == []


def test_codex_cli_command_rejects_output_limit_before_running(monkeypatch):
    from packages.story_core import codex_cli_provider

    calls = []
    monkeypatch.setattr(
        codex_cli_provider.subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(ValueError, match="max_output_limit_not_enforceable"):
        codex_cli_provider.post_json_via_codex_cli(
            {
                "model": "gpt-test",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "Write"}],
            },
            command="fake-codex",
        )

    assert calls == []


def test_antigravity_cli_adapter_uses_its_own_provider(monkeypatch):
    captured = {}

    def fake_cli(payload, *, command, config):
        captured.update(payload=payload, command=command, config=config)
        return {"choices": [{"message": {"content": "from antigravity"}}]}

    monkeypatch.setattr(
        "packages.story_core.antigravity_cli_provider.post_json_via_antigravity_cli",
        fake_cli,
    )
    adapter = AntigravityCLIAdapter(command="agy-custom")

    response = adapter.complete(request(provider="antigravity", json_mode=True, max_tokens=None))

    assert captured["command"] == "agy-custom"
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert response.ok and response.text == "from antigravity"


def test_antigravity_cli_adapter_fails_closed_when_output_limit_is_requested(monkeypatch):
    calls = []

    def unexpected_call(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("Antigravity CLI command must not run without a hard output limit")

    monkeypatch.setattr(
        "packages.story_core.antigravity_cli_provider.post_json_via_antigravity_cli",
        unexpected_call,
    )

    response = AntigravityCLIAdapter().complete(
        request(
            provider="antigravity",
            max_tokens=128,
            output_limit_requirement="required",
        )
    )

    assert not response.ok
    assert response.error == "max_output_limit_not_enforceable"
    assert calls == []


@pytest.mark.parametrize(
    ("adapter", "provider", "monkeypatch_path"),
    [
        (CodexCLIAdapter(), "codexcli", "packages.story_core.codex_cli_provider.post_json_via_codex_cli"),
        (AntigravityCLIAdapter(), "antigravity", "packages.story_core.antigravity_cli_provider.post_json_via_antigravity_cli"),
    ],
)
def test_cli_adapters_continue_best_effort_output_estimates_without_payload_cap(
    monkeypatch, adapter, provider, monkeypatch_path
):
    captured = {}

    def fake_cli(payload, *, command, config):
        captured.update(payload=payload, command=command)
        return {"choices": [{"message": {"content": "estimate-only result"}}]}

    monkeypatch.setattr(monkeypatch_path, fake_cli)
    response = adapter.complete(
        request(provider=provider, max_tokens=128, output_limit_requirement="best_effort")
    )

    assert response.ok
    assert captured["payload"].get("max_tokens") is None


def test_antigravity_cli_command_rejects_output_limit_before_running(monkeypatch):
    from packages.story_core import antigravity_cli_provider

    calls = []
    monkeypatch.setattr(
        antigravity_cli_provider,
        "_run",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(ValueError, match="max_output_limit_not_enforceable"):
        antigravity_cli_provider.post_json_via_antigravity_cli(
            {
                "model": "gemini-test",
                "max_tokens": 128,
                "messages": [{"role": "user", "content": "Write"}],
            },
            command="fake-agy",
        )

    assert calls == []


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
    assert response.error == "runtime_configuration_unavailable"
    assert response.preflight_report["status"] == "BLOCKED"
    assert response.preflight_report["reason"] == "runtime_configuration_unavailable"
    assert "secret-token" not in response.error
    assert "secret-token" not in json.dumps(response.raw)
    assert "secret-token" not in json.dumps(response.preflight_report)
