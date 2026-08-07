"""Director agent.

The director decides *what* happens. It is the only path that
turns a director context into a ``DirectorArtifact``; the
writer never sees the raw prompt that produced the artifact.
The agent boundary is:

* one ``DirectorContext`` in, one ``DirectorArtifact`` out
  per ``plan(...)`` call;
* when the context already contains the target chapter's
  outline, the agent skips the model call and derives the
  artifact directly;
* otherwise the agent calls a ``DirectorRuntime`` and parses
  the response into the canonical ``DirectorArtifact``;
* every run is persisted under
  ``.story-system/director/NNNN.json`` with the input trace,
  the output, the provider, the model, and the status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..contracts import DirectorArtifact
from ...context.director_context import DirectorContext
from ...context.contracts import ArtifactRead, ContextTrace
from ...persistence.director_store import DirectorStore
from .prompt import build_director_prompt, parse_director_response
from .runtime import DirectorRuntime


@dataclass
class _ModelRequest:
    prompt: str
    stage: str
    metadata: dict[str, Any]


def _extract_payload(response: Any) -> dict[str, Any]:
    if response is None:
        return {}
    if isinstance(response, dict):
        return response
    payload = getattr(response, "payload", None)
    if isinstance(payload, dict):
        return payload
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        import json

        try:
            parsed = json.loads(text)
        except ValueError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _outline_artifact(context: DirectorContext) -> Optional[DirectorArtifact]:
    """Derive an artifact from the context's outline when it is complete."""
    target = None
    for entry in context.nearby_outline:
        if isinstance(entry, dict) and entry.get("number") == context.chapter_number:
            target = entry
            break
    if not target:
        return None
    summary = str(target.get("summary") or "").strip()
    if not summary:
        return None
    return DirectorArtifact(
        chapter_number=context.chapter_number,
        chapter_goal=summary,
        opening_state=context.previous_chapter_tail or "",
        scene_beats=[],
        ending_state="",
        hook="",
        entity_requirements=[],
    )


class DirectorAgent:
    """The single director boundary.

    The agent takes a ``DirectorContext`` and produces a
    ``DirectorArtifact``. It never writes prose; it never
    reaches into the writer's view. Every call records a
    ``DirectorStore`` envelope so the workbench and the
    migration script can later prove what the director saw
    and produced.
    """

    def __init__(
        self,
        *,
        runtime: DirectorRuntime,
        project_root: Any,
        provider: str = "",
        model: str = "",
        store: DirectorStore | None = None,
    ) -> None:
        self._runtime = runtime
        self._project_root = project_root
        self._provider = provider or "outline"
        self._model = model or "outline/v1"
        self._store = store or DirectorStore(project_root)

    @property
    def store(self) -> DirectorStore:
        return self._store

    def plan(self, context: DirectorContext) -> DirectorArtifact:
        trace = ContextTrace(agent="director", chapter_number=context.chapter_number)
        # Record what the director consumed from the project. The
        # workbench and the migration script use this trace to
        # prove which structural artifacts each chapter plan
        # depended on.
        if context.volume:
            trace.add(
                ArtifactRead(
                    kind="volume",
                    path="volume.json",
                    sha256="",
                    chars=len(str(context.volume)),
                )
            )
        for entry in context.nearby_outline:
            if not isinstance(entry, dict):
                continue
            number = entry.get("number")
            if not isinstance(number, int):
                continue
            trace.add(
                ArtifactRead(
                    kind="outline",
                    path=f"outline.json#chapter-{number:04d}",
                    sha256="",
                    chars=len(str(entry.get("summary") or "")),
                )
            )
        if context.previous_chapter_summary:
            trace.add(
                ArtifactRead(
                    kind="previous-chapter",
                    path=f"chapters/{context.chapter_number - 1:04d}.json",
                    sha256="",
                    chars=len(context.previous_chapter_summary),
                )
            )
        outline_artifact = _outline_artifact(context)
        status = "ok"
        provider = self._provider
        model = self._model
        if outline_artifact is not None:
            artifact = outline_artifact
            status = "outline_only"
        else:
            prompt = build_director_prompt(context)
            model_request = _ModelRequest(
                prompt=prompt,
                stage="director",
                metadata={
                    "chapter_number": context.chapter_number,
                    "agent": "director",
                    "schema_version": "director-artifact/v1",
                },
            )
            response = self._runtime.complete(model_request)
            payload = _extract_payload(response)
            payload.setdefault("chapter_number", context.chapter_number)
            artifact = parse_director_response(payload)
        self._store.save(
            chapter_number=context.chapter_number,
            payload={
                "status": status,
                "provider": provider,
                "model": model,
                "input_trace": trace.model_dump(mode="json"),
                "output": artifact.model_dump(mode="json"),
            },
        )
        return artifact


__all__ = ["DirectorAgent"]
