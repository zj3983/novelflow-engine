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


def test_file_project_list_ignores_backup_directories(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    for name in [
        "p-main",
        "p-main.backup-20260623-222859",
        "p-main.before-outline-20260623-223951",
        "_backups",
    ]:
        project_root = export_root / name
        _write_json(
            project_root / ".story-system" / "MASTER_SETTING.json",
            {"project": {"project_id": name, "title": "Same Title"}},
        )
        _write_json(project_root / ".webnovel" / "state.json", {"current_chapter": 1})
        _write_json(project_root / ".webnovel" / "project.json", {"project_id": name, "title": "Same Title"})

    response = client.get("/file-projects")

    assert response.status_code == 200
    projects = response.json()
    assert [project["project_id"] for project in projects] == ["file:p-main"]


def test_file_project_update_persists_outline_for_file_project(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    project_root = export_root / "outline-fixture"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    _write_json(project_root / ".story-system" / "MASTER_SETTING.json", {"project": {"title": "Outline Fixture"}})
    _write_json(project_root / ".webnovel" / "state.json", {"story_id": "s-file", "current_chapter": 4})
    _write_json(
        project_root / ".webnovel" / "project.json",
        {"project_id": "outline-fixture", "title": "Outline Fixture", "world_blueprint": {}},
    )

    response = client.put(
        "/file-projects/file:outline-fixture",
        json={
            "current_focus": "第5章写白河仓库收购方追问材料来源。",
            "world_blueprint": {
                "current_arc": "新手村交易线",
                "opening_arc": {
                    "chapter_beats": [
                        {
                            "chapter": 5,
                            "title": "担保名单",
                            "required_payoff": "确认白河仓库收购规则",
                            "ending_hook": "收购方追问材料来源",
                        }
                    ]
                },
                "forbidden_breaks": ["不能让收购方直接知道千倍爆率。"],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_focus"] == "第5章写白河仓库收购方追问材料来源。"
    project = json.loads((project_root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    state = json.loads((project_root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert project["world_blueprint"]["opening_arc"]["chapter_beats"][0]["title"] == "担保名单"
    assert state["current_focus"] == "第5章写白河仓库收购方追问材料来源。"


def test_file_project_outline_get_projects_legacy_data_without_writing(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    project_root = export_root / "outline-legacy"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    master_path = project_root / ".story-system" / "MASTER_SETTING.json"
    state_path = project_root / ".webnovel" / "state.json"
    project_path = project_root / ".webnovel" / "project.json"
    outline_path = project_root / ".webnovel" / "outline.json"
    _write_json(master_path, {"project": {"title": "Outline Legacy"}})
    _write_json(state_path, {"story_id": "s-outline-legacy", "current_chapter": 2})
    _write_json(
        project_path,
        {
            "project_id": "outline-legacy",
            "title": "Outline Legacy",
            "seed_outline": "A courier investigates a vanished caravan.",
            "world_blueprint": {
                "current_arc": "Trace the caravan through the border town.",
                "opening_arc": {
                    "chapter_beats": [
                        {
                            "chapter": 3,
                            "title": "The Empty Stable",
                            "required_payoff": "Find the caravan seal.",
                            "ending_hook": "The seal is still warm.",
                        }
                    ]
                },
            },
        },
    )
    original_files = {
        path: path.read_bytes()
        for path in (master_path, project_path, state_path)
    }

    response = client.get("/file-projects/file:outline-legacy/outline")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "legacy"
    assert payload["schema_version"] == "project-outline/v1"
    assert payload["overall"]["story"] == "A courier investigates a vanished caravan."
    assert payload["arcs"][0]["goal"] == "Trace the caravan through the border town."
    assert payload["chapters"] == [
        {
            "chapter_number": 3,
            "title": "The Empty Stable",
            "goal": "",
            "obstacle": "",
            "action": "",
            "turn": "",
            "payoff": "Find the caravan seal.",
            "ending_hook": "The seal is still warm.",
        }
    ]
    assert not outline_path.exists()
    assert {path: path.read_bytes() for path in original_files} == original_files


def test_file_project_outline_put_persists_canonical_data_and_gets_it_back(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    project_root = export_root / "outline-saved"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    _write_json(project_root / ".story-system" / "MASTER_SETTING.json", {"project": {"title": "Outline Saved"}})
    _write_json(project_root / ".webnovel" / "state.json", {"story_id": "s-outline-saved"})
    _write_json(project_root / ".webnovel" / "project.json", {"project_id": "outline-saved"})
    outline_path = project_root / ".webnovel" / "outline.json"
    request_payload = {
        "overall": {
            "story": "A courier investigates a vanished caravan.",
            "protagonist_goal": "Bring the missing drivers home.",
        },
        "arcs": [
            {
                "id": "border-town",
                "title": "Border Town",
                "start_chapter": 1,
                "end_chapter": 6,
                "goal": "Identify the caravan's attacker.",
            }
        ],
        "chapters": [
            {
                "chapter_number": 2,
                "title": "The Empty Stable",
                "goal": "Search the stable.",
                "ending_hook": "A fresh hoofprint points north.",
            }
        ],
    }

    saved = client.put("/file-projects/file:outline-saved/outline", json=request_payload)

    assert saved.status_code == 200
    saved_payload = saved.json()
    assert saved_payload["source"] == "saved"
    assert saved_payload["overall"]["story"] == request_payload["overall"]["story"]
    assert saved_payload["arcs"][0]["id"] == "border-town"
    assert saved_payload["chapters"][0]["chapter_number"] == 2
    persisted = json.loads(outline_path.read_text(encoding="utf-8"))
    assert "source" not in persisted
    assert persisted == {key: value for key, value in saved_payload.items() if key != "source"}

    loaded = client.get("/file-projects/file:outline-saved/outline")

    assert loaded.status_code == 200
    assert loaded.json() == saved_payload


def test_file_project_outline_put_rejects_duplicate_chapter_without_overwriting(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    project_root = export_root / "outline-duplicate"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    _write_json(project_root / ".story-system" / "MASTER_SETTING.json", {"project": {"title": "Outline Duplicate"}})
    _write_json(project_root / ".webnovel" / "state.json", {"story_id": "s-outline-duplicate"})
    _write_json(project_root / ".webnovel" / "project.json", {"project_id": "outline-duplicate"})
    outline_path = project_root / ".webnovel" / "outline.json"
    _write_json(
        outline_path,
        {
            "schema_version": "project-outline/v1",
            "overall": {"story": "The valid saved outline."},
            "arcs": [],
            "chapters": [{"chapter_number": 1, "goal": "Begin the search."}],
        },
    )
    original_bytes = outline_path.read_bytes()

    response = client.put(
        "/file-projects/file:outline-duplicate/outline",
        json={
            "overall": {"story": "This update is invalid."},
            "chapters": [
                {"chapter_number": 2, "goal": "Search the stable."},
                {"chapter_number": 2, "goal": "Search it again."},
            ],
        },
    )

    assert response.status_code == 422
    assert "duplicate_chapter_outline" in response.json()["detail"]
    assert outline_path.read_bytes() == original_bytes


def test_file_project_outline_get_rejects_corrupt_file_without_rewriting(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    project_root = export_root / "outline-corrupt"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    _write_json(project_root / ".story-system" / "MASTER_SETTING.json", {"project": {"title": "Outline Corrupt"}})
    _write_json(project_root / ".webnovel" / "state.json", {"story_id": "s-outline-corrupt"})
    _write_json(project_root / ".webnovel" / "project.json", {"project_id": "outline-corrupt"})
    outline_path = project_root / ".webnovel" / "outline.json"
    corrupt_bytes = b'{"schema_version":"project-outline/v1","chapters":['
    outline_path.write_bytes(corrupt_bytes)

    response = client.get("/file-projects/file:outline-corrupt/outline")

    assert response.status_code == 422
    assert response.json()["detail"]
    assert outline_path.read_bytes() == corrupt_bytes


def test_file_project_outline_get_rejects_unsupported_schema_without_rewriting(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    project_root = export_root / "outline-unsupported"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    _write_json(project_root / ".story-system" / "MASTER_SETTING.json", {"project": {"title": "Outline Unsupported"}})
    _write_json(project_root / ".webnovel" / "state.json", {"story_id": "s-outline-unsupported"})
    _write_json(project_root / ".webnovel" / "project.json", {"project_id": "outline-unsupported"})
    outline_path = project_root / ".webnovel" / "outline.json"
    _write_json(outline_path, {"schema_version": "project-outline/v2"})
    original_bytes = outline_path.read_bytes()

    response = client.get("/file-projects/file:outline-unsupported/outline")

    assert response.status_code == 422
    assert "project-outline/v1" in response.json()["detail"]
    assert outline_path.read_bytes() == original_bytes


def test_file_project_outline_routes_keep_unknown_project_404(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path / "exported-projects"))

    get_response = client.get("/file-projects/file:missing-outline/outline")
    put_response = client.put("/file-projects/file:missing-outline/outline", json={})

    assert get_response.status_code == 404
    assert get_response.json()["detail"] == "file_project_not_found"
    assert put_response.status_code == 404
    assert put_response.json()["detail"] == "file_project_not_found"


def test_file_project_writing_packet_uses_file_outline_and_character_cards(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    project_root = export_root / "packet-fixture"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    _write_json(project_root / ".story-system" / "MASTER_SETTING.json", {"project": {"title": "Packet Fixture"}})
    _write_json(project_root / ".webnovel" / "state.json", {"story_id": "s-file", "current_chapter": 4, "world_facts": []})
    _write_json(
        project_root / ".webnovel" / "project.json",
        {
            "project_id": "packet-fixture",
            "title": "Packet Fixture",
            "current_focus": "第5章确认白河仓库收购规则，收购方开始追问材料来源。",
            "world_blueprint": {
                "current_arc": "新手村交易线",
                "opening_arc": {
                    "chapter_beats": [
                        {
                            "chapter": 5,
                            "title": "担保名单",
                            "required_payoff": "确认白河仓库收购规则",
                            "ending_hook": "收购方追问材料来源",
                        }
                    ]
                },
            },
        },
    )

    response = client.get("/file-projects/file:packet-fixture/writing-packet?chapter_number=5")

    assert response.status_code == 200
    packet = response.json()
    assert packet["schema_version"] == "file-writing-packet/v1"
    assert packet["target_chapter"] == 5
    assert packet["outline_constraints"]["opening_arc"]["chapter_beats"][0]["title"] == "担保名单"
    buyer = next(character for character in packet["state"]["characters"] if character["name"] == "白河仓库收购方")
    assert buyer["lifecycle_state"] == "proposed"


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
