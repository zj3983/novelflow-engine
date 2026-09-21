"""Deterministic ownership and candidate-validation boundaries."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from .contracts import (
    BuildDiagnostic,
    BuildOwnershipViolation,
    BuildTaskStateError,
    BuildValidationResult,
    Disposition,
)
from .definition import BuildTaskDefinition, normalize_path, path_covers, paths_overlap


Validator = Callable[[Any], Any]


def _diagnostics_from(value: Any) -> tuple[BuildDiagnostic, ...]:
    if value is None:
        return ()
    if isinstance(value, BuildDiagnostic):
        return (value,)
    if isinstance(value, Mapping):
        return (
            BuildDiagnostic(
                code=str(value.get("code") or "validator.diagnostic"),
                path=str(value.get("path") or ""),
                message=str(value.get("message") or "validation failed"),
                severity=str(value.get("severity") or "blocking"),  # type: ignore[arg-type]
            ),
        )
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        diagnostics: list[BuildDiagnostic] = []
        for item in value:
            diagnostics.extend(_diagnostics_from(item))
        return tuple(diagnostics)
    return (
        BuildDiagnostic(
            code="validator.invalid_result",
            path="",
            message="validator returned an unsupported result",
        ),
    )


def enforce_ownership(
    task: BuildTaskDefinition,
    requested_writes: Iterable[str] | None,
) -> tuple[str, ...]:
    """Reject writes outside the task's declared ownership boundary."""

    if requested_writes is None:
        requested = task.owns
    else:
        requested = tuple(normalize_path(path) for path in requested_writes)
    for path in requested:
        if any(paths_overlap(path, forbidden) for forbidden in task.forbidden_writes):
            raise BuildOwnershipViolation(
                "build_ownership_violation",
                "candidate writes a forbidden path",
                path=path,
                details={"task_id": task.task_id, "forbidden_writes": list(task.forbidden_writes)},
            )
        if not any(path_covers(owner, path) for owner in task.owns):
            raise BuildOwnershipViolation(
                "build_ownership_violation",
                "candidate writes outside the task ownership boundary",
                path=path,
                details={"task_id": task.task_id, "owns": list(task.owns)},
            )
    return tuple(requested)


def disposition_for(validation: BuildValidationResult, review_policy: str) -> Disposition:
    if validation.blocking or not validation.passed:
        return "FAIL"
    if review_policy == "review":
        return "PASS_REVIEW"
    if review_policy == "auto":
        return "PASS_AUTO"
    raise BuildTaskStateError(
        "build_review_policy_invalid",
        "review_policy must be auto or review",
    )


def validate_candidate(
    task: BuildTaskDefinition,
    payload: Any,
    *,
    requested_writes: Iterable[str] | None = None,
    validators: Mapping[str, Validator] | None = None,
) -> tuple[BuildValidationResult, tuple[str, ...]]:
    """Run ownership first, then the optional domain validator.

    Validator exceptions become a bounded structured diagnostic.  Tracebacks,
    prompts, and request metadata deliberately never enter the persisted
    result.
    """

    writes = enforce_ownership(task, requested_writes)
    if not task.validator_id:
        return BuildValidationResult(passed=True), writes
    validator = (validators or {}).get(task.validator_id)
    if validator is None:
        return (
            BuildValidationResult(
                passed=False,
                diagnostics=(
                    BuildDiagnostic(
                        "validator.not_registered",
                        f"tasks.{task.task_id}.validator_id",
                        "the configured validator is not registered",
                    ),
                ),
            ),
            writes,
        )
    try:
        raw_result = validator(payload)
    except Exception:
        return (
            BuildValidationResult(
                passed=False,
                diagnostics=(
                    BuildDiagnostic(
                        "validator.failed",
                        f"tasks.{task.task_id}",
                        "the task validator rejected the candidate",
                    ),
                ),
            ),
            writes,
        )
    if isinstance(raw_result, BuildValidationResult):
        return raw_result, writes
    if raw_result is True or raw_result is None:
        return BuildValidationResult(passed=True), writes
    if raw_result is False:
        return (
            BuildValidationResult(
                passed=False,
                diagnostics=(
                    BuildDiagnostic(
                        "validator.rejected",
                        f"tasks.{task.task_id}",
                        "the task validator rejected the candidate",
                    ),
                ),
            ),
            writes,
        )
    diagnostics = _diagnostics_from(raw_result)
    return BuildValidationResult(
        passed=not any(item.severity == "blocking" for item in diagnostics),
        diagnostics=diagnostics,
    ), writes


__all__ = [
    "Validator",
    "disposition_for",
    "enforce_ownership",
    "validate_candidate",
]
