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


def test_post_rolling_fill_writes_chapters_and_returns_status(rolling_api) -> None:
    client, export_root = rolling_api
    project_id = _seed_minimal_file_project(export_root)
    response = client.post(
        f"/file-projects/{project_id}/outline/rolling-fill",
        params={"target_chapter": 1},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] in ("filled", "present")
    if payload["status"] == "filled":
        assert payload["chapter_numbers"] == [1, 2, 3, 4, 5]
    # The rolling outline file should now exist on disk.
    rolling_path = export_root / "p-rolling-test" / ".story-system" / "outline-generation" / "rolling_outline.json"
    assert rolling_path.is_file()


def test_get_rolling_fill_status_reports_present_after_fill(rolling_api) -> None:
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
    assert payload["status"] == "present"
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


def test_post_rolling_fill_handles_generator_failure(rolling_api, monkeypatch) -> None:
    """When the generator raises, the endpoint must surface a 422 with
    a meaningful detail, not a 500 or a silent failure."""
    from packages.story_core import outline_rolling_planner

    client, export_root = rolling_api
    project_id = _seed_minimal_file_project(export_root)

    def boom(_chapter_number: int) -> dict:
        raise RuntimeError("injected generator failure")

    monkeypatch.setattr(
        outline_rolling_planner.RollingOutlinePlanner,
        "_generator_thunk",
        lambda self, gen: boom,
        raising=False,
    )
    # Simpler: monkeypatch the FileProjectStore._default_rolling_chapter_generator
    from packages.story_core import file_project_store as fps_module
    monkeypatch.setattr(
        fps_module.FileProjectStore,
        "_default_rolling_chapter_generator",
        staticmethod(boom),
    )
    response = client.post(
        f"/file-projects/{project_id}/outline/rolling-fill",
        params={"target_chapter": 1},
    )
    assert response.status_code == 422, response.text
    detail = response.json().get("detail", "")
    assert "generator" in str(detail).lower() or "failure" in str(detail).lower()
