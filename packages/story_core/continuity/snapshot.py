"""Per-chapter continuity snapshot.

A ``ChapterSnapshot`` is the durable record of a confirmed chapter:
the chapter number, the candidate that produced it, the timestamps,
the post-confirm state slice, and the body's SHA-256. Snapshots are
written under ``.story-system/continuity/snapshots/NNNN.json`` and
serve two purposes:

1. **Regeneration base state** — when the user rewrites an earlier
   chapter, the new pipeline reads the snapshot of the chapter just
   before the target so it can rebuild a clean chapter-start state
   without inferring from later prose.
2. **Audit trail** — the workbench and the migration script can
   answer "who confirmed this chapter, when, and from which
   candidate?" by reading the snapshot.

Snapshots are intentionally write-once. A rewrite produces a new
snapshot; the old one stays on disk for history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


SNAPSHOT_SCHEMA_VERSION = "chapter-snapshot/v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ChapterSnapshot:
    chapter_number: int
    candidate_id: str
    operation: str  # "generate" | "regenerate"
    confirmed_at: str
    body_sha256: str
    body_chars: int
    state_after: dict[str, Any] = field(default_factory=dict)
    continuity_delta_summary: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SNAPSHOT_SCHEMA_VERSION
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = self.confirmed_at or _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "chapter_number": self.chapter_number,
            "candidate_id": self.candidate_id,
            "operation": self.operation,
            "confirmed_at": self.confirmed_at,
            "created_at": self.created_at,
            "body_sha256": self.body_sha256,
            "body_chars": self.body_chars,
            "state_after": self.state_after,
            "continuity_delta_summary": self.continuity_delta_summary,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChapterSnapshot":
        return cls(
            chapter_number=int(payload.get("chapter_number") or 0),
            candidate_id=str(payload.get("candidate_id") or ""),
            operation=str(payload.get("operation") or "generate"),
            confirmed_at=str(payload.get("confirmed_at") or ""),
            created_at=str(payload.get("created_at") or ""),
            body_sha256=str(payload.get("body_sha256") or ""),
            body_chars=int(payload.get("body_chars") or 0),
            state_after=dict(payload.get("state_after") or {}),
            continuity_delta_summary=dict(payload.get("continuity_delta_summary") or {}),
            schema_version=str(payload.get("schema_version") or SNAPSHOT_SCHEMA_VERSION),
        )


__all__ = ["ChapterSnapshot", "SNAPSHOT_SCHEMA_VERSION"]
