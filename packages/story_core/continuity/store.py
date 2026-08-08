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
from pathlib import Path
from typing import Iterable

from .snapshot import ChapterSnapshot


_STALE_SCHEMA_VERSION = "continuity-stale/v1"


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
        return ChapterSnapshot.from_dict(json.loads(target.read_text(encoding="utf-8")))

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

    def _read_stale(self) -> dict[str, object]:
        if not self.stale_path.is_file():
            return {"schema_version": _STALE_SCHEMA_VERSION, "chapters": []}
        try:
            return json.loads(self.stale_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {"schema_version": _STALE_SCHEMA_VERSION, "chapters": []}

    def _write_stale(self, payload: dict[str, object]) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.stale_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.stale_path

    def get_stale_chapters(self) -> list[int]:
        payload = self._read_stale()
        chapters = payload.get("chapters") or []
        return sorted({int(item) for item in chapters if isinstance(item, int) or (isinstance(item, str) and item.isdigit())})

    def mark_stale(self, chapter_numbers: Iterable[int]) -> Path:
        existing = set(self.get_stale_chapters())
        for number in chapter_numbers:
            existing.add(int(number))
        return self._write_stale(
            {
                "schema_version": _STALE_SCHEMA_VERSION,
                "chapters": sorted(existing),
            }
        )

    def clear_stale(self, chapter_numbers: Iterable[int] | None = None) -> Path:
        if chapter_numbers is None:
            return self._write_stale(
                {"schema_version": _STALE_SCHEMA_VERSION, "chapters": []}
            )
        keep = set(self.get_stale_chapters()) - {int(item) for item in chapter_numbers}
        return self._write_stale(
            {
                "schema_version": _STALE_SCHEMA_VERSION,
                "chapters": sorted(keep),
            }
        )


__all__ = ["ContinuityStore", "_STALE_SCHEMA_VERSION"]
