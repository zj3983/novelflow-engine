from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.story_core.volume_outline_migration import (  # noqa: E402
    DEFAULT_BACKUP_ROOT,
    migrate_project_volume_outline,
)
from packages.story_core.persistence.snapshot_store import SnapshotStore  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate legacy outlines to complete, non-overlapping volumes.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("data/exported-projects"),
        help="Directory containing file projects.",
    )
    parser.add_argument(
        "--project",
        help="Migrate one project ID or project directory.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser


def _project_roots(root: Path, project: str | None) -> list[Path]:
    resolved_root = root.resolve()
    if project:
        candidate = Path(project)
        if not candidate.is_absolute():
            candidate = resolved_root / candidate
        return [candidate.resolve()]
    if not resolved_root.exists():
        return []
    return sorted(
        (
            path
            for path in resolved_root.iterdir()
            if path.is_dir()
            and not path.name.startswith(".")
            and (path / ".webnovel" / "outline.json").is_file()
        ),
        key=lambda path: path.name,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    roots = _project_roots(args.root, args.project)
    if not roots:
        print("No file projects found.", file=sys.stderr)
        return 2
    reports: list[dict[str, object]] = []
    for root in roots:
        try:
            report = migrate_project_volume_outline(
                root,
                apply=False,
                backup_root=DEFAULT_BACKUP_ROOT,
            )
        except Exception as exc:
            report = {
                "project_id": root.name,
                "project_root": str(root),
                "status": "blocked",
                "blockers": [f"migration_exception:{type(exc).__name__}:{exc}"],
                "changed_files": [],
                "backup_path": None,
            }
        reports.append(report)

    blocked = any(report.get("status") == "blocked" for report in reports)
    if not args.apply or blocked:
        for report in reports:
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1 if args.apply and blocked else 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    # Freeze every source version before the first write. A mismatch blocks
    # the complete batch, so --apply never starts from mixed preflight data.
    refreshed: list[dict[str, object]] = []
    for root, preflight in zip(roots, reports):
        try:
            report = migrate_project_volume_outline(
                root,
                apply=False,
                backup_root=DEFAULT_BACKUP_ROOT,
                expected_outline_hash=str(preflight.get("outline_hash") or ""),
            )
        except Exception as exc:
            report = {
                "project_id": root.name,
                "project_root": str(root),
                "status": "blocked",
                "blockers": [f"migration_exception:{type(exc).__name__}:{exc}"],
                "changed_files": [],
                "backup_path": None,
            }
        refreshed.append(report)
    if any(report.get("status") == "blocked" for report in refreshed):
        for report in refreshed:
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1

    snapshots = {
        root / ".webnovel" / "outline.json":
        (root / ".webnovel" / "outline.json").read_bytes()
        for root in roots
    }
    applied_reports: list[dict[str, object]] = []
    for root, preflight in zip(roots, refreshed):
        try:
            report = migrate_project_volume_outline(
                root,
                apply=True,
                timestamp=stamp,
                backup_root=DEFAULT_BACKUP_ROOT,
                expected_outline_hash=str(preflight.get("outline_hash") or ""),
            )
        except Exception as exc:
            report = {
                "project_id": root.name,
                "project_root": str(root),
                "status": "blocked",
                "blockers": [f"migration_exception:{type(exc).__name__}:{exc}"],
                "changed_files": [],
                "backup_path": None,
            }
        applied_reports.append(report)

    if any(report.get("status") == "blocked" for report in applied_reports):
        SnapshotStore().restore_bytes_atomic(snapshots)
        for report in applied_reports:
            if report.get("status") == "applied":
                report["status"] = "rolled_back"
                report["blockers"] = ["batch_apply_rolled_back"]

    for report in applied_reports:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 1 if any(report.get("status") == "blocked" for report in applied_reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
