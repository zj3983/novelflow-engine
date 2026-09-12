"""Candidate chapter state kept separate from confirmed project state.

A candidate is a *proposed* chapter: it carries the prose the writer
produced, the review verdict, the structured facts the extractor
proposed, and a list of context-trace ids so the workbench can prove
which artifacts shaped the draft. The candidate stays in the
``.story-system/candidates/`` directory until the user confirms or
discards it; only confirmed candidates touch the canonical chapter
store, the entity registry, and the continuity ledger.

Schema evolution:

* ``candidate-draft/v1`` — original v1 shape (body, quality report,
  revision history, submission payload). Still loadable.
* ``candidate-draft/v2`` — adds ``continuity_delta`` and
  ``context_trace_ids``. New writes use v2 once any of the new
  fields are populated; v1 writes still load transparently so
  existing candidate files keep working.
* ``candidate-draft/v3`` — adds the provisional fact/resource
  extraction and validation review. It is still candidate-only until
  confirmation commits the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


CandidateStatus = str

CANDIDATE_SCHEMA_V1 = "candidate-draft/v1"
CANDIDATE_SCHEMA_V2 = "candidate-draft/v2"
CANDIDATE_SCHEMA_V3 = "candidate-draft/v3"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CandidateDraft:
    candidate_id: str
    project_id: str
    chapter_number: int
    chapter_title: str = ""
    body: str = ""
    context_snapshot_id: str = ""
    quality_report: dict[str, Any] = field(default_factory=dict)
    revision_history: list[dict[str, Any]] = field(default_factory=list)
    submission_payload: dict[str, Any] = field(default_factory=dict)
    operation: str = "generate"
    status: CandidateStatus = "pending"
    created_at: str = ""
    confirmed_at: str = ""
    # --- v2 additions ---
    continuity_delta: Any | None = None  # ContinuityDelta | None; lazy import
    context_trace_ids: list[str] = field(default_factory=list)
    # --- v3 additions ---
    fact_resource_extraction: Any | None = None
    fact_resource_review: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        chapter_number: int,
        body: str,
        chapter_title: str = "",
        context_snapshot_id: str = "",
        quality_report: Mapping[str, Any] | None = None,
        revision_history: list[Mapping[str, Any]] | None = None,
        submission_payload: Mapping[str, Any] | None = None,
        operation: str = "generate",
        continuity_delta: Any | None = None,
        context_trace_ids: list[str] | None = None,
        fact_resource_extraction: Any | None = None,
        fact_resource_review: Mapping[str, Any] | None = None,
    ) -> "CandidateDraft":
        if chapter_number < 1:
            raise ValueError("chapter_number_must_be_positive")
        if not str(body).strip():
            raise ValueError("candidate_body_required")
        if operation not in {"generate", "regenerate"}:
            raise ValueError("candidate_operation_invalid")
        return cls(
            candidate_id=f"cd-{uuid4().hex}",
            project_id=str(project_id),
            chapter_number=chapter_number,
            chapter_title=str(chapter_title or ""),
            body=str(body),
            context_snapshot_id=str(context_snapshot_id or ""),
            quality_report=dict(quality_report or {}),
            revision_history=[dict(item) for item in (revision_history or [])],
            submission_payload=dict(submission_payload or {}),
            operation=operation,
            created_at=_now(),
            continuity_delta=continuity_delta,
            context_trace_ids=list(context_trace_ids or []),
            fact_resource_extraction=fact_resource_extraction,
            fact_resource_review=dict(fact_resource_review or {}),
        )

    @property
    def current_chapter_after_confirm(self) -> int:
        return self.chapter_number

    def confirm(self) -> "CandidateDraft":
        if self.status == "confirmed":
            return self
        if self.status != "pending":
            raise ValueError("candidate_not_pending")
        self.status = "confirmed"
        self.confirmed_at = _now()
        return self

    def discard(self) -> "CandidateDraft":
        if self.status != "pending":
            raise ValueError("candidate_not_pending")
        self.status = "discarded"
        return self

    def supersede(self) -> "CandidateDraft":
        if self.status != "pending":
            return self
        self.status = "superseded"
        return self

    def to_dict(self) -> dict[str, Any]:
        # Pick the schema version by content. v1 has no new fields;
        # v2 carries at least one of the new fields. This keeps the
        # on-disk format honest: a candidate that claims v2 actually
        # uses the new fields.
        has_v3 = self.fact_resource_extraction is not None or bool(self.fact_resource_review)
        has_v2 = self.continuity_delta is not None or bool(self.context_trace_ids)
        schema_version = (
            CANDIDATE_SCHEMA_V3
            if has_v3
            else CANDIDATE_SCHEMA_V2
            if has_v2
            else CANDIDATE_SCHEMA_V1
        )

        payload: dict[str, Any] = {
            "schema_version": schema_version,
            "candidate_id": self.candidate_id,
            "project_id": self.project_id,
            "chapter_number": self.chapter_number,
            "chapter_title": self.chapter_title,
            "body": self.body,
            "context_snapshot_id": self.context_snapshot_id,
            "quality_report": self.quality_report,
            "revision_history": self.revision_history,
            "submission_payload": self.submission_payload,
            "operation": self.operation,
            "status": self.status,
            "created_at": self.created_at,
            "confirmed_at": self.confirmed_at,
        }
        if schema_version in {CANDIDATE_SCHEMA_V2, CANDIDATE_SCHEMA_V3}:
            payload["continuity_delta"] = _delta_to_dict(self.continuity_delta)
            payload["context_trace_ids"] = list(self.context_trace_ids)
        if schema_version == CANDIDATE_SCHEMA_V3:
            payload["fact_resource_extraction"] = _fact_resource_to_dict(
                self.fact_resource_extraction
            )
            payload["fact_resource_review"] = dict(self.fact_resource_review)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CandidateDraft":
        schema_version = str(payload.get("schema_version") or CANDIDATE_SCHEMA_V1)
        if schema_version not in {CANDIDATE_SCHEMA_V1, CANDIDATE_SCHEMA_V2, CANDIDATE_SCHEMA_V3}:
            # Forward compatibility: unknown schemas still load, but
            # the new fields are simply absent. This is the same
            # posture the v1 → v2 migration takes.
            schema_version = CANDIDATE_SCHEMA_V1
        delta_payload = payload.get("continuity_delta")
        continuity_delta = _delta_from_dict(delta_payload) if delta_payload else None
        return cls(
            candidate_id=str(payload.get("candidate_id") or ""),
            project_id=str(payload.get("project_id") or ""),
            chapter_number=int(payload.get("chapter_number") or 0),
            chapter_title=str(payload.get("chapter_title") or ""),
            body=str(payload.get("body") or ""),
            context_snapshot_id=str(payload.get("context_snapshot_id") or ""),
            quality_report=dict(payload.get("quality_report") or {}),
            revision_history=[dict(item) for item in (payload.get("revision_history") or [])],
            submission_payload=dict(payload.get("submission_payload") or {}),
            operation=str(payload.get("operation") or "generate"),
            status=str(payload.get("status") or "pending"),
            created_at=str(payload.get("created_at") or ""),
            confirmed_at=str(payload.get("confirmed_at") or ""),
            continuity_delta=continuity_delta,
            context_trace_ids=[str(item) for item in (payload.get("context_trace_ids") or [])],
            fact_resource_extraction=_fact_resource_from_dict(
                payload.get("fact_resource_extraction")
            ),
            fact_resource_review=dict(payload.get("fact_resource_review") or {}),
        )


def _delta_to_dict(delta: Any) -> dict[str, Any] | None:
    """Serialize a ContinuityDelta to a plain dict (None-safe)."""
    if delta is None:
        return None
    if hasattr(delta, "model_dump"):
        return delta.model_dump(mode="json")
    if isinstance(delta, Mapping):
        return dict(delta)
    return None


def _delta_from_dict(payload: Any) -> Any:
    """Rehydrate a ContinuityDelta payload without a hard import cycle.

    The continuity package depends on nothing in candidate_draft, so
    the import is safe at function-call time. The lazy import keeps
    the module surface small for callers that never use v2 fields.
    """
    if payload is None:
        return None
    try:
        from packages.story_core.continuity.delta import ContinuityDelta  # type: ignore
    except Exception:
        return None
    if isinstance(payload, ContinuityDelta):
        return payload
    if isinstance(payload, Mapping):
        return ContinuityDelta.model_validate(payload)
    return None


def _fact_resource_to_dict(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _fact_resource_from_dict(payload: Any) -> Any:
    if payload is None:
        return None
    try:
        from packages.story_core.fact_resource_ledger import FactResourceExtraction

        if isinstance(payload, FactResourceExtraction):
            return payload
        if isinstance(payload, Mapping):
            return FactResourceExtraction.model_validate(payload)
    except Exception:
        return None
    return None
