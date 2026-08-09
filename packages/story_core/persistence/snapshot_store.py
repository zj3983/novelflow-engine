"""Atomic JSON writes and rollback snapshots for file projects."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class SnapshotStore:
    def read_json(self, path: str | Path, default: Any = None) -> Any:
        target = Path(path)
        if not target.exists():
            return default
        return json.loads(target.read_text(encoding="utf-8-sig"))

    def write_json(self, path: str | Path, payload: Any) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_text(self, path: str | Path, text: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    @staticmethod
    def _replace_file(source: str | Path, target: str | Path) -> None:
        os.replace(source, target)

    @staticmethod
    def _temporary_path(target: Path) -> tuple[int, Path]:
        fd, name = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        return fd, Path(name)

    def write_json_atomic(self, path: str | Path, payload: Any) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd: int | None = None
        temporary: Path | None = None
        try:
            fd, temporary = self._temporary_path(target)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = None
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            self._replace_file(temporary, target)
        finally:
            if fd is not None:
                os.close(fd)
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _write_bytes_temporary(target: Path, content: bytes) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd: int | None = None
        temporary: Path | None = None
        try:
            fd, temporary = SnapshotStore._temporary_path(target)
            with os.fdopen(fd, "wb") as handle:
                fd = None
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            return temporary
        except Exception:
            if fd is not None:
                os.close(fd)
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise

    def restore_bytes_atomic(self, snapshots: dict[Path, bytes | None]) -> None:
        """Restore complete files via fsynced same-directory replacements."""

        prepared: dict[Path, Path] = {}
        try:
            for raw_path, content in snapshots.items():
                path = Path(raw_path)
                if content is not None:
                    prepared[path] = self._write_bytes_temporary(path, content)
            for raw_path, content in snapshots.items():
                path = Path(raw_path)
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    self._replace_file(prepared[path], path)
        except Exception as exc:
            raise RuntimeError("rollback_failed") from exc
        finally:
            for temporary in prepared.values():
                temporary.unlink(missing_ok=True)

    def replace_json_transaction(self, payloads: dict[Path, Any]) -> None:
        targets = [(Path(path), payload) for path, payload in payloads.items()]
        snapshots = {path: path.read_bytes() if path.exists() else None for path, _ in targets}
        prepared: dict[Path, Path] = {}
        try:
            for path, payload in targets:
                path.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = self._temporary_path(path)
                prepared[path] = temporary
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
                    handle.flush()
                    os.fsync(handle.fileno())
            for path, _ in targets:
                self._replace_file(prepared[path], path)
        except Exception as exc:
            try:
                self.restore_bytes_atomic(snapshots)
            except RuntimeError as rollback_exc:
                raise RuntimeError("json_transaction_rollback_failed") from rollback_exc
            raise
        finally:
            for temporary in prepared.values():
                temporary.unlink(missing_ok=True)

    @staticmethod
    def snapshot_managed_files(
        paths: list[Path],
        directories: list[Path],
    ) -> tuple[dict[Path, bytes | None], tuple[Path, ...]]:
        managed_paths = {Path(path).resolve() for path in paths}
        managed_directories = tuple(Path(path).resolve() for path in directories)
        for directory in managed_directories:
            if directory.exists():
                managed_paths.update(path.resolve() for path in directory.rglob("*") if path.is_file())
        return (
            {path: path.read_bytes() if path.exists() else None for path in managed_paths},
            managed_directories,
        )

    @staticmethod
    def restore_managed_files(
        snapshot: dict[Path, bytes | None],
        directories: tuple[Path, ...],
    ) -> None:
        snapshotted_paths = set(snapshot)
        for directory in directories:
            if not directory.exists():
                continue
            for path in directory.rglob("*"):
                resolved = path.resolve()
                if path.is_file() and resolved not in snapshotted_paths:
                    path.unlink()
        for path, content in snapshot.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
