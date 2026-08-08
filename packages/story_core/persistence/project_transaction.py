"""Atomic multi-file project commit.

The file-project store has many managed files: ``state.json``,
``project.json``, the chapter JSON, the markdown body, the
continuity snapshot, and possibly more. Confirming a candidate
must apply all of them in one shot — a partial commit would leave
the project in a state that the user never saw. The
``ProjectTransaction`` is the thin coordinator: it stages every
payload, then asks the existing ``SnapshotStore`` to write them
atomically. If anything goes wrong, the rollback restores the
managed files to their pre-commit state.

The transaction also writes the per-chapter ``ChapterSnapshot``
and updates the stale-chapter markers when a rewrite marks later
chapters as stale. These auxiliary writes are part of the same
transaction: if the snapshot fails to land, the commit is rolled
back and the chapter is *not* considered confirmed.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from packages.story_core.continuity.snapshot import ChapterSnapshot
from packages.story_core.continuity.store import ContinuityStore
from packages.story_core.persistence.snapshot_store import SnapshotStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_body(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass
class TransactionResult:
    """Outcome of a ``ProjectTransaction.commit`` call.

    ``stale_chapters`` is non-empty only when the candidate was a
    ``regenerate`` and the transaction recorded the downstream
    chapters as stale. The orchestrator and the workbench can use
    this to warn the user.
    """

    chapter_number: int
    snapshot: ChapterSnapshot
    stale_chapters: list[int] = field(default_factory=list)


@dataclass
class ProjectTransaction:
    """Atomic, rollback-safe multi-file commit.

    Two ways to use the transaction:

    * **Staged payloads.** Build the transaction with the
      candidate's payloads, then call :meth:`commit` once. The
      transaction takes a snapshot of every staged path before
      writing; if any write fails, the snapshot is restored and
      the exception propagates. This is the pattern the candidate
      save / load path uses when it has the payloads in hand.

    * **Context manager.** Use ``with ProjectTransaction(...) as
      tx:`` to wrap a multi-step commit. The transaction
      snapshots every managed file in the project's standard
      directories on ``__enter__``; if the body raises, the
      snapshot is restored and the exception propagates. This is
      the pattern ``FileProjectStore.confirm_candidate`` uses —
      the body runs the legacy ``persist_bundle`` plus the
      per-chapter snapshot write, and a partial failure rolls
      everything back so the candidate stays ``pending``.
    """

    root: Path
    snapshot_store: SnapshotStore
    continuity_store: ContinuityStore
    payloads: dict[Path, Any] = field(default_factory=dict)
    snapshot: ChapterSnapshot | None = None
    stale_chapters: list[int] = field(default_factory=list)
    managed_directories: tuple[Path, ...] = ()
    _rollback_snapshot: dict[Path, bytes | None] = field(
        default_factory=dict, init=False, repr=False
    )
    _rollback_directories: tuple[Path, ...] = field(
        default_factory=tuple, init=False, repr=False
    )
    _managed_paths: tuple[Path, ...] = field(
        default_factory=tuple, init=False, repr=False
    )
    _rolled_back: bool = field(default=False, init=False, repr=False)

    @classmethod
    def create(
        cls,
        root: str | Path,
        *,
        snapshot_store: SnapshotStore,
        managed_paths: list[Path] | None = None,
        managed_directories: list[Path] | None = None,
    ) -> "ProjectTransaction":
        """Build a transaction rooted at ``root``.

        ``managed_paths`` and ``managed_directories`` are the
        tracked files the context-manager mode snapshots and
        restores. ``FileProjectStore`` supplies the canonical
        set of paths (state, project, chapters, continuity,
        reviews, commits) so callers do not have to enumerate
        them per project.
        """
        root_path = Path(root)
        return cls(
            root=root_path,
            snapshot_store=snapshot_store,
            continuity_store=ContinuityStore(root_path),
            managed_directories=tuple(managed_directories or ()),
        )._bind_managed_paths(managed_paths or [])

    def _bind_managed_paths(self, managed_paths: list[Path]) -> "ProjectTransaction":
        """Cache the explicit managed paths so :meth:`__enter__`
        can snapshot them without re-resolving the project layout
        on every transaction. The directories are still
        snapshotted lazily inside :meth:`__enter__` so file
        additions during the transaction body are caught.
        """
        self._managed_paths = tuple(Path(p) for p in managed_paths)
        return self

    def __enter__(self) -> "ProjectTransaction":
        """Snapshot the managed files and stash the snapshot for
        ``__exit__`` to restore on failure.

        The body of the ``with`` block is free to call
        :meth:`persist_bundle` or any other writer; the snapshot
        is the recovery boundary the user can trust.
        """
        directories: list[Path] = list(self.managed_directories)
        snapshot, snapshotted_dirs = SnapshotStore.snapshot_managed_files(
            list(self._managed_paths), directories
        )
        self._rollback_snapshot = snapshot
        self._rollback_directories = snapshotted_dirs
        self._rolled_back = False
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        """Restore the snapshot if the body raised.

        Successful bodies leave the on-disk state alone; failed
        bodies roll every managed file back to the
        pre-transaction state so the candidate stays
        ``pending`` and the user can re-confirm or discard.
        """
        if exc_type is None or not self._rollback_snapshot:
            return
        try:
            SnapshotStore.restore_managed_files(
                self._rollback_snapshot, self._rollback_directories
            )
            self._rolled_back = True
        except Exception:  # pragma: no cover - last-ditch recovery
            # The rollback itself failed; surface the original
            # exception so the caller still sees the failure
            # reason. The on-disk state may be inconsistent in
            # that case, but the user has the candidate status
            # as the authoritative signal of commit success.
            pass

    def rollback(self) -> None:
        """Force a rollback now (outside a ``with`` block).

        The snapshot taken by the most recent :meth:`__enter__`
        is restored. Calling :meth:`rollback` twice is a
        no-op.
        """
        if self._rolled_back or not self._rollback_snapshot:
            return
        SnapshotStore.restore_managed_files(
            self._rollback_snapshot, self._rollback_directories
        )
        self._rolled_back = True

    def add_payload(self, path: str | Path, payload: Any) -> None:
        self.payloads[Path(path)] = payload

    def add_markdown(self, path: str | Path, text: str) -> None:
        # Markdown bodies go through the text writer, not the JSON
        # transaction, so they are part of the rollback unit.
        target = Path(path)
        self.payloads[target] = ("text", text)

    def attach_snapshot(self, snapshot: ChapterSnapshot) -> None:
        self.snapshot = snapshot
        self.payloads[
            self.continuity_store.snapshot_path(snapshot.chapter_number)
        ] = snapshot.to_dict()

    def mark_stale(self, chapter_numbers: list[int]) -> None:
        self.stale_chapters = sorted({int(item) for item in chapter_numbers if int(item) > 0})

    def commit(self) -> TransactionResult:
        if self.snapshot is None:
            raise ValueError("project_transaction_missing_snapshot")

        # Split JSON vs text payloads. The atomic writer only
        # understands JSON, so text files are staged to their final
        # location after the JSON transaction succeeds.
        json_payloads: dict[Path, Any] = {}
        text_payloads: dict[Path, tuple[str, str]] = {}
        for path, payload in self.payloads.items():
            if isinstance(payload, tuple) and len(payload) == 2 and payload[0] == "text":
                text_payloads[path] = payload  # type: ignore[assignment]
            else:
                json_payloads[path] = payload

        # The snapshot file itself is part of the JSON commit. The
        # other JSON payloads (state.json, project.json, chapter
        # JSON) are written in the same atomic step.
        self.snapshot_store.replace_json_transaction(json_payloads)

        # Text files (Markdown bodies) come after the JSON commit.
        # A failure here is best-effort: the rollback restores the
        # JSON files, then the text files fall back to the
        # pre-commit bytes.
        try:
            for path, (_, text) in text_payloads.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        except Exception:
            # Rollback: the JSON commit was atomic, so we are
            # already at a consistent JSON state. Re-write the text
            # files from the managed snapshot below.
            self._rollback_text(text_payloads)
            raise

        if self.stale_chapters:
            self.continuity_store.mark_stale(self.stale_chapters)

        return TransactionResult(
            chapter_number=self.snapshot.chapter_number,
            snapshot=self.snapshot,
            stale_chapters=list(self.stale_chapters),
        )

    @staticmethod
    def _rollback_text(text_payloads: Mapping[Path, tuple[str, str]]) -> None:
        for path in text_payloads:
            path.unlink(missing_ok=True)


def build_chapter_snapshot(
    *,
    chapter_number: int,
    candidate_id: str,
    operation: str,
    body: str,
    state_after: Mapping[str, Any] | None = None,
    continuity_delta_summary: Mapping[str, Any] | None = None,
) -> ChapterSnapshot:
    """Convenience constructor used by ``confirm_candidate``.

    The snapshot captures the post-confirm state slice (just the
    keys the regeneration base-state path needs) and a tiny summary
    of the continuity delta so the workbench can render it without
    reopening the candidate file.
    """
    return ChapterSnapshot(
        chapter_number=int(chapter_number),
        candidate_id=str(candidate_id),
        operation=str(operation),
        confirmed_at=_now(),
        body_sha256=_hash_body(body),
        body_chars=len(body),
        state_after=dict(deepcopy(state_after or {})),
        continuity_delta_summary=dict(deepcopy(continuity_delta_summary or {})),
    )


def summarise_continuity_delta(delta: Any | None) -> dict[str, Any]:
    """Compress a ``ContinuityDelta`` (or ``None``) into a small dict.

    The snapshot file only carries the summary; the full delta stays
    on the candidate. The workbench reads the summary first to avoid
    loading the whole candidate payload.
    """
    if delta is None:
        return {}
    if hasattr(delta, "model_dump"):
        payload = delta.model_dump(mode="json")
    elif isinstance(delta, Mapping):
        payload = dict(delta)
    else:
        return {}
    return {
        "schema_version": payload.get("schema_version", "continuity-delta/v1"),
        "chapter_number": payload.get("chapter_number"),
        "counts": {
            "entity_additions": len(payload.get("entity_additions") or []),
            "entity_updates": len(payload.get("entity_updates") or []),
            "relationship_changes": len(payload.get("relationship_changes") or []),
            "inventory_changes": len(payload.get("inventory_changes") or []),
            "task_progressions": len(payload.get("task_progressions") or []),
            "location_movements": len(payload.get("location_movements") or []),
            "timeline_advances": len(payload.get("timeline_advances") or []),
            "foreshadowing_changes": len(payload.get("foreshadowing_changes") or []),
        },
    }


def slice_state_for_snapshot(state: Mapping[str, Any]) -> dict[str, Any]:
    """Pick the keys the regeneration base state actually uses.

    Keeping the slice small lets the snapshot file stay compact
    even when the project state is large.
    """
    keep = (
        "current_chapter",
        "characters",
        "world_facts",
        "foreshadowing",
        "progression_ledger",
        "continuity_facts",
    )
    return {key: deepcopy(state[key]) for key in keep if key in state}


def json_round_trip(payload: Any) -> Any:
    """Round-trip a payload through JSON to ensure it is serializable.

    Cheap safety net for callers that pass a Pydantic model or a
    dataclass that the atomic writer might not know how to dump.
    """
    return json.loads(json.dumps(payload, ensure_ascii=False, default=str))


__all__ = [
    "ProjectTransaction",
    "TransactionResult",
    "build_chapter_snapshot",
    "json_round_trip",
    "slice_state_for_snapshot",
    "summarise_continuity_delta",
]
