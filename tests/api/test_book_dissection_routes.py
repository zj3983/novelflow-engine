import json
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import app


client = TestClient(app)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_book_dissection_reference_returns_report():
    response = client.post(
        "/book-dissection/reference",
        json={
            "text": "夜烬绕开人群，先观察任务牌。短发玩家问他为什么不接任务，他说还差两份材料。",
            "genre": "网游",
            "focus": "爽点",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "book-dissection/v1"
    assert payload["mode"] == "reference"
    assert "爽点来源" in payload["sections"]


def test_book_dissection_reference_empty_text_returns_422():
    response = client.post("/book-dissection/reference", json={"text": "   "})

    assert response.status_code == 422
    assert response.json()["detail"] == "text_required"


def test_file_project_book_dissection_chapter_uses_store(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    project_root = export_root / "dissection-fixture"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    _write_json(
        project_root / ".story-system" / "MASTER_SETTING.json",
        {"project": {"project_id": "dissection-fixture", "title": "Dissection Fixture"}},
    )
    _write_json(
        project_root / ".webnovel" / "state.json",
        {"current_chapter": 1, "progression_ledger": {"protagonist": {"level": "Lv.1"}}},
    )
    _write_json(
        project_root / ".webnovel" / "project.json",
        {"project_id": "dissection-fixture", "title": "Dissection Fixture"},
    )
    _write_json(
        project_root / ".story-system" / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "提前转职",
            "body": "夜烬1级就接了转职任务。\n他说：\"行。\"\n他说：\"好。\"",
        },
    )

    projects_response = client.get("/file-projects")
    assert projects_response.status_code == 200
    projects = projects_response.json()
    assert [project["project_id"] for project in projects] == ["file:dissection-fixture"]

    response = client.post(
        "/file-projects/file:dissection-fixture/book-dissection/chapter",
        json={"chapter_number": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "book-dissection/v1"
    assert payload["mode"] == "project"
    assert "下一版改法" in payload["sections"]
    assert any("转职" in item for item in payload["sections"]["设定冲突"])
