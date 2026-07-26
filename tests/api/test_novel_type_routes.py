from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import stories as story_routes
from apps.api.routes.novel_types import NovelTypeWriteRequest
from apps.api.storage import SQLiteStoryStore
from packages.story_core.models import NovelProject


@pytest.fixture
def novel_type_api(tmp_path: Path, monkeypatch):
    types_path = tmp_path / "novel-types.json"
    file_projects_dir = tmp_path / "file-projects"
    sqlite_store = SQLiteStoryStore(str(tmp_path / "stories.db"))
    monkeypatch.setenv("NOVEL_AUTOGROWTH_NOVEL_TYPES_PATH", str(types_path))
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(file_projects_dir))
    monkeypatch.setattr(story_routes, "store", sqlite_store)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, sqlite_store, file_projects_dir


def _custom_payload(type_id: str = "sports") -> dict:
    return {
        "id": type_id,
        "name": "  Sports fiction  ",
        "description": "  Competition and team growth.  ",
        "keywords": ["  league  ", "championship"],
        "core_promises": ["Every match changes the standings."],
        "ledger_fields": ["ranking"],
        "rulebook": {
            "progression_rules": ["Training has a visible cost."],
            "economy_rules": [],
            "quest_rules": [],
            "faction_rules": ["Teams pursue conflicting goals."],
            "panel_rules": [],
            "chapter_formula": ["Prepare, compete, recover."],
            "forbidden_breaks": ["No unexplained power spikes."],
        },
        "quality_checks": ["The result changes future choices."],
        "trope_templates": [{"name": "underdog season", "beats": ["loss", "rebuild"]}],
    }


def _create_file_project(
    root: Path,
    project_id: str,
    state_genre_ids: list[str],
    *,
    project_genre_ids: list[str] | None = None,
) -> None:
    project_root = root / project_id
    story_system = project_root / ".story-system"
    webnovel = project_root / ".webnovel"
    story_system.mkdir(parents=True)
    webnovel.mkdir(parents=True)
    (story_system / "MASTER_SETTING.json").write_text("{}", encoding="utf-8")
    (webnovel / "state.json").write_text(
        json.dumps({"world_blueprint": {"genre_plugin_ids": state_genre_ids}}),
        encoding="utf-8",
    )
    project_blueprint = (
        {"world_blueprint": {"genre_plugin_ids": project_genre_ids}}
        if project_genre_ids is not None
        else {}
    )
    (webnovel / "project.json").write_text(
        json.dumps(
            {
                "project_id": project_id,
                "title": project_id,
                **project_blueprint,
            }
        ),
        encoding="utf-8",
    )


def test_get_returns_complete_types_in_stable_order(novel_type_api):
    client, _, _ = novel_type_api

    first = client.get("/novel-types")
    second = client.get("/novel-types")

    assert first.status_code == 200
    assert first.json() == second.json()
    assert [item["id"] for item in first.json()] == [
        "generic_webnovel",
        "game_webnovel",
        "xuanhuan",
        "xianxia",
        "urban",
        "romance",
        "suspense",
        "rules_mystery",
    ]
    assert set(first.json()[0]) == {
        "id",
        "name",
        "description",
        "keywords",
        "core_promises",
        "ledger_fields",
        "rulebook",
        "quality_checks",
        "trope_templates",
        "power_system_template",
        "builtin",
    }


def test_get_power_template_round_trips_through_put(novel_type_api):
    client, _, _ = novel_type_api
    original = next(
        item for item in client.get("/novel-types").json() if item["id"] == "xuanhuan"
    )
    expected_template = original["power_system_template"]
    original.pop("builtin")

    updated = client.put("/novel-types/xuanhuan", json=original)

    assert expected_template
    assert updated.status_code == 200
    assert updated.json()["power_system_template"] == expected_template


def test_write_request_distinguishes_omitted_and_explicit_empty_power_template():
    omitted = NovelTypeWriteRequest(id="first", name="First")
    explicit = NovelTypeWriteRequest(
        id="second", name="Second", power_system_template={}
    )

    assert omitted.power_system_template is None
    assert "power_system_template" not in omitted.model_dump(exclude_unset=True)
    assert explicit.power_system_template == {}
    assert explicit.model_dump(exclude_unset=True)["power_system_template"] == {}


def test_put_omitting_power_template_preserves_builtin_override(novel_type_api):
    client, _, _ = novel_type_api
    payload = next(
        item for item in client.get("/novel-types").json() if item["id"] == "xuanhuan"
    )
    payload.pop("builtin")
    payload["power_system_template"] = {"system_form": "review override"}
    assert client.put("/novel-types/xuanhuan", json=payload).status_code == 200

    payload.pop("power_system_template")
    payload["name"] = "Edited without template"
    updated = client.put("/novel-types/xuanhuan", json=payload)

    assert updated.status_code == 200
    assert updated.json()["power_system_template"] == {"system_form": "review override"}


def test_put_omitting_power_template_preserves_custom_override(novel_type_api):
    client, _, _ = novel_type_api
    payload = {
        **_custom_payload(),
        "power_system_template": {"system_form": "custom review override"},
    }
    created = client.post("/novel-types", json=payload)
    expected_template = created.json()["power_system_template"]

    payload.pop("power_system_template")
    payload["name"] = "Updated without template"
    updated = client.put("/novel-types/sports", json=payload)

    assert updated.status_code == 200
    assert updated.json()["power_system_template"] == expected_template


def test_put_explicit_empty_power_template_applies_existing_merge_semantics(novel_type_api):
    client, _, _ = novel_type_api
    builtin = next(
        item for item in client.get("/novel-types").json() if item["id"] == "xuanhuan"
    )
    builtin.pop("builtin")
    builtin["power_system_template"] = {}
    builtin_updated = client.put("/novel-types/xuanhuan", json=builtin)

    custom_payload = {
        **_custom_payload(),
        "power_system_template": {"system_form": "custom review override"},
    }
    assert client.post("/novel-types", json=custom_payload).status_code == 201
    custom_payload["power_system_template"] = {}
    custom_updated = client.put("/novel-types/sports", json=custom_payload)

    assert builtin_updated.status_code == 200
    assert builtin_updated.json()["power_system_template"] == {}
    assert custom_updated.status_code == 200
    assert custom_updated.json()["power_system_template"]["system_form"]
    assert custom_updated.json()["power_system_template"]["system_form"] != (
        "custom review override"
    )


def test_create_edit_and_delete_unused_custom_type(novel_type_api):
    client, _, _ = novel_type_api

    created = client.post("/novel-types", json=_custom_payload())

    assert created.status_code == 201
    assert created.json()["id"] == "sports"
    assert created.json()["name"] == "Sports fiction"
    assert created.json()["keywords"] == ["league", "championship"]
    assert created.json()["builtin"] is False
    assert created.json()["power_system_template"]["system_form"]
    assert created.json()["power_system_template"]["required_sections"]

    reloaded = next(
        item for item in client.get("/novel-types").json() if item["id"] == "sports"
    )
    assert reloaded["power_system_template"] == created.json()["power_system_template"]

    updated_payload = _custom_payload()
    updated_payload["name"] = "Sports drama"
    updated = client.put("/novel-types/sports", json=updated_payload)

    assert updated.status_code == 200
    assert updated.json()["id"] == "sports"
    assert updated.json()["name"] == "Sports drama"
    assert updated.json()["power_system_template"]["required_sections"]
    assert client.delete("/novel-types/sports").status_code == 204
    assert all(item["id"] != "sports" for item in client.get("/novel-types").json())


def test_builtin_can_be_edited_but_not_renamed_or_deleted(novel_type_api):
    client, _, _ = novel_type_api
    original = next(
        item for item in client.get("/novel-types").json() if item["id"] == "xuanhuan"
    )
    original["name"] = "Edited xuanhuan"
    original.pop("builtin")

    edited = client.put("/novel-types/xuanhuan", json=original)
    renamed = client.put("/novel-types/xuanhuan", json={**original, "id": "renamed"})
    deleted = client.delete("/novel-types/xuanhuan")

    assert edited.status_code == 200
    assert edited.json()["id"] == "xuanhuan"
    assert edited.json()["name"] == "Edited xuanhuan"
    assert renamed.status_code == 422
    assert deleted.status_code == 409
    assert "built-in" in deleted.json()["detail"]


def test_unknown_duplicate_and_custom_id_conflict_errors(novel_type_api):
    client, _, _ = novel_type_api
    assert client.put("/novel-types/missing", json=_custom_payload("missing")).status_code == 404
    assert client.delete("/novel-types/missing").status_code == 404

    assert client.post("/novel-types", json=_custom_payload()).status_code == 201
    duplicate = client.post("/novel-types", json=_custom_payload())
    mismatched = client.put("/novel-types/sports", json=_custom_payload("history"))

    assert duplicate.status_code == 409
    assert mismatched.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {**_custom_payload(), "unknown": "ignored"},
        {**_custom_payload(), "name": "   "},
        {**_custom_payload(), "keywords": ["valid", "   "]},
        {**_custom_payload(), "rulebook": {"unknown_rules": ["no"]}},
        {**_custom_payload(), "keywords": "league"},
        {**_custom_payload(), "power_system_template": None},
    ],
)
def test_create_rejects_unknown_or_invalid_fields(novel_type_api, payload):
    client, _, _ = novel_type_api

    response = client.post("/novel-types", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize(
    "invalid_id",
    [
        "sports/fiction",
        "sports fiction",
        " sports",
        "sports\nfiction",
        "SPORTS",
        "a" * 65,
    ],
)
def test_create_rejects_ids_that_are_not_path_safe(novel_type_api, invalid_id):
    client, _, _ = novel_type_api

    response = client.post("/novel-types", json=_custom_payload(invalid_id))

    assert response.status_code == 422


def test_create_accepts_64_character_path_safe_id(novel_type_api):
    client, _, _ = novel_type_api
    type_id = "a" + "1" * 63

    response = client.post("/novel-types", json=_custom_payload(type_id))

    assert response.status_code == 201
    assert response.json()["id"] == type_id


@pytest.mark.parametrize("invalid_id", ["SPORTS", "a" * 65])
def test_delete_rejects_invalid_path_ids(novel_type_api, invalid_id):
    client, _, _ = novel_type_api

    response = client.delete(f"/novel-types/{invalid_id}")

    assert response.status_code == 422


def test_delete_rejects_custom_type_used_by_sqlite_project(novel_type_api):
    client, sqlite_store, _ = novel_type_api
    assert client.post("/novel-types", json=_custom_payload()).status_code == 201
    sqlite_store.create_project(
        NovelProject(
            project_id="sqlite-project",
            title="SQLite project",
            world_blueprint={"genre_plugin_ids": ["urban", "sports"]},
        )
    )

    response = client.delete("/novel-types/sports")

    assert response.status_code == 409
    assert "sqlite-project" in response.json()["detail"]
    assert "sports" in {item["id"] for item in client.get("/novel-types").json()}


def test_delete_rejects_casefold_equivalent_sqlite_reference(novel_type_api):
    client, sqlite_store, _ = novel_type_api
    assert client.post("/novel-types", json=_custom_payload()).status_code == 201
    sqlite_store.create_project(
        NovelProject(
            project_id="sqlite-uppercase-project",
            title="SQLite uppercase project",
            world_blueprint={"genre_plugin_ids": ["SPORTS"]},
        )
    )

    response = client.delete("/novel-types/sports")

    assert response.status_code == 409
    assert "sqlite-uppercase-project" in response.json()["detail"]


def test_delete_rejects_custom_type_used_by_file_project(novel_type_api):
    client, _, file_projects_dir = novel_type_api
    assert client.post("/novel-types", json=_custom_payload()).status_code == 201
    _create_file_project(file_projects_dir, "file-project", ["sports"])

    response = client.delete("/novel-types/sports")

    assert response.status_code == 409
    assert "file-project" in response.json()["detail"]
    assert "sports" in {item["id"] for item in client.get("/novel-types").json()}


def test_delete_rejects_casefold_equivalent_file_project_reference(novel_type_api):
    client, _, file_projects_dir = novel_type_api
    assert client.post("/novel-types", json=_custom_payload()).status_code == 201
    _create_file_project(file_projects_dir, "file-uppercase-project", ["SpOrTs"])

    response = client.delete("/novel-types/sports")

    assert response.status_code == 409
    assert "file-uppercase-project" in response.json()["detail"]


def test_delete_checks_project_and_state_blueprints_independently(novel_type_api):
    client, _, file_projects_dir = novel_type_api
    assert client.post("/novel-types", json=_custom_payload()).status_code == 201
    _create_file_project(
        file_projects_dir,
        "split-blueprint-project",
        ["sports"],
        project_genre_ids=["urban"],
    )

    response = client.delete("/novel-types/sports")

    assert response.status_code == 409
    assert "split-blueprint-project" in response.json()["detail"]
