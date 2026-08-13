from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import packages.story_core.volume_outline_migration as migration_module
from packages.story_core.volume_outline_migration import (
    migrate_project_volume_outline,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _migrate(project: Path, **kwargs: object) -> dict[str, object]:
    kwargs.setdefault(
        "backup_root",
        project.parent / "test-migration-backups" / "volume-outline",
    )
    return migrate_project_volume_outline(project, **kwargs)


def _protected_hashes(root: Path) -> dict[str, str]:
    protected = [
        root / ".webnovel" / "state.json",
        root / ".story-system" / "characters.json",
        root / ".story-system" / "facts.json",
        root / ".story-system" / "foreshadowing.json",
        *sorted((root / "chapters").glob("*.md")),
    ]
    return {
        str(path.relative_to(root)): _hash(path)
        for path in protected
        if path.exists()
    }


def _arc(
    arc_id: str,
    start: int,
    end: int,
    *,
    goal: str,
    payoff: str,
    key_results: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": arc_id,
        "title": arc_id,
        "start_chapter": start,
        "end_chapter": end,
        "goal": goal,
        "obstacle": f"{arc_id} pressure",
        "payoff": payoff,
        "end_state": f"{arc_id} end",
        "next_arc_entry": f"{arc_id} next",
        "key_results": list(key_results or []),
    }


def _legacy_project(root: Path, *, project_id: str = "p-legacy") -> Path:
    project = root / project_id
    outline = {
        "schema_version": "project-outline/v1",
        "overall": {
            "story": "Legacy story",
            "core_ending_chapter": 130,
            "extension_ceiling_chapter": 180,
            "planned_arc_count": 6,
            "planned_length": 130,
        },
        "arcs": [
            _arc("arc-1", 1, 20, goal="Find the fault", payoff="First proof", key_results=["A"]),
            _arc("arc-2", 18, 40, goal="Find the fault", payoff="Second proof", key_results=["A", "B"]),
            _arc("arc-3", 41, 60, goal="Reach the hearing", payoff="Public hearing", key_results=["C"]),
            _arc("arc-4", 61, 85, goal="Trace the order", payoff="Hidden order", key_results=["D"]),
            _arc("arc-5", 80, 115, goal="Trace the order", payoff="Name the buyer", key_results=["D", "E"]),
            _arc("arc-6", 116, 130, goal="Close the case", payoff="Final choice", key_results=["F"]),
        ],
        "chapters": [
            {
                "chapter_number": number,
                "title": f"Chapter {number}",
                "payoff": f"Detail payoff {number}",
                "ending_hook": f"Hook {number}",
            }
            for number in range(1, 131)
        ],
    }
    summaries = [
        {
            "chapter_number": number,
            "chapter_title": f"Chapter {number}",
            "summary": f"Summary {number}",
        }
        for number in range(1, 131)
    ]
    _write_json(project / ".webnovel" / "outline.json", outline)
    _write_json(
        project / ".webnovel" / "state.json",
        {
            "current_chapter": 3,
            "chapter_summaries": summaries,
            "world_facts": ["Fact remains unchanged"],
            "foreshadowing": [{"text": "Thread remains unchanged"}],
        },
    )
    _write_json(project / ".story-system" / "characters.json", [{"name": "Lin"}])
    _write_json(project / ".story-system" / "facts.json", ["Fact remains unchanged"])
    _write_json(
        project / ".story-system" / "foreshadowing.json",
        [{"text": "Thread remains unchanged"}],
    )
    chapters = project / "chapters"
    chapters.mkdir(parents=True, exist_ok=True)
    for number in range(1, 4):
        (chapters / f"{number:04d}-chapter.md").write_text(
            f"# Chapter {number}\n\nBody {number}\n",
            encoding="utf-8",
        )
    return project


def test_migration_consolidates_overlaps_and_preserves_prose_and_continuity(
    tmp_path: Path,
) -> None:
    project = _legacy_project(tmp_path / "data" / "exported-projects")
    before = _protected_hashes(project)

    report = _migrate(project, apply=True)

    outline = _read_json(project / ".webnovel" / "outline.json")
    assert isinstance(outline, dict)
    arcs = outline["arcs"]
    assert [(arc["start_chapter"], arc["end_chapter"]) for arc in arcs] == [
        (1, 60),
        (61, 115),
        (116, 130),
    ]
    assert all(
        arc["end_chapter"] - arc["start_chapter"] + 1 >= 50
        or arc["is_final_arc"]
        for arc in arcs
    )
    assert [arc["is_final_arc"] for arc in arcs] == [False, False, True]
    assert report["overlap_count_before"] == 2
    assert report["overlap_count_after"] == 0
    assert report["changed_files"] == [".webnovel/outline.json"]
    assert _protected_hashes(project) == before


def test_migration_builds_complete_fifteen_chapter_nodes_from_summaries(
    tmp_path: Path,
) -> None:
    project = _legacy_project(tmp_path / "data" / "exported-projects")

    _migrate(project, apply=True)

    outline = _read_json(project / ".webnovel" / "outline.json")
    first = outline["arcs"][0]
    assert [
        (node["start_chapter"], node["end_chapter"])
        for node in first["story_nodes"]
    ] == [(1, 15), (16, 30), (31, 45), (46, 60)]
    assert all(
        node["end_chapter"] - node["start_chapter"] + 1 <= 15
        for arc in outline["arcs"]
        for node in arc["story_nodes"]
    )
    assert "Summary 1" in first["story_nodes"][0]["objective"]
    assert "Summary 15" in first["story_nodes"][0]["payoff"]
    assert "Summary 16" in first["story_nodes"][0]["next_effect"]


def test_migration_merges_text_and_list_fields_with_ordered_deduplication(
    tmp_path: Path,
) -> None:
    project = _legacy_project(tmp_path / "data" / "exported-projects")

    _migrate(project, apply=True)

    outline = _read_json(project / ".webnovel" / "outline.json")
    first = outline["arcs"][0]
    assert first["goal"] == "Find the fault；Reach the hearing"
    assert first["key_results"] == ["A", "B", "C"]


def test_dry_run_reports_changes_without_writing_or_backing_up(tmp_path: Path) -> None:
    project = _legacy_project(tmp_path / "data" / "exported-projects")
    outline_path = project / ".webnovel" / "outline.json"
    before = _hash(outline_path)

    report = _migrate(project, apply=False)

    assert report["status"] == "pending"
    assert report["old_volume_ranges"] == [[1, 20], [18, 40], [41, 60], [61, 85], [80, 115], [116, 130]]
    assert report["new_volume_ranges"] == [[1, 60], [61, 115], [116, 130]]
    assert report["backup_path"] is None
    assert _hash(outline_path) == before
    assert not (tmp_path / "data" / "migration-backups").exists()


def test_apply_creates_timestamped_outline_backup(tmp_path: Path) -> None:
    project = _legacy_project(tmp_path / "data" / "exported-projects")
    outline_path = project / ".webnovel" / "outline.json"
    original = outline_path.read_bytes()
    backup_root = tmp_path / "data" / "migration-backups" / "volume-outline"

    report = migrate_project_volume_outline(
        project,
        apply=True,
        timestamp="20260813T120000000000Z",
        backup_root=backup_root,
    )

    backup = Path(report["backup_path"])
    assert backup == (
        backup_root
        / "20260813T120000000000Z"
        / "p-legacy"
        / ".webnovel"
        / "outline.json"
    )
    assert backup.read_bytes() == original


def test_migration_is_idempotent(tmp_path: Path) -> None:
    project = _legacy_project(tmp_path / "data" / "exported-projects")
    _migrate(project, apply=True, timestamp="first")
    outline_path = project / ".webnovel" / "outline.json"
    first = _hash(outline_path)

    report = _migrate(project, apply=True, timestamp="second")

    assert _hash(outline_path) == first
    assert report["status"] == "unchanged"
    assert report["changed_files"] == []
    assert report["backup_path"] is None


def test_gap_is_reported_as_blocker_and_apply_refuses_to_write(tmp_path: Path) -> None:
    project = _legacy_project(tmp_path / "data" / "exported-projects")
    outline_path = project / ".webnovel" / "outline.json"
    outline = _read_json(outline_path)
    outline["arcs"][2]["start_chapter"] = 45
    _write_json(outline_path, outline)
    before = _hash(outline_path)

    report = _migrate(project, apply=True)

    assert report["status"] == "blocked"
    assert report["blockers"] == ["volume_gap:41:44"]
    assert _hash(outline_path) == before


def test_migration_does_not_split_an_overlap_cluster_at_fifty_chapters(
    tmp_path: Path,
) -> None:
    project = _legacy_project(tmp_path / "data" / "exported-projects")
    outline_path = project / ".webnovel" / "outline.json"
    outline = _read_json(outline_path)
    outline["arcs"] = [
        _arc("arc-1", 1, 50, goal="First", payoff="First payoff"),
        _arc("arc-2", 45, 70, goal="Bridge", payoff="Bridge payoff"),
        _arc("arc-3", 71, 120, goal="Second", payoff="Second payoff"),
        _arc("arc-4", 121, 130, goal="Ending", payoff="Ending payoff"),
    ]
    _write_json(outline_path, outline)

    report = _migrate(project, apply=False)

    assert report["new_volume_ranges"] == [[1, 70], [71, 120], [121, 130]]


def test_migration_blocks_when_overall_ending_has_no_legacy_arc(
    tmp_path: Path,
) -> None:
    project = _legacy_project(tmp_path / "data" / "exported-projects")
    outline_path = project / ".webnovel" / "outline.json"
    outline = _read_json(outline_path)
    outline["overall"]["core_ending_chapter"] = 150
    _write_json(outline_path, outline)

    report = _migrate(project, apply=False)

    assert report["status"] == "blocked"
    assert report["blockers"] == ["core_ending_mismatch:150:130"]


def test_migration_blocks_when_overall_ending_is_before_legacy_arc_end(
    tmp_path: Path,
) -> None:
    project = _legacy_project(tmp_path / "data" / "exported-projects")
    outline_path = project / ".webnovel" / "outline.json"
    outline = _read_json(outline_path)
    outline["overall"]["core_ending_chapter"] = 120
    _write_json(outline_path, outline)

    report = _migrate(project, apply=False)

    assert report["status"] == "blocked"
    assert report["blockers"] == ["core_ending_mismatch:120:130"]


def test_migration_blocks_non_mapping_arc_instead_of_dropping_it(
    tmp_path: Path,
) -> None:
    project = _legacy_project(tmp_path / "data" / "exported-projects")
    outline_path = project / ".webnovel" / "outline.json"
    outline = _read_json(outline_path)
    outline["arcs"].insert(2, "broken arc")
    _write_json(outline_path, outline)

    report = _migrate(project, apply=True)

    assert report["status"] == "blocked"
    assert report["blockers"] == ["invalid_volume_entry:2"]
    assert _read_json(outline_path)["arcs"][2] == "broken arc"


def test_apply_rechecks_outline_hash_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _legacy_project(tmp_path / "data" / "exported-projects")
    outline_path = project / ".webnovel" / "outline.json"
    original_migrator = migration_module._migrated_outline

    def mutate_after_read(outline: object, state: object):
        result = original_migrator(outline, state)
        changed = _read_json(outline_path)
        changed["overall"]["story"] = "Changed concurrently"
        _write_json(outline_path, changed)
        return result

    monkeypatch.setattr(migration_module, "_migrated_outline", mutate_after_read)

    report = _migrate(project, apply=True)

    assert report["status"] == "blocked"
    assert report["blockers"] == ["concurrent_outline_change"]
    assert _read_json(outline_path)["overall"]["story"] == "Changed concurrently"
    assert report["backup_path"] is None


def test_external_project_uses_explicit_workspace_backup_root(tmp_path: Path) -> None:
    project = _legacy_project(tmp_path / "external" / "projects")
    backup_root = tmp_path / "workspace" / "data" / "migration-backups" / "volume-outline"

    report = migrate_project_volume_outline(
        project,
        apply=True,
        timestamp="fixed",
        backup_root=backup_root,
    )

    assert Path(report["backup_path"]) == (
        backup_root / "fixed" / "p-legacy" / ".webnovel" / "outline.json"
    )


def test_report_declares_boundaries_come_only_from_legacy_arc_ends(
    tmp_path: Path,
) -> None:
    project = _legacy_project(tmp_path / "data" / "exported-projects")

    report = _migrate(project, apply=False)

    assert report["boundary_policy"] == "legacy_arc_ends_only"
    assert report["summary_policy"] == "story_nodes_only"
    old_ends = {end for _, end in report["old_volume_ranges"]}
    assert all(end in old_ends for _, end in report["new_volume_ranges"])


@pytest.mark.parametrize("mode", ["--dry-run", "--apply"])
def test_cli_supports_root_mode(tmp_path: Path, mode: str) -> None:
    projects_root = tmp_path / "data" / "exported-projects"
    project = _legacy_project(projects_root)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/migrate_volume_outlines.py",
            "--root",
            str(projects_root),
            mode,
        ],
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    assert "p-legacy" in result.stdout
    if mode == "--dry-run":
        assert _read_json(project / ".webnovel" / "outline.json")["arcs"][0]["end_chapter"] == 20
    else:
        assert _read_json(project / ".webnovel" / "outline.json")["arcs"][0]["end_chapter"] == 60
        report = json.loads(result.stdout.strip())
        shutil.rmtree(Path(report["backup_path"]).parents[2])


def test_cli_supports_single_project_id(tmp_path: Path) -> None:
    projects_root = tmp_path / "data" / "exported-projects"
    _legacy_project(projects_root, project_id="p-one")
    _legacy_project(projects_root, project_id="p-two")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/migrate_volume_outlines.py",
            "--root",
            str(projects_root),
            "--project",
            "p-one",
            "--dry-run",
        ],
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    assert "p-one" in result.stdout
    assert "p-two" not in result.stdout


def test_cli_dry_run_reports_empty_project_as_skipped(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "data" / "exported-projects"
    project = projects_root / "p-empty"
    _write_json(
        project / ".webnovel" / "outline.json",
        {"schema_version": "project-outline/v1", "overall": {}, "arcs": [], "chapters": []},
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/migrate_volume_outlines.py",
            "--root",
            str(projects_root),
            "--dry-run",
        ],
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0
    assert '"status": "skipped"' in result.stdout
    assert "volume_missing" in result.stdout


def test_cli_apply_skips_empty_project_without_blocking_valid_migration(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "data" / "exported-projects"
    valid = _legacy_project(projects_root, project_id="p-valid")
    empty = projects_root / "p-empty"
    _write_json(
        empty / ".webnovel" / "outline.json",
        {"schema_version": "project-outline/v1", "overall": {}, "arcs": [], "chapters": []},
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/migrate_volume_outlines.py",
            "--root",
            str(projects_root),
            "--apply",
        ],
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    assert '"project_id": "p-empty"' in result.stdout
    assert '"status": "skipped"' in result.stdout
    assert _read_json(valid / ".webnovel" / "outline.json")["arcs"][0]["story_nodes"]


def test_cli_apply_preflights_all_projects_before_writing(tmp_path: Path) -> None:
    projects_root = tmp_path / "external" / "projects"
    valid = _legacy_project(projects_root, project_id="p-valid")
    blocked = _legacy_project(projects_root, project_id="p-blocked")
    blocked_outline = _read_json(blocked / ".webnovel" / "outline.json")
    blocked_outline["arcs"].insert(1, None)
    _write_json(blocked / ".webnovel" / "outline.json", blocked_outline)
    valid_before = _hash(valid / ".webnovel" / "outline.json")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/migrate_volume_outlines.py",
            "--root",
            str(projects_root),
            "--apply",
        ],
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 1
    assert _hash(valid / ".webnovel" / "outline.json") == valid_before
    assert "invalid_volume_entry:1" in result.stdout


def test_cli_single_project_invalid_json_becomes_report(tmp_path: Path) -> None:
    projects_root = tmp_path / "external" / "projects"
    project = projects_root / "p-invalid"
    outline_path = project / ".webnovel" / "outline.json"
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    outline_path.write_text("{broken", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/migrate_volume_outlines.py",
            "--root",
            str(projects_root),
            "--project",
            "p-invalid",
            "--apply",
        ],
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 1
    report = json.loads(result.stdout.strip())
    assert report["project_id"] == "p-invalid"
    assert report["status"] == "blocked"
    assert report["blockers"][0].startswith("migration_exception:JSONDecodeError")


def test_cli_apply_exception_in_later_project_writes_nothing(tmp_path: Path) -> None:
    projects_root = tmp_path / "external" / "projects"
    valid = _legacy_project(projects_root, project_id="p-a-valid")
    invalid_outline = projects_root / "p-z-invalid" / ".webnovel" / "outline.json"
    invalid_outline.parent.mkdir(parents=True, exist_ok=True)
    invalid_outline.write_text("{broken", encoding="utf-8")
    valid_outline = valid / ".webnovel" / "outline.json"
    valid_before = _hash(valid_outline)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/migrate_volume_outlines.py",
            "--root",
            str(projects_root),
            "--apply",
        ],
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 1
    assert _hash(valid_outline) == valid_before
    assert "migration_exception:JSONDecodeError" in result.stdout


def test_cli_external_project_backs_up_under_workspace_data(tmp_path: Path) -> None:
    projects_root = tmp_path / "external" / "projects"
    _legacy_project(projects_root)
    workspace_backup_root = (
        Path(__file__).parents[2]
        / "data"
        / "migration-backups"
        / "volume-outline"
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/migrate_volume_outlines.py",
            "--root",
            str(projects_root),
            "--apply",
        ],
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip())
    assert Path(report["backup_path"]).is_relative_to(workspace_backup_root)
    shutil.rmtree(Path(report["backup_path"]).parents[2])
