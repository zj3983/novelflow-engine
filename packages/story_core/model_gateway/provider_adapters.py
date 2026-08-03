"""Native and OpenAI-compatible model protocol adapters."""

from __future__ import annotations

import http.client
import json
import math
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Any, Callable, Mapping
from urllib.parse import quote

from packages.story_core.http_retry import (
    ResponseTooLargeError,
    RetryConfig,
    read_bounded_response_bytes,
)

from .contracts import ModelRequest, ModelResponse


JsonTransport = Callable[..., dict[str, Any]]


def _post_json_with_retry(
    *,
    url: str,
    payload: dict[str, Any],
    headers: Mapping[str, str],
    config: RetryConfig,
) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    delay = config.initial_delay
    last_error: Exception | None = None
    attempts = max(1, config.max_retries)
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            data=data,
            headers=dict(headers),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=config.timeout) as response:
                raw = read_bounded_response_bytes(response, config.max_response_bytes)
            decoded = json.loads(raw.decode("utf-8"))
            if not isinstance(decoded, dict):
                raise ValueError("response_root_not_object")
            return decoded
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in config.retry_on_status or attempt >= attempts:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if retry_after:
                try:
                    parsed_delay = float(retry_after)
                    if math.isfinite(parsed_delay) and parsed_delay >= 0:
                        delay = min(parsed_delay, max(0.0, config.max_delay))
                except ValueError:
                    pass
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            http.client.IncompleteRead,
            json.JSONDecodeError,
        ) as exc:
            last_error = exc
            if attempt >= attempts:
                raise
        time.sleep(delay)
        delay = min(delay * config.backoff_factor, config.max_delay)
    raise last_error or urllib.error.URLError("request_failed")


def _request_config(request: ModelRequest, base: RetryConfig) -> RetryConfig:
    changes: dict[str, Any] = {}
    if request.timeout_seconds is not None:
        changes["timeout"] = request.timeout_seconds
    metadata = request.metadata
    for key in ("max_retries", "max_response_bytes", "allow_compatibility_fallback"):
        if key in metadata:
            changes[key] = metadata[key]
    return replace(base, **changes) if changes else base


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("text") is not None:
                parts.append(str(block["text"]))
        return "".join(parts)
    return ""


_SECRET_FIELD_NAMES = {
    "authorization",
    "api_key",
    "apikey",
    "x-api-key",
    "x-goog-api-key",
}


def _redact_raw(value: Any, secret: str = "") -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if str(key).lower() in _SECRET_FIELD_NAMES
            else _redact_raw(item, secret)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_raw(item, secret) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_raw(item, secret) for item in value)
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    return value


def _stable_error(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return {
            401: "authentication_failed",
            403: "authentication_failed",
            404: "model_not_found",
            429: "rate_limited",
        }.get(exc.code, "provider_unavailable")
    if isinstance(exc, (TimeoutError, socket.timeout, subprocess.TimeoutExpired)):
        return "request_timed_out"
    if isinstance(exc, urllib.error.URLError) and isinstance(
        getattr(exc, "reason", None), (TimeoutError, socket.timeout)
    ):
        return "request_timed_out"
    if isinstance(
        exc,
        (json.JSONDecodeError, ResponseTooLargeError, ValueError, KeyError, TypeError, IndexError),
    ):
        return "invalid_provider_response"
    return "provider_unavailable"


class _Adapter:
    def __init__(
        self,
        *,
        transport: JsonTransport | None = None,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self._transport = transport or _post_json_with_retry
        self._retry_config = retry_config or RetryConfig(max_response_bytes=20 * 1024 * 1024)

    def _call(
        self,
        request: ModelRequest,
        *,
        url: str,
        payload: dict[str, Any],
        headers: Mapping[str, str],
    ) -> dict[str, Any]:
        return self._transport(
            url=url,
            payload=payload,
            headers=dict(headers),
            config=_request_config(request, self._retry_config),
        )

    def _failure(self, request: ModelRequest, exc: Exception) -> ModelResponse:
        # Provider exceptions may contain request URLs or headers, so never retain them.
        return ModelResponse.failure(request, _stable_error(exc), raw=None)


class OpenAICompatibleAdapter(_Adapter):
    def __init__(self, *, base_url: str, api_key: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def complete(self, request: ModelRequest) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": list(request.normalized_messages()),
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            raw = self._call(
                request,
                url=f"{self.base_url}/chat/completions",
                payload=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            choice = raw["choices"][0]
            text = _content_text(choice["message"]["content"])
            if not text:
                raise ValueError("empty_content")
            return ModelResponse.success(
                request,
                text=text,
                request_id=str(raw.get("id") or ""),
                usage=raw.get("usage") if isinstance(raw.get("usage"), dict) else {},
                raw=_redact_raw(raw, self.api_key),
            )
        except Exception as exc:
            return self._failure(request, exc)


class AnthropicAdapter(_Adapter):
    def __init__(self, *, base_url: str, api_key: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def complete(self, request: ModelRequest) -> ModelResponse:
        system_parts: list[str] = []
        messages: list[dict[str, Any]] = []
        for message in request.normalized_messages():
            role = str(message.get("role") or "user")
            content = message.get("content", "")
            if role == "system":
                system_parts.append(_content_text(content) or str(content))
            else:
                messages.append({"role": "assistant" if role == "assistant" else "user", "content": content})
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,
        }
        if system_parts:
            payload["system"] = "\n\n".join(part for part in system_parts if part)
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        try:
            raw = self._call(
                request,
                url=f"{self.base_url}/v1/messages",
                payload=payload,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            text = _content_text(raw["content"])
            if not text:
                raise ValueError("empty_content")
            return ModelResponse.success(
                request,
                text=text,
                request_id=str(raw.get("id") or ""),
                usage=raw.get("usage") if isinstance(raw.get("usage"), dict) else {},
                raw=_redact_raw(raw, self.api_key),
            )
        except Exception as exc:
            return self._failure(request, exc)


class GeminiAdapter(_Adapter):
    def __init__(self, *, base_url: str, api_key: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def complete(self, request: ModelRequest) -> ModelResponse:
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for message in request.normalized_messages():
            role = str(message.get("role") or "user")
            text = _content_text(message.get("content")) or str(message.get("content") or "")
            if role == "system":
                system_parts.append(text)
            else:
                contents.append(
                    {"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]}
                )
        payload: dict[str, Any] = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        generation_config: dict[str, Any] = {}
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        if request.max_tokens is not None:
            generation_config["maxOutputTokens"] = request.max_tokens
        if request.json_mode:
            generation_config["responseMimeType"] = "application/json"
        if generation_config:
            payload["generationConfig"] = generation_config
        try:
            raw = self._call(
                request,
                url=f"{self.base_url}/models/{quote(request.model, safe='')}:generateContent",
                payload=payload,
                headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            )
            parts = raw["candidates"][0]["content"]["parts"]
            text = _content_text(parts)
            if not text:
                raise ValueError("empty_content")
            usage = raw.get("usageMetadata") if isinstance(raw.get("usageMetadata"), dict) else {}
            return ModelResponse.success(
                request,
                text=text,
                usage=usage,
                raw=_redact_raw(raw, self.api_key),
            )
        except Exception as exc:
            return self._failure(request, exc)


class CodexCLIAdapter(_Adapter):
    def __init__(self, *, command: str = "codex", retry_config: RetryConfig | None = None) -> None:
        super().__init__(retry_config=retry_config)
        self.command = command or "codex"

    def complete(self, request: ModelRequest) -> ModelResponse:
        from packages.story_core.codex_cli_provider import post_json_via_codex_cli

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": list(request.normalized_messages()),
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        reasoning_effort = request.metadata.get("reasoning_effort")
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        try:
            raw = post_json_via_codex_cli(
                payload,
                command=self.command,
                config=_request_config(request, self._retry_config),
            )
            text = _content_text(raw["choices"][0]["message"]["content"])
            if not text:
                raise ValueError("empty_content")
            return ModelResponse.success(request, text=text, raw=_redact_raw(raw))
        except Exception as exc:
            return self._failure(request, exc)
