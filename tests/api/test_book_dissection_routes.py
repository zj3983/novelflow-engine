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


def test_file_project_book_dissection_returns_concrete_progress_without_filler(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    project_root = export_root / "dissection-progress"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    _write_json(
        project_root / ".story-system" / "MASTER_SETTING.json",
        {"project": {"project_id": "dissection-progress", "title": "Dissection Progress"}},
    )
    _write_json(
        project_root / ".webnovel" / "state.json",
        {"current_chapter": 1, "progression_ledger": {"protagonist": {"level": "Lv.1"}}},
    )
    _write_json(
        project_root / ".webnovel" / "project.json",
        {"project_id": "dissection-progress", "title": "Dissection Progress"},
    )
    _write_json(
        project_root / ".story-system" / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "chapter_title": "灰狼坡试水",
            "body": "\n".join(
                [
                    "夜烬击杀第五只灰狼。",
                    "【经验：0/100】【生命：100/100】【法力：60/60】",
                    "【经验：30/100】",
                    "【获得：灰狼毒腺×58】【获得：粗糙狼皮×31】",
                    "Lv.1，经验30/100。生命42/100。法力0/60。新手法杖4/10。灰狼毒腺八份，粗糙狼皮七张。",
                    "【清道夫委托】",
                    "【前置任务：提交灰狼毒腺×10】",
                    "【底层协议校验通过】",
                    "【掉落判定×1000】",
                    "【混沌之种：未解析】",
                ]
            ),
        },
    )

    response = client.post(
        "/file-projects/file:dissection-progress/book-dissection/chapter",
        json={"chapter_number": 1},
    )

    assert response.status_code == 200
    payload = response.json()
    joined = "\n".join(item for items in payload["sections"].values() for item in items)
    assert "经验30/100" in joined
    assert "灰狼毒腺8" in joined
    assert "还差2份" in joined
    assert "掉落判定×1000" in joined
    assert "暂未命中" not in joined
    assert "未发现硬性错误" not in joined
