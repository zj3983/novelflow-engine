"""Small provider-neutral contracts shared by CLI and HTTP model callers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class ModelRequest:
    prompt: str
    provider: str
    model: str
    operation: str
    system_prompt: str = ""
    messages: tuple[Mapping[str, Any], ...] = ()
    temperature: float | None = None
    max_tokens: int | None = None
    json_mode: bool = False
    timeout_seconds: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    # Zero-based indexes into ``messages`` whose contents are explicitly
    # optional context. They may be removed only by the shared preflight
    # compaction path; the system prompt and legacy ``prompt`` are required.
    optional_input_messages: tuple[int, ...] = ()
    # ``best_effort`` preserves legacy callers that use max_tokens as a
    # planning budget. Adapters enforce it when they can; protocols without a
    # verifiable output cap may continue and must report estimate-only mode.
    # ``required`` makes an executable provider-side cap part of the request
    # contract, so preflight blocks protocols that cannot enforce one.
    output_limit_requirement: Literal["best_effort", "required"] = "best_effort"

    def __post_init__(self) -> None:
        if self.output_limit_requirement not in ("best_effort", "required"):
            raise ValueError("invalid_output_limit_requirement")

    def normalized_messages(self) -> tuple[dict[str, Any], ...]:
        """Return a chat-style representation while preserving legacy prompts."""

        normalized: list[dict[str, Any]] = []
        if self.system_prompt.strip():
            normalized.append({"role": "system", "content": self.system_prompt})
        if self.messages:
            normalized.extend(dict(message) for message in self.messages)
        elif self.prompt:
            normalized.append({"role": "user", "content": self.prompt})
        return tuple(normalized)


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
    temperature_omitted: bool = False
    resolved_model: str = ""
    preflight_report: Mapping[str, Any] = field(default_factory=dict)

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
            resolved_model=(
                str(raw.get("model") or "") if isinstance(raw, dict) else ""
            ),
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
