"""Provider-neutral model call contracts and adapters."""

from .contracts import ModelGateway, ModelRequest, ModelResponse, normalize_model_error
from .capabilities import (
    CapabilityObservation,
    CapabilityProvenance,
    CapabilityRecord,
    ContextPreflightResult,
    ModelCapabilityResolver,
    ModelCapabilityStore,
    ModelIdentity,
    ModelProfile,
    StreamingDecision,
    decide_streaming,
    effective_streaming,
    normalize_base_url,
    preflight_context,
    resolve_model_profile,
)
from .provider_catalog import (
    BUILTIN_PROVIDER_IDS,
    ProviderDefinition,
    provider_definition,
    provider_id_for_base_url,
)
from .provider_adapters import (
    AntigravityCLIAdapter,
    AnthropicAdapter,
    CodexCLIAdapter,
    GeminiAdapter,
    OpenAICompatibleAdapter,
)
from .runtime_gateway import RuntimeModelGateway

__all__ = [
    "BUILTIN_PROVIDER_IDS",
    "CapabilityObservation",
    "CapabilityProvenance",
    "CapabilityRecord",
    "ContextPreflightResult",
    "AnthropicAdapter",
    "AntigravityCLIAdapter",
    "CodexCLIAdapter",
    "GeminiAdapter",
    "ModelGateway",
    "ModelCapabilityResolver",
    "ModelCapabilityStore",
    "ModelIdentity",
    "ModelProfile",
    "ModelRequest",
    "ModelResponse",
    "ProviderDefinition",
    "OpenAICompatibleAdapter",
    "RuntimeModelGateway",
    "StreamingDecision",
    "decide_streaming",
    "effective_streaming",
    "normalize_base_url",
    "normalize_model_error",
    "preflight_context",
    "provider_definition",
    "provider_id_for_base_url",
    "resolve_model_profile",
]
