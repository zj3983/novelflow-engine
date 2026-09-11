from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects as file_project_routes


@pytest.fixture
def inspection_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    export_root = tmp_path / "exported-projects"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    project_root = export_root / "p-inspection-api"
    (project_root / ".story-system").mkdir(parents=True)
    (project_root / ".webnovel").mkdir(parents=True)
    project = {"project_id": "p-inspection-api", "title": "Inspection API"}
    state = {"story_id": "s-inspection-api", "current_chapter": 40, "characters": []}
    for path, payload in (
        (project_root / ".webnovel" / "project.json", project),
        (project_root / ".webnovel" / "state.json", state),
        (project_root / ".story-system" / "MASTER_SETTING.json", {"project": project, "state": state}),
    ):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, export_root


def _payload() -> dict:
    return {
        "current_chapter": 40,
        "characters": [
            {
                "name": "林照",
                "role": "protagonist",
                "current_state": {
                    "current": {"location": "FUTURE_LOCATION_999"},
                    "history": [{"chapter": 10, "current": {"location": "青云城"}}],
                },
            }
        ],
        "progression_ledger": {
            "protagonist": {
                "history": [{"chapter": 25, "current": {"skills": ["御剑术"]}}]
            }
        },
        "knowledge_ledger": [
            {
                "fact_id": "future-secret",
                "fact": "FUTURE_KNOWLEDGE_999",
                "learned_chapter": 30,
                "known_by": ["林照"],
                "visibility": "private",
            }
        ],
    }


def test_character_timeline_route_serializes_range_and_history_status(
    inspection_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = inspection_api
    monkeypatch.setattr(file_project_routes, "_character_inspection_payload", lambda store: _payload())

    response = client.get(
        "/file-projects/file:p-inspection-api/characters/林照/timeline",
        params={"end_chapter": 20},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["history_status"] == "available"
    assert body["events_in_range"] == len(body["events"])
    assert all(item["chapter_number"] <= 20 for item in body["events"])
    assert "FUTURE_LOCATION_999" not in json.dumps(body, ensure_ascii=False)


def test_character_consistency_route_reports_start_boundary_and_warnings(
    inspection_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = inspection_api
    monkeypatch.setattr(file_project_routes, "_character_inspection_payload", lambda store: _payload())

    response = client.post(
        "/file-projects/file:p-inspection-api/characters/林照/consistency-check",
        json={
            "target_chapter": 20,
            "planned_context": {"location": "黑风城", "skills_used": ["御剑术"]},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["historical_boundary"] == 19
    assert {item["code"] for item in body["warnings"]} == {
        "LOCATION_MISMATCH",
        "SKILL_NOT_YET_ACQUIRED",
    }
    assert all(item["target_chapter"] == 20 for item in body["warnings"])


def test_character_inspection_routes_validate_inputs_and_unknown_characters(
    inspection_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = inspection_api
    monkeypatch.setattr(file_project_routes, "_character_inspection_payload", lambda store: _payload())

    invalid = client.post(
        "/file-projects/file:p-inspection-api/characters/林照/consistency-check",
        json={"target_chapter": 0, "planned_context": {}},
    )
    unknown = client.get(
        "/file-projects/file:p-inspection-api/characters/%E9%99%8C%E7%94%9F/timeline"
    )

    assert invalid.status_code == 422
    assert unknown.status_code == 404
