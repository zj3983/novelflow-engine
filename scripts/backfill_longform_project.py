"""Safely preview, verify and apply long-form project metadata backfills."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from packages.story_core.persistence.snapshot_store import SnapshotStore
from packages.story_core.project_backfill import (
    apply_backfill_preview,
    backfill_preview_path,
    build_backfill_preview,
    protected_chapter_hashes,
    validate_backfill_preview,
    verify_backfill_hashes,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--payload", type=Path, help="Structured generated backfill JSON")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--hash-only", action="store_true")
    modes.add_argument("--check-preview", action="store_true")
    modes.add_argument("--verify-hashes", action="store_true")
    modes.add_argument("--apply", action="store_true")
    return parser


def _read_mapping(path: Path, *, error: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"{error}_not_found:{path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{error}_invalid:{path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{error}_invalid:{path}")
    return value


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                continue


def main(argv: Sequence[str] | None = None) -> int:
    _configure_console_encoding()
    args = _parser().parse_args(argv)
    root = args.project_root.resolve()
    try:
        preview_path = backfill_preview_path(root)
        if args.hash_only:
            if args.payload is not None:
                raise ValueError("payload_not_allowed_with_hash_only")
            _print(protected_chapter_hashes(root))
            return 0
        if args.payload is not None:
            if args.check_preview or args.verify_hashes or args.apply:
                raise ValueError("payload_only_supports_preview")
            payload = _read_mapping(args.payload, error="payload")
            preview = build_backfill_preview(root, payload)
            SnapshotStore().write_json_atomic(preview_path, preview)
            _print(
                {
                    "status": "preview_created",
                    "preview_path": str(preview_path),
                    "project_id": preview["project_id"],
                    "chapter_hashes": preview["chapter_hashes"],
                }
            )
            return 0
        if not (args.check_preview or args.verify_hashes or args.apply):
            raise ValueError("payload_required_or_preview_operation")
        preview = _read_mapping(preview_path, error="preview")
        if args.verify_hashes:
            _print({"status": "hashes_match", **verify_backfill_hashes(root, preview)})
        elif args.check_preview:
            checked = validate_backfill_preview(root, preview)
            _print(
                {
                    "status": "preview_valid",
                    "project_id": checked["project_id"],
                    "current_chapter": checked["patch"]["continuity"]["current_chapter"],
                }
            )
        else:
            _print(apply_backfill_preview(root, preview))
        return 0
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        print(f"backfill_error:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
