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

from .snapshot import ChapterSnapshot


_STALE_SCHEMA_VERSION = "continuity-stale/v1"
_STALE_METADATA_VALID = "VALID"
_STALE_METADATA_MISSING = "MISSING"
_STALE_METADATA_CORRUPT = "CORRUPT"
_STALE_METADATA_UNREADABLE = "UNREADABLE"


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

    def read_fresh_snapshot(self, chapter_number: int) -> ChapterSnapshot | None:
        """Read a snapshot only when its chapter is not marked stale."""

        metadata = self.read_stale_metadata()
        if not metadata.trusted or int(chapter_number) in set(metadata.chapters):
            return None
        return self.read_snapshot(chapter_number)

    def latest_fresh_snapshot_before(self, chapter_number: int) -> ChapterSnapshot | None:
        """Return the nearest trusted snapshot strictly before ``chapter_number``."""

        target = int(chapter_number)
        metadata = self.read_stale_metadata()
        if not metadata.trusted:
            return None
        candidates = [
            snapshot
            for snapshot in self.list_snapshots()
            if snapshot.chapter_number < target
            and snapshot.chapter_number not in set(metadata.chapters)
        ]
        return max(candidates, key=lambda item: item.chapter_number, default=None)

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
    "StaleMetadataRead",
    "_STALE_SCHEMA_VERSION",
]
