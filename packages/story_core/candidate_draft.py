"""Candidate chapter state kept separate from confirmed project state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


CandidateStatus = str


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
        return {
            "schema_version": "candidate-draft/v1",
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

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CandidateDraft":
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
        )
