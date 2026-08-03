"""Small provider-neutral contracts shared by CLI and HTTP model callers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class ModelRequest:
    prompt: str
    provider: str
    model: str
    operation: str
    system_prompt: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelResponse:
    ok: bool
    text: str
    provider: str
    model: str
    operation: str
    request_id: str = ""
    usage: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""
    raw: Any = None

    @classmethod
    def success(
        cls,
        request: ModelRequest,
        *,
        text: str,
        request_id: str = "",
        usage: Mapping[str, Any] | None = None,
        raw: Any = None,
    ) -> "ModelResponse":
        return cls(
            ok=True,
            text=str(text or ""),
            provider=request.provider,
            model=request.model,
            operation=request.operation,
            request_id=request_id,
            usage=dict(usage or {}),
            raw=raw,
        )

    @classmethod
    def failure(cls, request: ModelRequest, error: str, *, raw: Any = None) -> "ModelResponse":
        return cls(
            ok=False,
            text="",
            provider=request.provider,
            model=request.model,
            operation=request.operation,
            error=str(error or "model_call_failed"),
            raw=raw,
        )


@runtime_checkable
class ModelGateway(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse: ...


def normalize_model_error(response: ModelResponse) -> str:
    """Return a stable diagnostic that can be shown in workflow logs."""

    if response.ok:
        return ""
    location = "/".join(
        value or "unknown"
        for value in (response.provider, response.model, response.operation)
    )
    return f"{location}: {response.error or 'model_call_failed'}"
