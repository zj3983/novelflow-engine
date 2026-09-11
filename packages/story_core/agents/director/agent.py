"""Director agent.

The director decides *what* happens. It is the only path that
turns a director context into a ``DirectorArtifact``; the
writer never sees the raw prompt that produced the artifact.
The agent boundary is:

* one ``DirectorContext`` in, one ``DirectorArtifact`` out
  per ``plan(...)`` call;
* the agent always calls a ``DirectorRuntime`` and parses the
  response into the canonical ``DirectorArtifact`` — the
  outline is an input, not a substitute for an executable
  plan;
* the artifact is validated before it is persisted; a bad
  response (empty scene_beats, missing causal results) raises
  so the writer never has to improvise against a half-built
  plan;
* every run is persisted under
  ``.story-system/director/NNNN.json`` with the input trace,
  the output, the provider, the model, and the status.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..contracts import DirectorArtifact
from ...context.director_context import DirectorContext
from ...context.contracts import ArtifactRead, ContextTrace
from ...persistence.director_store import DirectorStore
from .prompt import (
    build_director_prompt,
    outline_chapter_number,
    parse_director_response,
    planned_chapter_title,
)
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

        candidate = text.strip()
        if candidate.startswith("```"):
            lines = candidate.splitlines()
            if lines and lines[0].strip().lower() in {"```", "```json"}:
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            candidate = "\n".join(lines).strip()
        try:
            parsed = json.loads(candidate)
        except ValueError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _validate_executable_artifact(artifact: DirectorArtifact) -> None:
    """Reject director outputs the writer cannot execute.

    A director response is only useful when it has at least two
    scene beats (one is rarely a real chapter), every beat has
    a non-empty location / action / result (the writer needs
    the causal chain to write prose), and the chapter goal and
    ending state are populated. A validation failure here is a
    blocking finding for the orchestrator — the writer never
    improvises against a half-built plan.
    """
    if len(artifact.scene_beats) < 2:
        raise ValueError("director_artifact_insufficient_beats")
    for beat in artifact.scene_beats:
        if not beat.location or not beat.action or not beat.result:
            raise ValueError("director_artifact_incomplete_beat")
    if not artifact.chapter_goal.strip() or not artifact.ending_state.strip():
        raise ValueError("director_artifact_missing_state")


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

    def plan(self, context: DirectorContext, *, persist: bool = True) -> DirectorArtifact:
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
            number = outline_chapter_number(entry)
            if number is None:
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
        # Always call the director runtime. The plan rule says
        # the outline is an *input* the model has to expand into
        # a real chapter plan, never a substitute for the plan
        # itself. Earlier rounds short-circuited this and the
        # writer then had to improvise against an empty
        # ``scene_beats`` list.
        planned_title = planned_chapter_title(context)
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
        artifact: DirectorArtifact | None = None
        last_error: Exception | None = None
        for attempt in range(2):
            attempt_request = _ModelRequest(
                prompt=model_request.prompt,
                stage=model_request.stage,
                metadata={**model_request.metadata, "attempt": attempt + 1},
            )
            try:
                response = self._runtime.complete(attempt_request)
                if getattr(response, "ok", True) is False:
                    error = str(getattr(response, "error", "") or "model_call_failed")
                    raise RuntimeError(f"director_unavailable:{error}")
                payload = _extract_payload(response)
                payload.setdefault("chapter_number", context.chapter_number)
                artifact = parse_director_response(payload)
                _validate_executable_artifact(artifact)
                break
            except (RuntimeError, ValueError) as exc:
                last_error = exc
                if attempt == 1:
                    raise
        if artifact is None:  # pragma: no cover - defensive loop invariant
            raise last_error or RuntimeError("director_unavailable")
        if planned_title:
            artifact = artifact.model_copy(update={"chapter_title": planned_title})
        if persist:
            self._store.save(
                chapter_number=context.chapter_number,
                payload={
                    "status": "ok",
                    "provider": self._provider,
                    "model": self._model,
                    "input_trace": trace.model_dump(mode="json"),
                    "output": artifact.model_dump(mode="json"),
                },
            )
        return artifact


__all__ = ["DirectorAgent"]
