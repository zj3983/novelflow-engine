"""Provider-neutral model call contracts and adapters."""

from .contracts import ModelGateway, ModelRequest, ModelResponse, normalize_model_error
from .provider_catalog import (
    BUILTIN_PROVIDER_IDS,
    ProviderDefinition,
    provider_definition,
    provider_id_for_base_url,
)

__all__ = [
    "BUILTIN_PROVIDER_IDS",
    "ModelGateway",
    "ModelRequest",
    "ModelResponse",
    "ProviderDefinition",
    "normalize_model_error",
    "provider_definition",
    "provider_id_for_base_url",
]
