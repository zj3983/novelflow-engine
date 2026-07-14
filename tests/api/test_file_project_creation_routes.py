import json
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects as file_project_routes
from apps.api.routes import stories as story_routes


@pytest.fixture
def creation_api(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    legacy_create = Mock(side_effect=AssertionError("legacy SQLite project creation called"))
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    monkeypatch.setattr(story_routes.store, "create_project", legacy_create)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, export_root, legacy_create


def test_blank_file_project_creation_returns_201_and_is_readable(creation_api):
    client, export_root, legacy_create = creation_api

    response = client.post(
        "/file-projects",
        json={"mode": "blank", "title": "Blank Route Project", "novel_type_id": "urban"},
    )

    assert response.status_code == 201
    project = response.json()
    assert project["project_id"].startswith("file:p-")
    assert project["storage_source"] == "file"
    assert project["next_path"] == f"/projects/{quote(project['project_id'], safe='')}/outline"
    assert Path(project["source_path"]).parent == export_root
    assert client.get(f"/file-projects/{project['project_id']}").json() == {
        key: value for key, value in project.items() if key != "next_path"
    }
    legacy_create.assert_not_called()


def test_inspiration_file_project_creation_returns_setup_path_and_opening_brief(creation_api):
    client, _, legacy_create = creation_api

    response = client.post(
        "/file-projects",
        json={
            "mode": "inspiration",
            "novel_type_id": "xianxia",
            "idea": "A courier discovers every sealed letter predicts tomorrow.",
        },
    )

    assert response.status_code == 201
    project = response.json()
    assert project["project_id"].startswith("file:p-")
    assert project["storage_source"] == "file"
    assert project["next_path"] == f"/projects/{quote(project['project_id'], safe='')}/setup"
    opening_brief = json.loads(
        (Path(project["source_path"]) / ".webnovel" / "opening_brief.json").read_text(encoding="utf-8")
    )
    assert opening_brief["idea"] == "A courier discovers every sealed letter predicts tomorrow."
    assert opening_brief["novel_type_id"] == "xianxia"
    legacy_create.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "blank", "title": "", "novel_type_id": "urban"},
        {"mode": "inspiration", "novel_type_id": "urban", "idea": ""},
        {"mode": "blank", "title": "Unknown Type", "novel_type_id": "not-a-type"},
    ],
)
def test_invalid_file_project_creation_returns_422_without_leaving_a_project(creation_api, payload):
    client, export_root, legacy_create = creation_api

    response = client.post("/file-projects", json=payload)

    assert response.status_code == 422
    assert not export_root.exists() or list(export_root.iterdir()) == []
    legacy_create.assert_not_called()


def test_file_project_creation_rejects_extra_fields(creation_api):
    client, export_root, legacy_create = creation_api

    response = client.post(
        "/file-projects",
        json={
            "mode": "blank",
            "title": "Strict Contract",
            "novel_type_id": "urban",
            "source_path": "ignored-by-contract",
        },
    )

    assert response.status_code == 422
    assert not export_root.exists() or list(export_root.iterdir()) == []
    legacy_create.assert_not_called()


def test_file_project_creation_maps_file_conflict_to_422(creation_api, monkeypatch):
    client, export_root, legacy_create = creation_api

    def raise_conflict(*args, **kwargs):
        raise FileExistsError("project_id_conflict")

    monkeypatch.setattr(file_project_routes, "create_file_project", raise_conflict, raising=False)
    response = client.post(
        "/file-projects",
        json={"mode": "blank", "title": "Conflict", "novel_type_id": "urban"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "project_id_conflict"
    assert not export_root.exists() or list(export_root.iterdir()) == []
    legacy_create.assert_not_called()


def test_file_project_creation_leaves_unexpected_disk_errors_as_500(creation_api, monkeypatch):
    client, export_root, legacy_create = creation_api

    def raise_disk_error(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(file_project_routes, "create_file_project", raise_disk_error, raising=False)
    response = client.post(
        "/file-projects",
        json={"mode": "blank", "title": "Disk Failure", "novel_type_id": "urban"},
    )

    assert response.status_code == 500
    assert not export_root.exists() or list(export_root.iterdir()) == []
    assert client.get("/file-projects").json() == []
    legacy_create.assert_not_called()
