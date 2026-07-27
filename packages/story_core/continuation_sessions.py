from __future__ import annotations

import hashlib
import errno
import json
import os
import re
import shutil
import tempfile
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .continuation_import import (
    SUPPORTED_SUFFIXES,
    ContinuationChapter,
    ContinuationScanResult,
    scan_continuation_source,
)


_SESSION_ID_RE = re.compile(r"^ci-[A-Za-z0-9][A-Za-z0-9_-]*$")
_LOCK_REGISTRY_GUARD = threading.Lock()
_LOCK_REGISTRY: dict[str, threading.RLock] = {}
_LOCK_STATE = threading.local()
_ANALYSIS_LEASE_GUARD = threading.Lock()
_HELD_ANALYSIS_LEASES: set[str] = set()


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


class _SourceManifestFile(BaseModel):
    relative_path: str
    fingerprint: str


class _SourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["continuation-source-manifest/v1"]
    source_path: str
    source_kind: Literal["file", "directory"]
    source_fingerprint: str
    encoding: str
    files: list[_SourceManifestFile]


def _is_link_or_junction(path: Path) -> bool:
    is_junction = getattr(os.path, "isjunction", lambda candidate: False)
    if path.is_symlink() or bool(is_junction(path)):
        return True
    if os.name != "nt":
        return False
    try:
        import ctypes

        get_attributes = ctypes.WinDLL("kernel32", use_last_error=True).GetFileAttributesW
        get_attributes.argtypes = [ctypes.c_wchar_p]
        get_attributes.restype = ctypes.c_uint32
        attributes = get_attributes(str(path))
    except (AttributeError, FileNotFoundError, OSError):
        return False
    return attributes != 0xFFFFFFFF and bool(attributes & 0x400)


def _resolve_contained_path(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve(strict=False)
    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError:
        raise ValueError("invalid_session_path") from None
    return resolved_candidate


def _before_secure_open(path: Path) -> None:
    return None


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _final_path_from_handle(handle: BinaryIO, fallback: Path) -> Path:
    if os.name == "nt":
        import ctypes
        import msvcrt

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_final_path = kernel32.GetFinalPathNameByHandleW
        get_final_path.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        get_final_path.restype = ctypes.c_uint32
        os_handle = msvcrt.get_osfhandle(handle.fileno())
        required = get_final_path(os_handle, None, 0, 0)
        if required == 0:
            raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
        buffer = ctypes.create_unicode_buffer(required + 1)
        written = get_final_path(os_handle, buffer, len(buffer), 0)
        if written == 0 or written >= len(buffer):
            raise OSError(ctypes.get_last_error(), "GetFinalPathNameByHandleW failed")
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return Path(value)

    descriptor_path = Path("/proc/self/fd") / str(handle.fileno())
    try:
        return Path(os.readlink(descriptor_path))
    except OSError:
        return fallback.resolve(strict=False)


def _validate_open_handle(
    handle: BinaryIO,
    *,
    fixed_root: Path,
    expected_path: Path,
) -> None:
    final_path = _final_path_from_handle(handle, expected_path)
    try:
        final_path.relative_to(fixed_root)
    except ValueError:
        raise ValueError("invalid_session_path") from None
    if _path_key(final_path) != _path_key(expected_path):
        raise ValueError("invalid_session_path")


@contextmanager
def _secure_open_binary(
    path: Path,
    *,
    fixed_root: Path,
    invoke_hook: bool = True,
) -> Iterator[BinaryIO]:
    expected_path = path.resolve(strict=False)
    if _is_link_or_junction(path):
        raise ValueError("invalid_session_path")
    if invoke_hook:
        _before_secure_open(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP or _is_link_or_junction(path):
            raise ValueError("invalid_session_path") from None
        raise
    handle = os.fdopen(descriptor, "rb")
    try:
        _validate_open_handle(
            handle,
            fixed_root=fixed_root,
            expected_path=expected_path,
        )
        yield handle
    finally:
        handle.close()


def _secure_read_json(path: Path, *, fixed_root: Path) -> Any:
    with _secure_open_binary(path, fixed_root=fixed_root) as handle:
        return json.loads(handle.read().decode("utf-8"))


def _secure_read_bytes(path: Path, *, fixed_root: Path) -> bytes:
    with _secure_open_binary(path, fixed_root=fixed_root) as handle:
        return handle.read()


def secure_read_bytes(path: Path, *, fixed_root: Path) -> bytes:
    """Read a file through a handle that is verified against a fixed root."""
    return _secure_read_bytes(path, fixed_root=fixed_root)


def _directory_identity(path: Path) -> tuple[int, int]:
    if _is_link_or_junction(path):
        raise ValueError("invalid_session_path")
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def _validate_directory_identity(path: Path, identity: tuple[int, int]) -> None:
    if _directory_identity(path) != identity:
        raise ValueError("invalid_session_path")


def _registered_lock(lock_path: Path) -> threading.RLock:
    key = os.path.normcase(str(lock_path.resolve(strict=False)))
    with _LOCK_REGISTRY_GUARD:
        return _LOCK_REGISTRY.setdefault(key, threading.RLock())


def _try_lock_file(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ContinuationAnalysisLease:
    def __init__(self, handle: BinaryIO, key: str) -> None:
        self._handle = handle
        self._key = key
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            _unlock_file(self._handle)
        finally:
            try:
                self._handle.close()
            finally:
                with _ANALYSIS_LEASE_GUARD:
                    _HELD_ANALYSIS_LEASES.discard(self._key)


def try_acquire_analysis_lease(
    session_root: Path | str, session_id: str
) -> ContinuationAnalysisLease | None:
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise ValueError("invalid_session_id")
    root = Path(session_root).resolve(strict=True)
    lease_root = root / ".analysis-leases"
    lease_root.mkdir(mode=0o700, exist_ok=True)
    resolved_lease_root = lease_root.resolve(strict=True)
    if _is_link_or_junction(lease_root) or resolved_lease_root.parent != root:
        raise ValueError("invalid_session_path")
    lease_path = lease_root / f"{session_id}.lock"
    key = _path_key(lease_path)
    with _ANALYSIS_LEASE_GUARD:
        if key in _HELD_ANALYSIS_LEASES:
            return None
        _HELD_ANALYSIS_LEASES.add(key)

    handle: BinaryIO | None = None
    try:
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(lease_path, flags, 0o600)
        handle = os.fdopen(descriptor, "r+b")
        _validate_open_handle(
            handle,
            fixed_root=resolved_lease_root,
            expected_path=lease_path.resolve(strict=False),
        )
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        try:
            _try_lock_file(handle)
        except (BlockingIOError, PermissionError):
            handle.close()
            handle = None
            with _ANALYSIS_LEASE_GUARD:
                _HELD_ANALYSIS_LEASES.discard(key)
            return None
        return ContinuationAnalysisLease(handle, key)
    except BaseException:
        if handle is not None:
            handle.close()
        with _ANALYSIS_LEASE_GUARD:
            _HELD_ANALYSIS_LEASES.discard(key)
        raise


@contextmanager
def _interprocess_lock(
    lock_path: Path,
    *,
    timeout: float,
    poll_interval: float,
) -> Iterator[None]:
    key = os.path.normcase(str(lock_path.resolve(strict=False)))
    held_locks = getattr(_LOCK_STATE, "held_locks", None)
    if held_locks is None:
        held_locks = {}
        _LOCK_STATE.held_locks = held_locks
    if key in held_locks:
        held_locks[key] += 1
        try:
            yield
        finally:
            held_locks[key] -= 1
        return

    deadline = time.monotonic() + timeout
    process_lock = _registered_lock(lock_path)
    remaining = max(0.0, deadline - time.monotonic())
    if not process_lock.acquire(timeout=remaining):
        raise ValueError("session_lock_timeout")
    try:
        with lock_path.open("a+b") as handle:
            _validate_open_handle(
                handle,
                fixed_root=lock_path.parent,
                expected_path=lock_path.resolve(strict=False),
            )
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            while True:
                try:
                    _try_lock_file(handle)
                    break
                except (BlockingIOError, OSError):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValueError("session_lock_timeout") from None
                    time.sleep(min(poll_interval, remaining))
            held_locks[key] = 1
            try:
                yield
            finally:
                del held_locks[key]
                _unlock_file(handle)
    finally:
        process_lock.release()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _source_files(source: Path, source_kind: Literal["file", "directory"]) -> list[Path]:
    if source_kind == "file":
        if _is_link_or_junction(source):
            raise ValueError("path_outside_allowed_roots")
        if not source.is_file():
            raise FileNotFoundError(source)
        return [source]
    if not source.is_dir():
        raise FileNotFoundError(source)
    files: list[Path] = []
    for path in source.rglob("*"):
        if _is_link_or_junction(path):
            raise ValueError("path_outside_allowed_roots")
        if path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES:
            files.append(path)
    return sorted(files, key=lambda path: path.relative_to(source).as_posix())


def _snapshot_source(
    source: Path, source_kind: Literal["file", "directory"]
) -> tuple[str, list[_SourceFile]]:
    files = _source_files(source, source_kind)
    snapshots: list[_SourceFile] = []
    for path in files:
        fixed_root = source.parent if source_kind == "file" else source
        try:
            payload = _secure_read_bytes(path, fixed_root=fixed_root)
        except ValueError as exc:
            if str(exc) == "invalid_session_path":
                raise ValueError("path_outside_allowed_roots") from None
            raise
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


def _normalized_text(value: str, *, collapse_whitespace: bool) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    if collapse_whitespace:
        return " ".join(normalized.split())
    return normalized.strip()


def _scan_signature(scan: ContinuationScanResult) -> tuple[object, ...]:
    chapters = tuple(
        (
            chapter.number,
            _normalized_text(chapter.title, collapse_whitespace=True),
            _normalized_text(chapter.body, collapse_whitespace=False),
            chapter.fingerprint,
            chapter.source_name,
            chapter.source_start,
            chapter.source_end,
        )
        for chapter in scan.chapters
    )
    return scan.source_kind, scan.encoding, len(chapters), chapters


def _forced_encoding(encoding: str) -> str | None:
    return None if not encoding or encoding == "mixed" else encoding


def _manifest_relative_path(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    windows_path = Path(value)
    if (
        not value
        or "\\" in value
        or relative.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != value
    ):
        raise ValueError("source_manifest_invalid")
    return relative


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parent_identity = _directory_identity(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            _validate_open_handle(
                handle.buffer,
                fixed_root=path.parent,
                expected_path=temporary_path.resolve(strict=False),
            )
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _before_secure_open(path)
        _validate_directory_identity(path.parent, parent_identity)
        if _is_link_or_junction(path):
            raise ValueError("invalid_session_path")
        os.replace(temporary_path, path)
        _validate_directory_identity(path.parent, parent_identity)
        with _secure_open_binary(
            path,
            fixed_root=path.parent,
            invoke_hook=False,
        ):
            pass
    except BaseException:
        try:
            _validate_directory_identity(path.parent, parent_identity)
        except (OSError, ValueError):
            pass
        else:
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
        lock_timeout: float = 60.0,
        lock_poll_interval: float = 0.05,
    ) -> None:
        if lock_timeout <= 0 or lock_poll_interval <= 0:
            raise ValueError("session_lock_configuration_invalid")
        requested_root = Path(root).expanduser()
        requested_root.mkdir(parents=True, exist_ok=True)
        self.root = requested_root.resolve(strict=True)
        if not self.root.is_dir() or _is_link_or_junction(self.root):
            raise ValueError("invalid_session_path")
        self._locks_root = self.root / ".locks"
        self._locks_root.mkdir(parents=True, exist_ok=True)
        self._validate_locks_root()
        self._session_id_factory = session_id_factory or (lambda: f"ci-{uuid.uuid4().hex}")
        self._clock = clock or _utc_now
        self._lock_timeout = lock_timeout
        self._lock_poll_interval = lock_poll_interval

    def create(self, scan: ContinuationScanResult) -> ContinuationImportSession:
        session_id = self._session_id_factory()
        _validate_session_id(session_id)
        with self._session_lock(session_id):
            final_root = self._session_root(session_id, require_exists=False)
            if final_root.exists():
                raise FileExistsError(final_root)

            staging_root = Path(tempfile.mkdtemp(dir=self.root, prefix=f".{session_id}."))
            _resolve_contained_path(self.root, staging_root)
            try:
                session = self._build_staged_session(staging_root, session_id, scan)
                self._read_validated_session_root(staging_root, session_id)
                final_root = self._session_root(session_id, require_exists=False)
                if final_root.exists():
                    raise FileExistsError(final_root)
                os.rename(staging_root, final_root)
                staging_root = None
                return session.model_copy(deep=True)
            finally:
                if staging_root is not None:
                    self._cleanup_staging(staging_root)

    def get(self, session_id: str) -> ContinuationImportSession:
        _validate_session_id(session_id)
        with self._session_lock(session_id):
            session, _ = self._read_validated_session(session_id)
            return session

    def replace_chapters(
        self,
        session_id: str,
        chapters: list[ContinuationChapter],
        expected_revision: int | None = None,
        *,
        invalidate_analysis: bool = False,
    ) -> ContinuationImportSession:
        def mutate(session: ContinuationImportSession) -> None:
            validated = _validated_chapters(chapters)
            session_root = self._session_root(session_id, require_exists=True)
            source_kind = self._read_source_manifest(session_root).source_kind
            try:
                current_fingerprint = fingerprint_continuation_source(
                    session.source_path,
                    source_kind,
                )
            except OSError:
                raise ValueError("source_changed_since_scan") from None
            if current_fingerprint != session.source_fingerprint:
                raise ValueError("source_changed_since_scan")
            session.chapters = validated
            if invalidate_analysis:
                session.status = "parsed"
                session.analysis = {}
                session.analysis_progress = {}
                session.error = ""

        return self.update(session_id, mutate, expected_revision=expected_revision)

    def update(
        self,
        session_id: str,
        mutate: Callable[[ContinuationImportSession], ContinuationImportSession | None],
        expected_revision: int | None = None,
    ) -> ContinuationImportSession:
        _validate_session_id(session_id)
        with self._session_lock(session_id):
            current, manifest = self._read_validated_session(session_id)
            if expected_revision is not None and current.revision != expected_revision:
                raise ValueError("session_revision_conflict")
            self._validate_current_source_kind(current, manifest)

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
            session_root = self._session_root(session_id, require_exists=True)
            self._write_session(candidate, session_root)
            return candidate.model_copy(deep=True)

    def _validate_current_source_kind(
        self,
        session: ContinuationImportSession,
        manifest: _SourceManifest,
    ) -> None:
        source = Path(session.source_path)
        current_kind = "file" if source.is_file() else "directory" if source.is_dir() else None
        if current_kind != manifest.source_kind:
            raise ValueError("source_changed_since_scan")

    def _assert_root(self) -> None:
        if not self.root.is_dir() or _is_link_or_junction(self.root):
            raise ValueError("invalid_session_path")
        if self.root.resolve(strict=True) != self.root:
            raise ValueError("invalid_session_path")

    def _validate_locks_root(self) -> Path:
        self._assert_root()
        if _is_link_or_junction(self._locks_root):
            raise ValueError("invalid_session_path")
        resolved = _resolve_contained_path(self.root, self._locks_root)
        if not resolved.is_dir():
            raise ValueError("invalid_session_path")
        return resolved

    def _lock_path(self, session_id: str) -> Path:
        _validate_session_id(session_id)
        locks_root = self._validate_locks_root()
        return _resolve_contained_path(locks_root, locks_root / f"{session_id}.lock")

    @contextmanager
    def _session_lock(self, session_id: str) -> Iterator[None]:
        lock_path = self._lock_path(session_id)
        with _interprocess_lock(
            lock_path,
            timeout=self._lock_timeout,
            poll_interval=self._lock_poll_interval,
        ):
            self._assert_root()
            if self._lock_path(session_id) != lock_path:
                raise ValueError("invalid_session_path")
            yield

    def _session_root(self, session_id: str, *, require_exists: bool) -> Path:
        _validate_session_id(session_id)
        self._assert_root()
        candidate = self.root / session_id
        if _is_link_or_junction(candidate):
            raise ValueError("invalid_session_path")
        resolved = _resolve_contained_path(self.root, candidate)
        if require_exists:
            if not resolved.exists():
                raise FileNotFoundError(f"continuation import session not found: {session_id}")
            if not resolved.is_dir():
                raise ValueError("invalid_session_path")
        return resolved

    def _build_staged_session(
        self,
        staging_root: Path,
        session_id: str,
        scan: ContinuationScanResult,
    ) -> ContinuationImportSession:
        staging_root = _resolve_contained_path(self.root, staging_root)
        if _is_link_or_junction(staging_root):
            raise ValueError("invalid_session_path")
        source = Path(scan.source_path).expanduser().resolve(strict=False)
        forced_encoding = _forced_encoding(scan.encoding)
        fresh_scan = scan_continuation_source(source, forced_encoding=forced_encoding)
        if _scan_signature(fresh_scan) != _scan_signature(scan):
            raise ValueError("source_changed_since_scan")

        source_fingerprint, snapshots = _snapshot_source(source, scan.source_kind)
        source_root = _resolve_contained_path(staging_root, staging_root / "source")
        original_root = _resolve_contained_path(source_root, source_root / "original")
        original_root.mkdir(parents=True)
        for snapshot in snapshots:
            relative = _manifest_relative_path(snapshot.relative_path)
            backup_path = original_root.joinpath(*relative.parts)
            _resolve_contained_path(original_root, backup_path)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path.write_bytes(snapshot.payload)
            if (
                _sha256(_secure_read_bytes(backup_path, fixed_root=original_root))
                != snapshot.fingerprint
            ):
                raise OSError("source_backup_verification_failed")

        backup_source = (
            original_root / snapshots[0].relative_path
            if scan.source_kind == "file"
            else original_root
        )
        backup_scan = scan_continuation_source(backup_source, forced_encoding=forced_encoding)
        if _scan_signature(backup_scan) != _scan_signature(fresh_scan):
            raise ValueError("source_changed_since_scan")

        manifest = _SourceManifest(
            schema_version="continuation-source-manifest/v1",
            source_path=str(source),
            source_kind=scan.source_kind,
            source_fingerprint=source_fingerprint,
            encoding=scan.encoding,
            files=[
                _SourceManifestFile(
                    relative_path=snapshot.relative_path,
                    fingerprint=snapshot.fingerprint,
                )
                for snapshot in snapshots
            ],
        )
        manifest_path = _resolve_contained_path(source_root, source_root / "manifest.json")
        _write_json_atomic(manifest_path, manifest.model_dump(mode="json"))

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
        self._write_session(session, staging_root)
        return session

    def _read_validated_session(
        self,
        session_id: str,
    ) -> tuple[ContinuationImportSession, _SourceManifest]:
        session_root = self._session_root(session_id, require_exists=True)
        return self._read_validated_session_root(session_root, session_id)

    def _read_validated_session_root(
        self,
        session_root: Path,
        expected_session_id: str,
    ) -> tuple[ContinuationImportSession, _SourceManifest]:
        resolved_root = _resolve_contained_path(self.root, session_root)
        if _is_link_or_junction(session_root) or not resolved_root.is_dir():
            raise ValueError("invalid_session_path")
        session_path = _resolve_contained_path(resolved_root, resolved_root / "session.json")
        if _is_link_or_junction(session_path) or not session_path.is_file():
            raise FileNotFoundError(
                f"continuation import session not found: {expected_session_id}"
            )
        session = ContinuationImportSession.model_validate(
            _secure_read_json(session_path, fixed_root=resolved_root)
        )
        if session.session_id != expected_session_id:
            raise ValueError("source_manifest_invalid")
        manifest = self._read_source_manifest(resolved_root)
        self._validate_source_backup(resolved_root, session, manifest)
        return session, manifest

    def _read_source_manifest(self, session_root: Path) -> _SourceManifest:
        try:
            manifest_path = _resolve_contained_path(
                session_root,
                session_root / "source" / "manifest.json",
            )
            if _is_link_or_junction(manifest_path) or not manifest_path.is_file():
                raise ValueError("source_manifest_invalid")
            manifest = _SourceManifest.model_validate(
                _secure_read_json(manifest_path, fixed_root=session_root)
            )
            relative_paths = [
                _manifest_relative_path(item.relative_path) for item in manifest.files
            ]
            if len(relative_paths) != len(set(relative_paths)):
                raise ValueError("source_manifest_invalid")
            return manifest
        except ValueError as exc:
            if str(exc) == "source_manifest_invalid":
                raise
            raise ValueError("source_manifest_invalid") from None
        except (OSError, json.JSONDecodeError, ValidationError):
            raise ValueError("source_manifest_invalid") from None

    def _validate_source_backup(
        self,
        session_root: Path,
        session: ContinuationImportSession,
        manifest: _SourceManifest,
    ) -> None:
        if (
            manifest.source_path != session.source_path
            or manifest.source_fingerprint != session.source_fingerprint
            or manifest.encoding != session.encoding
        ):
            raise ValueError("source_manifest_invalid")

        backup_root = session_root / "source" / "original"
        try:
            resolved_backup_root = _resolve_contained_path(session_root, backup_root)
        except ValueError:
            raise ValueError("source_backup_invalid") from None
        if _is_link_or_junction(backup_root) or not resolved_backup_root.is_dir():
            raise ValueError("source_backup_invalid")

        expected = {item.relative_path: item.fingerprint for item in manifest.files}
        actual: set[str] = set()
        for path in resolved_backup_root.rglob("*"):
            if _is_link_or_junction(path):
                raise ValueError("source_backup_invalid")
            if path.is_file():
                try:
                    resolved_path = _resolve_contained_path(resolved_backup_root, path)
                except ValueError:
                    raise ValueError("source_backup_invalid") from None
                actual.add(resolved_path.relative_to(resolved_backup_root).as_posix())
        if actual != set(expected):
            raise ValueError("source_backup_invalid")

        for relative_path, fingerprint in expected.items():
            relative = _manifest_relative_path(relative_path)
            backup_path = resolved_backup_root.joinpath(*relative.parts)
            try:
                resolved_backup = _resolve_contained_path(resolved_backup_root, backup_path)
            except ValueError:
                raise ValueError("source_backup_invalid") from None
            if (
                _is_link_or_junction(backup_path)
                or not resolved_backup.is_file()
                or _sha256(
                    _secure_read_bytes(
                        resolved_backup,
                        fixed_root=resolved_backup_root,
                    )
                )
                != fingerprint
            ):
                raise ValueError("source_backup_invalid")

        if manifest.source_kind == "file":
            if len(expected) != 1:
                raise ValueError("source_manifest_invalid")
            calculated_fingerprint = next(iter(expected.values()))
        else:
            combined = hashlib.sha256()
            for relative_path in sorted(expected):
                combined.update(relative_path.encode("utf-8"))
                combined.update(b"\0")
                combined.update(expected[relative_path].encode("ascii"))
                combined.update(b"\n")
            calculated_fingerprint = combined.hexdigest()
        if calculated_fingerprint != manifest.source_fingerprint:
            raise ValueError("source_manifest_invalid")

    def _cleanup_staging(self, staging_root: Path) -> None:
        try:
            resolved = _resolve_contained_path(self.root, staging_root)
        except ValueError:
            return
        if resolved.exists() and not _is_link_or_junction(staging_root):
            shutil.rmtree(resolved, ignore_errors=True)

    def _write_session(
        self,
        session: ContinuationImportSession,
        session_root: Path,
    ) -> None:
        resolved_root = _resolve_contained_path(self.root, session_root)
        if _is_link_or_junction(session_root):
            raise ValueError("invalid_session_path")
        session_path = _resolve_contained_path(resolved_root, resolved_root / "session.json")
        _write_json_atomic(
            session_path,
            session.model_dump(mode="json"),
        )
