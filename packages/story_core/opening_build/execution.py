"""Bind prose candidates to the materialized opening plan and confirmed state."""
from copy import deepcopy
import hashlib
import json

from packages.story_core.models import NovelProject
from packages.story_core.persistence.project_locking import project_update_lock
from . import runtime


def source_fingerprint(store):
    values = {
        "source_revision": runtime.source_revision(store),
        "state": store.snapshot_store.read_json(store.webnovel_dir / "state.json", {}),
        "rolling": store.snapshot_store.read_json(store.story_system_dir / "outline-generation" / "rolling_outline.json", None),
        "handoff": store.snapshot_store.read_json(store.webnovel_dir / "opening_execution_contracts.json", None),
    }
    for directory in (store.story_system_dir / "canon", store.chapters_dir):
        if directory.exists():
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    values[str(path.relative_to(store.root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def capture(store):
    """Short admission lock. Model work must happen after this returns."""
    with project_update_lock(store.root):
        config = runtime.settings(store)
        if not config or config.get("sync_pending"):
            raise ValueError("opening_prose_not_ready")
        state_data = store.snapshot_store.read_json(store.webnovel_dir / "state.json", {})
        target = int(state_data.get("current_chapter") or 0) + 1
        project = NovelProject.model_validate(store.project())
        graph = runtime.graph_for(store, project)
        state = store.build_graph_store().read_state()
        if state is None or state.definition_fingerprint != graph.definition.definition_fingerprint:
            raise ValueError("opening_prose_graph_conflict")
        if any(task.status != "completed" or task.active_run_id for task in state.tasks.values()):
            raise ValueError("opening_prose_graph_not_clean")
        revisions = {key: task.current_artifact_revision for key, task in state.tasks.items()}
        marker = store.build_graph_materialization()
        if not marker or marker.get("artifact_revisions") != revisions:
            raise ValueError("opening_prose_materialization_required")
        handoff = store.build_graph_store().read_artifact("outline_execution_contract")
        if handoff is None or store.snapshot_store.read_json(store.webnovel_dir / "opening_execution_contracts.json", None) != handoff.payload:
            raise ValueError("opening_prose_handoff_conflict")
        if not any(item.get("chapter_number") == target for item in handoff.payload["outline_execution_contract"]):
            raise ValueError("opening_prose_chapter_not_planned")
        # Keep the established complete-volume requirement, including its
        # canonical chapter/rolling-outline checks, before any model call.
        store.require_volume_detail_for_prose(target)
        fingerprint = source_fingerprint(store)
        execution = config.get("execution")
        if execution:
            if execution.get("source_fingerprint") != fingerprint or execution.get("graph_revision") != state.graph_revision:
                raise ValueError("opening_prose_source_conflict")
        else:
            runtime.assert_sources_current(store)
            if target != 1 or project.pipeline_stage != "environment_ready":
                raise ValueError("opening_prose_not_ready")
        return {
            "schema_version": "opening-prose-authority/v1",
            "chapter_number": target, "graph_revision": state.graph_revision,
            "definition_fingerprint": state.definition_fingerprint,
            "artifact_revisions": revisions, "source_fingerprint": fingerprint,
        }


def verify(store, authority):
    if not isinstance(authority, dict) or authority != capture(store):
        raise ValueError("opening_prose_revision_conflict")


def record_confirmation(store, candidate):
    """Called inside the existing chapter+Canon confirmation transaction."""
    if not runtime.enabled(store):
        return
    authority = candidate.submission_payload.get("opening_authority")
    if not isinstance(authority, dict):
        raise ValueError("opening_prose_authority_missing")
    config = dict(runtime.settings(store))
    config["execution"] = {
        "graph_revision": authority["graph_revision"],
        "confirmed_through": candidate.chapter_number,
        "source_fingerprint": source_fingerprint(store),
    }
    receipt = {
        "schema_version": "opening-prose-receipt/v1", "candidate_id": candidate.candidate_id,
        "chapter_number": candidate.chapter_number, "authority": deepcopy(authority),
        "context_trace_ids": list(candidate.context_trace_ids),
    }
    store.snapshot_store.replace_json_transaction({
        store.webnovel_dir / runtime.SETTINGS: config,
        store.webnovel_dir / "opening_execution_receipts" / f"{candidate.chapter_number}.json": receipt,
    })
