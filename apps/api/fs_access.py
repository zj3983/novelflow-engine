from __future__ import annotations

import os
from pathlib import Path

ENV_ALLOWED_FS_ROOTS = "NOVEL_AUTOGROWTH_ALLOWED_FS_ROOTS"


def allowed_fs_roots() -> list[Path]:
    """Roots that filesystem-browsing API endpoints may touch.

    Configured via NOVEL_AUTOGROWTH_ALLOWED_FS_ROOTS (os.pathsep-separated).
    Defaults to the user's home directory and the current working directory.
    """
    raw = os.environ.get(ENV_ALLOWED_FS_ROOTS, "").strip()
    candidates = (
        [entry for entry in raw.split(os.pathsep) if entry.strip()]
        if raw
        else [str(Path.home()), str(Path.cwd())]
    )
    roots: list[Path] = []
    for candidate in candidates:
        try:
            roots.append(Path(candidate).expanduser().resolve())
        except OSError:
            continue
    return roots


def is_within_allowed_roots(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return any(resolved.is_relative_to(root) for root in allowed_fs_roots())


def require_allowed_path(path: Path) -> Path:
    resolved = path.resolve()
    if not is_within_allowed_roots(resolved):
        raise ValueError(f"path_outside_allowed_roots: {resolved}")
    return resolved
