"""Persistent storage for director artifacts.

The director is the structural agent — its artifact is an
inspectable work product, not confirmed canon. The store
writes the artifact to ``.story-system/director/NNNN.json``
atomically and keeps the full envelope (status, provider,
model, input trace, output) so the workbench and the
migration script can later prove which model produced each
chapter plan.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class DirectorStore:
    """Write and read director artifacts under a project root."""

    def __init__(self, project_root: Path) -> None:
        self._project_root = Path(project_root).resolve()
        system_root = self._project_root / ".story-system"
        system_root.mkdir(parents=True, exist_ok=True)
        self._director_dir = system_root / "director"
        self._director_dir.mkdir(parents=True, exist_ok=True)

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def director_dir(self) -> Path:
        return self._director_dir

    def path_for(self, chapter_number: int) -> Path:
        if not isinstance(chapter_number, int) or chapter_number < 1:
            raise ValueError(f"invalid_chapter_number: {chapter_number!r}")
        return self._director_dir / f"{chapter_number:04d}.json"

    def save(self, *, chapter_number: int, payload: Any) -> Path:
        target = self.path_for(chapter_number)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = -1  # ownership transferred to handle
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise
        Path(temporary).unlink(missing_ok=True)
        return target

    def load(self, chapter_number: int) -> dict | None:
        target = self.path_for(chapter_number)
        if not target.exists() or not target.is_file():
            return None
        return json.loads(target.read_text(encoding="utf-8-sig"))


__all__ = ["DirectorStore"]
