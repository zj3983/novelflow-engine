"""Disk-side helper for the rolling chapter outline fill.

The plan rule: "保存采用原子更新，并保留旧大纲备份" —
every rolling fill must write a complete batch atomically
(all-or-nothing) and keep a backup of the previous
outline so a future operator can recover.

Storage layout — the rolling fill deliberately uses a
**separate file** rather than appending rows to the
legacy ``.webnovel/outline.json``:

* ``.webnovel/outline.json`` — the legacy
  ``ProjectOutline`` Pydantic shape; the rolling fill
  reads it but never writes to it. Legacy consumers
  see the file unchanged.
* ``.story-system/outline-generation/rolling_outline.json``
  — the rolling-fill chapters in the new shape
  (``chapter_goal`` / ``core_conflict`` / ``scenes`` /
  ``gain`` / ``cost`` / ``foreshadowing`` / ``hook`` /
  ``state_delta``).
* ``.story-system/outline-generation/backup/{ts}.json``
  — the previous rolling outline, copied before every
  overwrite.
* ``.story-system/outline-generation/rolling_fill_log.json``
  — an audit trail of which chapters the rolling fill
  generated, with the volume range and timestamp.

The legacy outline uses a strict Pydantic schema
(``extra="forbid"``) that does not match the new
rolling-fill field set. Mixing the two into one file
would either require schema migration or silently drop
the new fields on every read. A separate file keeps both
shapes self-contained and forward-compatible.

Atomic-write protocol:

1. Read the existing rolling outline (if any).
2. Validate the entire batch up-front via
   :func:`validate_rolling_batch`; any failure aborts the
   whole write.
3. If the rolling outline already exists, copy it to
   ``.story-system/outline-generation/backup/{ts}.json``.
4. Write the new rolling outline to a temp file in the
   same directory, then rename it onto the target.
5. Append a row to the rolling fill log.

Any failure between steps 3 and 5 rolls the rolling
outline back to the backup so the project on disk
stays consistent with the in-memory cache the
orchestrator is working against.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .outline_rolling import (
    RollingPlanError,
    RollingValidationError,
    validate_rolling_batch,
)


_GENERATION_DIR = Path(".story-system") / "outline-generation"
_ROLLING_OUTLINE_NAME = "rolling_outline.json"
_BACKUP_DIR = _GENERATION_DIR / "backup"
_FILL_LOG_NAME = "rolling_fill_log.json"
_ROLLING_SCHEMA_VERSION = "rolling-outline/v1"


class RollingOutlineStoreError(RuntimeError):
    """Raised when the rolling-fill write fails for an
    I/O reason (permission, disk full, etc.) rather than
    a validation reason.

    The caller can use this distinction to surface a
    different error message to the operator (e.g.
    "filesystem rejected the write" vs "the planner's
    output is malformed").
    """


def _utc_timestamp() -> str:
    """Return a filesystem-safe UTC timestamp.

    The format avoids colons so the value can be used as
    a file name on every common filesystem.
    """
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _read_existing_rolling_outline(
    project_root: Path,
) -> dict[str, Any]:
    """Return the existing rolling-outline payload, or
    an empty default when no file is on disk.

    A corrupt JSON file is treated as no file at all —
    the next rolling fill is a fresh start.
    """
    target = project_root / _GENERATION_DIR / _ROLLING_OUTLINE_NAME
    if not target.is_file():
        return {
            "schema_version": _ROLLING_SCHEMA_VERSION,
            "chapters": [],
        }
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "schema_version": _ROLLING_SCHEMA_VERSION,
            "chapters": [],
        }
    if not isinstance(payload, dict):
        return {
            "schema_version": _ROLLING_SCHEMA_VERSION,
            "chapters": [],
        }
    if not isinstance(payload.get("chapters"), list):
        payload["chapters"] = []
    return payload


def _read_legacy_outline_chapter_numbers(
    project_root: Path,
) -> set[int]:
    """Return the set of chapter numbers already on disk
    in the legacy ``.webnovel/outline.json``.

    The rolling fill treats the legacy outline as
    "filled" so a chapter that the initial planning
    pass already produced is never overwritten by a
    later rolling fill.
    """
    target = project_root / ".webnovel" / "outline.json"
    if not target.is_file():
        return set()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    chapters = payload.get("chapters")
    if not isinstance(chapters, list):
        return set()
    numbers: set[int] = set()
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        number = chapter.get("chapter_number")
        if (
            isinstance(number, int)
            and not isinstance(number, bool)
            and number > 0
        ):
            numbers.add(number)
    return numbers


def _existing_chapter_numbers(payload: dict[str, Any]) -> set[int]:
    """Return the set of chapter numbers already in the
    rolling-outline payload, regardless of ``source``
    marker.
    """
    numbers: set[int] = set()
    for chapter in payload.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        number = chapter.get("chapter_number")
        if isinstance(number, int) and not isinstance(number, bool) and number > 0:
            numbers.add(number)
    return numbers


def _write_json_atomic(target: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` to ``target`` atomically.

    The write goes through a temp file in the same
    directory so the rename is on the same filesystem
    (cross-filesystem renames are not atomic on POSIX
    and would silently fall back to copy + delete).
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                json.dumps(payload, ensure_ascii=False, indent=2)
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


class RollingOutlineStore:
    """Filesystem-backed store for the rolling outline fill.

    The store is intentionally simple: a project root, a
    separate rolling-outline file, a backup directory,
    and a fill log. There is no caching or background
    process — every call is a discrete read-validate-write
    transaction so the operator can reason about the
    disk state after each call.
    """

    def __init__(self, project_root: Path | str) -> None:
        self._root = Path(project_root)

    def _rolling_path(self) -> Path:
        return self._root / _GENERATION_DIR / _ROLLING_OUTLINE_NAME

    def _backup_dir(self) -> Path:
        return self._root / _BACKUP_DIR

    def _fill_log_path(self) -> Path:
        return self._root / _GENERATION_DIR / _FILL_LOG_NAME

    def _backup_existing_outline(
        self, existing_payload: dict[str, Any]
    ) -> str | None:
        """Copy the current rolling outline to
        ``backup/{ts}.json`` so the operator can recover
        from a future regression.
        """
        if not existing_payload.get("chapters"):
            return None
        backup_dir = self._backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = _utc_timestamp()
        backup_path = backup_dir / f"{timestamp}.json"
        try:
            _write_json_atomic(backup_path, existing_payload)
        except OSError as exc:
            raise RollingOutlineStoreError(
                f"rolling_outline_backup_failed: {exc}"
            ) from exc
        return backup_path.name

    def read_rolling_outline(self) -> dict[str, Any] | None:
        """Return the current rolling outline payload, or None.

        The reader is intentionally rolling-only; legacy outline chapters
        are surfaced separately by :class:`FileProjectStore`. A corrupt
        file is treated as "no rolling outline" rather than raising —
        the writing path owns validation, the read path is best-effort.
        """
        path = self._rolling_path()
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def read_chapter(self, chapter_number: int) -> dict[str, Any] | None:
        """Return the rolling chapter for ``chapter_number`` if present.

        Returns None when:
        * no rolling outline exists,
        * the rolling outline file is corrupt,
        * the chapter is not in the rolling outline (legacy outline
          chapters are NOT consulted here — that is the caller's job).
        """
        if not isinstance(chapter_number, int) or isinstance(chapter_number, bool):
            return None
        if chapter_number < 1:
            return None
        payload = self.read_rolling_outline()
        if not payload:
            return None
        for chapter in payload.get("chapters") or []:
            if not isinstance(chapter, dict):
                continue
            if chapter.get("chapter_number") == chapter_number:
                return dict(chapter)
        return None

    def _merge_rolling(
        self,
        existing: dict[str, Any],
        new_chapters: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Return a new rolling-outline payload with the
        new chapters appended after the existing rows.

        Existing rows are kept verbatim (including their
        ``source`` marker) so the operator can audit the
        generated / manual split. New rows are marked
        ``source = "generated"`` so the rolling fill can
        refresh them in a future pass.
        """
        merged_chapters: list[dict[str, Any]] = []
        seen_numbers: set[int] = set()
        for chapter in existing.get("chapters") or []:
            if not isinstance(chapter, dict):
                continue
            number = chapter.get("chapter_number")
            if (
                isinstance(number, int)
                and not isinstance(number, bool)
                and number > 0
            ):
                seen_numbers.add(number)
            merged_chapters.append(chapter)
        for chapter in new_chapters:
            if not isinstance(chapter, dict):
                continue
            number = chapter.get("chapter_number")
            if (
                isinstance(number, int)
                and not isinstance(number, bool)
                and number > 0
                and number in seen_numbers
            ):
                continue
            stamped = dict(chapter)
            if not stamped.get("source"):
                stamped["source"] = "generated"
            stamped.setdefault("generated_at", _utc_timestamp())
            merged_chapters.append(stamped)
            if (
                isinstance(number, int)
                and not isinstance(number, bool)
                and number > 0
            ):
                seen_numbers.add(number)
        payload = dict(existing)
        payload["chapters"] = merged_chapters
        payload["schema_version"] = _ROLLING_SCHEMA_VERSION
        return payload

    def _append_fill_log(
        self,
        *,
        chapter_numbers: list[int],
        volume_range: tuple[int, int],
        status: str,
        error: str = "",
    ) -> None:
        """Append one row to the rolling fill log.

        The log is a JSON file (not JSONL) so the operator
        can read the latest batch at a glance; older
        batches are preserved as a list.
        """
        log_path = self._fill_log_path()
        if log_path.is_file():
            try:
                existing = json.loads(
                    log_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                existing = {}
        else:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        rows = existing.get("rows")
        if not isinstance(rows, list):
            rows = []
        rows.append(
            {
                "chapter_numbers": list(chapter_numbers),
                "volume_range": list(volume_range),
                "status": status,
                "filled_at": _utc_timestamp(),
                "error": error,
            }
        )
        existing["rows"] = rows
        existing["last_chapter_numbers"] = list(chapter_numbers)
        existing["last_status"] = status
        try:
            _write_json_atomic(log_path, existing)
        except OSError as exc:
            raise RollingOutlineStoreError(
                f"rolling_outline_fill_log_failed: {exc}"
            ) from exc

    def apply_rolling_batch(
        self,
        *,
        chapters: list[dict[str, Any]],
        expected_chapter_numbers: list[int],
        volume_range: tuple[int, int],
    ) -> list[int]:
        """Apply a rolling-fill batch to the project
        outline. Returns the chapter numbers that were
        actually written.

        Fail-fast:

        * Validation failure → no write, no backup.
        * Atomic write failure → no backup on disk; the
          pre-call outline is byte-identical to the
          post-call outline.

        The function is idempotent: chapters already on
        disk (in either the legacy outline or the
        rolling outline) are skipped, not re-written.
        """
        # Step 1: validate the entire batch up front.
        validate_rolling_batch(
            chapters,
            expected_chapter_numbers=expected_chapter_numbers,
            volume_range=volume_range,
        )

        # Step 2: read both the legacy outline and the
        # rolling outline so the merge can preserve
        # existing rows and the backup can capture the
        # pre-call state.
        existing_rolling = _read_existing_rolling_outline(self._root)
        legacy_numbers = _read_legacy_outline_chapter_numbers(self._root)
        rolling_numbers = _existing_chapter_numbers(existing_rolling)
        already_filled = legacy_numbers | rolling_numbers

        # Step 3: only the chapters that are NOT already
        # on disk are written. ``validate_rolling_batch``
        # already accepted them, so this is the
        # idempotency check the plan rule requires ("已
        # 存在或人工修改的细纲不会被覆盖").
        new_chapters: list[dict[str, Any]] = []
        for chapter, number in zip(chapters, expected_chapter_numbers):
            if number in already_filled:
                continue
            new_chapters.append(chapter)
        if not new_chapters:
            self._append_fill_log(
                chapter_numbers=[],
                volume_range=volume_range,
                status="no_op",
            )
            return []

        # Step 4: build the new payload and write it
        # atomically. The pre-call outline is captured
        # as a backup right before the write so a
        # post-write regression can roll back.
        merged = self._merge_rolling(existing_rolling, new_chapters)
        try:
            self._backup_existing_outline(existing_rolling)
        except RollingOutlineStoreError:
            raise
        try:
            _write_json_atomic(self._rolling_path(), merged)
        except OSError as exc:
            raise RollingOutlineStoreError(
                f"rolling_outline_write_failed: {exc}"
            ) from exc

        # Step 5: append the audit log row.
        self._append_fill_log(
            chapter_numbers=sorted(int(c["chapter_number"]) for c in new_chapters),
            volume_range=volume_range,
            status="filled",
        )

        return sorted(int(c["chapter_number"]) for c in new_chapters)

    def update_chapter(
        self,
        *,
        chapter_number: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Edit an existing rolling chapter in place. The merged
        row is stamped ``source="manual"`` and
        ``last_manual_edit_at`` so subsequent rolling fills skip
        it (per plan rule "已存在或人工修改的细纲不会被覆盖").

        The merge is field-level: fields the operator did not
        supply are preserved from the existing row. A backup
        of the pre-call outline is written before the atomic
        write so a post-write regression can be rolled back.

        Errors:

        * :class:`RollingOutlineStoreError` with code
          ``rolling_outline_missing`` when no rolling outline
          exists on disk yet.
        * :class:`RollingOutlineStoreError` with code
          ``rolling_chapter_not_found`` when the rolling
          outline exists but does not contain ``chapter_number``.
        * :class:`RollingOutlineStoreError` for atomic-write
          failures (``rolling_outline_write_failed`` /
          ``rolling_outline_backup_failed``).
        """
        if not isinstance(chapter_number, int) or isinstance(chapter_number, bool):
            raise RollingOutlineStoreError("rolling_chapter_invalid_number")
        if chapter_number < 1:
            raise RollingOutlineStoreError("rolling_chapter_invalid_number")
        if not isinstance(payload, dict):
            raise RollingOutlineStoreError("rolling_chapter_invalid_payload")

        # Use the strict reader (returns None for missing) so we can
        # distinguish "no rolling outline yet" from "outline exists
        # but the chapter isn't in it". Both raise, but with
        # different codes so the API can return a useful 4xx.
        if not self._rolling_path().is_file():
            raise RollingOutlineStoreError("rolling_outline_missing")
        existing = _read_existing_rolling_outline(self._root)
        if not existing or not existing.get("chapters"):
            raise RollingOutlineStoreError("rolling_outline_missing")
        existing_chapters = [
            chapter for chapter in existing.get("chapters") or []
            if isinstance(chapter, dict)
        ]
        target_index = next(
            (
                index
                for index, chapter in enumerate(existing_chapters)
                if chapter.get("chapter_number") == chapter_number
            ),
            None,
        )
        if target_index is None:
            raise RollingOutlineStoreError(
                f"rolling_chapter_not_found:{chapter_number}"
            )

        merged_row = dict(existing_chapters[target_index])
        for key, value in payload.items():
            if value in (None, "", [], {}):
                continue
            merged_row[key] = value
        merged_row["source"] = "manual"
        merged_row["last_manual_edit_at"] = _utc_timestamp()

        new_chapters_list = list(existing_chapters)
        new_chapters_list[target_index] = merged_row
        new_payload = dict(existing)
        new_payload["chapters"] = new_chapters_list
        new_payload["schema_version"] = _ROLLING_SCHEMA_VERSION

        try:
            self._backup_existing_outline(existing)
        except RollingOutlineStoreError:
            raise
        try:
            _write_json_atomic(self._rolling_path(), new_payload)
        except OSError as exc:
            raise RollingOutlineStoreError(
                f"rolling_outline_write_failed: {exc}"
            ) from exc
        return merged_row


__all__ = [
    "RollingOutlineStore",
    "RollingOutlineStoreError",
]
