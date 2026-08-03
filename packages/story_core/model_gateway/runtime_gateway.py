"""Runtime-selected model gateway shared by planner and writer stages."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Literal

from .contracts import ModelRequest, ModelResponse
from .provider_adapters import (
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
        stage: Literal["planner", "writer", "memory"] | None = None,
        *,
        runtime_resolver: Callable[[str], Any] | None = None,
        transport: JsonTransport | None = None,
    ) -> None:
        self.stage = stage
        if runtime_resolver is None:
            from packages.story_core.runtime_config import resolve_stage_runtime

            runtime_resolver = resolve_stage_runtime
        self.runtime_resolver = runtime_resolver
        self.transport = transport

    def complete(self, request: ModelRequest) -> ModelResponse:
        if self.stage is None:
            return ModelResponse.failure(request, "runtime_stage_required")
        return self.complete_stage(self.stage, request)

    def complete_stage(
        self,
        stage: Literal["planner", "writer", "memory"],
        request: ModelRequest,
    ) -> ModelResponse:
        resolved_stage = "planner" if stage == "memory" else stage
        settings = self.runtime_resolver(resolved_stage)
        runtime_request = replace(
            request,
            provider=settings.provider_id,
            model=settings.model,
            temperature=request.temperature if request.temperature is not None else settings.temperature,
        )
        common: dict[str, Any] = {}
        if self.transport is not None:
            common["transport"] = self.transport
        protocol = provider_definition(settings.provider_id).protocol
        if protocol == "openai_compatible":
            adapter = OpenAICompatibleAdapter(
                base_url=settings.base_url,
                api_key=settings.api_key,
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
        else:  # pragma: no cover - StageRuntimeSettings validates catalog protocols.
            return ModelResponse.failure(runtime_request, "unsupported_protocol")
        return adapter.complete(runtime_request)
