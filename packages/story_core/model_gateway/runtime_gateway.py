"""Runtime-selected model gateway shared by planner and writer stages."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Literal, Mapping
from urllib.parse import urlsplit

from .capabilities import ModelCapabilityResolver, ModelIdentity, ModelProfile
from .contracts import ModelRequest, ModelResponse
from .preflight import ModelPreflightPlan, preflight_request
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
        provider_metadata_resolver: Callable[[str, str, str, str], Any] | None = None,
    ) -> None:
        self.stage = stage
        if runtime_resolver is None:
            from packages.story_core.runtime_config import resolve_stage_runtime

            runtime_resolver = resolve_stage_runtime
        self.runtime_resolver = runtime_resolver
        self.transport = transport
        self.capability_resolver = capability_resolver or ModelCapabilityResolver()
        # This hook is for already available local/provider metadata only. The
        # gateway never probes a remote provider during preflight.
        self.provider_metadata_resolver = provider_metadata_resolver

    def complete(self, request: ModelRequest) -> ModelResponse:
        if self.stage is None:
            return ModelResponse.failure(request, "runtime_stage_required")
        return self.complete_stage(self.stage, request)

    def complete_stage(
        self,
        stage: Literal["planner", "writer", "memory", "director", "consistency"],
        request: ModelRequest,
        *,
        runtime_settings: Any | None = None,
    ) -> ModelResponse:
        resolved_stage = (
            "planner"
            if stage == "memory"
            else "writer"
            if stage == "consistency"
            else stage
        )
        if runtime_settings is None:
            try:
                runtime_settings = self.runtime_resolver(resolved_stage)
            except Exception:
                return replace(
                    ModelResponse.failure(request, "runtime_configuration_unavailable"),
                    preflight_report={
                        "schema_version": "model-preflight/v1",
                        "status": "BLOCKED",
                        "reason": "runtime_configuration_unavailable",
                        "repair_actions": ["检查该阶段的 provider、模型和连接配置后重试。"],
                    },
                )
        return self.complete_resolved(runtime_settings, request)

    def preflight_stage(
        self,
        stage: Literal["planner", "writer", "memory", "director", "consistency"],
        request: ModelRequest,
        *,
        runtime_settings: Any | None = None,
    ) -> ModelPreflightPlan:
        """Preview a request locally; it never invokes an adapter or probes."""

        resolved_stage = (
            "planner" if stage == "memory" else
            "writer" if stage == "consistency" else stage
        )
        settings = runtime_settings
        if settings is None:
            settings = self.runtime_resolver(resolved_stage)
        return self.preflight_resolved(settings, request)

    def preflight_resolved(self, settings: Any, request: ModelRequest) -> ModelPreflightPlan:
        """Preflight against one immutable settings snapshot."""

        runtime_request, definition, profile, profile_error = self._resolve_preflight(
            settings, request
        )
        plan = preflight_request(
            profile,
            runtime_request,
            allow_split=bool(runtime_request.metadata.get("preflight_allow_split")),
        )
        report = dict(plan.report)
        if definition is None:
            report["status"] = "BLOCKED"
            report["reason"] = "unsupported_protocol"
            report["repair_actions"] = ["核对所选 provider 与协议配置。"]
        if profile_error:
            report["capability_resolution"] = {
                "status": "unknown",
                "error_type": profile_error,
                "policy": "continue_bounded_without_claiming_support",
            }
        return ModelPreflightPlan(request=plan.request, report=report)

    def complete_resolved(self, settings: Any, request: ModelRequest) -> ModelResponse:
        """Complete a request using settings already resolved by the caller."""
        provider_id = str(
            getattr(settings, "provider_id", "") or getattr(settings, "provider", "")
        )
        runtime_request = replace(
            request,
            provider=provider_id,
            model=str(getattr(settings, "model", "") or request.model),
            temperature=(
                request.temperature
                if request.temperature is not None
                else getattr(settings, "temperature", None)
            ),
        )
        plan = self.preflight_resolved(settings, request)
        runtime_request = plan.request
        report = dict(plan.report)
        try:
            definition = provider_definition(provider_id)
        except Exception:
            report.update(
                status="BLOCKED",
                reason="unsupported_protocol",
                repair_actions=["选择有效 provider，或修正当前运行配置。"],
            )
            return replace(
                ModelResponse.failure(runtime_request, "unsupported_protocol"),
                preflight_report=report,
            )
        if str(getattr(settings, "protocol", "") or "") != definition.protocol:
            report.update(
                status="BLOCKED",
                reason="protocol_mismatch",
                repair_actions=["使运行配置中的 protocol 与所选 provider 一致。"],
            )
            return replace(
                ModelResponse.failure(runtime_request, "protocol_mismatch"),
                preflight_report=report,
            )
        if definition.requires_api_key and not str(getattr(settings, "api_key", "") or "").strip():
            report.update(
                status="BLOCKED",
                reason="missing_api_key",
                repair_actions=["为所选 provider 配置 API key，然后重新检查。"],
            )
            return replace(
                ModelResponse.failure(runtime_request, "missing_api_key"),
                preflight_report=report,
            )
        protocol = definition.protocol
        if not protocol.endswith("_cli") and not _valid_http_base_url(
            str(getattr(settings, "base_url", "") or "")
        ):
            report.update(
                status="BLOCKED",
                reason="invalid_base_url",
                repair_actions=["为所选 provider 配置有效的 HTTP(S) base URL。"],
            )
            return replace(
                ModelResponse.failure(runtime_request, "invalid_base_url"),
                preflight_report=report,
            )
        if not plan.ready:
            status = str(report.get("status") or "BLOCKED")
            error = (
                "model_preflight_split_required"
                if status == "SPLIT"
                else "model_preflight_blocked"
            )
            return replace(
                ModelResponse.failure(runtime_request, error),
                preflight_report=report,
            )

        try:
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
                adapter = AnthropicAdapter(base_url=settings.base_url, api_key=settings.api_key, **common)
            elif protocol == "gemini":
                adapter = GeminiAdapter(base_url=settings.base_url, api_key=settings.api_key, **common)
            elif protocol == "codex_cli":
                adapter = CodexCLIAdapter(command=settings.codex_command)
            elif protocol == "antigravity_cli":
                adapter = AntigravityCLIAdapter(command=settings.codex_command)
            else:
                return ModelResponse.failure(runtime_request, "unsupported_protocol")
        except Exception as exc:
            return ModelResponse.failure(
                runtime_request,
                f"adapter_initialization_failed:{type(exc).__name__}",
            )

        response = adapter.complete(runtime_request)
        adjustments = list(report.get("adjustments") or [])
        if response.temperature_omitted:
            adjustments.append({
                "parameter": "temperature",
                "action": "omitted_after_retry",
                "reason": "provider_rejected_temperature",
            })
            report["adjustments"] = adjustments
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
            report["resolved_model"] = response.resolved_model
            report["resolved_model_changed"] = response.resolved_model != runtime_request.model
        return replace(
            response,
            temperature_omitted=(
                response.temperature_omitted
                or any(
                    item.get("parameter") == "temperature"
                    and item.get("action") == "omitted"
                    for item in adjustments
                )
            ),
            preflight_report=report,
        )

    def _resolve_preflight(
        self, settings: Any, request: ModelRequest
    ) -> tuple[ModelRequest, Any | None, ModelProfile, str | None]:
        provider_id = str(
            getattr(settings, "provider_id", "") or getattr(settings, "provider", "")
        )
        model = str(getattr(settings, "model", "") or request.model)
        runtime_request = replace(
            request,
            provider=provider_id,
            model=model,
            temperature=(
                request.temperature
                if request.temperature is not None
                else getattr(settings, "temperature", None)
            ),
        )
        try:
            definition = provider_definition(provider_id)
        except Exception:
            identity = self.capability_resolver.identity(
                provider_id,
                str(getattr(settings, "base_url", "") or ""),
                model,
                str(getattr(settings, "protocol", "") or ""),
            )
            return runtime_request, None, ModelProfile.unknown(identity), "provider_resolution"

        profile_error = None
        try:
            provider_metadata = None
            if self.provider_metadata_resolver is not None:
                provider_metadata = self.provider_metadata_resolver(
                    provider_id,
                    definition.protocol,
                    str(getattr(settings, "base_url", "") or ""),
                    model,
                )
            profile = self.capability_resolver.resolve_model_profile(
                provider_id,
                str(getattr(settings, "base_url", "") or ""),
                model,
                definition.protocol,
                provider_metadata=(provider_metadata if isinstance(provider_metadata, Mapping) else None),
                user_declared=(
                    getattr(settings, "user_declared_capabilities", None)
                    if isinstance(getattr(settings, "user_declared_capabilities", None), dict)
                    else None
                ),
            )
        except Exception as exc:
            profile_error = type(exc).__name__
            profile = ModelProfile.unknown(
                self.capability_resolver.identity(
                    provider_id,
                    str(getattr(settings, "base_url", "") or ""),
                    model,
                    definition.protocol,
                )
            )
        return runtime_request, definition, profile, profile_error


def _valid_http_base_url(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)
    except (AttributeError, ValueError):
        return False
