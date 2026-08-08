"""Persistence for per-stage workflow artifacts.

Each generation job records the artifacts (reads, module ids, model
metadata, prompt template id, output path, summary, elapsed time)
that every stage produced. The workbench pulls this record on
page refresh so the operator can audit what each agent saw and
emitted without re-running the pipeline.

Layout::

    .story-system/workflow/{job_id}/{stage_id}.json
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKFLOW_ARTIFACT_SCHEMA = "workflow-artifact/v1"

# ``job_id`` and ``stage_id`` end up as path components inside
# ``.story-system/workflow/``; an attacker-controlled value with
# ``..`` or a drive letter would let an API caller escape the
# directory. The store rejects anything that is not a plain
# identifier built from safe characters. The check is intentionally
# conservative — real job ids come from the orchestrator
# (``chapter-{N}-{timestamp}``), real stage ids come from the
# pipeline (e.g. ``director``, ``writer``, ``fact-extractor``).
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_id(label: str, value: str) -> str:
    """Reject path-traversal payloads in job / stage ids.

    Empty strings, ``..``, absolute paths, separators, and
    characters outside ``[A-Za-z0-9._-]`` are all rejected. The
    cap of 128 chars matches the file name limit on common file
    systems and prevents absurdly long ids that would still
    otherwise pass the charset check.
    """
    if not isinstance(value, str) or not value:
        raise ValueError(f"workflow_artifact_invalid_{label}: empty")
    if not _SAFE_ID_RE.match(value):
        raise ValueError(f"workflow_artifact_invalid_{label}: {value!r}")
    if value in {".", ".."}:
        raise ValueError(f"workflow_artifact_invalid_{label}: {value!r}")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StageArtifactRecord:
    """One stage's per-step artifact record."""

    stage_id: str
    agent_id: str
    status: str  # "running" | "done" | "failed"
    started_at: str = ""
    finished_at: str = ""
    elapsed_ms: int = 0
    artifact_path: str = ""
    artifact_sha256: str = ""
    reads: list[dict[str, Any]] = field(default_factory=list)
    selected_entity_ids: list[str] = field(default_factory=list)
    selected_module_ids: list[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    prompt_template_id: str = ""
    prompt_template_version: str = ""
    output_summary: str = ""
    error: str = ""
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": WORKFLOW_ARTIFACT_SCHEMA,
            "stage_id": self.stage_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_ms": self.elapsed_ms,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "reads": list(self.reads),
            "selected_entity_ids": list(self.selected_entity_ids),
            "selected_module_ids": list(self.selected_module_ids),
            "provider": self.provider,
            "model": self.model,
            "prompt_template_id": self.prompt_template_id,
            "prompt_template_version": self.prompt_template_version,
            "output_summary": self.output_summary,
            "error": self.error,
            "blocking_issues": list(self.blocking_issues),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StageArtifactRecord":
        return cls(
            stage_id=str(payload.get("stage_id") or ""),
            agent_id=str(payload.get("agent_id") or ""),
            status=str(payload.get("status") or "running"),
            started_at=str(payload.get("started_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
            elapsed_ms=int(payload.get("elapsed_ms") or 0),
            artifact_path=str(payload.get("artifact_path") or ""),
            artifact_sha256=str(payload.get("artifact_sha256") or ""),
            reads=list(payload.get("reads") or []),
            selected_entity_ids=list(payload.get("selected_entity_ids") or []),
            selected_module_ids=list(payload.get("selected_module_ids") or []),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            prompt_template_id=str(payload.get("prompt_template_id") or ""),
            prompt_template_version=str(payload.get("prompt_template_version") or ""),
            output_summary=str(payload.get("output_summary") or ""),
            error=str(payload.get("error") or ""),
            blocking_issues=list(payload.get("blocking_issues") or []),
        )


class WorkflowArtifactStore:
    """Filesystem-backed store for per-stage workflow artifacts."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.directory = self.root / ".story-system" / "workflow"

    def job_dir(self, job_id: str) -> Path:
        return self.directory / _validate_id("job_id", job_id)

    def stage_path(self, job_id: str, stage_id: str) -> Path:
        return self.job_dir(job_id) / f"{_validate_id('stage_id', stage_id)}.json"

    def write_stage(self, job_id: str, record: StageArtifactRecord) -> Path:
        target = self.stage_path(job_id, record.stage_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not record.started_at:
            record.started_at = _now()
        if not record.finished_at and record.status in {"done", "failed"}:
            record.finished_at = _now()
        target.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    def read_stage(self, job_id: str, stage_id: str) -> StageArtifactRecord | None:
        target = self.stage_path(job_id, stage_id)
        if not target.is_file():
            return None
        return StageArtifactRecord.from_dict(json.loads(target.read_text(encoding="utf-8")))

    def list_stages(self, job_id: str) -> list[StageArtifactRecord]:
        job = self.job_dir(job_id)
        if not job.is_dir():
            return []
        return [
            StageArtifactRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(job.glob("*.json"))
        ]


__all__ = [
    "StageArtifactRecord",
    "WORKFLOW_ARTIFACT_SCHEMA",
    "WorkflowArtifactStore",
]
