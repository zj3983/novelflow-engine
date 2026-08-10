from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.migrate_world_context import migrate_project


def _project(root: Path) -> None:
    webnovel = root / ".webnovel"
    chapters = root / "chapters"
    webnovel.mkdir(parents=True)
    chapters.mkdir(parents=True)
    (webnovel / "project.json").write_text(
        json.dumps(
            {
                "project_id": "migration-test",
                "title": "Migration Test",
                "current_focus": "守住入口。",
                "world_blueprint": {
                    "premise": "灵气依赖地脉。",
                    "current_arc": "雪山封锁。",
                    "continuity_state": {"running_facts": ["林修负伤。"]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (webnovel / "state.json").write_text(
        json.dumps(
            {
                "story_id": "migration-test",
                "world_facts": [
                    "世界前提：灵气依赖地脉。",
                    "第147章事实：林修负伤。",
                    "第147章摘要：不应继续进入写作上下文。",
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (chapters / "第147章.md").write_text("# 第147章\n\n正文不应改变。\n", encoding="utf-8")


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_migration_dry_run_does_not_write_files(tmp_path: Path) -> None:
    _project(tmp_path)
    before_project = (tmp_path / ".webnovel" / "project.json").read_bytes()
    before_state = (tmp_path / ".webnovel" / "state.json").read_bytes()

    report = migrate_project(tmp_path, apply=False)

    assert report["changed"] is True
    assert report["continuity_fact_count"] == 1
    assert (tmp_path / ".webnovel" / "project.json").read_bytes() == before_project
    assert (tmp_path / ".webnovel" / "state.json").read_bytes() == before_state
    assert not (tmp_path / ".story-system" / "world-context-backups").exists()


def test_migration_apply_is_idempotent_and_preserves_chapters(tmp_path: Path) -> None:
    _project(tmp_path)
    chapter = tmp_path / "chapters" / "第147章.md"
    chapter_hash = _hash(chapter)

    first = migrate_project(tmp_path, apply=True, timestamp="20260810T120000Z")
    second = migrate_project(tmp_path, apply=True, timestamp="20260810T120100Z")

    project = json.loads((tmp_path / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    state = json.loads((tmp_path / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert first["changed"] is True
    assert second["changed"] is False
    assert "current_arc" not in project["world_blueprint"]
    assert "continuity_state" not in project["world_blueprint"]
    assert state["world_snapshot"]["current_arc"] == "雪山封锁。"
    assert [item["text"] for item in state["continuity_facts"]] == ["林修负伤。"]
    assert state["world_facts"] == []
    assert len(state["legacy_world_facts"]) == 3
    assert _hash(chapter) == chapter_hash
    backup = tmp_path / ".story-system" / "world-context-backups" / "20260810T120000Z"
    assert (backup / "project.json").is_file()
    assert (backup / "state.json").is_file()


def test_migration_rejects_malformed_json_without_writing(tmp_path: Path) -> None:
    _project(tmp_path)
    state_path = tmp_path / ".webnovel" / "state.json"
    state_path.write_text("{broken", encoding="utf-8")
    project_before = (tmp_path / ".webnovel" / "project.json").read_bytes()

    with pytest.raises(ValueError, match="invalid_json:state.json"):
        migrate_project(tmp_path, apply=True)

    assert (tmp_path / ".webnovel" / "project.json").read_bytes() == project_before
    assert state_path.read_text(encoding="utf-8") == "{broken"


def test_migration_cli_runs_from_outside_repository(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _project(project)
    script = Path(__file__).resolve().parents[2] / "scripts" / "migrate_world_context.py"

    result = subprocess.run(
        [sys.executable, str(script), str(project), "--dry-run"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["changed"] is True
