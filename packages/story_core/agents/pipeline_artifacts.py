"""Bridge between the modular agent pipeline and the on-disk
workflow artifact store.

Every stage of the modular pipeline (Director, Writer,
FactExtractor) is recorded under
``.story-system/workflow/{job_id}/{stage_id}.json`` so the
workbench can re-render what each agent saw and produced
without re-running the model. The record is the same shape
the workbench already speaks — a :class:`StageArtifactRecord`
— so the UI does not need a second reader.

The bridge is intentionally side-effect-free: callers pass in
the store and the helper serialises whatever the stage
returned. The pipeline never reaches into the store directly,
and the store never reaches into the pipeline — the two
sides meet through this module.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from ..continuity.delta import ContinuityDelta
from ..context.director_context import DirectorContext
from ..context.writer_context import WriterContext
from ..persistence.workflow_artifact_store import (
    StageArtifactRecord,
    WorkflowArtifactStore,
)
from .contracts import DirectorArtifact, WriterResult


def _truncate(text: str, *, limit: int = 40) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _stage_elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _summarise_director(artifact: DirectorArtifact) -> str:
    beats = len(artifact.scene_beats or [])
    requirements = len(artifact.entity_requirements or [])
    return (
        f"chapter_goal='{_truncate(artifact.chapter_goal)}' "
        f"beats={beats} requirements={requirements}"
    )


def _summarise_writer(body: str) -> str:
    return f"body_chars={len(body or '')}"


def _summarise_fact_extractor(delta: ContinuityDelta | None) -> str:
    if delta is None:
        return "delta=None"
    counts = {
        "entity_additions": len(delta.entity_additions or []),
        "entity_updates": len(delta.entity_updates or []),
        "relationship_changes": len(delta.relationship_changes or []),
        "inventory_changes": len(delta.inventory_changes or []),
        "task_progressions": len(delta.task_progressions or []),
        "location_movements": len(delta.location_movements or []),
        "timeline_advances": len(delta.timeline_advances or []),
        "foreshadowing_changes": len(delta.foreshadowing_changes or []),
    }
    return " ".join(f"{key}={value}" for key, value in counts.items() if value)


def _read_first_existing(
    paths: tuple[Path, ...], reader: Callable[[Path], bytes | None]
) -> dict[str, str]:
    """Best-effort: read each path through ``reader`` and
    return the first non-empty result. The bridge surfaces
    the artifact the stage wrote; the path comes from the
    agent, not the bridge.
    """
    for path in paths:
        try:
            content = reader(path)
        except OSError:
            continue
        if content is None:
            continue
        return {
            "path": str(path),
            "sha256": _sha256(content.decode("utf-8", errors="replace")),
        }
    return {"path": "", "sha256": ""}


def record_director_stage(
    *,
    store: WorkflowArtifactStore,
    job_id: str,
    artifact: DirectorArtifact,
    context: DirectorContext | None = None,
    started_monotonic: float | None = None,
    artifact_paths: tuple[Path, ...] = (),
    artifact_reader: Callable[[Path], bytes | None] | None = None,
    provider: str = "",
    model: str = "",
    prompt_template_id: str = "",
    prompt_template_version: str = "",
) -> Path:
    """Record the director stage outcome on disk.

    The director's reads come from the
    :class:`DirectorContext` it saw; the output is the
    :class:`DirectorArtifact` it produced. When the agent
    persisted the artifact under
    ``.story-system/director/NNNN.json`` the caller passes the
    path in ``artifact_paths`` so the bridge can link to it.
    """
    started_monotonic = (
        started_monotonic if started_monotonic is not None else time.monotonic()
    )
    reads: list[dict[str, Any]] = []
    if context is not None:
        if context.volume:
            reads.append({"kind": "volume", "id": str(context.volume.get("id") or "")})
        for entry in context.nearby_outline or []:
            if isinstance(entry, dict):
                number = entry.get("number")
                if isinstance(number, int):
                    reads.append({"kind": "outline", "id": f"chapter-{number:04d}"})
        if context.previous_chapter_summary:
            reads.append(
                {
                    "kind": "previous-chapter",
                    "id": f"chapter-{context.chapter_number - 1:04d}",
                }
            )
        for card in context.character_cards or []:
            if isinstance(card, dict):
                reads.append({"kind": "character", "id": str(card.get("name") or "")})
    artifact_meta = (
        _read_first_existing(artifact_paths, artifact_reader)
        if artifact_paths and artifact_reader
        else {"path": "", "sha256": ""}
    )
    record = StageArtifactRecord(
        stage_id="director",
        agent_id="DirectorAgent",
        status="done",
        elapsed_ms=_stage_elapsed_ms(started_monotonic),
        artifact_path=artifact_meta["path"],
        artifact_sha256=artifact_meta["sha256"],
        reads=reads,
        selected_entity_ids=[
            str(req.name or "")
            for req in (artifact.entity_requirements or [])
            if str(req.name or "")
        ],
        selected_module_ids=[],
        provider=provider,
        model=model,
        prompt_template_id=prompt_template_id,
        prompt_template_version=prompt_template_version,
        output_summary=_summarise_director(artifact),
        error="",
    )
    return store.write_stage(job_id, record)


def record_writer_stage(
    *,
    store: WorkflowArtifactStore,
    job_id: str,
    result: WriterResult,
    context: WriterContext | None = None,
    started_monotonic: float | None = None,
    provider: str = "",
    model: str = "",
    prompt_template_id: str = "",
    prompt_template_version: str = "",
) -> Path:
    """Record the writer stage outcome on disk."""
    started_monotonic = (
        started_monotonic if started_monotonic is not None else time.monotonic()
    )
    reads: list[dict[str, Any]] = []
    if context is not None:
        if context.director_artifact:
            reads.append(
                {
                    "kind": "director-artifact",
                    "id": f"chapter-{context.chapter_number:04d}",
                }
            )
        for card in context.character_cards or []:
            if isinstance(card, dict):
                reads.append({"kind": "character", "id": str(card.get("name") or "")})
        for card in context.entity_cards or []:
            if isinstance(card, dict):
                reads.append({"kind": "entity", "id": str(card.get("name") or "")})
    record = StageArtifactRecord(
        stage_id="writer",
        agent_id="WriterAgent",
        status="done",
        elapsed_ms=_stage_elapsed_ms(started_monotonic),
        artifact_path="",
        artifact_sha256=_sha256(result.body or ""),
        reads=reads,
        selected_entity_ids=[],
        selected_module_ids=[
            str(module.get("id") or "")
            for module in (context.craft_modules if context else [])
            if isinstance(module, dict) and str(module.get("id") or "")
        ],
        provider=provider,
        model=model,
        prompt_template_id=prompt_template_id,
        prompt_template_version=prompt_template_version,
        output_summary=_summarise_writer(result.body or ""),
        error="",
    )
    return store.write_stage(job_id, record)


def record_fact_extractor_stage(
    *,
    store: WorkflowArtifactStore,
    job_id: str,
    delta: ContinuityDelta | None,
    started_monotonic: float | None = None,
    provider: str = "",
    model: str = "",
) -> Path:
    """Record the fact-extractor stage outcome on disk."""
    started_monotonic = (
        started_monotonic if started_monotonic is not None else time.monotonic()
    )
    record = StageArtifactRecord(
        stage_id="fact-extractor",
        agent_id="FactExtractor",
        status="done",
        elapsed_ms=_stage_elapsed_ms(started_monotonic),
        artifact_path="",
        artifact_sha256="",
        reads=[],
        selected_entity_ids=[],
        selected_module_ids=[],
        provider=provider,
        model=model,
        prompt_template_id="",
        prompt_template_version="",
        output_summary=_summarise_fact_extractor(delta),
        error="",
    )
    return store.write_stage(job_id, record)


__all__ = [
    "record_director_stage",
    "record_writer_stage",
    "record_fact_extractor_stage",
]
