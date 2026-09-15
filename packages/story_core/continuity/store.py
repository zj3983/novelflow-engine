"""Filesystem persistence for continuity snapshots and stale markers.

The store owns the on-disk layout under ``.story-system/continuity/``:

* ``snapshots/NNNN.json`` — one file per confirmed chapter, holds the
  ``ChapterSnapshot`` payload.
* ``stale.json`` — single file listing chapter numbers whose
  downstream state is no longer trustworthy because an earlier
  chapter was regenerated. The workbench reads this to warn the
  user before they regenerate or re-render the project.

The store stays small: it only reads and writes JSON. The actual
atomicity is the file-project store's ``SnapshotStore``; this
module just provides a typed view.
"""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .snapshot import ChapterSnapshot, SNAPSHOT_SCHEMA_VERSION


_STALE_SCHEMA_VERSION = "continuity-stale/v1"
_STALE_METADATA_VALID = "VALID"
_STALE_METADATA_MISSING = "MISSING"
_STALE_METADATA_CORRUPT = "CORRUPT"
_STALE_METADATA_UNREADABLE = "UNREADABLE"
_SNAPSHOT_VALID = "VALID"
_SNAPSHOT_MISSING = "MISSING"
_SNAPSHOT_CORRUPT = "CORRUPT"
_SNAPSHOT_UNREADABLE = "UNREADABLE"
_SNAPSHOT_BODY_MISMATCH = "BODY_MISMATCH"
_SNAPSHOT_IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


@dataclass(frozen=True)
class StaleMetadataRead:
    """Strict read result for the stale-chapter trust metadata."""

    status: str
    chapters: tuple[int, ...] = ()
    error: str | None = None

    @property
    def trusted(self) -> bool:
        return self.status in {_STALE_METADATA_VALID, _STALE_METADATA_MISSING}

    @property
    def writable(self) -> bool:
        return self.trusted


@dataclass(frozen=True)
class SnapshotIntegrityRead:
    """Status-aware read result for a chapter snapshot trust boundary."""

    status: str
    snapshot: ChapterSnapshot | None = None
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.status == _SNAPSHOT_VALID and self.snapshot is not None


@dataclass
class ContinuitySnapshotPlan:
    """Read-only decision for the continuity side of confirmation."""

    status: str
    mode: str
    chapter_number: int
    candidate_id: str = ""
    boundary_source_chapter: int | None = None
    snapshot_payload: dict[str, Any] | None = None
    stale_from_chapter: int | None = None
    findings: list[str] = field(default_factory=list)

    def to_result_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode,
            "chapter_number": self.chapter_number,
            "candidate_id": self.candidate_id,
            "boundary_source_chapter": self.boundary_source_chapter,
            "stale_from_chapter": self.stale_from_chapter,
            "findings": list(self.findings),
        }


class ContinuityStore:
    """Read / write continuity snapshots and stale markers."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.directory = self.root / ".story-system" / "continuity"
        self.snapshots_dir = self.directory / "snapshots"
        self.stale_path = self.directory / "stale.json"

    # --- snapshots ---------------------------------------------------------

    def snapshot_path(self, chapter_number: int) -> Path:
        return self.snapshots_dir / f"{int(chapter_number):04d}.json"

    def write_snapshot(self, snapshot: ChapterSnapshot) -> Path:
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        target = self.snapshot_path(snapshot.chapter_number)
        target.write_text(
            json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return target

    def read_snapshot(self, chapter_number: int) -> ChapterSnapshot | None:
        target = self.snapshot_path(chapter_number)
        if not target.is_file():
            return None
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            return ChapterSnapshot.from_dict(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def read_snapshot_integrity(
        self,
        chapter_number: int,
        *,
        expected_body_sha256: str | None = None,
        expected_body_chars: int | None = None,
        expected_candidate_id: str | None = None,
    ) -> SnapshotIntegrityRead:
        """Read and validate a snapshot without repairing or rewriting it.

        ``ChapterSnapshot.from_dict`` is intentionally permissive for legacy
        readers.  Historical authority selection needs a stricter boundary:
        the file must have the current snapshot shape, identify the requested
        chapter, and, when the caller has the current chapter artifact, match
        its body and provenance.
        """

        target = self.snapshot_path(chapter_number)
        try:
            snapshot_stat = target.stat()
        except FileNotFoundError:
            return SnapshotIntegrityRead(status=_SNAPSHOT_MISSING)
        except OSError as exc:
            return SnapshotIntegrityRead(
                status=_SNAPSHOT_UNREADABLE,
                error=str(exc),
            )
        if not stat.S_ISREG(snapshot_stat.st_mode):
            return SnapshotIntegrityRead(
                status=_SNAPSHOT_CORRUPT,
                error="snapshot_path_not_regular_file",
            )
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            return SnapshotIntegrityRead(
                status=_SNAPSHOT_UNREADABLE,
                error=str(exc),
            )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            return SnapshotIntegrityRead(
                status=_SNAPSHOT_CORRUPT,
                error=str(exc),
            )
        if not isinstance(payload, dict):
            return SnapshotIntegrityRead(
                status=_SNAPSHOT_CORRUPT,
                error="snapshot_payload_not_object",
            )
        required = {
            "schema_version",
            "chapter_number",
            "candidate_id",
            "operation",
            "confirmed_at",
            "body_sha256",
            "body_chars",
            "state_after",
        }
        if not required.issubset(payload):
            return SnapshotIntegrityRead(
                status=_SNAPSHOT_CORRUPT,
                error="snapshot_required_field_missing",
            )
        if payload.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
            return SnapshotIntegrityRead(
                status=_SNAPSHOT_CORRUPT,
                error="snapshot_schema_version_invalid",
            )
        raw_number = payload.get("chapter_number")
        raw_candidate = payload.get("candidate_id")
        raw_body_hash = payload.get("body_sha256")
        raw_body_chars = payload.get("body_chars")
        if (
            isinstance(raw_number, bool)
            or not isinstance(raw_number, int)
            or raw_number <= 0
            or not isinstance(raw_candidate, str)
            or not raw_candidate.strip()
            or not isinstance(raw_body_hash, str)
            or not raw_body_hash.strip()
            or isinstance(raw_body_chars, bool)
            or not isinstance(raw_body_chars, int)
            or raw_body_chars < 0
            or not isinstance(payload.get("state_after"), dict)
        ):
            return SnapshotIntegrityRead(
                status=_SNAPSHOT_CORRUPT,
                error="snapshot_field_shape_invalid",
            )
        if raw_number != int(chapter_number):
            return SnapshotIntegrityRead(
                status=_SNAPSHOT_IDENTITY_MISMATCH,
                error="snapshot_chapter_number_mismatch",
            )
        try:
            snapshot = ChapterSnapshot.from_dict(payload)
        except (TypeError, ValueError, KeyError) as exc:
            return SnapshotIntegrityRead(
                status=_SNAPSHOT_CORRUPT,
                error=str(exc),
            )
        if expected_body_sha256 is not None and snapshot.body_sha256 != str(expected_body_sha256):
            return SnapshotIntegrityRead(
                status=_SNAPSHOT_BODY_MISMATCH,
                snapshot=snapshot,
                error="snapshot_body_sha256_mismatch",
            )
        if expected_body_chars is not None and snapshot.body_chars != int(expected_body_chars):
            return SnapshotIntegrityRead(
                status=_SNAPSHOT_BODY_MISMATCH,
                snapshot=snapshot,
                error="snapshot_body_chars_mismatch",
            )
        if expected_candidate_id is not None and snapshot.candidate_id != str(expected_candidate_id):
            return SnapshotIntegrityRead(
                status=_SNAPSHOT_IDENTITY_MISMATCH,
                snapshot=snapshot,
                error="snapshot_candidate_id_mismatch",
            )
        return SnapshotIntegrityRead(status=_SNAPSHOT_VALID, snapshot=snapshot)

    def is_stale(self, chapter_number: int) -> bool:
        """Return whether a snapshot is currently outside the trusted chain."""

        metadata = self.read_stale_metadata()
        if not metadata.trusted:
            # An unreadable/corrupt trust file must never make a snapshot look
            # fresh.  The status-aware readers below also return no authority,
            # but treating the individual chapter as stale keeps this bool
            # API fail-safe for existing callers.
            return True
        return int(chapter_number) in set(metadata.chapters)

    def read_fresh_snapshot(
        self,
        chapter_number: int,
        *,
        expected_body_sha256: str | None = None,
        expected_body_chars: int | None = None,
        expected_candidate_id: str | None = None,
    ) -> ChapterSnapshot | None:
        """Read a snapshot only when its chapter is not marked stale."""

        metadata = self.read_stale_metadata()
        if not metadata.trusted or int(chapter_number) in set(metadata.chapters):
            return None
        result = self.read_snapshot_integrity(
            chapter_number,
            expected_body_sha256=expected_body_sha256,
            expected_body_chars=expected_body_chars,
            expected_candidate_id=expected_candidate_id,
        )
        return result.snapshot if result.valid else None

    def latest_fresh_snapshot_before(self, chapter_number: int) -> ChapterSnapshot | None:
        """Return the nearest trusted snapshot strictly before ``chapter_number``."""

        target = int(chapter_number)
        metadata = self.read_stale_metadata()
        if not metadata.trusted:
            return None
        candidates: list[ChapterSnapshot] = []
        stale = set(metadata.chapters)
        for snapshot_number in self.snapshot_numbers():
            if snapshot_number >= target or snapshot_number in stale:
                continue
            result = self.read_snapshot_integrity(snapshot_number)
            if result.valid and result.snapshot is not None:
                candidates.append(result.snapshot)
        return max(candidates, key=lambda item: item.chapter_number, default=None)

    def snapshot_numbers(self) -> list[int]:
        """Return numeric snapshot paths, including malformed files."""

        if not self.snapshots_dir.is_dir():
            return []
        numbers: list[int] = []
        for path in self.snapshots_dir.glob("*.json"):
            try:
                numbers.append(int(path.stem))
            except ValueError:
                continue
        return sorted(set(numbers))

    def list_snapshots(self) -> list[ChapterSnapshot]:
        if not self.snapshots_dir.is_dir():
            return []
        items: list[ChapterSnapshot] = []
        for path in sorted(self.snapshots_dir.glob("*.json")):
            try:
                items.append(ChapterSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return items

    def remove_snapshot(self, chapter_number: int) -> None:
        target = self.snapshot_path(chapter_number)
        target.unlink(missing_ok=True)

    # --- stale markers -----------------------------------------------------

    def read_stale_metadata(self) -> StaleMetadataRead:
        """Read stale metadata without treating failures as an empty set.

        A missing file is the compatible new-project state.  Once a file
        exists, malformed JSON, invalid schema, or an I/O failure makes the
        freshness trust boundary unavailable.  Callers that decide whether a
        snapshot is authoritative must inspect this result rather than
        falling back to ``chapters=[]``.
        """

        try:
            stale_stat = self.stale_path.stat()
        except FileNotFoundError:
            return StaleMetadataRead(status=_STALE_METADATA_MISSING)
        except OSError as exc:
            return StaleMetadataRead(
                status=_STALE_METADATA_UNREADABLE,
                error=str(exc),
            )
        if not stat.S_ISREG(stale_stat.st_mode):
            return StaleMetadataRead(
                status=_STALE_METADATA_CORRUPT,
                error="stale_metadata_path_not_regular_file",
            )
        try:
            raw = self.stale_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return StaleMetadataRead(
                status=_STALE_METADATA_UNREADABLE,
                error=str(exc),
            )
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            return StaleMetadataRead(
                status=_STALE_METADATA_CORRUPT,
                error=str(exc),
            )
        if not isinstance(payload, dict):
            return StaleMetadataRead(
                status=_STALE_METADATA_CORRUPT,
                error="stale_metadata_payload_not_object",
            )
        if payload.get("schema_version") != _STALE_SCHEMA_VERSION:
            return StaleMetadataRead(
                status=_STALE_METADATA_CORRUPT,
                error="stale_metadata_schema_version_invalid",
            )
        chapters = payload.get("chapters")
        if not isinstance(chapters, list):
            return StaleMetadataRead(
                status=_STALE_METADATA_CORRUPT,
                error="stale_metadata_chapters_not_list",
            )
        normalized: set[int] = set()
        for chapter in chapters:
            if (
                isinstance(chapter, bool)
                or not isinstance(chapter, int)
                or chapter <= 0
            ):
                return StaleMetadataRead(
                    status=_STALE_METADATA_CORRUPT,
                    error="stale_metadata_chapter_number_invalid",
                )
            normalized.add(chapter)
        return StaleMetadataRead(
            status=_STALE_METADATA_VALID,
            chapters=tuple(sorted(normalized)),
        )

    def _require_writable_stale_metadata(self) -> StaleMetadataRead:
        metadata = self.read_stale_metadata()
        if not metadata.writable:
            raise ValueError("continuity_freshness_metadata_unavailable")
        return metadata

    def _write_stale(self, payload: dict[str, object]) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.stale_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.stale_path

    def get_stale_chapters(self) -> list[int]:
        metadata = self.read_stale_metadata()
        if not metadata.trusted:
            raise ValueError("continuity_freshness_metadata_unavailable")
        return list(metadata.chapters)

    def mark_stale(self, chapter_numbers: Iterable[int]) -> Path:
        metadata = self._require_writable_stale_metadata()
        existing = set(metadata.chapters)
        for number in chapter_numbers:
            existing.add(int(number))
        return self._write_stale(
            {
                "schema_version": _STALE_SCHEMA_VERSION,
                "chapters": sorted(existing),
            }
        )

    def clear_stale(self, chapter_numbers: Iterable[int] | None = None) -> Path:
        metadata = self._require_writable_stale_metadata()
        if chapter_numbers is None:
            return self._write_stale(
                {"schema_version": _STALE_SCHEMA_VERSION, "chapters": []}
            )
        keep = set(metadata.chapters) - {int(item) for item in chapter_numbers}
        return self._write_stale(
            {
                "schema_version": _STALE_SCHEMA_VERSION,
                "chapters": sorted(keep),
            }
        )


__all__ = [
    "ContinuitySnapshotPlan",
    "ContinuityStore",
    "SnapshotIntegrityRead",
    "StaleMetadataRead",
    "_STALE_SCHEMA_VERSION",
]
