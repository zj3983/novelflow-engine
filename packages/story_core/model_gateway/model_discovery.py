"""Discover provider models without assuming every visible model can write text."""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Mapping

from packages.story_core.http_retry import read_bounded_response_bytes

from .provider_catalog import provider_definition


DiscoveryTransport = Callable[..., dict[str, Any]]

_NON_WRITING_MARKERS = (
    "embedding",
    "embed-",
    "rerank",
    "moderation",
    "whisper",
    "transcribe",
    "speech",
    "tts",
    "audio",
    "image",
    "dall-e",
)


def _get_json(*, url: str, headers: Mapping[str, str], timeout: float = 20.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = read_bounded_response_bytes(response, 4 * 1024 * 1024)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("model_discovery_response_not_object")
    return payload


def _entry(model_id: str, compatibility: str, endpoint: str, reason: str) -> dict[str, str]:
    return {
        "model_id": model_id,
        "compatibility": compatibility,
        "endpoint": endpoint,
        "reason": reason,
    }


def _model_ids(payload: dict[str, Any], *, key: str = "data") -> list[str]:
    return sorted(
        {
            str(item.get("id") or "").strip()
            for item in payload.get(key, [])
            if isinstance(item, dict) and str(item.get("id") or "").strip()
        }
    )


def _openai_compatibility(provider_id: str, model_id: str) -> tuple[str, str]:
    definition = provider_definition(provider_id)
    curated = set(definition.planner_models) | set(definition.writer_models)
    if model_id in curated:
        return "supported", "内置文本模型"
    lowered = model_id.lower()
    if any(marker in lowered for marker in _NON_WRITING_MARKERS):
        return "unsupported", "模型名称表明它不是文本生成模型"
    return "unknown", "服务商没有返回文本能力信息，请先测试"


def discover_provider_models(runtime: Any, *, transport: DiscoveryTransport | None = None) -> list[dict[str, str]]:
    """Return discovered models with text-writing compatibility metadata."""

    if runtime.protocol == "codex_cli":
        from packages.story_core.codex_cli_provider import read_codex_cli_models

        return [
            _entry(model_id, "supported", "codex-cli", "Codex CLI 文本模型")
            for model_id in sorted(set(read_codex_cli_models()))
        ]

    if runtime.protocol == "antigravity_cli":
        from packages.story_core.antigravity_cli_provider import read_antigravity_cli_models

        return [
            _entry(model_id, "supported", "antigravity-cli", "Antigravity CLI 文本模型")
            for model_id in sorted(set(read_antigravity_cli_models(runtime.codex_command or "agy")))
        ]

    fetch = transport or _get_json
    base_url = runtime.base_url.rstrip("/")
    if runtime.protocol == "openai_compatible":
        payload = fetch(
            url=f"{base_url}/models",
            headers={"Authorization": f"Bearer {runtime.api_key}"},
        )
        entries = []
        for model_id in _model_ids(payload):
            compatibility, reason = _openai_compatibility(runtime.provider_id, model_id)
            entries.append(
                _entry(model_id, compatibility, "/chat/completions", reason)
            )
        return entries

    if runtime.protocol == "anthropic":
        payload = fetch(
            url=f"{base_url}/v1/models",
            headers={
                "x-api-key": runtime.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        return [
            _entry(model_id, "supported", "/v1/messages", "Anthropic 文本模型")
            for model_id in _model_ids(payload)
        ]

    if runtime.protocol == "gemini":
        payload = fetch(
            url=f"{base_url}/models",
            headers={"x-goog-api-key": runtime.api_key},
        )
        entries = []
        for item in payload.get("models", []):
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("name") or "").removeprefix("models/").strip()
            if not model_id:
                continue
            methods = item.get("supportedGenerationMethods") or []
            supported = "generateContent" in methods
            entries.append(
                _entry(
                    model_id,
                    "supported" if supported else "unsupported",
                    ":generateContent",
                    "支持 generateContent" if supported else "不支持 generateContent",
                )
            )
        return sorted(entries, key=lambda item: item["model_id"])

    raise ValueError("unsupported_model_discovery_protocol")
