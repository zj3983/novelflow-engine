"""Bind prose candidates to the materialized opening plan and confirmed state."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

from packages.story_core.models import NovelProject
from packages.story_core.persistence.project_locking import project_update_lock
from . import runtime


def source_fingerprint(store):
    values = {
        "source_revision": runtime.source_revision(store),
        "state": store.snapshot_store.read_json(store.webnovel_dir / "state.json", {}),
        "rolling": store.snapshot_store.read_json(store.story_system_dir / "outline-generation" / "rolling_outline.json", None),
        "canonical_outline": store.snapshot_store.read_json(store.story_system_dir / "outline.json", None),
        "canonical_volume": store.snapshot_store.read_json(store.story_system_dir / "volume.json", None),
        "handoff": store.snapshot_store.read_json(store.webnovel_dir / "opening_execution_contracts.json", None),
    }
    for directory in (store.story_system_dir / "canon", store.chapters_dir):
        if directory.exists():
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    values[str(path.relative_to(store.root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def planning_projection(store, chapter_number):
    """Project only committed Opening artifacts, never canonical/rolling overrides."""
    from packages.story_core.agents.director.prompt import build_outline_execution_contract
    plan = runtime.canonical_plan(store).outline.model_dump(mode="json")
    handoff = store.build_graph_store().read_artifact("outline_execution_contract")
    expected = next((item for item in (handoff.payload["outline_execution_contract"] if handoff else [])
                     if item["chapter_number"] == chapter_number), None)
    contract = build_outline_execution_contract(SimpleNamespace(
        chapter_number=chapter_number, nearby_outline=plan["chapters"]))
    if expected is None or contract is None or contract.model_dump(mode="json") != expected:
        raise ValueError("opening_prose_planning_contract_conflict")
    chapter = next(item for item in plan["chapters"] if item["chapter_number"] == chapter_number)
    volume = next(item for item in plan["arcs"] if item["start_chapter"] <= chapter_number <= item["end_chapter"])
    return plan, chapter, volume, deepcopy(expected)


def bind_story_planning(store, story):
    with project_update_lock(store.root):
        plan, chapter, volume, contract = planning_projection(store, story.current_chapter + 1)
        return story.model_copy(update={"outline_context": {
            "overall": plan["overall"], "arc": volume,
            "chapter": {**chapter, "execution_contract": contract},
        }}, deep=True)


def bind_director_planning(project_root, context):
    from packages.story_core.file_project_store import FileProjectStore
    store = FileProjectStore(project_root)
    if not runtime.enabled(store):
        return context
    with project_update_lock(store.root):
        authority = capture(store)
        if authority["chapter_number"] != context.chapter_number:
            raise ValueError("opening_prose_revision_conflict")
        plan, _chapter, volume, _contract = planning_projection(store, context.chapter_number)
        return context.model_copy(update={
            "nearby_outline": [item for item in plan["chapters"] if abs(item["chapter_number"] - context.chapter_number) <= 2],
            "volume": {**volume, "chapter_range": [volume["start_chapter"], volume["end_chapter"]]},
            "book_outline_summary": str(plan["overall"].get("story") or ""),
        }, deep=True)


def verify_writer_planning(project_root, artifact):
    """Reject a Director handoff that differs from the committed Opening contract."""
    from packages.story_core.file_project_store import FileProjectStore
    store = FileProjectStore(project_root)
    if not runtime.enabled(store):
        return
    with project_update_lock(store.root):
        authority = capture(store)
        if artifact.chapter_number != authority["chapter_number"]:
            raise ValueError("opening_prose_revision_conflict")
        _plan, _chapter, _volume, expected = planning_projection(store, artifact.chapter_number)
        if artifact.outline_contract is None or artifact.outline_contract.model_dump(mode="json") != expected or artifact.hook != expected["planned_hook"]:
            raise ValueError("opening_prose_planning_contract_conflict")


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
        planning_projection(store, target)
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
