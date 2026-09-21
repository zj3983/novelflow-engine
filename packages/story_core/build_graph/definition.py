"""Immutable, provider-neutral Build Graph definitions.

Definitions are application code.  They describe what a task may read and
write, while the graph manifest stores only the project's mutable run state.
Keeping those two concerns separate is what lets the same graph be used by a
human editor, an AI run, or a deterministic repair.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from .contracts import (
    BuildDefinitionError,
    BuildDiagnostic,
    REVIEW_POLICIES,
    ReviewPolicy,
)


_TASK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PATH_SEGMENT_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_-]*(?:\[(?:0|[1-9][0-9]*|\*)\])?$"
)


def validate_task_id(task_id: str) -> str:
    value = str(task_id or "").strip()
    if not _TASK_ID_RE.fullmatch(value):
        raise BuildDefinitionError(
            "build_unsafe_task_id",
            "task_id must be a safe stable identifier",
            path="task_id",
            details={"task_id": value},
        )
    return value


def normalize_path(path: str) -> str:
    """Return a canonical dotted path or raise a stable definition error."""

    value = str(path or "").strip()
    if not value or value.startswith(".") or value.endswith(".") or ".." in value:
        raise BuildDefinitionError(
            "build_path_invalid",
            "ownership and projection paths must use canonical dotted notation",
            path=value,
        )
    segments = value.split(".")
    if any(not _PATH_SEGMENT_RE.fullmatch(segment) for segment in segments):
        raise BuildDefinitionError(
            "build_path_invalid",
            "ownership and projection paths must use canonical dotted notation",
            path=value,
        )
    return ".".join(segments)


def path_tokens(path: str) -> tuple[tuple[str, str], ...]:
    """Split a canonical path into field/index tokens for containment checks."""

    canonical = normalize_path(path)
    tokens: list[tuple[str, str]] = []
    for segment in canonical.split("."):
        if "[" in segment:
            field, index = segment[:-1].split("[", 1)
            tokens.append(("field", field))
            tokens.append(("index", index))
        else:
            tokens.append(("field", segment))
    return tuple(tokens)


def _tokens_compatible(left: tuple[str, str], right: tuple[str, str]) -> bool:
    if left[0] != right[0]:
        return False
    return left[1] == right[1] or (left[0] == "index" and "*" in {left[1], right[1]})


def paths_overlap(left: str, right: str) -> bool:
    """Whether two writes can address the same canonical path."""

    left_tokens = path_tokens(left)
    right_tokens = path_tokens(right)
    common = min(len(left_tokens), len(right_tokens))
    return all(
        _tokens_compatible(left_tokens[index], right_tokens[index])
        for index in range(common)
    )


def path_covers(owner: str, requested: str) -> bool:
    """Whether ``owner`` is broad enough to contain ``requested``."""

    owner_tokens = path_tokens(owner)
    requested_tokens = path_tokens(requested)
    if len(owner_tokens) > len(requested_tokens):
        return False
    return all(
        _tokens_compatible(owner_tokens[index], requested_tokens[index])
        for index in range(len(owner_tokens))
    )


def _normalize_paths(values: Iterable[str] | None) -> tuple[str, ...]:
    result: list[str] = []
    for value in values or ():
        canonical = normalize_path(value)
        if canonical not in result:
            result.append(canonical)
    return tuple(result)


@dataclass(frozen=True)
class BuildTaskDefinition:
    task_id: str
    title: str
    dependencies: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()
    owns: tuple[str, ...] = ()
    forbidden_writes: tuple[str, ...] = ()
    validator_id: str | None = None
    model_stage: str | None = None
    context_policy: Mapping[str, Any] | str | None = None
    output_budget: Mapping[str, Any] | int | None = None
    review_policy: ReviewPolicy = "auto"
    required_for_readiness: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", validate_task_id(self.task_id))
        title = str(self.title or "").strip()
        if not title:
            raise BuildDefinitionError(
                "build_task_title_required",
                "task title is required",
                path=f"tasks.{self.task_id}.title",
            )
        object.__setattr__(self, "title", title)
        dependencies = tuple(str(item).strip() for item in self.dependencies or ())
        if any(not item for item in dependencies):
            raise BuildDefinitionError(
                "build_dependency_invalid",
                "dependency identifiers cannot be empty",
                path=f"tasks.{self.task_id}.dependencies",
            )
        if len(set(dependencies)) != len(dependencies):
            raise BuildDefinitionError(
                "build_dependency_duplicate",
                "a task cannot list the same dependency twice",
                path=f"tasks.{self.task_id}.dependencies",
            )
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "reads", _normalize_paths(self.reads))
        object.__setattr__(self, "owns", _normalize_paths(self.owns))
        object.__setattr__(self, "forbidden_writes", _normalize_paths(self.forbidden_writes))
        if self.review_policy not in REVIEW_POLICIES:
            raise BuildDefinitionError(
                "build_review_policy_invalid",
                "review_policy must be auto or review",
                path=f"tasks.{self.task_id}.review_policy",
            )
        object.__setattr__(self, "review_policy", str(self.review_policy))
        if self.validator_id is not None:
            object.__setattr__(self, "validator_id", str(self.validator_id).strip() or None)
        if self.model_stage is not None:
            object.__setattr__(self, "model_stage", str(self.model_stage).strip() or None)
        object.__setattr__(self, "required_for_readiness", bool(self.required_for_readiness))

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "dependencies": list(self.dependencies),
            "reads": list(self.reads),
            "owns": list(self.owns),
            "forbidden_writes": list(self.forbidden_writes),
            "validator_id": self.validator_id,
            "model_stage": self.model_stage,
            "context_policy": self.context_policy,
            "output_budget": self.output_budget,
            "review_policy": self.review_policy,
            "required_for_readiness": self.required_for_readiness,
        }

    def semantic_dict(self) -> dict[str, Any]:
        """Return only fields whose changes alter execution semantics."""

        return {
            "task_id": self.task_id,
            "dependencies": sorted(self.dependencies),
            "reads": sorted(self.reads),
            "owns": sorted(self.owns),
            "forbidden_writes": sorted(self.forbidden_writes),
            "validator_id": self.validator_id,
            "model_stage": self.model_stage,
            "context_policy": self.context_policy,
            "output_budget": self.output_budget,
            "review_policy": self.review_policy,
            "required_for_readiness": self.required_for_readiness,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BuildTaskDefinition":
        return cls(
            task_id=str(value.get("task_id") or ""),
            title=str(value.get("title") or ""),
            dependencies=tuple(str(item) for item in value.get("dependencies", []) or []),
            reads=tuple(str(item) for item in value.get("reads", []) or []),
            owns=tuple(str(item) for item in value.get("owns", []) or []),
            forbidden_writes=tuple(
                str(item) for item in value.get("forbidden_writes", []) or []
            ),
            validator_id=(str(value["validator_id"]) if value.get("validator_id") else None),
            model_stage=(str(value["model_stage"]) if value.get("model_stage") else None),
            context_policy=value.get("context_policy"),
            output_budget=value.get("output_budget"),
            review_policy=str(value.get("review_policy") or "auto"),  # type: ignore[arg-type]
            required_for_readiness=bool(value.get("required_for_readiness", False)),
        )


@dataclass(frozen=True)
class BuildGraphDefinition:
    graph_id: str
    tasks: tuple[BuildTaskDefinition, ...] = field(default_factory=tuple)
    schema_version: str = "build-graph-definition/v1"

    def __post_init__(self) -> None:
        graph_id = str(self.graph_id or "").strip()
        if not graph_id:
            raise BuildDefinitionError("build_graph_id_required", "graph_id is required", path="graph_id")
        object.__setattr__(self, "graph_id", graph_id)
        tasks = tuple(self.tasks or ())
        if not tasks:
            raise BuildDefinitionError("build_graph_tasks_required", "graph must define at least one task")
        if any(not isinstance(task, BuildTaskDefinition) for task in tasks):
            raise BuildDefinitionError("build_task_definition_invalid", "tasks must be BuildTaskDefinition values")
        object.__setattr__(self, "tasks", tasks)
        self.validate()

    @property
    def tasks_by_id(self) -> dict[str, BuildTaskDefinition]:
        return {task.task_id: task for task in self.tasks}

    @property
    def ordered_task_ids(self) -> tuple[str, ...]:
        tasks = self.tasks_by_id
        indegree = {task_id: 0 for task_id in tasks}
        children: dict[str, set[str]] = {task_id: set() for task_id in tasks}
        for task in self.tasks:
            indegree[task.task_id] = len(task.dependencies)
            for dependency in task.dependencies:
                children[dependency].add(task.task_id)
        ready = sorted(task_id for task_id, degree in indegree.items() if degree == 0)
        ordered: list[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for child in sorted(children[current]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
                    ready.sort()
        return tuple(ordered)

    def validate(self) -> None:
        diagnostics: list[BuildDiagnostic] = []
        seen: set[str] = set()
        for task in self.tasks:
            if task.task_id in seen:
                diagnostics.append(
                    BuildDiagnostic(
                        "build_task_id_duplicate",
                        f"tasks.{task.task_id}",
                        "task_id must be unique",
                    )
                )
            seen.add(task.task_id)
        tasks = self.tasks_by_id
        for task in self.tasks:
            for dependency in task.dependencies:
                if dependency == task.task_id:
                    diagnostics.append(
                        BuildDiagnostic(
                            "build_graph_self_dependency",
                            f"tasks.{task.task_id}.dependencies",
                            "a task cannot depend on itself",
                        )
                    )
                elif dependency not in tasks:
                    diagnostics.append(
                        BuildDiagnostic(
                            "build_graph_unknown_dependency",
                            f"tasks.{task.task_id}.dependencies",
                            f"unknown dependency: {dependency}",
                        )
                    )
        ownership: list[tuple[str, str]] = [
            (task.task_id, path) for task in self.tasks for path in task.owns
        ]
        for index, (left_task, left_path) in enumerate(ownership):
            for right_task, right_path in ownership[index + 1 :]:
                if left_task != right_task and paths_overlap(left_path, right_path):
                    diagnostics.append(
                        BuildDiagnostic(
                            "build_ownership_overlap",
                            left_path,
                            f"ownership overlaps {right_task}:{right_path}",
                        )
                    )
        if not diagnostics:
            ordered = self.ordered_task_ids
            if len(ordered) != len(tasks):
                diagnostics.append(
                    BuildDiagnostic(
                        "build_graph_cycle",
                        "tasks",
                        "task dependencies must form a directed acyclic graph",
                    )
                )
        if diagnostics:
            raise BuildDefinitionError(
                diagnostics[0].code,
                "invalid Build Graph definition",
                path=diagnostics[0].path,
                diagnostics=tuple(diagnostics),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "graph_id": self.graph_id,
            "tasks": [self.tasks_by_id[item].to_dict() for item in self.ordered_task_ids],
        }

    @property
    def definition_fingerprint(self) -> str:
        semantic_definition = {
            "schema_version": self.schema_version,
            "graph_id": self.graph_id,
            "tasks": [
                self.tasks_by_id[task_id].semantic_dict()
                for task_id in self.ordered_task_ids
            ],
        }
        canonical = json.dumps(
            semantic_definition,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "BuildGraphDefinition":
        raw_tasks = value.get("tasks")
        tasks = tuple(
            BuildTaskDefinition.from_dict(item)
            for item in raw_tasks or ()
            if isinstance(item, Mapping)
        )
        return cls(
            graph_id=str(value.get("graph_id") or ""),
            tasks=tasks,
            schema_version=str(value.get("schema_version") or "build-graph-definition/v1"),
        )


__all__ = [
    "BuildGraphDefinition",
    "BuildTaskDefinition",
    "normalize_path",
    "path_covers",
    "path_tokens",
    "paths_overlap",
    "validate_task_id",
]
