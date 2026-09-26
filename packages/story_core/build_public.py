"""Content-free projections for automation; persisted graph remains authoritative."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from packages.story_core.build_graph.contracts import BuildTaskStateError
from packages.story_core.model_gateway.capabilities import KNOWN_CAPABILITIES, KNOWN_LIMITS

SCHEMA = "public-build/v1"


def safe_code(value: Any) -> str:
    value = str(value or "")
    return value if re.fullmatch(r"[a-z][a-z0-9_]{0,95}", value) else "diagnostic_redacted"


def diagnostics(items) -> list[dict]:
    # Validator messages, paths and details can contain excerpts or provider errors.
    return [{"code": safe_code(item.code), "severity": item.severity} for item in items]


def assert_matching(definition, state) -> None:
    if state is not None and (
        state.graph_id != definition.graph_id
        or state.definition_fingerprint != definition.definition_fingerprint
        or set(state.tasks) != set(definition.tasks_by_id)
    ):
        raise BuildTaskStateError("build_graph_state_mismatch", "graph definition changed")


def task_projection(task, state, artifact=None) -> dict:
    return {
        "task_id": task.task_id, "title": task.title,
        "dependencies": list(task.dependencies), "reads": list(task.reads),
        "owns": list(task.owns), "forbidden_writes": list(task.forbidden_writes),
        "review_policy": task.review_policy, "required_for_readiness": task.required_for_readiness,
        "model_stage": task.model_stage, "validator_id": task.validator_id,
        "status": state.status if state else "uninitialized",
        "artifact_revision": state.current_artifact_revision if state else None,
        "dependency_revisions": dict(state.dependency_revisions) if state else {},
        "validation_status": state.validation_status if state else "unknown",
        "diagnostics": diagnostics(state.diagnostics) if state else [],
        "active_run_id": state.active_run_id if state else None,
        "artifact": artifact_projection(artifact) if artifact else None,
    }


def artifact_projection(artifact) -> dict:
    return {
        "task_id": artifact.task_id, "revision": artifact.revision,
        "source": artifact.source,
        "dependency_revisions": dict(artifact.dependency_revisions),
        "validation": {"passed": artifact.validation.passed,
                       "disposition": artifact.validation.disposition,
                       "diagnostics": diagnostics(artifact.validation.diagnostics)},
        "content_omitted": True,
    }


def graph_projection(definition, state, build_store) -> dict:
    assert_matching(definition, state)
    tasks = []
    for task_id in definition.ordered_task_ids:
        task = definition.tasks_by_id[task_id]
        current = state.tasks[task_id] if state else None
        revision = current.current_artifact_revision if current else None
        artifact = build_store.read_artifact(task_id, revision) if revision else None
        if revision and artifact is None:
            raise BuildTaskStateError("build_graph_artifact_missing", "artifact is missing")
        tasks.append(task_projection(task, current, artifact))
    blockers = [{"task_id": task["task_id"], "code": task["status"]}
                for task in tasks if task["required_for_readiness"] and task["status"] != "completed"]
    return {
        "schema_version": SCHEMA, "initialized": state is not None,
        "graph_id": definition.graph_id, "graph_revision": state.graph_revision if state else None,
        "tasks": tasks,
        "readiness": {"ready": state is not None and not blockers,
                      "blockers": blockers,
                      "human_confirmation": [{"kind": "task_review", "task_id": task["task_id"],
                                              "artifact_revision": task["artifact_revision"]}
                                             for task in tasks if task["status"] == "review_required"]},
    }


def capability_projection(profile) -> dict:
    def timestamp(value):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat() if value else None
        except (ValueError, TypeError, AttributeError):
            return None
    def record(item, *, limit=False):
        provenance = item.provenance
        return {
            "state": item.state,
            "value": item.value if limit and type(item.value) is int and item.value > 0 else None,
            "source": provenance.source if provenance.source in {
                "runtime_observation", "provider_metadata", "official_catalog", "user_declared", "unknown"
            } else "unknown",
            "verification_status": provenance.verification_status if provenance.verification_status in {
                "verified", "declared", "inferred", "unknown"
            } else "unknown",
            "verified_at": timestamp(provenance.verified_at), "expires_at": timestamp(provenance.expires_at),
        }
    identity = profile.identity
    def label(value):
        value = str(value or "")
        return value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", value) and not value.startswith("sk-") else "redacted"
    return {
        "provider_id": label(identity.provider_id), "protocol": label(identity.protocol),
        "model": label(identity.requested_model),
        "resolved_model": label(identity.resolved_model) if identity.resolved_model else None,
        "capabilities": {name: record(profile.effective_capability(name)) for name in KNOWN_CAPABILITIES},
        "limits": {name: record(profile.effective_capability(name), limit=True) for name in KNOWN_LIMITS},
        "output_budget_enforcement": "best_effort" if "cli" in identity.protocol else "provider_dependent",
    }
