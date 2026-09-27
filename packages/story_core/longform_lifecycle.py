"""Author acceptance and explicit continuation over the existing persistence APIs.

No model calls, recovery runner, plan store, or scheduler live here. The caller
supplies the existing generation admission function and job reader. In particular,
reading a continuation never resumes work after an application restart.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4
from threading import Lock
from weakref import WeakValueDictionary

from packages.story_core.candidate_editing import candidate_authority, digest
from packages.story_core.opening_build import execution, runtime as opening
from packages.story_core.persistence.project_locking import project_update_lock
from packages.story_core.persistence.project_transaction import ProjectTransaction

_launch_locks = WeakValueDictionary()
_launch_locks_guard = Lock()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _metadata(store):
    if opening.enabled(store):
        return store.webnovel_dir / opening.SETTINGS, deepcopy(opening.settings(store))
    return store.webnovel_dir / "project.json", deepcopy(store.project())


def _plan_fingerprint(store):
    # Unlike the execution source, this excludes chapter confirmations. An author
    # accepts the actual published plan once, until its content/authority changes.
    config = opening.settings(store) if opening.enabled(store) else {}
    graph = store.build_graph_store().read_state() if config else None
    project = store.project()
    return digest({
        "outline": store.snapshot_store.read_json(store.webnovel_dir / "outline.json", None),
        "handoff": store.snapshot_store.read_json(store.webnovel_dir / "opening_execution_contracts.json", None),
        "canonical_outline": store.snapshot_store.read_json(store.story_system_dir / "outline.json", None),
        "canonical_volume": store.snapshot_store.read_json(store.story_system_dir / "volume.json", None),
        "rolling": store.snapshot_store.read_json(store.story_system_dir / "outline-generation" / "rolling_outline.json", None),
        "versions": (config or {}).get("plan_versions", []),
        "artifacts": {key: task.current_artifact_revision for key, task in graph.tasks.items()} if graph else {},
        "definition": graph.definition_fingerprint if graph else None,
        "requirements": project.get("author_constraints", []),
        "targets": {key: project[key] for key in ("target_words", "target_chapter_words") if key in project},
        "future_intent": author_future_intent(store),
    })


def plan_state(store):
    """Read-only internal projection; the product layer owns user wording."""
    with project_update_lock(store.root):
        _, metadata = _metadata(store)
        fingerprint = _plan_fingerprint(store)
        accepted = metadata.get("longform_plan_acceptance", {}).get("fingerprint") == fingerprint
        try:
            if opening.enabled(store):
                execution.capture(store)
            else:
                store.require_volume_detail_for_prose(int(store.state().get("current_chapter") or 0) + 1)
            ready = True
        except (ValueError, FileNotFoundError):
            ready = False
        return {"fingerprint": fingerprint, "accepted": accepted, "ready": ready}


def accept_plan(store, expected: str):
    with project_update_lock(store.root):
        state = plan_state(store)
        if state["fingerprint"] != expected:
            raise ValueError("longform_plan_changed")
        if not state["ready"]:
            raise ValueError("longform_plan_not_ready")
        path, metadata = _metadata(store)
        metadata["longform_plan_acceptance"] = {"fingerprint": expected, "accepted_at": _now()}
        store.snapshot_store.replace_json_transaction({path: metadata})
        return {**state, "accepted": True}


def require_accepted_plan(store, expected=None):
    state = plan_state(store)
    if expected is not None and expected != state["fingerprint"]:
        raise ValueError("longform_plan_changed")
    if not state["accepted"]:
        raise ValueError("longform_plan_acceptance_required")
    if not state["ready"]:
        raise ValueError("longform_plan_not_ready")
    return state["fingerprint"]


def _receipt_path(store, candidate):
    return store.webnovel_dir / "opening_execution_receipts" / f"{candidate.chapter_number}.json"


def _read_receipt(store, candidate):
    receipt = store.snapshot_store.read_json(_receipt_path(store, candidate), {})
    if receipt.get("candidate_id") not in (None, candidate.candidate_id):
        raise ValueError("candidate_revision_conflict")
    return deepcopy(receipt)


def _candidate(store, candidate_id):
    import re
    if not re.fullmatch(r"cd-[a-f0-9]+", candidate_id):
        raise FileNotFoundError("candidate_not_found")
    candidate = store.candidate_store.get(candidate_id)
    if candidate is None or candidate.project_id != str(store.project().get("project_id") or store.project().get("active_story_id") or store.state().get("story_id") or store.root.name):
        raise FileNotFoundError("candidate_not_found")
    return candidate


def continuation_state(store, candidate_id):
    with project_update_lock(store.root):
        candidate = _candidate(store, candidate_id)
        intent = _read_receipt(store, candidate).get("continuation")
        return deepcopy(intent) if intent else None


def _result(candidate, intent):
    return {"confirmed": True, "chapter_number": candidate.chapter_number,
            "next": {"state": intent["state"], "job_id": intent.get("job_id"),
                     "message": "本章已保存，下一章尚未开始。" if intent["state"] == "failed" else "本章已保存。"}}


def confirm_and_continue(store, candidate_id: str, **kwargs):
    # Only one local caller may cross admission. The receipt and the existing
    # reserved job ID provide the durable boundary across process restarts.
    key = (str(store.root.resolve()), candidate_id)
    with _launch_locks_guard:
        lock = _launch_locks.get(key)
        if lock is None:
            lock = Lock()
            _launch_locks[key] = lock
    with lock:
        return _confirm_and_continue(store, candidate_id, **kwargs)


def _confirm_and_continue(store, candidate_id: str, *, expected_candidate: str | None,
                         accept_quality_warnings: bool, start_next: Callable[[str], dict],
                         read_job: Callable[[str], dict | None], retry=False):
    """Confirm atomically first; only then explicitly admit the next candidate.

    ``start_next`` must pass this reserved ID to existing job admission, request
    candidate-only generation, and validate the accepted plan at worker admission.
    ``read_job`` must be a read-only job lookup. It must not recover jobs. It may
    report ``worker_active=False`` when the existing executor can prove a stored
    running/queued job has no live worker (for example after a process restart).
    Callback work happens outside the project lock. A interrupted launch is only
    recoverable by an explicit retry, using the same durable reservation.
    """
    # Job ownership may take the existing executor lock; never acquire it while
    # holding the project lock, because job admission uses the opposite order.
    previous_job = None
    previous_job_id = None
    if retry:
        with project_update_lock(store.root):
            previous = _read_receipt(store, _candidate(store, candidate_id)).get("continuation")
            previous_job_id = previous.get("job_id") if previous else None
        if previous_job_id:
            previous_job = read_job(previous_job_id)
    with project_update_lock(store.root):
        candidate = _candidate(store, candidate_id)
        if candidate.operation != "generate":
            raise ValueError("candidate_historical_edit_locked")
        if candidate.status != "confirmed":
            if not expected_candidate or candidate_authority(candidate) != expected_candidate:
                raise ValueError("candidate_revision_conflict")
            require_accepted_plan(store)
            if opening.enabled(store):
                execution.verify(store, candidate.submission_payload.get("opening_authority"))
            from packages.story_core.product_presentation import candidate_review
            _, _, blocked, warning = candidate_review(candidate, store=store)
            if blocked:
                raise ValueError("candidate_review_required")
            if warning and not accept_quality_warnings:
                raise ValueError("candidate_quality_warning_confirmation_required")
            store.confirm_candidate(candidate_id, accept_quality_warnings=accept_quality_warnings)
            candidate = _candidate(store, candidate_id)
        receipt = _read_receipt(store, candidate)
        intent = receipt.get("continuation")
        if intent and not retry:
            return _result(candidate, intent)
        if int(store.state().get("current_chapter") or 0) != candidate.chapter_number:
            return _result(candidate, {"state": "completed"})
        if intent:
            if previous_job_id != intent["job_id"]:
                return _result(candidate, intent)
            job = previous_job
            running = bool(job and job.get("status") in {"queued", "running"}
                           and job.get("worker_active") is not False)
            if job and (running or job.get("status") == "completed"):
                return _result(candidate, {**intent, "state": str(job["status"])})
            # A failed job has finished. A deliberate retry receives a new ID;
            # a crash before admission reuses its original durable reservation.
            if job:
                intent = {**intent, "job_id": f"fgj-{uuid4().hex[:12]}"}
        else:
            intent = {"job_id": f"fgj-{uuid4().hex[:12]}", "target_chapter": candidate.chapter_number + 1}
        intent.update(state="launching", updated_at=_now())
        receipt.update(candidate_id=candidate_id, chapter_number=candidate.chapter_number, continuation=intent)
        store.snapshot_store.replace_json_transaction({_receipt_path(store, candidate): receipt})
    try:
        require_accepted_plan(store)
        job = start_next(intent["job_id"])
        if str(job.get("job_id")) != intent["job_id"]:
            raise ValueError("longform_next_chapter_busy")
        intent = {**intent, "state": str(job.get("status") or "queued"), "updated_at": _now()}
    except Exception:
        # The first transaction is already successful. Never roll it back or
        # expose raw provider errors through this author-facing result.
        intent = {**intent, "state": "failed", "updated_at": _now()}
    with project_update_lock(store.root):
        receipt = _read_receipt(store, candidate)
        if receipt.get("continuation", {}).get("job_id") == intent["job_id"]:
            receipt["continuation"] = intent
            store.snapshot_store.replace_json_transaction({_receipt_path(store, candidate): receipt})
    return _result(candidate, intent)


def save_author_requirements(store, requirements: list[str], *, expected_source: str):
    if not isinstance(requirements, list) or len(requirements) > 100 or any(not isinstance(item, str) or len(item) > 4000 for item in requirements):
        raise ValueError("author_requirements_invalid")
    return _save_author_inputs(store, {"author_constraints": [item.strip() for item in requirements if item.strip()]}, expected_source=expected_source)


def author_future_intent(store):
    """Explicit future guidance, distinct from generated chapter next-focus."""
    _, metadata = _metadata(store)
    return str((metadata.get("longform_author_inputs") or {}).get("future_intent") or "")


def save_future_intent(store, text: str, *, expected_source: str):
    if not isinstance(text, str) or len(text) > 20000:
        raise ValueError("author_future_intent_invalid")
    return _save_author_inputs(store, {"current_focus": text.strip()},
                               expected_source=expected_source, future_intent=text.strip())


def _save_author_inputs(store, patch: dict, *, expected_source: str, future_intent=None):
    with project_update_lock(store.root):
        if execution.source_fingerprint(store) != expected_source:
            raise ValueError("candidate_source_changed")
        config = deepcopy(opening.settings(store)) if opening.enabled(store) else None
        if config and config.get("execution"):
            if config.get("pending_extension") or config.get("sync_pending") or config["execution"].get("source_fingerprint") != expected_source:
                raise ValueError("opening_planning_source_conflict")
            execution.capture(store)
        prepared, payloads = store.update_project(patch, _commit=False)
        metadata = config if config else prepared
        if future_intent is not None:
            metadata["longform_author_inputs"] = {
                **metadata.get("longform_author_inputs", {}), "future_intent": future_intent,
            }
        metadata.pop("longform_plan_acceptance", None)
        if config is None:
            payloads[store.webnovel_dir / "project.json"] = prepared
        paths = [*payloads, store.webnovel_dir / opening.SETTINGS]
        with ProjectTransaction.create(store.root, snapshot_store=store.snapshot_store, managed_paths=paths):
            store.snapshot_store.replace_json_transaction(payloads)
            if config:
                if config.get("execution"):
                    # A sanctioned author-input edit changes only future model
                    # inputs. Preserve all published planning and historical
                    # Canon; old candidates retain their now-stale authority.
                    config["execution"]["source_fingerprint"] = execution.source_fingerprint(store)
                    config["longform_author_requirements_change"] = {
                        "previous_source": expected_source,
                        "effective_after_chapter": int(store.state().get("current_chapter") or 0),
                        "changed_at": _now(),
                    }
                store.snapshot_store.replace_json_transaction({store.webnovel_dir / opening.SETTINGS: config})
        return prepared


def save_future_plan(store, payload: dict, *, expected_source: str):
    with project_update_lock(store.root):
        if execution.source_fingerprint(store) != expected_source:
            raise ValueError("candidate_source_changed")
        current = store.snapshot_store.read_json(store.webnovel_dir / "outline.json", {})
        confirmed = int(store.state().get("current_chapter") or 0)
        def consumed(plan):
            return [item for item in plan.get("chapters", []) if int(item.get("chapter_number") or 0) <= confirmed]
        if consumed(current) != consumed(payload):
            raise ValueError("opening_consumed_outline_changed")
        # Opening mode deliberately retains its sanctioned graph edit boundary.
        return store.update_project_outline(deepcopy(payload))
