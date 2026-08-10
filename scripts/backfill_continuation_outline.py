"""Safe legacy-project backfill for the continuation outline bootstrap.

Plan rule: the bootstrap is the only place that produces
future outline material, but legacy projects may have been
imported before the bootstrap was wired into the import flow.
This script lets the operator backfill those layers without
ever overwriting the user-edited history.

Usage:

    python scripts/backfill_continuation_outline.py <project-root> --dry-run
    python scripts/backfill_continuation_outline.py <project-root> --apply

The dry-run path prints the current chapter, the present
layers, the missing phases, the next window, and the proposed
files. It never touches the project on disk.

The apply path creates a timestamped backup under
``.story-system/backups/continuation-bootstrap/``, runs only
the missing phases, and refuses to run on non-continuation
projects (no ``continuation.session_id`` in the project
payload).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from packages.story_core.continuation_outline_bootstrap import (  # noqa: E402
    BOOTSTRAP_PHASES,
    ContinuationOutlineBootstrapper,
    BootstrapReadiness,
    validate_continuation_bootstrap,
)


def _read_json(path: Path) -> object:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _is_continuation_project(root: Path) -> tuple[bool, str]:
    project = _read_json(root / ".webnovel" / "project.json")
    if not isinstance(project, dict):
        return False, "project.json is missing or not a JSON object"
    continuation = project.get("continuation")
    if not isinstance(continuation, dict):
        return False, "project.json has no continuation metadata"
    session_id = continuation.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return False, "continuation.session_id is missing or empty"
    return True, "ok"


def _current_chapter(root: Path) -> int:
    state = _read_json(root / ".webnovel" / "state.json")
    if isinstance(state, dict):
        try:
            value = int(state.get("current_chapter") or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    project = _read_json(root / ".webnovel" / "project.json")
    if isinstance(project, dict):
        try:
            value = int(project.get("current_chapter") or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return 0


def _rolling_outline_present(root: Path) -> bool:
    path = root / ".story-system" / "outline-generation" / "rolling_outline.json"
    if not path.is_file():
        return False
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("chapters"))


def _present_layers(root: Path) -> list[str]:
    layers: list[str] = []
    outline = _read_json(root / ".webnovel" / "outline.json")
    if isinstance(outline, dict):
        overall = outline.get("overall")
        if isinstance(overall, dict) and str(overall.get("story") or "").strip():
            layers.append("overall")
        arcs = outline.get("arcs")
        if isinstance(arcs, list) and arcs:
            layers.append("arcs")
    project = _read_json(root / ".webnovel" / "project.json")
    if isinstance(project, dict):
        if project.get("character_profiles"):
            layers.append("character_profiles")
        blueprint = project.get("world_blueprint")
        if isinstance(blueprint, dict) and (
            blueprint.get("premise")
            or blueprint.get("world_rules")
            or blueprint.get("power_system")
        ):
            layers.append("world_blueprint")
    if _rolling_outline_present(root):
        layers.append("rolling_outline")
    checkpoint = _read_json(
        root / ".story-system" / "continuation-bootstrap" / "checkpoint.json"
    )
    if isinstance(checkpoint, dict):
        layers.append("bootstrap_checkpoint")
    return layers


def _missing_phases(root: Path) -> list[str]:
    """Map the readiness validator's errors to bootstrap phase ids.

    The script does not run the validator (the project on disk
    may have been modified by a previous run). Instead it asks
    the bootstrapper which phases are still pending.
    """

    checkpoint_path = root / ".story-system" / "continuation-bootstrap" / "checkpoint.json"
    payload = _read_json(checkpoint_path)
    completed: set[str] = set()
    if isinstance(payload, dict):
        for record in payload.get("phases", []) or []:
            if not isinstance(record, dict):
                continue
            status = str(record.get("status") or "")
            phase = str(record.get("id") or "")
            if status in {"completed", "adopted"}:
                completed.add(phase)
    result: list[str] = []
    for phase in BOOTSTRAP_PHASES:
        if phase not in completed:
            result.append(phase)
    return result


def _print_dry_run(root: Path) -> int:
    ok, message = _is_continuation_project(root)
    if not ok:
        print(f"rejected: {message}", file=sys.stderr)
        return 2

    current_chapter = _current_chapter(root)
    next_chapter = current_chapter + 1
    rolling_window = list(range(next_chapter, next_chapter + 5))
    present = _present_layers(root)
    missing = _missing_phases(root)
    readiness: BootstrapReadiness = validate_continuation_bootstrap(root)

    print(f"project_root: {root}")
    print(f"current_chapter: {current_chapter}")
    print(f"present_layers: {present}")
    print(f"missing_phases: {missing}")
    print(f"readiness: ready={readiness.ready} errors={readiness.errors}")
    print(f"proposed_rolling_window: {rolling_window}")
    print(
        "proposed_files:",
        ", ".join(
            str(path.relative_to(root))
            for path in (
                root / ".webnovel" / "outline.json",
                root / ".webnovel" / "project.json",
                root / ".webnovel" / "state.json",
                root
                / ".story-system"
                / "outline-generation"
                / "rolling_outline.json",
                root
                / ".story-system"
                / "continuation-bootstrap"
                / "checkpoint.json",
            )
        ),
    )
    return 0


def _backup_existing(root: Path) -> str:
    backup_root = root / ".story-system" / "backups" / "continuation-bootstrap"
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir = backup_root / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    for relative in (
        ".webnovel/outline.json",
        ".webnovel/project.json",
        ".webnovel/state.json",
        ".story-system/outline-generation/rolling_outline.json",
        ".story-system/continuation-bootstrap/checkpoint.json",
    ):
        source = root / relative
        if source.is_file():
            target = backup_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return str(backup_dir.relative_to(root))


def _run_apply(root: Path) -> int:
    ok, message = _is_continuation_project(root)
    if not ok:
        print(f"rejected: {message}", file=sys.stderr)
        return 2

    backup = _backup_existing(root)
    print(f"backup_dir: {backup}")

    from packages.story_core.outline_planning_generation import (
        LLMOutlinePlanningGenerator,
    )
    from packages.story_core.continuation_outline_bootstrap import (
        LLMRollingWindowGenerator,
    )

    planning = LLMOutlinePlanningGenerator()
    rolling = LLMRollingWindowGenerator()
    bootstrapper = ContinuationOutlineBootstrapper(
        project_root=root,
        planning_generator=planning,
        rolling_generator=rolling,
    )
    missing = _missing_phases(root)
    if not missing:
        print("result: ready (no missing phases)")
        return 0
    print(f"running_phases: {missing}")
    try:
        bootstrapper.run()
    except Exception as exc:  # noqa: BLE001
        print(f"bootstrap_failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    readiness = validate_continuation_bootstrap(root)
    print(f"readiness: ready={readiness.ready} errors={readiness.errors}")
    return 0 if readiness.ready else 4


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Backfill the continuation outline bootstrap on a legacy project.",
    )
    parser.add_argument(
        "project_root",
        type=Path,
        help="Path to the file-project root (e.g. data/exported-projects/p-...).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Print the plan without touching the project on disk (default).",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Run the bootstrap for the missing phases after a backup.",
    )
    args = parser.parse_args(argv)

    root = args.project_root.expanduser().resolve()
    if not root.is_dir():
        print(f"project_root_not_found: {root}", file=sys.stderr)
        return 2
    if args.apply:
        return _run_apply(root)
    return _print_dry_run(root)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
