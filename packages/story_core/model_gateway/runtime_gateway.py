"""Runtime-selected model gateway shared by planner and writer stages."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Literal
from urllib.parse import urlsplit

from .capabilities import ModelCapabilityResolver, ModelProfile, decide_streaming
from .contracts import ModelRequest, ModelResponse
from .provider_adapters import (
    AntigravityCLIAdapter,
    AnthropicAdapter,
    CodexCLIAdapter,
    GeminiAdapter,
    JsonTransport,
    OpenAICompatibleAdapter,
)
from .provider_catalog import provider_definition


class RuntimeModelGateway:
    def __init__(
        self,
        stage: Literal["planner", "writer", "memory", "director", "consistency"] | None = None,
        *,
        runtime_resolver: Callable[[str], Any] | None = None,
        transport: JsonTransport | None = None,
        capability_resolver: ModelCapabilityResolver | None = None,
    ) -> None:
        self.stage = stage
        if runtime_resolver is None:
            from packages.story_core.runtime_config import resolve_stage_runtime

            runtime_resolver = resolve_stage_runtime
        self.runtime_resolver = runtime_resolver
        self.transport = transport
        self.capability_resolver = capability_resolver or ModelCapabilityResolver()

    def complete(self, request: ModelRequest) -> ModelResponse:
        if self.stage is None:
            return ModelResponse.failure(request, "runtime_stage_required")
        return self.complete_stage(self.stage, request)

    def complete_stage(
        self,
        stage: Literal["planner", "writer", "memory", "director", "consistency"],
        request: ModelRequest,
    ) -> ModelResponse:
        resolved_stage = (
            "planner"
            if stage == "memory"
            else "writer"
            if stage == "consistency"
            else stage
        )
        try:
            settings = self.runtime_resolver(resolved_stage)
        except Exception:
            return ModelResponse.failure(request, "unsupported_protocol")
        return self.complete_resolved(settings, request)

    def complete_resolved(self, settings: Any, request: ModelRequest) -> ModelResponse:
        """Complete a request using settings already resolved by the caller."""

        runtime_request = request
        try:
            provider_id = str(
                getattr(settings, "provider_id", "") or getattr(settings, "provider", "")
            )
            runtime_request = replace(
                request,
                provider=provider_id,
                model=settings.model,
                temperature=(
                    request.temperature
                    if request.temperature is not None
                    else settings.temperature
                ),
            )
            definition = provider_definition(provider_id)
            protocol = definition.protocol
            if settings.protocol != protocol:
                return ModelResponse.failure(runtime_request, "unsupported_protocol")
            if definition.requires_api_key and not settings.api_key.strip():
                return ModelResponse.failure(runtime_request, "missing_api_key")
            if not protocol.endswith("_cli") and not _valid_http_base_url(settings.base_url):
                return ModelResponse.failure(runtime_request, "invalid_base_url")

            try:
                profile = self.capability_resolver.resolve_model_profile(
                    provider_id,
                    settings.base_url,
                    settings.model,
                    protocol,
                )
            except Exception:
                profile = ModelProfile.unknown(
                    self.capability_resolver.identity(
                        provider_id,
                        settings.base_url,
                        settings.model,
                        protocol,
                    )
                )
            metadata = dict(runtime_request.metadata)
            requested_streaming = bool(metadata.get("stream"))
            if "stream" in metadata:
                streaming_decision = decide_streaming(
                    requested_streaming,
                    profile.effective_capability("streaming"),
                )
                # Keep the standalone decision primitive conservative for
                # unknown capabilities, but do not change existing production
                # requests until a real discovery source is wired in.
                metadata["stream"] = (
                    requested_streaming
                    if streaming_decision.capability_state == "unknown"
                    else streaming_decision.effective_streaming
                )
            if (
                runtime_request.temperature is not None
                and profile.effective_capability("temperature").state == "unsupported"
            ):
                runtime_request = replace(runtime_request, temperature=None)
            runtime_request = replace(runtime_request, metadata=metadata)

            common: dict[str, Any] = {}
            if self.transport is not None:
                common["transport"] = self.transport
            if protocol == "openai_compatible":
                adapter = OpenAICompatibleAdapter(
                    base_url=settings.base_url,
                    api_key=settings.api_key,
                    capability_observer=self.capability_resolver.record_runtime_observation,
                    **common,
                )
            elif protocol == "anthropic":
                adapter = AnthropicAdapter(
                    base_url=settings.base_url,
                    api_key=settings.api_key,
                    **common,
                )
            elif protocol == "gemini":
                adapter = GeminiAdapter(
                    base_url=settings.base_url,
                    api_key=settings.api_key,
                    **common,
                )
            elif protocol == "codex_cli":
                adapter = CodexCLIAdapter(command=settings.codex_command)
            elif protocol == "antigravity_cli":
                adapter = AntigravityCLIAdapter(command=settings.codex_command)
            else:
                return ModelResponse.failure(runtime_request, "unsupported_protocol")
        except Exception:
            return ModelResponse.failure(runtime_request, "unsupported_protocol")
        response = adapter.complete(runtime_request)
        if response.ok and response.resolved_model:
            try:
                self.capability_resolver.record_resolved_model(
                    self.capability_resolver.identity(
                        provider_id,
                        settings.base_url,
                        settings.model,
                        protocol,
                        resolved_model=response.resolved_model,
                    )
                )
            except Exception:
                # A cache/update failure must not turn a successful model call
                # into a failed generation.
                pass
        return response


def _valid_http_base_url(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except (AttributeError, ValueError):
        return False
