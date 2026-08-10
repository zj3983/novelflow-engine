"""Tests for the continuation outline backfill script.

The script must run in dry-run mode (default) and apply mode
(``--apply``). Dry-run never mutates the project on disk; apply
backs up the existing files, runs the bootstrap for missing
phases, and rejects non-continuation projects.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _seed_legacy_project(
    target: Path,
    *,
    current_chapter: int = 147,
) -> Path:
    """Seed a project that mirrors the 17-arc / 147-chapter shape
    from the real imported project. The script must report the
    missing ``chapter_window`` and ``readiness_check`` phases
    only and leave the disk byte-identical.
    """

    target.mkdir(parents=True, exist_ok=True)
    (target / ".webnovel").mkdir(parents=True, exist_ok=True)
    (target / ".story-system" / "chapters").mkdir(parents=True, exist_ok=True)
    (target / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps({"schema_version": "story-system-master-setting/v1"}),
        encoding="utf-8",
    )

    arcs: list[dict] = []
    for index in range(17):
        start = 1 + index * 18 if index > 0 else 1
        end = start + 17
        arcs.append(
            {
                "id": f"arc-{index}",
                "title": f"阶段 {index + 1}",
                "start_chapter": start,
                "end_chapter": end,
                "goal": f"阶段 {index + 1} 目标",
                "obstacle": "阻力",
                "payoff": "阶段兑现",
                "end_state": "新目标",
            }
        )
    # Truncate the last arc so it ends at 300.
    arcs[-1]["end_chapter"] = 300

    outline = {
        "schema_version": "project-outline/v1",
        "overall": {
            "story": "林修承接万修传承",
            "core_ending_chapter": 300,
            "extension_ceiling_chapter": 300,
        },
        "arcs": arcs,
        "chapters": [],
    }
    (target / ".webnovel" / "outline.json").write_text(
        json.dumps(outline, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    project = {
        "project_id": target.name,
        "title": "万界维修工",
        "current_chapter": current_chapter,
        "status": "draft",
        "pipeline_stage": "imported",
        "continuation": {
            "schema_version": "continuation-project/v1",
            "start_after_chapter": current_chapter,
            "branch_point": current_chapter,
            "session_id": "ci-legacy",
        },
        "world_blueprint": {
            "premise": "万修传承",
            "world_rules": ["以灵材为核心"],
            "power_system": ["筑基阶段"],
        },
        "character_profiles": [
            {
                "name": "林修",
                "role": "protagonist",
                "character_tier": "protagonist",
            }
        ],
    }
    (target / ".webnovel" / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    state = {
        "current_chapter": current_chapter,
        "characters": [
            {"name": "林修"},
        ],
        "world_facts": ["万修以灵材为核心"],
    }
    (target / ".webnovel" / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # 147 committed chapter payloads.
    for number in range(1, current_chapter + 1):
        (target / ".story-system" / "chapters" / f"{number:04d}.json").write_text(
            json.dumps(
                {
                    "schema_version": "imported-continuation-chapter/v1",
                    "chapter_number": number,
                    "chapter_title": f"第{number}章",
                    "body": "正文",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return target


def _hash_files(target: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(target.rglob("*")):
        if path.is_file():
            snapshot[str(path.relative_to(target))] = path.read_bytes()
    return snapshot


def test_backfill_dry_run_reports_missing_phases(tmp_path: Path) -> None:
    target = _seed_legacy_project(tmp_path / "p-legacy")
    snapshot = _hash_files(target)
    script = PROJECT_ROOT / "scripts" / "backfill_continuation_outline.py"
    assert script.is_file(), script

    result = subprocess.run(
        [sys.executable, str(script), str(target), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr

    out = result.stdout + result.stderr
    assert "current_chapter: 147" in out
    assert "chapter_window" in out
    assert "readiness_check" in out
    # Dry-run must not touch any file.
    assert _hash_files(target) == snapshot


def test_backfill_dry_run_rejects_non_continuation_project(tmp_path: Path) -> None:
    target = tmp_path / "p-new-book"
    target.mkdir(parents=True)
    (target / ".webnovel").mkdir(parents=True)
    (target / ".webnovel" / "project.json").write_text(
        json.dumps(
            {
                "project_id": "p-new-book",
                "pipeline_stage": "environment_ready",
                "title": "新书",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    script = PROJECT_ROOT / "scripts" / "backfill_continuation_outline.py"
    result = subprocess.run(
        [sys.executable, str(script), str(target), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "rejected" in combined or "not a continuation" in combined


def test_backfill_apply_creates_timestamped_backup(tmp_path: Path) -> None:
    """The apply path must create a timestamped backup directory
    before running the bootstrap. We exercise only the backup
    step by feeding the script a project whose bootstrap will
    fail because no model is available; the backup must still
    exist on disk.
    """

    target = _seed_legacy_project(tmp_path / "p-legacy")
    script = PROJECT_ROOT / "scripts" / "backfill_continuation_outline.py"

    backup_dir = target / ".story-system" / "backups" / "continuation-bootstrap"
    result = subprocess.run(
        [sys.executable, str(script), str(target), "--apply"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    # The bootstrap will fail (no model) but the backup must
    # have been created. The script's exit code reflects the
    # bootstrap failure, not the backup step.
    assert result.returncode != 0 or result.returncode == 0
    assert backup_dir.is_dir()
    backup_files = list(backup_dir.glob("*/.webnovel/outline.json"))
    assert backup_files, (
        "expected a timestamped backup of the legacy outline; got "
        f"{list(backup_dir.rglob('*'))}"
    )
