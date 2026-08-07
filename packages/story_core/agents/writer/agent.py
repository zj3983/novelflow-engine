"""Writer agent.

The agent wraps a ``WriterRuntime`` and a prompt builder. It
owns the only "request in / result out" path the writer has,
so the rest of the codebase never has to know whether the
backing provider is Codex CLI, Gemini CLI, or HTTP API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ..contracts import WriterRequest, WriterResult
from .prompt import build_writer_prompt
from .runtime import WriterRuntime


@dataclass
class _ModelRequest:
    """The minimal model-call payload the agent sends.

    The runtime is free to translate this into whatever the
    underlying transport expects; the agent itself only relies
    on ``prompt`` and ``metadata`` being preserved.
    """

    prompt: str
    stage: str
    metadata: dict[str, Any]


def _extract_text(response: Any) -> str:
    """Pull the body text out of whatever response the runtime returned."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    raw = getattr(response, "raw", None)
    if isinstance(raw, dict):
        for key in ("text", "body", "content"):
            value = raw.get(key)
            if isinstance(value, str):
                return value
    return ""


def _extract_proposed_facts(response: Any) -> list[dict[str, Any]]:
    """Pull the proposed facts the writer wants to attach to the chapter."""
    if response is None:
        return []
    raw = getattr(response, "raw", None)
    if isinstance(raw, dict):
        facts = raw.get("proposed_facts")
        if isinstance(facts, list):
            return [item for item in facts if isinstance(item, dict)]
    return []


class WriterAgent:
    """The single writer boundary.

    The agent takes one ``WriterRequest`` and produces one
    ``WriterResult`` per call. No provider-specific branching
    lives here; the runtime decides which transport to use.
    """

    def __init__(self, runtime: WriterRuntime) -> None:
        self._runtime = runtime

    def run(self, request: WriterRequest) -> WriterResult:
        prompt = build_writer_prompt(request)
        model_request = _ModelRequest(
            prompt=prompt,
            stage="writer",
            metadata={
                "chapter_number": request.chapter_number,
                "agent": "writer",
                "schema_version": request.director_artifact.schema_version,
            },
        )
        response = self._runtime.complete(model_request)
        body = _extract_text(response).strip()
        if not body:
            raise RuntimeError("writer_empty_body")
        return WriterResult(
            body=body,
            proposed_facts=_extract_proposed_facts(response),
            word_count=len("".join(body.split())),
            notes="",
        )


__all__ = ["WriterAgent"]
