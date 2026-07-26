from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import scripts.upgrade_project_power_system as migration
from packages.story_core.power_systems import (
    legacy_power_summary,
    validate_power_system_spec,
)
from packages.story_core.world_blueprint_context import MANAGED_MARKER
from scripts.upgrade_project_power_system import upgrade_project


CLASSES = ("战士", "法师", "游侠", "盗贼", "牧师", "召唤师")
BRANCHES = {
    "战士": ("守护骑士", "狂战士"),
    "法师": ("元素宗师", "奥术贤者"),
    "游侠": ("神射手", "荒野猎王"),
    "盗贼": ("影刃", "诡术师"),
    "牧师": ("圣愈者", "戒律祭司"),
    "召唤师": ("契约领主", "兽群主宰"),
}


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=4) + "\n").replace(
        "\n", "\r\n"
    ).encode("utf-8")


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "legacy-project"
    metadata = root / ".webnovel"
    settings = root / "设定集"
    chapters = root / "chapters"
    metadata.mkdir(parents=True)
    settings.mkdir()
    chapters.mkdir()

    project = {
        "title": "苟在网游里成神",
        "untouched": {"prose": "原样保留", "amount": "售价120金币"},
        "world_blueprint": {
            "premise": "神域映照现实。",
            "power_system": [
                "所有玩家以Lv.1见习者进入神域。",
                "Lv.10正式转职，Lv.30选择分支，Lv.60取得传承。",
            ],
            "unrelated_rule": {"nested": [1, "保持不变"]},
        },
    }
    outline = {
        "schema_version": 1,
        "overall": {
            "growth_path": "Lv.10正式转职→Lv.30职业分支→Lv.60职业传承。",
            "money_rule": "一件装备售价120金币，法术伤害+15%。",
        },
        "arcs": [
            {
                "goal": "夜烬在Lv.10完成正式法系职业，并进入主城。",
                "unchanged": "Lv.10职业进阶需要通关元素回廊。",
            }
        ],
        "chapters": [
            {
                "title": "Lv.20大关卡，属性解锁",
                "goal": "冲刺Lv.20突破，完成第二次职业进阶节点",
                "turn": "智力+8，体质+3，法术伤害+15%",
            },
            {
                "title": "正式法系职业的精算打法重构",
                "goal": "系统重构Lv.10正式法系职业的技能循环",
            },
            {
                "goal": "流霜保持远程弓手路线，并推进猎人专精线索。",
            },
        ],
    }
    (metadata / "project.json").write_bytes(_json_bytes(project))
    (metadata / "outline.json").write_bytes(_json_bytes(outline))
    (settings / "力量体系.md").write_text(
        f"{MANAGED_MARKER}\n\n# 旧力量体系\n", encoding="utf-8"
    )
    (settings / "世界观.md").write_text(
        "# 手写世界观\n\n绝不能覆盖。\n", encoding="utf-8"
    )
    (chapters / "0001.md").write_bytes(b"\xef\xbb\xbfchapter\r\n\x00exact-bytes\r\n")
    return root


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def test_upgrade_migrates_complete_system_and_preserves_unrelated_data(
    project_dir: Path,
) -> None:
    project_path = project_dir / ".webnovel" / "project.json"
    outline_path = project_dir / ".webnovel" / "outline.json"
    chapter_path = project_dir / "chapters" / "0001.md"
    world_path = project_dir / "设定集" / "世界观.md"
    original_project = _load(project_path)
    original_outline = _load(outline_path)
    original_project_bytes = project_path.read_bytes()
    original_outline_bytes = outline_path.read_bytes()
    original_chapter = chapter_path.read_bytes()
    original_world = world_path.read_bytes()

    result = upgrade_project(project_dir)

    assert result["changed"] is True
    assert result["valid"] is True
    assert Path(result["backup_path"]).parent == project_dir / ".webnovel" / "backups"
    assert "project.json: power system upgraded" in result["changes"]
    assert "outline.json: contradictory progression wording updated" in result["changes"]
    assert "设定集/力量体系.md: refreshed" in result["changes"]

    migrated_project = _load(project_path)
    migrated_outline = _load(outline_path)
    blueprint = migrated_project["world_blueprint"]
    spec = validate_power_system_spec(
        blueprint["power_system_spec"], novel_type_id="game_webnovel"
    )

    assert migrated_project["untouched"] == original_project["untouched"]
    assert blueprint["premise"] == original_project["world_blueprint"]["premise"]
    assert blueprint["unrelated_rule"] == original_project["world_blueprint"]["unrelated_rule"]
    assert blueprint["power_system"] == legacy_power_summary(spec)
    assert tuple(path["name"] for path in spec["paths"]) == CLASSES
    assert {path["name"]: tuple(path["branches"]) for path in spec["paths"]} == BRANCHES
    assert tuple(stage["level"] for stage in spec["stages"]) == (1, 10, 20, 30, 60)
    assert tuple(stage["name"] for stage in spec["stages"]) == (
        "见习者",
        "正式职业",
        "职业专精",
        "进阶分支",
        "传承职业",
    )
    assert all(
        path[field]
        for path in spec["paths"]
        for field in (
            "role",
            "core_attributes",
            "core_resource",
            "weapons",
            "armor",
            "skill_categories",
            "combat_loop",
            "strengths",
            "weaknesses",
            "transfer_task",
            "advancement",
        )
    )
    mage = next(path for path in spec["paths"] if path["name"] == "法师")
    mage_text = json.dumps(mage, ensure_ascii=False)
    assert all(
        token in mage_text
        for token in ("元素法师", "元素专精", "元素宗师", "元素权柄传承")
    )
    ranger = next(path for path in spec["paths"] if path["name"] == "游侠")
    ranger_text = json.dumps(ranger, ensure_ascii=False)
    assert "远程弓手" in ranger_text
    assert "猎人专精" in ranger_text

    assert "职业专精节点" in migrated_outline["chapters"][0]["goal"]
    assert "第二次职业进阶" not in json.dumps(migrated_outline, ensure_ascii=False)
    assert migrated_outline["arcs"][0]["goal"] == "夜烬在Lv.10完成元素法师，并进入主城。"
    assert migrated_outline["chapters"][1]["title"] == original_outline["chapters"][1]["title"]
    assert migrated_outline["chapters"][1]["goal"] == "系统重构Lv.10元素法师的技能循环"
    assert migrated_outline["overall"]["money_rule"] == original_outline["overall"]["money_rule"]
    assert migrated_outline["arcs"][0]["unchanged"] == original_outline["arcs"][0]["unchanged"]
    assert migrated_outline["chapters"][2] == original_outline["chapters"][2]

    power_markdown = (project_dir / "设定集" / "力量体系.md").read_text(
        encoding="utf-8"
    )
    assert power_markdown.startswith(MANAGED_MARKER)
    assert "元素宗师" in power_markdown
    assert world_path.read_bytes() == original_world
    assert chapter_path.read_bytes() == original_chapter

    backup = Path(result["backup_path"])
    assert (backup / "project.json").read_bytes() == original_project_bytes
    assert (backup / "outline.json").read_bytes() == original_outline_bytes


def test_upgrade_skips_unmanaged_power_markdown(project_dir: Path) -> None:
    power_path = project_dir / "设定集" / "力量体系.md"
    original = "# 手写力量体系\n\n保留作者判断。\n".encode("utf-8")
    power_path.write_bytes(original)

    result = upgrade_project(project_dir)

    assert power_path.read_bytes() == original
    assert "设定集/力量体系.md: skipped unmanaged" in result["changes"]


def test_upgrade_is_idempotent_and_does_not_create_second_backup(project_dir: Path) -> None:
    first = upgrade_project(project_dir)
    after_first = {
        path: path.read_bytes()
        for path in (
            project_dir / ".webnovel" / "project.json",
            project_dir / ".webnovel" / "outline.json",
            project_dir / "设定集" / "力量体系.md",
        )
    }

    second = upgrade_project(project_dir)

    assert first["changed"] is True
    assert second == {"changed": False, "valid": True, "backup_path": None, "changes": []}
    assert {path: path.read_bytes() for path in after_first} == after_first
    assert len(list((project_dir / ".webnovel" / "backups").glob("power-system-*"))) == 1


def test_check_reports_expected_changes_without_writes_or_backup(project_dir: Path) -> None:
    before = {
        path: path.read_bytes()
        for path in (
            project_dir / ".webnovel" / "project.json",
            project_dir / ".webnovel" / "outline.json",
            project_dir / "设定集" / "力量体系.md",
        )
    }

    result = upgrade_project(project_dir, check=True)

    assert result["changed"] is True
    assert result["valid"] is True
    assert result["backup_path"] is None
    assert result["changes"]
    assert {path: path.read_bytes() for path in before} == before
    assert not (project_dir / ".webnovel" / "backups").exists()


def test_no_backup_option_writes_without_backup(project_dir: Path) -> None:
    result = upgrade_project(project_dir, backup=False)

    assert result["changed"] is True
    assert result["backup_path"] is None
    assert not (project_dir / ".webnovel" / "backups").exists()


def test_outline_without_targeted_conflicts_keeps_exact_bytes(project_dir: Path) -> None:
    outline_path = project_dir / ".webnovel" / "outline.json"
    original = b'{"clean":"Lv.20 completes a specialization trial","amount":"120 gold"}'
    outline_path.write_bytes(original)

    result = upgrade_project(project_dir)

    assert result["valid"] is True
    assert outline_path.read_bytes() == original
    assert not any(change.startswith("outline.json:") for change in result["changes"])


def test_outline_cleanup_only_edits_allowlisted_narrative_fields(project_dir: Path) -> None:
    outline_path = project_dir / ".webnovel" / "outline.json"
    outline = _load(outline_path)
    protected = "Lv.20第二次职业进阶，Lv.10正式法系职业"
    outline.update(
        {
            "author_note": protected,
            "dialogue": protected,
            "quote_excerpt": protected,
            "negative_instruction": f"不要改写：{protected}",
            "world_rule": protected,
            "raw_source": protected,
            "metadata": {"text": protected},
            "beats": [
                "Lv.20第二次职业进阶",
                {"summary": "主角在Lv.10成为正式法系职业"},
            ],
            "key_events": [
                {"description": "Lv.20再次转职被改为既有职业强化"},
            ],
        }
    )
    outline_path.write_bytes(_json_bytes(outline))

    result = upgrade_project(project_dir)
    migrated = _load(outline_path)

    assert result["valid"] is True
    assert migrated["beats"] == [
        "Lv.20职业专精",
        {"summary": "主角在Lv.10成为元素法师"},
    ]
    assert migrated["key_events"][0]["description"] == "Lv.20职业专精被改为既有职业强化"
    for key in (
        "author_note",
        "dialogue",
        "quote_excerpt",
        "negative_instruction",
        "world_rule",
        "raw_source",
    ):
        assert migrated[key] == outline[key]
    assert migrated["metadata"] == outline["metadata"]


def test_replacement_failure_rolls_back_every_target_and_cleans_temps(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets = (
        project_dir / ".webnovel" / "project.json",
        project_dir / ".webnovel" / "outline.json",
        project_dir / "设定集" / "力量体系.md",
    )
    before = {path: (path.exists(), path.read_bytes()) for path in targets}
    real_replace = migration.os.replace
    calls = 0

    def fail_second_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert len(list(project_dir.rglob(".*.tmp"))) == len(targets)
        if calls == 2:
            raise OSError("injected second replacement failure")
        real_replace(source, destination)

    monkeypatch.setattr(migration.os, "replace", fail_second_replace)

    result = upgrade_project(project_dir, backup=False)

    assert calls >= 3
    assert result["changed"] is False
    assert result["valid"] is False
    assert result["backup_path"] is None
    assert "injected second replacement failure" in result["changes"][0]
    assert {
        path: (path.exists(), path.read_bytes() if path.exists() else b"")
        for path in targets
    } == before
    assert not list(project_dir.rglob(".*.tmp"))


def test_commit_and_rollback_failure_reports_persistent_change(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets = (
        project_dir / ".webnovel" / "project.json",
        project_dir / ".webnovel" / "outline.json",
        project_dir / "设定集" / "力量体系.md",
    )
    before = {path: path.read_bytes() for path in targets}
    real_replace = migration.os.replace
    calls = 0

    def fail_commit_and_rollback(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls in {2, 3}:
            raise OSError(f"injected replacement failure {calls}")
        real_replace(source, destination)

    monkeypatch.setattr(migration.os, "replace", fail_commit_and_rollback)

    result = upgrade_project(project_dir, backup=False)

    assert result["valid"] is False
    assert result["changed"] is True
    assert result["rollback_failed"] is True
    assert result["state"] == "indeterminate"
    assert targets[0].read_bytes() != before[targets[0]]
    assert targets[1].read_bytes() == before[targets[1]]
    assert targets[2].read_bytes() == before[targets[2]]
    assert not list(project_dir.rglob(".*.tmp"))


def test_commit_rollback_and_cleanup_failures_preserve_primary_error(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_replace = migration.os.replace
    real_unlink = Path.unlink
    replace_calls = 0
    locked_temps: set[Path] = set()

    def fail_commit_and_rollback(source: str | Path, destination: str | Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        source_path = Path(source)
        if replace_calls == 2:
            locked_temps.add(source_path)
            raise OSError("PRIMARY COMMIT FAILURE")
        if replace_calls == 3:
            locked_temps.add(source_path)
            raise OSError("ROLLBACK RESTORE FAILURE")
        real_replace(source, destination)

    def fail_locked_cleanup(self: Path, missing_ok: bool = False) -> None:
        if self in locked_temps:
            raise PermissionError("LOCKED TEMP CLEANUP FAILURE")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(migration.os, "replace", fail_commit_and_rollback)
    monkeypatch.setattr(Path, "unlink", fail_locked_cleanup)

    result = upgrade_project(project_dir, backup=False)

    assert result["valid"] is False
    assert result["changed"] is True
    assert result["rollback_failed"] is True
    assert result["cleanup_failed"] is True
    assert result["state"] == "indeterminate"
    assert "PRIMARY COMMIT FAILURE" in result["changes"][0]
    assert "ROLLBACK RESTORE FAILURE" in " ".join(result["rollback_errors"])
    assert "LOCKED TEMP CLEANUP FAILURE" in " ".join(result["cleanup_errors"])
    assert set(map(Path, result["residual_temp_paths"])) == locked_temps
    assert all(path.exists() for path in locked_temps)

    monkeypatch.setattr(Path, "unlink", real_unlink)
    for path in locked_temps:
        path.unlink(missing_ok=True)


def test_cleanup_failure_after_successful_commit_reports_valid_changed_state(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_replace = migration.os.replace
    real_unlink = Path.unlink
    residuals: set[Path] = set()

    def replace_but_leave_residual(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        content = source_path.read_bytes()
        real_replace(source_path, destination)
        source_path.write_bytes(content)
        residuals.add(source_path)

    def fail_residual_cleanup(self: Path, missing_ok: bool = False) -> None:
        if self in residuals:
            raise PermissionError("RESIDUAL TEMP LOCKED")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(migration.os, "replace", replace_but_leave_residual)
    monkeypatch.setattr(Path, "unlink", fail_residual_cleanup)

    result = upgrade_project(project_dir, backup=False)

    assert result["changed"] is True
    assert result["valid"] is True
    assert result["rollback_failed"] is False
    assert result["cleanup_failed"] is True
    assert result["state"] == "changed"
    assert result["residual_temp_paths"]
    assert "RESIDUAL TEMP LOCKED" in " ".join(result["cleanup_errors"])

    monkeypatch.setattr(Path, "unlink", real_unlink)
    for path in residuals:
        path.unlink(missing_ok=True)


def test_cli_returns_nonzero_when_cleanup_failed(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        migration,
        "upgrade_project",
        lambda *args, **kwargs: {
            "changed": True,
            "valid": True,
            "backup_path": None,
            "changes": ["error: cleanup failed"],
            "rollback_failed": False,
            "cleanup_failed": True,
            "state": "changed",
            "rollback_errors": [],
            "cleanup_errors": ["locked"],
            "residual_temp_paths": ["temp"],
        },
    )

    exit_code = migration.main([str(project_dir), "--no-backup"])

    assert exit_code != 0
    assert json.loads(capsys.readouterr().out)["cleanup_failed"] is True


def test_second_backup_write_failure_publishes_no_partial_backup(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = migration._write_fsynced_file
    calls = 0

    def fail_second_write(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second backup write failure")
        real_write(path, content)

    monkeypatch.setattr(migration, "_write_fsynced_file", fail_second_write)

    result = upgrade_project(project_dir)

    backups = project_dir / ".webnovel" / "backups"
    assert result["valid"] is False
    assert result["changed"] is False
    assert result["backup_path"] is None
    assert not backups.exists() or not list(backups.iterdir())
    assert not list(project_dir.rglob(".power-system-*.tmp"))


def test_rejects_canonical_file_symlink_escape_before_external_change(
    project_dir: Path, tmp_path: Path
) -> None:
    project_path = project_dir / ".webnovel" / "project.json"
    external = tmp_path / "external-project.json"
    external.write_bytes(project_path.read_bytes())
    project_path.unlink()
    try:
        os.symlink(external, project_path)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlink creation unavailable: {exc}")
    before = external.read_bytes()

    result = upgrade_project(project_dir)

    assert result["valid"] is False
    assert result["changed"] is False
    assert "path_escape: project_json" in result["changes"][0]
    assert external.read_bytes() == before
    assert not (project_dir / ".webnovel" / "backups").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_rejects_settings_junction_escape_before_external_change(
    project_dir: Path, tmp_path: Path
) -> None:
    settings = project_dir / "设定集"
    original_settings = project_dir / "设定集-original"
    external = tmp_path / "external-settings"
    external.mkdir()
    external_power = external / "力量体系.md"
    external_power.write_text(f"{MANAGED_MARKER}\nexternal\n", encoding="utf-8")
    settings.rename(original_settings)
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(settings), str(external)],
        capture_output=True,
        check=False,
    )
    if created.returncode != 0:
        original_settings.rename(settings)
        pytest.skip("junction creation unavailable")
    before = external_power.read_bytes()
    try:
        result = upgrade_project(project_dir)
    finally:
        os.rmdir(settings)
        original_settings.rename(settings)

    assert result["valid"] is False
    assert result["changed"] is False
    assert "path_escape: power_markdown" in result["changes"][0]
    assert external_power.read_bytes() == before
    assert not (project_dir / ".webnovel" / "backups").exists()


def test_malformed_json_is_invalid_and_atomic(project_dir: Path) -> None:
    project_path = project_dir / ".webnovel" / "project.json"
    outline_path = project_dir / ".webnovel" / "outline.json"
    power_path = project_dir / "设定集" / "力量体系.md"
    outline_path.write_bytes(b'{"broken":')
    before = {path: path.read_bytes() for path in (project_path, outline_path, power_path)}

    result = upgrade_project(project_dir)

    assert result["changed"] is False
    assert result["valid"] is False
    assert result["backup_path"] is None
    assert result["changes"] and result["changes"][0].startswith("error:")
    assert {path: path.read_bytes() for path in before} == before
    assert not (project_dir / ".webnovel" / "backups").exists()


def test_cli_emits_json_and_returns_nonzero_for_invalid_project(project_dir: Path) -> None:
    script = Path(__file__).parents[1] / "scripts" / "upgrade_project_power_system.py"
    valid = subprocess.run(
        [sys.executable, str(script), str(project_dir), "--check", "--no-backup"],
        cwd=script.parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    invalid = subprocess.run(
        [sys.executable, str(script), str(project_dir / "missing")],
        cwd=script.parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert valid.returncode == 0
    assert json.loads(valid.stdout)["valid"] is True
    assert invalid.returncode != 0
    assert json.loads(invalid.stdout)["valid"] is False


def test_migration_does_not_mutate_spec_between_calls(project_dir: Path) -> None:
    upgrade_project(project_dir)
    first = deepcopy(_load(project_dir / ".webnovel" / "project.json"))

    upgrade_project(project_dir, check=True)

    assert _load(project_dir / ".webnovel" / "project.json") == first
