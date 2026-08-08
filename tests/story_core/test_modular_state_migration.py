"""Tests for the modular agent migration script.

Task 15 of the modular agent migration plan adds a
``scripts/migrate_modular_story_state.py`` that brings legacy
``.webnovel/`` projects up to the canonical
``.story-system/`` layout the new agents expect. The tests
pin the script's contract on five representative project
shapes:

* a long game project (the "director-context-probe" fixture
  the orchestrator was originally wired against);
* a non-game fantasy project (no game_id / no panel rules);
* a legacy project whose chapter JSON lives in ``.webnovel/``
  without a corresponding Markdown body;
* a project carrying duplicate character display names;
* a project with no generated chapters yet.

The migration must be idempotent (re-runnable without side
effects) and must back up the existing ``.story-system/``
files before writing anything new.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.migrate_modular_story_state import (
    MIGRATION_MARKER,
    MigrationReport,
    migrate_project,
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _build_game_project(root: Path) -> None:
    """Long-running game project with a real + game alias per character."""
    _write_json(
        root / ".webnovel" / "outline.json",
        {
            "schema_version": "project-outline/v1",
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "第一章",
                    "goal": "进入游戏",
                    "obstacle": "教程",
                    "action": "完成新手任务",
                },
                {
                    "chapter_number": 2,
                    "title": "第二章",
                    "goal": "进入矿区",
                    "obstacle": "守卫",
                    "action": "提交证据",
                },
            ],
            "arcs": [
                {"id": "v1", "title": "第一卷", "start_chapter": 1, "end_chapter": 50},
            ],
            "overall": {"story": "新手村冒险"},
        },
    )
    _write_json(
        root / ".webnovel" / "state.json",
        {
            "current_chapter": 2,
            "characters": [
                {
                    "name": "林昭",
                    "role": "protagonist",
                    "game_id": "大罗",
                    "lifecycle_state": "active",
                    "location": "新手村",
                },
                {
                    "name": "苏婉",
                    "role": "support",
                    "game_id": "夜烬",
                    "lifecycle_state": "active",
                    "location": "新手村",
                },
            ],
            "world_facts": ["现实世界有玩家"],
            "chapter_summaries": [
                {
                    "chapter_number": 1,
                    "title": "第一章",
                    "summary": "主角进入游戏",
                    "facts": ["主角在第一章进入游戏"],
                },
                {
                    "chapter_number": 2,
                    "title": "第二章",
                    "summary": "主角进入矿区",
                    "facts": ["主角获得许可"],
                },
            ],
            "foreshadowing": [{"text": "一场更大的风暴即将来临", "first_chapter": 1}],
        },
    )
    _write_json(
        root / ".webnovel" / "project.json",
        {
            "title": "游戏项目",
            "character_profiles": [],
            "enabled_skill_ids": [],
        },
    )


def _build_fantasy_project(root: Path) -> None:
    """Non-game fantasy project: no game_id, no panel rules."""
    _write_json(
        root / ".webnovel" / "outline.json",
        {
            "chapters": [
                {
                    "chapter_number": 1,
                    "title": "山门",
                    "goal": "踏入修真界",
                    "obstacle": "门规",
                    "action": "拜师",
                },
            ],
            "arcs": [],
        },
    )
    _write_json(
        root / ".webnovel" / "state.json",
        {
            "current_chapter": 1,
            "characters": [
                {
                    "name": "苏叶",
                    "role": "protagonist",
                    "lifecycle_state": "active",
                },
            ],
            "world_facts": ["灵气复苏"],
            "chapter_summaries": [
                {
                    "chapter_number": 1,
                    "title": "山门",
                    "summary": "苏叶踏入修真界",
                    "facts": ["苏叶获得功法"],
                },
            ],
            "foreshadowing": [],
        },
    )


def _build_legacy_json_only_project(root: Path) -> None:
    """Legacy project with chapter JSON only, no Markdown bodies."""
    _write_json(
        root / ".webnovel" / "outline.json",
        {"chapters": [{"chapter_number": 1, "title": "旧章"}]},
    )
    _write_json(
        root / ".webnovel" / "state.json",
        {
            "current_chapter": 1,
            "characters": [{"name": "旧主角", "lifecycle_state": "active"}],
            "world_facts": [],
            "chapter_summaries": [
                {"chapter_number": 1, "title": "旧章", "summary": "旧正文", "facts": []}
            ],
        },
    )
    chapters_dir = root / ".story-system" / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        chapters_dir / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "旧章",
            "body": "旧正文全文...",
            "schema_version": "story-chapter/v1",
        },
    )


def _build_duplicate_alias_project(root: Path) -> None:
    """Project with two characters that share a display name."""
    _write_json(
        root / ".webnovel" / "outline.json",
        {"chapters": [{"chapter_number": 1, "title": "第一章"}]},
    )
    _write_json(
        root / ".webnovel" / "state.json",
        {
            "current_chapter": 1,
            "characters": [
                {"name": "林昭", "role": "protagonist", "lifecycle_state": "active"},
                {"name": "林昭", "role": "shadow", "lifecycle_state": "active"},
            ],
            "world_facts": [],
            "chapter_summaries": [],
        },
    )


def _build_empty_project(root: Path) -> None:
    """Project with no generated chapters yet."""
    _write_json(
        root / ".webnovel" / "outline.json",
        {"chapters": [], "arcs": []},
    )
    _write_json(
        root / ".webnovel" / "state.json",
        {
            "current_chapter": 0,
            "characters": [],
            "world_facts": [],
            "chapter_summaries": [],
        },
    )


# --- Tests -----------------------------------------------------------------


def test_migrate_game_project_creates_canon_registry_and_snapshots(tmp_path):
    project = tmp_path
    _build_game_project(project)

    report = migrate_project(project)

    # The report carries the per-step counts the CLI prints.
    assert isinstance(report, MigrationReport)
    assert report.chapters == 2
    assert report.entities_seeded == 2
    assert report.snapshots_created == 2
    assert report.director_artifacts == 2
    assert report.warnings == []
    assert report.backup_dir is not None
    # The backup directory is timestamped and lives inside
    # the project's ``.story-system/`` so a copy of the
    # pre-migration state is always one ls away.
    assert report.backup_dir.name.startswith(".migrate-backup-")
    assert report.backup_dir.parent == project / ".story-system"

    # The canon registry carries the two characters with
    # the game_id as an alias.
    registry_path = project / ".story-system" / "canon" / "registry.json"
    assert registry_path.is_file()
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    by_id = payload["by_id"]
    assert len(by_id) == 2
    linzhao = next(
        entity for entity in by_id.values() if entity["display_name"] == "林昭"
    )
    assert linzhao["kind"] == "character"
    assert linzhao["lifecycle"] == "active"
    assert "大罗" in linzhao["aliases"]

    # Per-chapter snapshots exist for both confirmed chapters.
    snapshots_dir = project / ".story-system" / "continuity" / "snapshots"
    assert (snapshots_dir / "0001.json").is_file()
    assert (snapshots_dir / "0002.json").is_file()
    snapshot = json.loads(
        (snapshots_dir / "0001.json").read_text(encoding="utf-8")
    )
    assert snapshot["chapter_number"] == 1

    # Per-chapter director stubs exist.
    director_dir = project / ".story-system" / "director"
    assert (director_dir / "0001.json").is_file()
    director = json.loads(
        (director_dir / "0001.json").read_text(encoding="utf-8")
    )
    assert director["status"] == "outline_only"

    # The migration marker is written.
    story_state = project / ".story-system" / "state.json"
    assert story_state.is_file()
    state_payload = json.loads(story_state.read_text(encoding="utf-8"))
    assert MIGRATION_MARKER in state_payload


def test_migrate_fantasy_project_handles_no_game_alias(tmp_path):
    project = tmp_path
    _build_fantasy_project(project)

    report = migrate_project(project)

    assert report.entities_seeded == 1
    assert report.snapshots_created == 1
    assert report.director_artifacts == 1
    assert report.warnings == []

    registry_path = project / ".story-system" / "canon" / "registry.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    by_id = payload["by_id"]
    assert len(by_id) == 1
    entity = next(iter(by_id.values()))
    assert entity["display_name"] == "苏叶"
    # No game_id → no alias.
    assert entity["aliases"] == []


def test_migrate_legacy_json_only_project_preserves_existing_files(tmp_path):
    project = tmp_path
    _build_legacy_json_only_project(project)
    chapters_dir = project / ".story-system" / "chapters"
    pre_migration_chapter = (chapters_dir / "0001.json").read_text(encoding="utf-8")
    pre_migration_bytes = (chapters_dir / "0001.json").read_bytes()

    migrate_project(project)

    # The legacy chapter file is still on disk and unchanged.
    assert chapters_dir.is_dir()
    assert (chapters_dir / "0001.json").read_bytes() == pre_migration_bytes
    # Its body is still embedded (the migration does not
    # promote JSON-only chapters to Markdown; the existing
    # chapter_store migration is a separate step the workbench
    # performs on next save).
    payload = json.loads(
        (chapters_dir / "0001.json").read_text(encoding="utf-8")
    )
    assert payload.get("body") == "旧正文全文..."

    # The script also wrote a snapshot for chapter 1.
    snapshots_dir = project / ".story-system" / "continuity" / "snapshots"
    assert (snapshots_dir / "0001.json").is_file()

    # The backup captured the pre-migration state.
    backup_dirs = list(
        (project / ".story-system").glob(".migrate-backup-*")
    )
    assert len(backup_dirs) == 1
    assert (backup_dirs[0] / "chapters" / "0001.json").is_file()
    # The pre_migration_chapter string is preserved verbatim.
    assert (
        backup_dirs[0] / "chapters" / "0001.json"
    ).read_text(encoding="utf-8") == pre_migration_chapter


def test_migrate_duplicate_character_name_warns_and_keeps_first(tmp_path):
    project = tmp_path
    _build_duplicate_alias_project(project)

    report = migrate_project(project)

    # The migration logs a warning and seeds only the first
    # occurrence so the registry stays consistent.
    assert any("duplicate_character_name" in w for w in report.warnings)
    registry_path = project / ".story-system" / "canon" / "registry.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    by_id = payload["by_id"]
    assert len(by_id) == 1
    assert next(iter(by_id.values()))["display_name"] == "林昭"


def test_migrate_empty_project_creates_skeleton_without_chapter_files(tmp_path):
    project = tmp_path
    _build_empty_project(project)

    report = migrate_project(project)

    # No characters and no chapters means the canon registry
    # is created but empty, and no snapshots / director stubs
    # land on disk.
    assert report.chapters == 0
    assert report.entities_seeded == 0
    assert report.snapshots_created == 0
    assert report.director_artifacts == 0
    assert report.warnings == []
    # The canonical directories are present even when the
    # project has no content yet.
    system_root = project / ".story-system"
    assert (system_root / "director").is_dir()
    assert (system_root / "canon").is_dir()
    assert (system_root / "continuity" / "snapshots").is_dir()


def test_migrate_is_idempotent(tmp_path):
    project = tmp_path
    _build_game_project(project)

    first = migrate_project(project)
    # Snapshot the post-migration file mtimes so the second
    # run is provably a no-op for the on-disk content.
    registry_path = project / ".story-system" / "canon" / "registry.json"
    first_registry = registry_path.read_bytes()
    snapshot_path = (
        project / ".story-system" / "continuity" / "snapshots" / "0001.json"
    )
    first_snapshot = snapshot_path.read_bytes()
    director_path = project / ".story-system" / "director" / "0001.json"
    first_director = director_path.read_bytes()
    first_marker = (
        project / ".story-system" / "state.json"
    ).read_text(encoding="utf-8")

    second = migrate_project(project)

    # The second run creates nothing new.
    assert second.chapters == first.chapters
    assert second.entities_seeded == 0
    assert second.snapshots_created == 0
    assert second.director_artifacts == 0
    assert second.warnings == []
    # The on-disk files are byte-for-byte identical.
    assert registry_path.read_bytes() == first_registry
    assert snapshot_path.read_bytes() == first_snapshot
    assert director_path.read_bytes() == first_director
    # The migration marker is refreshed (the timestamp moves
    # forward) but the schema version stays put.
    second_marker = json.loads(
        (project / ".story-system" / "state.json").read_text(encoding="utf-8")
    )
    first_marker_payload = json.loads(first_marker)
    assert second_marker["modular_migration_schema"] == first_marker_payload[
        "modular_migration_schema"
    ]
    assert (
        second_marker[MIGRATION_MARKER] >= first_marker_payload[MIGRATION_MARKER]
    )

    # Two backup directories exist now (one per run); the
    # second is also a no-op write against the system root.
    backup_dirs = sorted(
        (project / ".story-system").glob(".migrate-backup-*")
    )
    assert len(backup_dirs) == 2


def test_migrate_dry_run_reports_counts_without_writing(tmp_path):
    project = tmp_path
    _build_game_project(project)

    report = migrate_project(project, dry_run=True)

    # The counts are still accurate.
    assert report.entities_seeded == 2
    assert report.snapshots_created == 2
    assert report.director_artifacts == 2
    # But nothing landed on disk.
    assert not (project / ".story-system" / "canon" / "registry.json").exists()
    assert not (project / ".story-system" / "continuity" / "snapshots" / "0001.json").exists()
    assert not (project / ".story-system" / "director" / "0001.json").exists()
    assert not (project / ".story-system" / "state.json").exists()
    # And the backup directory was not created.
    assert not any(
        (project / ".story-system").glob(".migrate-backup-*")
    )


def test_migrate_unknown_layout_warns_without_crash(tmp_path):
    """A directory with neither ``.webnovel/`` nor ``.story-system/`` is rejected."""
    project = tmp_path
    report = migrate_project(project)
    assert any("missing_legacy_layout" in w for w in report.warnings)
    assert report.entities_seeded == 0
    assert report.snapshots_created == 0
    assert report.director_artifacts == 0
