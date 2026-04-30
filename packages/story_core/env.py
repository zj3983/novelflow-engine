from __future__ import annotations

import os
from pathlib import Path


_LOADED = False


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    key, value = stripped.split("=", 1)
    key = key.strip()
    if key.startswith("export "):
        key = key[len("export ") :].strip()
    if not key:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def load_environment_files() -> None:
    """Load .env files without overriding real process environment values."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    root = project_root()
    protected_keys = set(os.environ)
    for path in (root / ".env", root / ".env.local"):
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            parsed = _parse_env_line(line)
            if parsed is None:
                continue
            key, value = parsed
            if key not in protected_keys:
                os.environ[key] = value


load_environment_files()
