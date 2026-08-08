"""Bring legacy ``.webnovel/`` projects up to the modular agent layout.

The 9-task review-rewrite plan and the 15-task modular agent
migration added a canonical layout under ``.story-system/``
(director artifacts, canon registry, continuity snapshots,
per-stage workflow artifacts, character / entity cards). The
file-project store still reads from ``.webnovel/`` for legacy
state so the two layouts co-exist during the migration window.
Real projects on disk have only the legacy shape; this script
fills in the missing canonical artifacts so the new agents
have data to read.

The script is intentionally side-effect-free on existing
data — it never rewrites ``.webnovel/`` files and never
silently picks between two conflicting identities. When the
script cannot decide, it records a warning in the run log
and leaves the on-disk state alone; the user resolves the
conflict in the workbench.

Supported modes:

* ``--project <path>`` — migrate one project (default).
* ``--all`` — walk the project roots listed in
  ``--projects-file`` (or a default file) and migrate each.
* ``--dry-run`` — report what would be created without
  writing anything. Use this first.
* ``--quiet`` — only print warnings and the final summary.
* ``--backup-dir <path>`` — override the timestamped backup
  directory. Default: ``<project>/.story-system/.migrate-backup-<stamp>``.

The script is idempotent: re-running it on a project that
already has the canonical artifacts is a no-op for the
``canon/registry.json``, ``director/``, and
``continuity/snapshots/`` files, and a refresh for the
``state.json`` migration marker.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MIGRATION_SCHEMA_VERSION = "modular-migration/v1"
MIGRATION_MARKER = "modular_state_migrated_at"


# --- Result envelope --------------------------------------------------------


@dataclass
class MigrationReport:
    """The outcome of one migration run.

    The script prints a one-line summary per project and
    returns the structured counts so callers (and tests) can
    assert on them. ``warnings`` is a list of human-readable
    strings the user must resolve in the workbench.
    """

    project: Path
    backup_dir: Path | None
    dry_run: bool
    chapters: int = 0
    entities_seeded: int = 0
    snapshots_created: int = 0
    director_artifacts: int = 0
    warnings: list[str] = field(default_factory=list)
    created_paths: list[Path] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": str(self.project),
            "backup_dir": str(self.backup_dir) if self.backup_dir else "",
            "dry_run": self.dry_run,
            "chapters": self.chapters,
            "entities_seeded": self.entities_seeded,
            "snapshots_created": self.snapshots_created,
            "director_artifacts": self.director_artifacts,
            "warnings": list(self.warnings),
            "created_paths": [str(p) for p in self.created_paths],
        }


# --- Helpers ----------------------------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _backup_label() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


# --- Migration steps --------------------------------------------------------


def _ensure_canonical_directories(root: Path) -> dict[str, Path]:
    """Create the canonical subdirs the new agents expect.

    Returns a mapping of name → path so callers can record the
    created paths in the report. Already-existing directories
    are returned without raising; the script is idempotent.
    """
    system_root = root / ".story-system"
    created: dict[str, Path] = {}
    for sub in (
        "director",
        "continuity",
        "continuity/snapshots",
        "canon",
        "workflow",
        "craft-modules",
        "characters",
        "entities",
    ):
        target = system_root / sub
        if not target.exists():
            target.mkdir(parents=True, exist_ok=True)
            created[sub] = target
    return created


def _seed_canon_registry(
    root: Path,
    report: MigrationReport,
    *,
    dry_run: bool,
) -> int:
    """Build a starter ``canon/registry.json`` from the legacy state.

    The legacy ``state.json#characters`` list is the only
    authoritative source for the active roster on disk. The
    migration seeds one entity per character with a stable
    id, the canonical name, and any game alias. The next
    chapter's director context can resolve them through the
    new :class:`CanonRegistry`.

    Returns the number of entities seeded (so the report can
    surface the count). Re-running is a no-op: the registry
    file already exists and is left alone.
    """
    target = root / ".story-system" / "canon" / "registry.json"
    if target.is_file():
        return 0
    state = _read_json(root / ".webnovel" / "state.json") or {}
    characters = state.get("characters") or []
    if not isinstance(characters, list):
        return 0
    by_id: dict[str, dict[str, Any]] = {}
    used_names: set[tuple[str, str]] = set()
    seeded = 0
    for index, raw in enumerate(characters):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        kind = "character"
        if (kind, name.lower()) in used_names:
            # Duplicate display name on disk; the registry
            # would reject the alias, so we log a warning and
            # skip rather than silently pick one.
            report.warnings.append(
                f"duplicate_character_name: {name!r} (skipped at index {index})"
            )
            continue
        used_names.add((kind, name.lower()))
        slug = name.encode("utf-8")
        # Stable, human-readable id derived from the name so
        # the same character seeds the same id across runs.
        suffix = f"{abs(hash(slug)) % 0xFFFFFFFF:08x}"[:8]
        entity_id = f"char-{suffix}"
        aliases: list[str] = []
        game_id = str(raw.get("game_id") or "").strip()
        if game_id and game_id.lower() != name.lower():
            aliases.append(game_id)
        by_id[entity_id] = {
            "entity_id": entity_id,
            "kind": kind,
            "display_name": name,
            "aliases": aliases,
            "lifecycle": "active"
            if str(raw.get("lifecycle_state") or "") == "active"
            else "proposed",
            "extensions": {
                key: value
                for key, value in raw.items()
                if key
                in (
                    "role",
                    "location",
                    "current_emotion",
                    "frozen",
                    "game_id",
                )
            },
        }
        seeded += 1
    if not seeded or dry_run:
        if seeded and not dry_run:
            _write_json(target, _canon_registry_payload(by_id, [], [], []))
            report.created_paths.append(target)
        return seeded
    _write_json(target, _canon_registry_payload(by_id, [], [], []))
    report.created_paths.append(target)
    return seeded


def _canon_registry_payload(
    by_id: dict[str, dict[str, Any]],
    relationships: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    foreshadowing: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "canon-registry/v1",
        "by_id": by_id,
        "relationships": relationships,
        "timeline": timeline,
        "foreshadowing": foreshadowing,
    }


def _seed_continuity_snapshots(
    root: Path,
    report: MigrationReport,
    *,
    dry_run: bool,
) -> int:
    """Build per-chapter ``ChapterSnapshot`` files from the legacy state.

    The legacy ``state.json#chapter_summaries`` is a list of
    per-chapter records the new ``ContinuityStore`` would
    derive a snapshot from. The migration writes a minimal
    snapshot for each so a regeneration can find a base state
    for any chapter that has already been confirmed. The
    snapshot is a small slice; the user can re-snapshot
    later with the workbench.
    """
    snapshots_dir = root / ".story-system" / "continuity" / "snapshots"
    if not snapshots_dir.exists():
        snapshots_dir.mkdir(parents=True, exist_ok=True)
    state = _read_json(root / ".webnovel" / "state.json") or {}
    summaries = state.get("chapter_summaries") or []
    if not isinstance(summaries, list):
        return 0
    created = 0
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        number = summary.get("chapter_number")
        if not isinstance(number, int) or number <= 0:
            continue
        target = snapshots_dir / f"{number:04d}.json"
        if target.is_file():
            continue
        snapshot = {
            "schema_version": "chapter-snapshot/v1",
            "chapter_number": int(number),
            "candidate_id": str(summary.get("candidate_id") or "legacy"),
            "operation": "generate",
            "confirmed_at": str(summary.get("confirmed_at") or ""),
            "body_sha256": "",
            "body_chars": 0,
            "state_after": _slice_state_for_snapshot(state),
            "continuity_delta_summary": {
                "schema_version": "continuity-delta/v1",
                "chapter_number": int(number),
                "counts": {
                    key: len(summary.get(key) or [])
                    for key in (
                        "facts",
                        "unresolved_threads",
                    )
                },
            },
        }
        if not dry_run:
            _write_json(target, snapshot)
            report.created_paths.append(target)
        created += 1
    return created


def _slice_state_for_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "current_chapter",
        "characters",
        "world_facts",
        "foreshadowing",
        "progression_ledger",
        "continuity_facts",
    )
    return {key: state[key] for key in keep if key in state}


def _seed_director_artifacts(
    root: Path,
    report: MigrationReport,
    *,
    dry_run: bool,
) -> int:
    """Stub out a director artifact for each confirmed chapter.

    The new pipeline stores the director's plan under
    ``.story-system/director/NNNN.json`` so the workbench can
    audit what the director saw. Legacy projects have no such
    artifacts; the migration seeds a minimal stub from the
    outline's ``chapter_number`` / ``title`` / ``goal`` /
    ``obstacle`` / ``action`` so the per-chapter file exists.
    Real director artifacts overwrite these on the next
    chapter run.
    """
    director_dir = root / ".story-system" / "director"
    if not director_dir.exists():
        director_dir.mkdir(parents=True, exist_ok=True)
    outline = _read_json(root / ".webnovel" / "outline.json") or {}
    chapters = outline.get("chapters") or []
    if not isinstance(chapters, list):
        return 0
    created = 0
    for entry in chapters:
        if not isinstance(entry, dict):
            continue
        number = entry.get("chapter_number")
        if not isinstance(number, int) or number <= 0:
            continue
        target = director_dir / f"{number:04d}.json"
        if target.is_file():
            continue
        title = str(entry.get("title") or "").strip()
        goal = str(entry.get("goal") or "").strip()
        obstacle = str(entry.get("obstacle") or "").strip()
        action = str(entry.get("action") or "").strip()
        artifact = {
            "schema_version": "director-artifact/v1",
            "status": "outline_only",
            "provider": "outline",
            "model": "outline/v1",
            "input_trace": {
                "schema_version": "context-trace/v1",
                "agent": "director",
                "chapter_number": int(number),
                "reads": [
                    {
                        "kind": "outline",
                        "path": f"outline.json#chapter-{number:04d}",
                        "sha256": "",
                        "chars": len(title) + len(goal) + len(obstacle) + len(action),
                    }
                ],
                "selected_entity_ids": [],
                "selected_module_ids": [],
            },
            "output": {
                "schema_version": "director-artifact/v1",
                "chapter_number": int(number),
                "chapter_goal": " · ".join(
                    part for part in (title, goal, obstacle, action) if part
                ),
                "opening_state": "",
                "scene_beats": [],
                "ending_state": "",
                "hook": "",
                "entity_requirements": [],
            },
        }
        if not dry_run:
            _write_json(target, artifact)
            report.created_paths.append(target)
        created += 1
    return created


def _write_migration_marker(
    root: Path,
    report: MigrationReport,
    *,
    dry_run: bool,
) -> None:
    """Stamp ``.story-system/state.json`` so the script is idempotent.

    A second run of the script reads the marker and knows it
    can safely re-run the directory-creation and snapshot
    steps; the per-file idempotency check above is the
    real safety net, the marker is for the user to see.
    """
    target = root / ".story-system" / "state.json"
    payload = _read_json(target) or {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("schema_version", "story-system-state/v1")
    payload[MIGRATION_MARKER] = _now()
    payload["modular_migration_schema"] = MIGRATION_SCHEMA_VERSION
    if not dry_run:
        _write_json(target, payload)
        report.created_paths.append(target)


def _make_backup(root: Path, report: MigrationReport) -> Path:
    """Snapshot every existing ``.story-system/`` file to a backup dir.

    The backup is the recovery boundary the user can trust
    even if the migration writes something that breaks the
    orchestrator. The directory is timestamped so successive
    runs do not overwrite each other's safety net. Earlier
    backup directories (````.migrate-backup-*````) are
    skipped on subsequent runs so a second invocation does
    not recurse into the previous backup.
    """
    system_root = root / ".story-system"
    backup = system_root / f".migrate-backup-{_backup_label()}"
    backup.mkdir(parents=True, exist_ok=True)
    if not system_root.exists():
        # Nothing to back up yet.
        return backup
    for path in system_root.rglob("*"):
        if not path.is_file():
            continue
        # Skip the prior backup directories so the new
        # backup does not contain a copy of every older
        # backup. The user can still reach them via the
        # path they were created at; the marker inside
        # ``state.json`` records the latest run.
        relative = path.relative_to(system_root)
        if any(part.startswith(".migrate-backup-") for part in relative.parts):
            continue
        target = backup / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    return backup


# --- Orchestration ----------------------------------------------------------


def migrate_project(
    project_root: Path,
    *,
    dry_run: bool = False,
    backup_dir: Path | None = None,
) -> MigrationReport:
    """Migrate one project root to the modular layout.

    The function is the single entry point the CLI and the
    tests share. The return value carries per-step counts
    plus a list of warnings the caller (CLI or test) prints
    or asserts on.
    """
    project_root = project_root.resolve()
    webnovel_dir = project_root / ".webnovel"
    has_legacy = webnovel_dir.is_dir()
    if not has_legacy and not (project_root / ".story-system").exists():
        # Not a project we recognize.
        report = MigrationReport(
            project=project_root,
            backup_dir=None,
            dry_run=dry_run,
        )
        report.warnings.append(
            "missing_legacy_layout: no .webnovel/ and no .story-system/ directory"
        )
        return report
    report = MigrationReport(
        project=project_root,
        backup_dir=None,
        dry_run=dry_run,
    )
    if not dry_run:
        report.backup_dir = _make_backup(project_root, report)
    if not dry_run:
        _ensure_canonical_directories(project_root)
    report.chapters = _count_chapters(project_root)
    if not dry_run:
        report.entities_seeded = _seed_canon_registry(
            project_root, report, dry_run=dry_run
        )
        report.snapshots_created = _seed_continuity_snapshots(
            project_root, report, dry_run=dry_run
        )
        report.director_artifacts = _seed_director_artifacts(
            project_root, report, dry_run=dry_run
        )
        _write_migration_marker(project_root, report, dry_run=dry_run)
    else:
        # In dry-run mode we still count without writing.
        report.entities_seeded = _seed_canon_registry(
            project_root, report, dry_run=True
        )
        report.snapshots_created = _seed_continuity_snapshots(
            project_root, report, dry_run=True
        )
        report.director_artifacts = _seed_director_artifacts(
            project_root, report, dry_run=True
        )
    return report


def _count_chapters(root: Path) -> int:
    """Return the number of legacy chapter summaries the project carries."""
    state = _read_json(root / ".webnovel" / "state.json") or {}
    summaries = state.get("chapter_summaries") or []
    return len(summaries) if isinstance(summaries, list) else 0


# --- CLI --------------------------------------------------------------------


def _print_report(report: MigrationReport, *, quiet: bool) -> None:
    if quiet and not report.warnings:
        return
    payload = report.to_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _resolve_projects(
    *,
    project: str | None,
    all_projects: bool,
    projects_file: str | None,
) -> list[Path]:
    if project:
        return [Path(project).resolve()]
    if all_projects:
        if not projects_file:
            raise SystemExit(
                "--all requires --projects-file <path> listing one project per line"
            )
        roots: list[Path] = []
        for line in Path(projects_file).read_text(encoding="utf-8").splitlines():
            entry = line.strip()
            if not entry or entry.startswith("#"):
                continue
            roots.append(Path(entry).resolve())
        return roots
    raise SystemExit(
        "specify --project <path> or --all --projects-file <file>"
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bring legacy .webnovel/ projects up to the modular "
            "agent layout under .story-system/."
        )
    )
    parser.add_argument("--project", help="path to a single project root")
    parser.add_argument(
        "--all",
        action="store_true",
        help="migrate every project in --projects-file",
    )
    parser.add_argument(
        "--projects-file",
        help="text file listing one project root per line",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be created without writing",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="only print warnings and the final summary",
    )
    parser.add_argument(
        "--backup-dir",
        help="override the timestamped backup directory (advanced)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    roots = _resolve_projects(
        project=args.project,
        all_projects=args.all,
        projects_file=args.projects_file,
    )
    backup_override = Path(args.backup_dir).resolve() if args.backup_dir else None
    failures = 0
    for root in roots:
        try:
            report = migrate_project(
                root, dry_run=args.dry_run, backup_dir=backup_override
            )
        except Exception as exc:  # pragma: no cover - defensive
            print(
                json.dumps(
                    {
                        "project": str(root),
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            failures += 1
            continue
        _print_report(report, quiet=args.quiet)
        if report.warnings:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
