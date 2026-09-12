from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.simplified_review import build_simplified_review


def _strip_file_prefix(value: str) -> str:
    return value[len("file:") :] if value.startswith("file:") else value


def _file_id(value: str) -> str:
    return value if value.startswith("file:") else f"file:{value}"


def _candidate_project_ids(
    store: FileProjectStore,
    requested_project_id: str,
) -> set[str]:
    project = store.project()
    state = store.persisted_state()
    raw_ids = {
        str(project.get("project_id") or "").strip(),
        str(project.get("active_story_id") or "").strip(),
        str(state.get("story_id") or "").strip(),
        str(store.root.name).strip(),
        str(requested_project_id or "").strip(),
    }
    accepted: set[str] = set()
    for raw_id in raw_ids:
        if not raw_id:
            continue
        plain_id = _strip_file_prefix(raw_id)
        accepted.update({raw_id, plain_id, _file_id(plain_id)})
    return accepted


def _candidate_payload(candidate: Any) -> dict[str, Any]:
    payload = candidate.to_dict()
    quality = dict(payload.get("quality_report") or {})
    quality["simplified_review"] = build_simplified_review(quality)
    payload["quality_report"] = quality
    return payload


def _candidate_list_item_payload(candidate: Any) -> dict[str, Any]:
    payload = _candidate_payload(candidate)
    payload.pop("submission_payload", None)
    payload.pop("continuity_delta", None)
    payload.pop("context_trace_ids", None)
    return payload


def _raise_candidate_error(exc: ValueError) -> None:
    detail = str(exc)
    if detail.startswith(
        (
            "chapter_frozen:",
            "next_volume_required:",
            "volume_detail_required:",
            "volume_detail_incomplete:",
            "fact_resource_historical_rewrite_requires_reconciliation",
            "fact_resource_validation_failed:",
        )
    ):
        raise HTTPException(status_code=409, detail=detail) from exc
    raise HTTPException(status_code=400, detail=detail) from exc


def register_file_project_candidate_routes(
    router: APIRouter,
    *,
    store_for: Callable[[str], FileProjectStore],
    assert_mutation_allowed: Callable[[FileProjectStore], None],
    project_payload: Callable[[FileProjectStore], dict[str, Any]],
    story_payload: Callable[[FileProjectStore], dict[str, Any]],
) -> None:
    @router.get("/file-projects/{project_id}/fact-resource-ledger")
    def get_file_project_fact_resource_ledger(project_id: str) -> dict[str, Any]:
        store = store_for(project_id)
        return store.fact_resource_ledger_payload()

    @router.get("/file-projects/{project_id}/candidates")
    def list_file_project_candidates(
        project_id: str,
        chapter_number: int | None = None,
    ) -> dict[str, Any]:
        store = store_for(project_id)
        accepted_project_ids = _candidate_project_ids(store, project_id)
        items = [
            item
            for item in store.candidate_store.list(chapter_number=chapter_number)
            if item.project_id in accepted_project_ids
        ]
        return {
            "schema_version": "file-project-candidate-list/v1",
            "items": [_candidate_list_item_payload(item) for item in items],
        }

    @router.get("/file-projects/{project_id}/candidates/{candidate_id}")
    def get_file_project_candidate(
        project_id: str,
        candidate_id: str,
    ) -> dict[str, Any]:
        store = store_for(project_id)
        candidate = store.candidate_store.get(candidate_id)
        if (
            candidate is None
            or candidate.project_id not in _candidate_project_ids(store, project_id)
        ):
            raise HTTPException(status_code=404, detail="candidate_not_found")
        return {
            "schema_version": "file-project-candidate/v1",
            "candidate": _candidate_payload(candidate),
        }

    @router.post("/file-projects/{project_id}/candidates/{candidate_id}/discard")
    def discard_file_project_candidate(
        project_id: str,
        candidate_id: str,
    ) -> dict[str, Any]:
        store = store_for(project_id)
        assert_mutation_allowed(store)
        candidate = store.candidate_store.get(candidate_id)
        if (
            candidate is None
            or candidate.project_id not in _candidate_project_ids(store, project_id)
        ):
            raise HTTPException(status_code=404, detail="candidate_not_found")
        try:
            candidate.discard()
        except ValueError as exc:
            _raise_candidate_error(exc)
        store.candidate_store.save(candidate)
        return {
            "schema_version": "file-project-candidate-discard/v1",
            "candidate": candidate.to_dict(),
        }

    @router.post("/file-projects/{project_id}/candidates/{candidate_id}/confirm")
    def confirm_file_project_candidate(
        project_id: str,
        candidate_id: str,
        force: bool = False,
    ) -> dict[str, Any]:
        store = store_for(project_id)
        assert_mutation_allowed(store)
        try:
            confirmed = store.confirm_candidate(
                candidate_id,
                accept_quality_warnings=force,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            _raise_candidate_error(exc)
        return {
            **confirmed,
            "project": project_payload(store),
            "story": story_payload(store),
        }
