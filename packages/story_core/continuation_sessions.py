from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .continuation_import import (
    SUPPORTED_SUFFIXES,
    ContinuationChapter,
    ContinuationScanResult,
)


_SESSION_ID_RE = re.compile(r"^ci-[A-Za-z0-9][A-Za-z0-9_-]*$")


class ContinuationImportSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["continuation-import-session/v1"] = "continuation-import-session/v1"
    session_id: str
    revision: int = 1
    status: Literal["parsed", "analyzing", "ready", "failed", "cancelled"] = "parsed"
    source_path: str
    source_fingerprint: str
    encoding: str
    chapters: list[ContinuationChapter]
    analysis: dict[str, Any] = Field(default_factory=dict)
    analysis_progress: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    created_at: str = ""
    updated_at: str = ""


class _SourceFile(BaseModel):
    relative_path: str
    fingerprint: str
    payload: bytes = Field(exclude=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _source_files(source: Path, source_kind: Literal["file", "directory"]) -> list[Path]:
    if source_kind == "file":
        if not source.is_file():
            raise FileNotFoundError(source)
        return [source]
    if not source.is_dir():
        raise FileNotFoundError(source)
    return sorted(
        (
            path
            for path in source.rglob("*")
            if path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES
        ),
        key=lambda path: path.relative_to(source).as_posix(),
    )


def _snapshot_source(
    source: Path, source_kind: Literal["file", "directory"]
) -> tuple[str, list[_SourceFile]]:
    files = _source_files(source, source_kind)
    snapshots: list[_SourceFile] = []
    for path in files:
        payload = path.read_bytes()
        relative_path = path.name if source_kind == "file" else path.relative_to(source).as_posix()
        snapshots.append(
            _SourceFile(
                relative_path=relative_path,
                fingerprint=_sha256(payload),
                payload=payload,
            )
        )

    if source_kind == "file":
        return snapshots[0].fingerprint, snapshots

    combined = hashlib.sha256()
    for snapshot in snapshots:
        combined.update(snapshot.relative_path.encode("utf-8"))
        combined.update(b"\0")
        combined.update(snapshot.fingerprint.encode("ascii"))
        combined.update(b"\n")
    return combined.hexdigest(), snapshots


def fingerprint_continuation_source(
    path: Path | str,
    source_kind: Literal["file", "directory"] | None = None,
) -> str:
    source = Path(path).expanduser().resolve(strict=False)
    kind = source_kind or ("directory" if source.is_dir() else "file")
    fingerprint, _ = _snapshot_source(source, kind)
    return fingerprint


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _validate_session_id(session_id: str) -> None:
    if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError("session_id_invalid")


def _validated_chapters(chapters: list[ContinuationChapter]) -> list[ContinuationChapter]:
    if not chapters:
        raise ValueError("chapters_empty")

    normalized = [ContinuationChapter.model_validate(chapter.model_dump()) for chapter in chapters]
    if any(chapter.number <= 0 for chapter in normalized):
        raise ValueError("chapter_number_invalid")
    numbers = [chapter.number for chapter in normalized]
    if len(numbers) != len(set(numbers)):
        raise ValueError("chapter_number_duplicate")
    chapter_ids = [chapter.chapter_id for chapter in normalized]
    if len(chapter_ids) != len(set(chapter_ids)):
        raise ValueError("chapter_id_duplicate")
    if any(not chapter.title.strip() for chapter in normalized):
        raise ValueError("chapter_title_empty")
    if any(not chapter.body.strip() for chapter in normalized):
        raise ValueError("chapter_body_empty")
    return sorted(normalized, key=lambda chapter: chapter.number)


class ContinuationSessionStore:
    def __init__(
        self,
        root: Path,
        *,
        session_id_factory: Callable[[], str] | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._session_id_factory = session_id_factory or (lambda: f"ci-{uuid.uuid4().hex}")
        self._clock = clock or _utc_now
        self._lock = threading.RLock()

    def create(self, scan: ContinuationScanResult) -> ContinuationImportSession:
        with self._lock:
            session_id = self._session_id_factory()
            _validate_session_id(session_id)
            session_root = self.root / session_id
            if session_root.exists():
                raise FileExistsError(session_root)

            source = Path(scan.source_path).expanduser().resolve(strict=False)
            source_fingerprint, snapshots = _snapshot_source(source, scan.source_kind)
            original_root = session_root / "source" / "original"
            original_root.mkdir(parents=True)
            for snapshot in snapshots:
                backup_path = original_root / Path(snapshot.relative_path)
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                backup_path.write_bytes(snapshot.payload)
                if _sha256(backup_path.read_bytes()) != snapshot.fingerprint:
                    raise OSError("source_backup_verification_failed")

            manifest = {
                "schema_version": "continuation-source-manifest/v1",
                "source_path": str(source),
                "source_kind": scan.source_kind,
                "source_fingerprint": source_fingerprint,
                "encoding": scan.encoding,
                "files": [
                    {
                        "relative_path": snapshot.relative_path,
                        "fingerprint": snapshot.fingerprint,
                    }
                    for snapshot in snapshots
                ],
            }
            _write_json_atomic(session_root / "source" / "manifest.json", manifest)

            timestamp = self._clock()
            session = ContinuationImportSession(
                session_id=session_id,
                source_path=str(source),
                source_fingerprint=source_fingerprint,
                encoding=scan.encoding,
                chapters=[chapter.model_copy(deep=True) for chapter in scan.chapters],
                created_at=timestamp,
                updated_at=timestamp,
            )
            self._write_session(session)
            return session.model_copy(deep=True)

    def get(self, session_id: str) -> ContinuationImportSession:
        _validate_session_id(session_id)
        session_path = self._session_path(session_id)
        if not session_path.is_file():
            raise FileNotFoundError(f"continuation import session not found: {session_id}")
        with session_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return ContinuationImportSession.model_validate(payload)

    def replace_chapters(
        self,
        session_id: str,
        chapters: list[ContinuationChapter],
        expected_revision: int | None = None,
    ) -> ContinuationImportSession:
        def mutate(session: ContinuationImportSession) -> None:
            validated = _validated_chapters(chapters)
            try:
                current_fingerprint = fingerprint_continuation_source(
                    session.source_path,
                    "directory" if Path(session.source_path).is_dir() else "file",
                )
            except OSError:
                raise ValueError("source_changed_since_scan") from None
            if current_fingerprint != session.source_fingerprint:
                raise ValueError("source_changed_since_scan")
            session.chapters = validated

        return self.update(session_id, mutate, expected_revision=expected_revision)

    def update(
        self,
        session_id: str,
        mutate: Callable[[ContinuationImportSession], ContinuationImportSession | None],
        expected_revision: int | None = None,
    ) -> ContinuationImportSession:
        with self._lock:
            current = self.get(session_id)
            if expected_revision is not None and current.revision != expected_revision:
                raise ValueError("session_revision_conflict")

            candidate = current.model_copy(deep=True)
            result = mutate(candidate)
            if result is not None:
                candidate = result
            candidate = ContinuationImportSession.model_validate(candidate.model_dump(mode="json"))
            if candidate.session_id != current.session_id:
                raise ValueError("session_id_immutable")
            candidate.revision = current.revision + 1
            candidate.created_at = current.created_at
            candidate.updated_at = self._clock()
            self._write_session(candidate)
            return candidate.model_copy(deep=True)

    def _session_path(self, session_id: str) -> Path:
        _validate_session_id(session_id)
        return self.root / session_id / "session.json"

    def _write_session(self, session: ContinuationImportSession) -> None:
        _write_json_atomic(
            self._session_path(session.session_id),
            session.model_dump(mode="json"),
        )
