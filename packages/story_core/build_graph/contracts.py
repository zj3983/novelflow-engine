"""Provider-neutral contracts for the versioned Build Graph core.

The graph package deliberately has no knowledge of world-building domains or
model providers.  It persists only task state, validated artifacts, bounded
provenance, and structured diagnostics.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping


BUILD_GRAPH_STATE_SCHEMA = "build-graph-state/v1"
BUILD_ARTIFACT_SCHEMA = "build-artifact/v1"
BUILD_RUN_SCHEMA = "build-run/v1"

TaskStatus = Literal[
    "pending",
    "blocked",
    "ready",
    "running",
    "validation_failed",
    "review_required",
    "completed",
    "stale",
]
ValidationStatus = Literal["unknown", "pending", "passed", "failed", "review_required"]
ReviewPolicy = Literal["auto", "review"]
ArtifactSource = Literal["llm", "ai_repair", "human", "imported", "deterministic"]
DiagnosticSeverity = Literal["warning", "blocking"]
Disposition = Literal["PASS_AUTO", "PASS_REVIEW", "FAIL"]
RunStatus = Literal["running", "committed", "failed", "conflict"]

TASK_STATUSES: tuple[str, ...] = (
    "pending",
    "blocked",
    "ready",
    "running",
    "validation_failed",
    "review_required",
    "completed",
    "stale",
)
VALIDATION_STATUSES: tuple[str, ...] = (
    "unknown",
    "pending",
    "passed",
    "failed",
    "review_required",
)
REVIEW_POLICIES: tuple[str, ...] = ("auto", "review")
ARTIFACT_SOURCES: tuple[str, ...] = (
    "llm",
    "ai_repair",
    "human",
    "imported",
    "deterministic",
)
DIAGNOSTIC_SEVERITIES: tuple[str, ...] = ("warning", "blocking")
DISPOSITIONS: tuple[str, ...] = ("PASS_AUTO", "PASS_REVIEW", "FAIL")
RUN_STATUSES: tuple[str, ...] = ("running", "committed", "failed", "conflict")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_tuple(values: Any) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        return (values,)
    if not isinstance(values, (list, tuple, set, frozenset)):
        return ()
    return tuple(str(value) for value in values)


class BuildGraphError(ValueError):
    """Stable, machine-readable Build Graph failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: str = "",
        details: Mapping[str, Any] | None = None,
        diagnostics: tuple["BuildDiagnostic", ...] = (),
    ) -> None:
        self.code = str(code)
        self.path = str(path or "")
        self.details = dict(details or {})
        self.diagnostics = tuple(diagnostics)
        super().__init__(str(message))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "message": str(self),
            "details": deepcopy(self.details),
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


class BuildDefinitionError(BuildGraphError):
    pass


class BuildOwnershipViolation(BuildGraphError):
    pass


class BuildRevisionConflict(BuildGraphError):
    pass


class BuildRunConflict(BuildGraphError):
    pass


class BuildTaskStateError(BuildGraphError):
    pass


@dataclass(frozen=True)
class BuildDiagnostic:
    code: str
    path: str
    message: str
    severity: DiagnosticSeverity = "blocking"
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.code).strip():
            raise ValueError("build_diagnostic_code_required")
        if self.severity not in DIAGNOSTIC_SEVERITIES:
            raise ValueError("build_diagnostic_severity_invalid")
        object.__setattr__(self, "code", str(self.code).strip())
        object.__setattr__(self, "path", str(self.path or "").strip())
        object.__setattr__(self, "message", str(self.message or "").strip())
        object.__setattr__(self, "details", deepcopy(dict(self.details or {})))

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "severity": self.severity,
        }
        if self.details:
            payload["details"] = deepcopy(dict(self.details))
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BuildDiagnostic":
        return cls(
            code=str(value.get("code") or "unknown"),
            path=str(value.get("path") or ""),
            message=str(value.get("message") or ""),
            severity=str(value.get("severity") or "blocking"),  # type: ignore[arg-type]
            details=value.get("details") if isinstance(value.get("details"), Mapping) else {},
        )


@dataclass(frozen=True)
class BuildValidationResult:
    passed: bool
    diagnostics: tuple[BuildDiagnostic, ...] = ()
    disposition: Disposition | None = None

    def __post_init__(self) -> None:
        diagnostics = tuple(self.diagnostics)
        if any(item.severity == "blocking" for item in diagnostics):
            object.__setattr__(self, "passed", False)
        else:
            object.__setattr__(self, "passed", bool(self.passed))
        if self.disposition is not None and self.disposition not in DISPOSITIONS:
            raise ValueError("build_disposition_invalid")
        object.__setattr__(self, "diagnostics", diagnostics)

    @property
    def blocking(self) -> tuple[BuildDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "blocking")

    @property
    def warnings(self) -> tuple[BuildDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "warning")

    def with_disposition(self, disposition: Disposition) -> "BuildValidationResult":
        return BuildValidationResult(
            passed=self.passed,
            diagnostics=self.diagnostics,
            disposition=disposition,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "disposition": self.disposition,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "BuildValidationResult":
        raw = value or {}
        diagnostics = tuple(
            BuildDiagnostic.from_dict(item)
            for item in raw.get("diagnostics", [])
            if isinstance(item, Mapping)
        )
        disposition = raw.get("disposition")
        return cls(
            passed=bool(raw.get("passed", not any(item.severity == "blocking" for item in diagnostics))),
            diagnostics=diagnostics,
            disposition=str(disposition) if disposition else None,  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class BuildTaskState:
    task_id: str
    status: TaskStatus = "pending"
    current_artifact_revision: int | None = None
    active_run_id: str | None = None
    dependency_revisions: Mapping[str, int] = field(default_factory=dict)
    validation_status: ValidationStatus = "unknown"
    diagnostics: tuple[BuildDiagnostic, ...] = ()
    updated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if self.status not in TASK_STATUSES:
            raise ValueError("build_task_status_invalid")
        if self.validation_status not in VALIDATION_STATUSES:
            raise ValueError("build_validation_status_invalid")
        if self.current_artifact_revision is not None and self.current_artifact_revision < 1:
            raise ValueError("build_artifact_revision_invalid")
        object.__setattr__(self, "dependency_revisions", dict(self.dependency_revisions))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "updated_at", str(self.updated_at or utc_now_iso()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "current_artifact_revision": self.current_artifact_revision,
            "active_run_id": self.active_run_id,
            "dependency_revisions": dict(sorted(self.dependency_revisions.items())),
            "validation_status": self.validation_status,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BuildTaskState":
        diagnostics = tuple(
            BuildDiagnostic.from_dict(item)
            for item in value.get("diagnostics", [])
            if isinstance(item, Mapping)
        )
        raw_revisions = value.get("dependency_revisions")
        revisions = (
            {str(key): int(item) for key, item in raw_revisions.items()}
            if isinstance(raw_revisions, Mapping)
            else {}
        )
        return cls(
            task_id=str(value.get("task_id") or ""),
            status=str(value.get("status") or "pending"),  # type: ignore[arg-type]
            current_artifact_revision=(
                int(value["current_artifact_revision"])
                if value.get("current_artifact_revision") is not None
                else None
            ),
            active_run_id=(str(value["active_run_id"]) if value.get("active_run_id") else None),
            dependency_revisions=revisions,
            validation_status=str(value.get("validation_status") or "unknown"),  # type: ignore[arg-type]
            diagnostics=diagnostics,
            updated_at=str(value.get("updated_at") or utc_now_iso()),
        )


@dataclass(frozen=True)
class BuildArtifact:
    artifact_id: str
    task_id: str
    schema_version: str
    revision: int
    payload: Any
    source: ArtifactSource
    dependency_revisions: Mapping[str, int]
    validation: BuildValidationResult
    created_at: str
    provider: str | None = None
    model: str | None = None
    prompt_call_id: str | None = None
    parent_revision: int | None = None
    written_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.revision < 1:
            raise ValueError("build_artifact_revision_invalid")
        if self.source not in ARTIFACT_SOURCES:
            raise ValueError("build_artifact_source_invalid")
        if self.parent_revision is not None and self.parent_revision < 1:
            raise ValueError("build_parent_revision_invalid")
        object.__setattr__(self, "dependency_revisions", dict(self.dependency_revisions))
        object.__setattr__(self, "written_paths", _as_tuple(self.written_paths))
        object.__setattr__(self, "provider", str(self.provider).strip() if self.provider else None)
        object.__setattr__(self, "model", str(self.model).strip() if self.model else None)
        object.__setattr__(
            self,
            "prompt_call_id",
            str(self.prompt_call_id).strip() if self.prompt_call_id else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "task_id": self.task_id,
            "schema_version": self.schema_version,
            "revision": self.revision,
            "payload": deepcopy(self.payload),
            "source": self.source,
            "dependency_revisions": dict(sorted(self.dependency_revisions.items())),
            "validation": self.validation.to_dict(),
            "created_at": self.created_at,
            "provider": self.provider,
            "model": self.model,
            "prompt_call_id": self.prompt_call_id,
            "parent_revision": self.parent_revision,
            "written_paths": list(self.written_paths),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BuildArtifact":
        raw_revisions = value.get("dependency_revisions")
        revisions = (
            {str(key): int(item) for key, item in raw_revisions.items()}
            if isinstance(raw_revisions, Mapping)
            else {}
        )
        return cls(
            artifact_id=str(value.get("artifact_id") or ""),
            task_id=str(value.get("task_id") or ""),
            schema_version=str(value.get("schema_version") or BUILD_ARTIFACT_SCHEMA),
            revision=int(value.get("revision") or 0),
            payload=deepcopy(value.get("payload")),
            source=str(value.get("source") or "imported"),  # type: ignore[arg-type]
            dependency_revisions=revisions,
            validation=BuildValidationResult.from_dict(value.get("validation")),
            created_at=str(value.get("created_at") or utc_now_iso()),
            provider=str(value["provider"]) if value.get("provider") else None,
            model=str(value["model"]) if value.get("model") else None,
            prompt_call_id=str(value["prompt_call_id"]) if value.get("prompt_call_id") else None,
            parent_revision=(int(value["parent_revision"]) if value.get("parent_revision") is not None else None),
            written_paths=_as_tuple(value.get("written_paths")),
        )


@dataclass(frozen=True)
class BuildRun:
    run_id: str
    task_id: str
    base_artifact_revision: int | None
    dependency_revisions: Mapping[str, int]
    started_at: str
    status: RunStatus = "running"
    finished_at: str | None = None
    diagnostics: tuple[BuildDiagnostic, ...] = ()
    input_fingerprint: str | None = None
    read_projection: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.status not in RUN_STATUSES:
            raise ValueError("build_run_status_invalid")
        if self.base_artifact_revision is not None and self.base_artifact_revision < 1:
            raise ValueError("build_run_revision_invalid")
        object.__setattr__(self, "dependency_revisions", dict(self.dependency_revisions))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if self.read_projection is not None:
            object.__setattr__(self, "read_projection", deepcopy(dict(self.read_projection)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BUILD_RUN_SCHEMA,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "base_artifact_revision": self.base_artifact_revision,
            "dependency_revisions": dict(sorted(self.dependency_revisions.items())),
            "started_at": self.started_at,
            "status": self.status,
            "finished_at": self.finished_at,
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "input_fingerprint": self.input_fingerprint,
            "read_projection": deepcopy(self.read_projection),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BuildRun":
        raw_revisions = value.get("dependency_revisions")
        revisions = (
            {str(key): int(item) for key, item in raw_revisions.items()}
            if isinstance(raw_revisions, Mapping)
            else {}
        )
        diagnostics = tuple(
            BuildDiagnostic.from_dict(item)
            for item in value.get("diagnostics", [])
            if isinstance(item, Mapping)
        )
        projection = value.get("read_projection")
        return cls(
            run_id=str(value.get("run_id") or ""),
            task_id=str(value.get("task_id") or ""),
            base_artifact_revision=(
                int(value["base_artifact_revision"])
                if value.get("base_artifact_revision") is not None
                else None
            ),
            dependency_revisions=revisions,
            started_at=str(value.get("started_at") or utc_now_iso()),
            status=str(value.get("status") or "running"),  # type: ignore[arg-type]
            finished_at=str(value["finished_at"]) if value.get("finished_at") else None,
            diagnostics=diagnostics,
            input_fingerprint=(str(value["input_fingerprint"]) if value.get("input_fingerprint") else None),
            read_projection=projection if isinstance(projection, Mapping) else None,
        )


@dataclass(frozen=True)
class BuildGraphState:
    schema_version: str
    graph_id: str
    graph_revision: int
    tasks: Mapping[str, BuildTaskState]
    runs: Mapping[str, BuildRun] = field(default_factory=dict)
    definition_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "graph_id": self.graph_id,
            "graph_revision": self.graph_revision,
            "definition_fingerprint": self.definition_fingerprint,
            "tasks": {
                key: self.tasks[key].to_dict() for key in sorted(self.tasks)
            },
            "runs": {key: self.runs[key].to_dict() for key in sorted(self.runs)},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BuildGraphState":
        raw_tasks = value.get("tasks")
        tasks = {
            str(key): BuildTaskState.from_dict(item)
            for key, item in raw_tasks.items()
            if isinstance(item, Mapping)
        } if isinstance(raw_tasks, Mapping) else {}
        raw_runs = value.get("runs")
        runs = {
            str(key): BuildRun.from_dict(item)
            for key, item in raw_runs.items()
            if isinstance(item, Mapping)
        } if isinstance(raw_runs, Mapping) else {}
        return cls(
            schema_version=str(value.get("schema_version") or BUILD_GRAPH_STATE_SCHEMA),
            graph_id=str(value.get("graph_id") or ""),
            graph_revision=int(value.get("graph_revision") or 0),
            tasks=tasks,
            runs=runs,
            definition_fingerprint=str(value.get("definition_fingerprint") or ""),
        )


@dataclass(frozen=True)
class BuildReadiness:
    ready: bool
    blocked_by: tuple[str, ...] = ()
    stale_tasks: tuple[str, ...] = ()
    failed_tasks: tuple[str, ...] = ()
    review_required_tasks: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "blocked_by": list(self.blocked_by),
            "stale_tasks": list(self.stale_tasks),
            "failed_tasks": list(self.failed_tasks),
            "review_required_tasks": list(self.review_required_tasks),
        }


@dataclass(frozen=True)
class BuildCommitResult:
    artifact: BuildArtifact | None
    validation: BuildValidationResult
    disposition: Disposition
    task_state: BuildTaskState

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact.to_dict() if self.artifact else None,
            "validation": self.validation.to_dict(),
            "disposition": self.disposition,
            "task_state": self.task_state.to_dict(),
        }


__all__ = [
    "ARTIFACT_SOURCES",
    "BUILD_ARTIFACT_SCHEMA",
    "BUILD_GRAPH_STATE_SCHEMA",
    "BUILD_RUN_SCHEMA",
    "BuildArtifact",
    "BuildCommitResult",
    "BuildDefinitionError",
    "BuildDiagnostic",
    "BuildGraphError",
    "BuildGraphState",
    "BuildOwnershipViolation",
    "BuildReadiness",
    "BuildRevisionConflict",
    "BuildRun",
    "BuildRunConflict",
    "BuildTaskState",
    "BuildTaskStateError",
    "BuildValidationResult",
    "DISPOSITIONS",
    "utc_now_iso",
]
