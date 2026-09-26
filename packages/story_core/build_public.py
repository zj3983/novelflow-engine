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
            "verification_status": ("unknown" if item.state == "unknown" else
                                    "verified" if provenance.source in {"runtime_observation", "provider_metadata"} else
                                    "declared" if provenance.source in {"official_catalog", "user_declared"} else "unknown"),
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


def lifecycle_projection(store, state, config, project_id, candidates) -> dict:
    """Read existing Opening authority; return links to established lifecycle APIs.

    ``body`` is the endpoint request; ``preconditions`` describe the authority
    reference and are not undocumented parameters for those existing endpoints.
    """
    from packages.story_core.opening_build import execution, runtime
    from packages.story_core.file_project_store import _assert_auto_chapter_quality

    prefix = f"/file-projects/{project_id}"
    revision = state.graph_revision if state else None
    confirmed = int(store.state().get("current_chapter") or 0)
    result = {"phase": "build", "confirmed_through": confirmed, "prose_ready": False,
              "actions": [], "blockers": []}

    def action(name, href, body, preconditions, *, human=False, method="POST"):
        result["actions"].append({"action": name, "method": method, "href": prefix + href,
            "body": body, "preconditions": preconditions, "requires_human_confirmation": human,
            "execution_surface": "existing_project_api"})

    if not config:
        if confirmed == 0:
            result["phase"] = "opening_activation"
            action("activate_opening", "/build-graph/opening", {"expected_graph_revision": revision},
                   {"expected_graph_revision": revision, "confirmed_through": 0}, human=True)
        else:
            result["phase"] = "legacy_project"
            result["blockers"].append({"code": "opening_requires_unwritten_project"})
        return result
    if config.get("sync_pending") or (not config.get("execution") and config.get("source_revision") != runtime.source_revision(store)):
        result["phase"] = "source_sync_required"
        action("sync_opening_input", "/build-graph/opening/input", {"expected_graph_revision": revision},
               {"expected_graph_revision": revision}, human=True)
        return result
    if state is None or any(task.status != "completed" or task.active_run_id for task in state.tasks.values()):
        return result
    marker = store.build_graph_materialization() or {}
    revisions = {key: task.current_artifact_revision for key, task in state.tasks.items()}
    if config.get("pending_extension") or (not config.get("execution") and (
        marker.get("artifact_revisions") != revisions or store.project().get("pipeline_stage") != "environment_ready"
    )):
        result["phase"] = "materialization_required"
        result["actions"].append({"action": "materialize_build", "task_id": "__materialize__",
            "method": "POST", "href": prefix + "/public-build/next",
            "preconditions": {"expected_graph_revision": revision, "task_id": "__materialize__"},
            "requires_human_confirmation": False})
        return result
    if not config.get("execution"):
        plan = runtime.canonical_plan(store).outline
        first = next((arc for arc in plan.arcs if arc.start_chapter == 1), None)
        if first and first.end_chapter > config.get("chapter_count", 3):
            result["phase"] = "volume_detail_required"
            action("extend_first_volume", "/build-graph/opening/volume-detail",
                   {"expected_graph_revision": revision},
                   {"expected_graph_revision": revision, "end_chapter": first.end_chapter})
            return result
    if config.get("execution") and confirmed == config.get("chapter_count"):
        recorded = config["execution"]
        if recorded.get("source_fingerprint") != execution.source_fingerprint(store) or recorded.get("graph_revision") != revision:
            result["blockers"].append({"code": "opening_prose_source_conflict"})
            return result
        plan = runtime.canonical_plan(store).outline
        following = next((arc for arc in plan.arcs if arc.start_chapter == confirmed + 1), None)
        result["phase"] = "next_volume" if following else "planned_book_complete"
        if following:
            action("extend_next_volume", "/build-graph/opening/next-volume", {"expected_graph_revision": revision},
                   {"expected_graph_revision": revision, "confirmed_through": confirmed,
                    "source_fingerprint": recorded["source_fingerprint"], "start_chapter": following.start_chapter})
        return result
    try:
        authority = execution.capture(store)
    except ValueError as exc:
        result["blockers"].append({"code": safe_code(str(exc).split(":", 1)[0])})
        return result
    result["prose_ready"] = True
    result["phase"] = "candidate_review" if candidates else "ready_for_candidate"
    reference = {key: authority[key] for key in (
        "chapter_number", "graph_revision", "source_fingerprint", "plan_version", "artifact_revisions")}
    if not candidates:
        action("generate_candidate", "/generation-jobs", {}, reference)
    for candidate in candidates:
        action("review_candidate", f"/candidates/{candidate.candidate_id}", None,
               {"candidate_id": candidate.candidate_id, "context_snapshot_id": candidate.context_snapshot_id},
               human=True, method="GET")
        if candidate.submission_payload.get("opening_authority") != authority:
            result["blockers"].append({"code": "opening_prose_revision_conflict", "candidate_id": candidate.candidate_id})
            continue
        try:
            _assert_auto_chapter_quality(candidate.quality_report, operation=candidate.operation)
        except ValueError:
            result["blockers"].append({"code": "candidate_validation_failed", "candidate_id": candidate.candidate_id})
            continue
        action("confirm_candidate", f"/candidates/{candidate.candidate_id}/confirm", {},
               {"candidate_id": candidate.candidate_id, "context_snapshot_id": candidate.context_snapshot_id,
                **reference}, human=True)
    return result
