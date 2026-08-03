"""Provider-neutral model call contracts and adapters."""

from .contracts import ModelGateway, ModelRequest, ModelResponse, normalize_model_error

__all__ = ["ModelGateway", "ModelRequest", "ModelResponse", "normalize_model_error"]
