"""Tests for Round 8 Task 7: rolling-fill API endpoints.

Two endpoints:

* ``POST /file-projects/{id}/outline/rolling-fill?target_chapter=N``
  — manually trigger a rolling fill (even when the window is large
  enough). Returns the new fill status (with the new chapter numbers).
* ``GET /file-projects/{id}/outline/rolling-fill-status?target_chapter=N``
  — return the current rolling fill status for the target chapter
  (no side effects).

Errors:
* 404 — missing project.
* 422 — invalid target_chapter (out of volume range, non-positive,
  NaN, etc.).
* 422 — generation failure (validation / I/O / generator exception).

The plan rule: "错误：missing project / chapter out of range /
generation failure → 4xx + detail".
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import stories as story_routes
from packages.story_core.file_project_store import FileProjectStore


@pytest.fixture
def rolling_api(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, export_root


def _seed_minimal_file_project(export_root: Path) -> str:
    """Create a minimal file project on disk and return its project_id."""
    project_dir = export_root / "p-rolling-test"
    project_dir.mkdir(parents=True)
    (project_dir / ".story-system" / "chapters").mkdir(parents=True)
    (project_dir / ".story-system" / "reviews").mkdir(parents=True)
    (project_dir / ".webnovel").mkdir(parents=True)
    (project_dir / "chapters").mkdir()
    project = {
        "project_id": "p-rolling-test",
        "title": "断香炉",
        "active_story_id": "s-file",
        "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        "character_profiles": [],
    }
    state = {
        "story_id": "s-file",
        "current_chapter": 0,
        "world_facts": [],
        "characters": [],
    }
    (project_dir / ".webnovel" / "project.json").write_text(
        json.dumps(project, ensure_ascii=False), encoding="utf-8"
    )
    (project_dir / ".webnovel" / "state.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )
    (project_dir / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": project,
                "state": state,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return "file:p-rolling-test"


def _outline_row(number: int) -> dict:
    return {
        "chapter_number": number,
        "title": f"第{number}章",
        "chapter_goal": "林修追查香炉裂纹的来源",
        "core_conflict": "修复香炉会暴露林修的位置",
        "cast": [{"name": "林修", "role": "protagonist", "this_chapter_role": "追查"}],
        "scenes": [
            {"location": "旧宅", "action": "检查香炉", "result": "发现暗纹"},
            {"location": "后巷", "action": "追踪暗纹", "result": "找到线索"},
        ],
        "gain": "获得线索",
        "cost": "暴露行踪",
        "foreshadowing": [],
        "hook": "门外有人敲门",
        "state_delta": "林修掌握新的暗纹位置",
    }


def test_post_rolling_fill_redirects_missing_outline_to_outline_workspace(rolling_api) -> None:
    client, export_root = rolling_api
    project_id = _seed_minimal_file_project(export_root)
    response = client.post(
        f"/file-projects/{project_id}/outline/rolling-fill",
        params={"target_chapter": 1},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "chapter_outline_required:1"
    rolling_path = export_root / "p-rolling-test" / ".story-system" / "outline-generation" / "rolling_outline.json"
    assert not rolling_path.exists()


def test_get_rolling_fill_status_stays_missing_after_compatibility_post(rolling_api) -> None:
    client, export_root = rolling_api
    project_id = _seed_minimal_file_project(export_root)
    # Trigger a fill first
    client.post(
        f"/file-projects/{project_id}/outline/rolling-fill",
        params={"target_chapter": 1},
    )
    # Now query status
    response = client.get(
        f"/file-projects/{project_id}/outline/rolling-fill-status",
        params={"target_chapter": 1},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "missing"
    assert payload["chapter_number"] == 1


def test_get_rolling_fill_status_reports_missing_before_fill(rolling_api) -> None:
    client, export_root = rolling_api
    project_id = _seed_minimal_file_project(export_root)
    response = client.get(
        f"/file-projects/{project_id}/outline/rolling-fill-status",
        params={"target_chapter": 1},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "missing"
    assert payload["chapter_number"] == 1


def test_start_body_generation_rejects_before_creating_job_when_outline_missing(rolling_api) -> None:
    client, export_root = rolling_api
    project_id = _seed_minimal_file_project(export_root)

    response = client.post(f"/file-projects/{project_id}/generation-jobs", json={})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "chapter_outline_required:1"
    jobs_dir = export_root / "p-rolling-test" / ".story-system" / "generation-jobs"
    assert not jobs_dir.exists() or not list(jobs_dir.glob("fgj-*.json"))


def test_legacy_generate_next_rejects_before_body_generation_when_outline_missing(rolling_api) -> None:
    client, export_root = rolling_api
    project_id = _seed_minimal_file_project(export_root)

    response = client.post(f"/file-projects/{project_id}/generate-next", json={})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "chapter_outline_required:1"
    candidates_dir = export_root / "p-rolling-test" / ".story-system" / "candidates"
    assert not candidates_dir.exists() or not list(candidates_dir.glob("*.json"))


def test_post_rolling_fill_returns_404_for_missing_project(rolling_api) -> None:
    client, _ = rolling_api
    response = client.post(
        "/file-projects/file:does-not-exist/outline/rolling-fill",
        params={"target_chapter": 1},
    )
    assert response.status_code == 404


def test_get_rolling_fill_status_returns_404_for_missing_project(rolling_api) -> None:
    client, _ = rolling_api
    response = client.get(
        "/file-projects/file:does-not-exist/outline/rolling-fill-status",
        params={"target_chapter": 1},
    )
    assert response.status_code == 404


def test_post_rolling_fill_rejects_non_positive_target_chapter(rolling_api) -> None:
    client, export_root = rolling_api
    project_id = _seed_minimal_file_project(export_root)
    response = client.post(
        f"/file-projects/{project_id}/outline/rolling-fill",
        params={"target_chapter": 0},
    )
    assert response.status_code == 422


def test_post_rolling_fill_does_not_invoke_hidden_generator(rolling_api) -> None:
    client, export_root = rolling_api
    project_id = _seed_minimal_file_project(export_root)

    response = client.post(
        f"/file-projects/{project_id}/outline/rolling-fill",
        params={"target_chapter": 1},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "chapter_outline_required:1"


def test_put_rolling_chapter_marks_source_manual_and_blocks_subsequent_fill(rolling_api) -> None:
    """Round 8 Task 8: manual-edit protection.

    After PUT marks chapter 1 as ``source="manual"`` with a custom
    title, the next POST to the fill endpoint must NOT overwrite the
    manual chapter.
    """
    client, export_root = rolling_api
    project_id = _seed_minimal_file_project(export_root)
    store = FileProjectStore(export_root / "p-rolling-test")
    store.ensure_rolling_outline(target_chapter=1, generator=_outline_row)
    # Edit chapter 1 (mark as manual with a custom title)
    update = client.put(
        f"/file-projects/{project_id}/outline/rolling-chapter/1",
        json={"title": "OPERATOR 定制章名"},
    )
    assert update.status_code == 200, update.text
    chapter = update.json()["chapter"]
    assert chapter["source"] == "manual"
    assert chapter["title"] == "OPERATOR 定制章名"
    # The disk file reflects the manual source.
    rolling_path = export_root / "p-rolling-test" / ".story-system" / "outline-generation" / "rolling_outline.json"
    on_disk = json.loads(rolling_path.read_text(encoding="utf-8"))
    by_number = {c["chapter_number"]: c for c in on_disk["chapters"]}
    assert by_number[1]["source"] == "manual"
    assert by_number[1]["title"] == "OPERATOR 定制章名"
    # The compatibility POST only reports the existing outline and never overwrites it.
    second_fill = client.post(
        f"/file-projects/{project_id}/outline/rolling-fill",
        params={"target_chapter": 1},
    )
    assert second_fill.status_code == 200, second_fill.text
    on_disk_2 = json.loads(rolling_path.read_text(encoding="utf-8"))
    by_number_2 = {c["chapter_number"]: c for c in on_disk_2["chapters"]}
    assert by_number_2[1]["title"] == "OPERATOR 定制章名"
    assert by_number_2[1]["source"] == "manual"


def test_put_rolling_chapter_returns_422_when_no_rolling_outline(rolling_api) -> None:
    client, export_root = rolling_api
    project_id = _seed_minimal_file_project(export_root)
    response = client.put(
        f"/file-projects/{project_id}/outline/rolling-chapter/1",
        json={"title": "no outline yet"},
    )
    assert response.status_code == 422


def test_put_rolling_chapter_returns_404_for_missing_project(rolling_api) -> None:
    client, _ = rolling_api
    response = client.put(
        "/file-projects/file:does-not-exist/outline/rolling-chapter/1",
        json={"title": "x"},
    )
    assert response.status_code == 404
