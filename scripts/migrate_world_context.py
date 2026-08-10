"""Migrate legacy file projects to separated world context storage."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from packages.story_core.world_state import normalize_world_context


def migrate_project(
    project_root: str | Path,
    *,
    apply: bool = False,
    timestamp: str | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    webnovel = root / ".webnovel"
    project_path = webnovel / "project.json"
    state_path = webnovel / "state.json"
    project_bytes = _read_required(project_path)
    state_bytes = _read_required(state_path)
    project = _decode_json(project_path, project_bytes)
    state = _decode_json(state_path, state_bytes)

    blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
    normalized = normalize_world_context(
        blueprint=blueprint,
        state=state,
        current_focus=project.get("current_focus"),
    )
    migrated_project = deepcopy(project)
    migrated_project["world_blueprint"] = normalized.static_blueprint
    migrated_state = deepcopy(state)
    legacy_facts = list(state.get("legacy_world_facts") or [])
    if not legacy_facts and isinstance(state.get("world_facts"), list):
        legacy_facts = deepcopy(state["world_facts"])
    migrated_state["world_snapshot"] = normalized.world_snapshot
    migrated_state["continuity_facts"] = normalized.continuity_facts
    migrated_state["legacy_world_facts"] = legacy_facts
    migrated_state["world_facts"] = []

    next_project_bytes = _encode_json(migrated_project)
    next_state_bytes = _encode_json(migrated_state)
    changed = next_project_bytes != project_bytes or next_state_bytes != state_bytes
    report = {
        "schema_version": "world-context-migration/v1",
        "root": str(root),
        "changed": changed,
        "applied": bool(apply and changed),
        "continuity_fact_count": len(normalized.continuity_facts),
        "snapshot_fields": sorted(normalized.world_snapshot),
        "backup": "",
    }
    if not apply or not changed:
        return report

    stamp = timestamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = root / ".story-system" / "world-context-backups" / stamp
    backup.mkdir(parents=True, exist_ok=False)
    (backup / "project.json").write_bytes(project_bytes)
    (backup / "state.json").write_bytes(state_bytes)
    report["backup"] = str(backup)

    project_tmp = _stage_atomic(project_path, next_project_bytes)
    state_tmp = _stage_atomic(state_path, next_state_bytes)
    try:
        os.replace(project_tmp, project_path)
        os.replace(state_tmp, state_path)
    except Exception:
        project_path.write_bytes(project_bytes)
        state_path.write_bytes(state_bytes)
        raise
    finally:
        for path in (project_tmp, state_tmp):
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
    return report


def _read_required(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"missing_file:{path}")
    return path.read_bytes()


def _decode_json(path: Path, payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid_json:{path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"invalid_json_object:{path.name}")
    return value


def _encode_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _stage_atomic(target: Path, payload: bytes) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    with os.fdopen(handle, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return name


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write migrated files after making a backup")
    mode.add_argument("--dry-run", action="store_true", help="inspect changes without writing files")
    args = parser.parse_args()
    report = migrate_project(args.project_root, apply=args.apply)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
