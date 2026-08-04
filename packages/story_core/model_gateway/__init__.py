"""Provider-neutral model call contracts and adapters."""

from .contracts import ModelGateway, ModelRequest, ModelResponse, normalize_model_error
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
    "AnthropicAdapter",
    "AntigravityCLIAdapter",
    "CodexCLIAdapter",
    "GeminiAdapter",
    "ModelGateway",
    "ModelRequest",
    "ModelResponse",
    "ProviderDefinition",
    "OpenAICompatibleAdapter",
    "RuntimeModelGateway",
    "normalize_model_error",
    "provider_definition",
    "provider_id_for_base_url",
]
