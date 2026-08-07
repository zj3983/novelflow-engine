"""Canonical project context reader.

Every agent that needs to look at a project artifact must go
through ``ProjectContextReader`` so the workbench, the migration
script, and the candidate's continuity trace can prove exactly
which files were read. The reader:

* never lets an agent pick its own path — callers must declare
  what they will read up front, or read through ``try_read_*``;
* refuses to leave the project root, including via
  ``..`` traversal or absolute paths that point outside;
* hashes the exact bytes that were read and reports the
  post-decode character count;
* tolerates UTF-8 with BOM for existing project data;
* returns ``None`` for missing optional artifacts instead of
  inventing content.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from .contracts import ArtifactRead


_MISSING_READ = ArtifactRead(
    kind="",
    path="",
    sha256="",
    chars=0,
)


class ProjectContextReader:
    """Read canonical project artifacts under a project root.

    The reader keeps a per-instance trace of every read so the
    agent can attach the exact set of inputs to its output
    context. ``try_read_*`` is the soft variant used for
    optional artifacts — the read is still recorded (with zero
    hash and zero chars) so the trace is honest about what the
    agent considered.
    """

    def __init__(
        self,
        root: Path,
        *,
        declared: Iterable[str] | None = None,
    ) -> None:
        self._root = Path(root).resolve()
        if not self._root.exists() or not self._root.is_dir():
            raise ValueError(f"project_root_not_found: {self._root}")
        self._declared: set[str] | None = (
            {self._normalize(path) for path in declared} if declared is not None else None
        )
        self._trace: list[ArtifactRead] = []

    # --- Public API -----------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._root

    @property
    def trace(self) -> list[ArtifactRead]:
        return list(self._trace)

    def last_read(self) -> ArtifactRead | None:
        return self._trace[-1] if self._trace else None

    def read_json(self, path: str, *, kind: str) -> dict | list:
        text = self._read_text(path, kind=kind, required=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"artifact_not_json: {path} ({exc})") from exc

    def read_text(self, path: str, *, kind: str) -> str:
        return self._read_text(path, kind=kind, required=True)

    def try_read_text(self, path: str, *, kind: str) -> str | None:
        return self._read_text(path, kind=kind, required=False)

    def try_read_json(self, path: str, *, kind: str) -> dict | list | None:
        text = self._read_text(path, kind=kind, required=False)
        if text is None:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    # --- Internals ------------------------------------------------------------

    def _read_text(self, path: str, *, kind: str, required: bool) -> str | None:
        normalized = self._normalize(path)
        self._ensure_declared(normalized)
        absolute = (self._root / normalized).resolve()
        if not self._is_inside(absolute):
            raise ValueError(
                f"artifact_path_outside_project: {path} resolves to {absolute}"
            )
        if not absolute.exists() or not absolute.is_file():
            if required:
                raise FileNotFoundError(f"artifact_missing: {path}")
            self._trace.append(
                ArtifactRead(kind=kind, path=normalized, sha256="", chars=0)
            )
            return None
        raw_bytes = absolute.read_bytes()
        sha = hashlib.sha256(raw_bytes).hexdigest()
        text = raw_bytes.decode("utf-8-sig")
        self._trace.append(
            ArtifactRead(kind=kind, path=normalized, sha256=sha, chars=len(text))
        )
        return text

    def _ensure_declared(self, normalized: str) -> None:
        if self._declared is None:
            return
        if normalized not in self._declared:
            raise ValueError(f"artifact_not_declared: {normalized}")

    def _normalize(self, path: str) -> str:
        text = str(path or "").strip()
        if not text:
            raise ValueError("artifact_path_empty")
        candidate = Path(text)
        if candidate.is_absolute():
            # Absolute paths are kept verbatim so the
            # ``inside-project`` containment check below can compare
            # them directly against the project root.
            return text
        # Strip a single leading ``./`` from relative paths so
        # callers can write ``./outline.json`` without us treating
        # it as a hidden file. Trailing path components are left
        # alone — the resolve() call below handles ``..`` segments
        # and the inside-project check rejects them.
        normalized = text.replace("\\", "/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized

    def _is_inside(self, absolute: Path) -> bool:
        try:
            absolute.relative_to(self._root)
            return True
        except ValueError:
            return False


__all__ = ["ProjectContextReader"]
