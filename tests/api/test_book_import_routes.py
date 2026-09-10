import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def allow_test_source_paths(monkeypatch, tmp_path: Path):
    # The production default intentionally allows the home and current
    # directories.  Pytest's isolated temp directory is outside both,
    # so include it explicitly while retaining the cwd case below.
    monkeypatch.setenv(
        "NOVEL_AUTOGROWTH_ALLOWED_FS_ROOTS",
        os.pathsep.join((str(tmp_path), str(Path.cwd()))),
    )


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_book_import_scan_rejects_path_outside_allowed_roots(tmp_path: Path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("NOVEL_AUTOGROWTH_ALLOWED_FS_ROOTS", str(allowed))

    response = client.post("/book-import/scan", json={"source_path": str(outside)})

    assert response.status_code == 403
    assert "path_outside_allowed_roots" in response.json()["detail"]


def test_book_import_scan_allows_path_inside_configured_root(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_ALLOWED_FS_ROOTS", str(tmp_path))
    _write(tmp_path / "volume_outline.md", "# Volume Outline\n\nA grand mystery.\n")
    _write(tmp_path / "current_focus.md", "# Current Focus\n\nOpen with the crime scene.\n")

    response = client.post("/book-import/scan", json={"source_path": str(tmp_path)})

    assert response.status_code == 200
    assert response.json()["can_bootstrap"] is True


def test_book_import_list_folders_returns_allowed_roots(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_ALLOWED_FS_ROOTS", str(tmp_path))

    response = client.post("/book-import/list-folders", json={"source_path": ""})

    assert response.status_code == 200
    payload = response.json()
    assert [Path(entry["path"]).resolve() for entry in payload["drives"]] == [tmp_path.resolve()]


def test_book_import_list_folders_rejects_path_outside_allowed_roots(tmp_path: Path, monkeypatch):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("NOVEL_AUTOGROWTH_ALLOWED_FS_ROOTS", str(allowed))

    response = client.post("/book-import/list-folders", json={"source_path": str(outside)})

    assert response.status_code == 403


def test_book_import_scan_valid_folder(tmp_path: Path):
    _write(tmp_path / "volume_outline.md", "# Volume Outline\n\nA grand mystery.\n")
    _write(tmp_path / "current_focus.md", "# Current Focus\n\nOpen with the crime scene.\n")

    response = client.post("/book-import/scan", json={"source_path": str(tmp_path)})
    assert response.status_code == 200

    payload = response.json()
    assert payload["source_path"] == str(tmp_path)
    assert payload["exists"] is True
    assert payload["can_bootstrap"] is True
    assert payload["missing_required_files"] == []


def test_book_import_scan_accepts_quoted_file_path_and_normalizes_to_parent_dir(tmp_path: Path):
    story_dir = tmp_path / "story"
    story_dir.mkdir()
    _write(story_dir / "volume_outline.md", "VOLUME: A hidden ledger drives the plot.\n")
    _write(story_dir / "current_focus.md", "FOCUS: Open with the first clue.\n")
    _write(story_dir / "story_bible.md", "BIBLE: Keep the opening grounded.\n")

    response = client.post("/book-import/scan", json={"source_path": f'"{story_dir / "story_bible.md"}"'})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(story_dir)
    assert payload["exists"] is True
    assert payload["can_bootstrap"] is True


def test_book_import_bootstrap_valid_folder_returns_draft_and_report(tmp_path: Path):
    _write(tmp_path / "volume_outline.md", "VOLUME: A magistrate hunts forged decrees.\n")
    _write(tmp_path / "current_focus.md", "FOCUS: Start with the ink shop.\n")
    _write(
        tmp_path / "character_matrix.md",
        "| Name | Role |\n| --- | --- |\n| Lin Yue | investigator |\n| Su Wan | witness |\n",
    )

    response = client.post("/book-import/bootstrap", json={"source_path": str(tmp_path)})
    assert response.status_code == 200

    payload = response.json()
    assert payload["report"]["exists"] is True
    assert payload["report"]["can_bootstrap"] is True
    assert payload["report"]["missing_required_files"] == []

    draft = payload["draft"]
    assert "VOLUME" in draft["outline"]
    assert "Start with the ink shop" in draft["outline"]
    assert draft["characters"] == [
        {"name": "Lin Yue", "goal": "investigator"},
        {"name": "Su Wan", "goal": "witness"},
    ]


def test_book_import_bootstrap_returns_structured_world_blueprint(tmp_path: Path):
    _write(tmp_path / "volume_outline.md", "VOLUME: A cautious reborn player builds early advantage.\n")
    _write(tmp_path / "current_focus.md", "FOCUS: Secure the first hidden quest.\n")
    _write(
        tmp_path / "story_bible.md",
        "\n".join(
            [
                "# Divine Gate Story Bible",
                "- Game: Divine Gate is a 100% immersive global VRMMO.",
                "- Rule: game currency can be exchanged with real money.",
                "- Power: levels, skills, equipment, professions, and hidden quests shape advancement.",
                "- Faction: the Dawn Guild hunts rare first-clear rewards.",
                "- Location: Novice Village is the first resource bottleneck.",
            ]
        ),
    )
    _write(
        tmp_path / "character_matrix.md",
        "\n".join(
            [
                "## Su Ye",
                "- **Role**: protagonist",
                "- **Motivation**: Use rebirth knowledge without exposing the secret.",
            ]
        ),
    )

    response = client.post("/book-import/bootstrap", json={"source_path": str(tmp_path)})
    assert response.status_code == 200

    draft = response.json()["draft"]
    assert draft["world_blueprint"]["premise"] == "Divine Gate Story Bible"
    assert draft["world_blueprint"]["world_rules"] == ["game currency can be exchanged with real money."]
    assert draft["world_blueprint"]["factions"][0]["name"] == "Dawn Guild"
    assert draft["character_profiles"][0]["name"] == "Su Ye"
    assert draft["character_profiles"][0]["motivation"] == "Use rebirth knowledge without exposing the secret."


def test_book_import_bootstrap_ignores_relationship_table_headers(tmp_path: Path):
    _write(tmp_path / "volume_outline.md", "VOLUME: A hidden ledger drives the plot.\n")
    _write(tmp_path / "current_focus.md", "FOCUS: Open with the first clue.\n")
    _write(
        tmp_path / "character_matrix.md",
        "\n".join(
            [
                "### 角色档案",
                "| 角色 | 核心标签 | 反差细节 | 说话风格 | 性格底色 | 与主角关系 | 核心动机 | 当前目标 |",
                "|------|----------|----------|----------|----------|------------|----------|----------|",
                "### 相遇记录",
                "| 角色A | 角色B | 首次相遇章 | 最近交互章 | 关系性质 | 关系变化 |",
                "|-------|-------|------------|------------|----------|----------|",
            ]
        ),
    )

    response = client.post("/book-import/bootstrap", json={"source_path": str(tmp_path)})
    assert response.status_code == 200

    payload = response.json()
    assert payload["draft"]["characters"] == []


def test_book_import_bootstrap_accepts_file_path_and_uses_parent_folder(tmp_path: Path):
    story_dir = tmp_path / "story"
    story_dir.mkdir()
    _write(story_dir / "volume_outline.md", "VOLUME: A magistrate hunts forged decrees.\n")
    _write(story_dir / "current_focus.md", "FOCUS: Start with the ink shop.\n")
    _write(story_dir / "story_bible.md", "BIBLE: Keep the opening grounded.\n")

    response = client.post("/book-import/bootstrap", json={"source_path": str(story_dir / "story_bible.md")})

    assert response.status_code == 200
    payload = response.json()
    assert payload["report"]["source_path"] == str(story_dir)
    assert payload["report"]["exists"] is True
    assert payload["report"]["can_bootstrap"] is True


def test_book_import_invalid_path_returns_clear_error():
    missing = Path.cwd() / "definitely_missing_book_import_folder"
    scan_response = client.post("/book-import/scan", json={"source_path": str(missing)})
    assert scan_response.status_code == 200
    scan_payload = scan_response.json()
    assert scan_payload["exists"] is False
    assert scan_payload["can_bootstrap"] is False
    assert "current_focus.md" in scan_payload["missing_required_files"]

    bootstrap_response = client.post("/book-import/bootstrap", json={"source_path": str(missing)})
    assert bootstrap_response.status_code == 404
    detail = bootstrap_response.json().get("detail", "")
    assert isinstance(detail, str)
    assert "source_path_not_found" in detail


def test_book_import_rejects_truly_invalid_path_string():
    response = client.post("/book-import/scan", json={"source_path": "bad\u0000path"})
    assert response.status_code == 400
    detail = response.json().get("detail", "")
    assert "invalid_source_path" in detail


def test_book_import_bootstrap_accepts_file_path_and_uses_parent_folder(tmp_path: Path):
    story_dir = tmp_path / "story"
    story_dir.mkdir()
    file_path = story_dir / "story_bible.md"
    _write(story_dir / "volume_outline.md", "VOLUME: A hidden ledger drives the plot.\n")
    _write(story_dir / "current_focus.md", "FOCUS: Open with the first clue.\n")
    _write(file_path, "Story bible notes.\n")

    response = client.post("/book-import/bootstrap", json={"source_path": str(file_path)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["report"]["source_path"] == str(story_dir)
    assert payload["report"]["can_bootstrap"] is True


def test_book_import_scan_allows_workbench_origin():
    response = client.options(
        "/book-import/scan",
        headers={
            "origin": "http://127.0.0.1:3000",
            "access-control-request-method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://127.0.0.1:3000"


def test_book_import_catalog_groups_source_docs_state_and_runtime(tmp_path: Path):
    (tmp_path / "state").mkdir()
    (tmp_path / "runtime").mkdir()
    _write(tmp_path / "volume_outline.md", "VOLUME: A hidden ledger drives the plot.\n")
    _write(tmp_path / "current_focus.md", "FOCUS: Open with the first clue.\n")
    _write(tmp_path / "author_intent.md", "INTENT: Keep the opening grounded.\n")
    _write(tmp_path / "character_matrix.md", "| Name | Role |\n| --- | --- |\n| Lin Yue | investigator |\n")
    _write(tmp_path / "state" / "manifest.json", '{"schemaVersion": 2, "lastAppliedChapter": 1}')
    _write(tmp_path / "runtime" / "chapter-0001.intent.md", "# Chapter 1 intent\n\nLoad the first clue.\n")

    response = client.post("/book-import/catalog", json={"source_path": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_path"] == str(tmp_path)
    assert payload["sections"][0]["section_id"] == "source_docs"
    assert payload["sections"][1]["section_id"] == "source_state"
    assert payload["sections"][2]["section_id"] == "runtime_chapters"
    assert payload["sections"][0]["items"][0]["filename"] == "author_intent.md"
    assert payload["sections"][2]["items"][0]["title"] == "Chapter 1"


def test_book_import_catalog_recognizes_extra_text_materials(tmp_path: Path):
    _write(tmp_path / "volume_outline.md", "VOLUME: A hidden ledger drives the plot.\n")
    _write(tmp_path / "current_focus.md", "FOCUS: Open with the first clue.\n")
    _write(tmp_path / "author_intent.md", "INTENT: Keep the opening grounded.\n")
    _write(tmp_path / "notes.txt", "Director note: keep the witness hidden.\n")
    _write(tmp_path / "sidecar.yaml", "theme: noir\n")
    _write(tmp_path / "manifest.json", '{"chapter": 1, "status": "draft"}')

    response = client.post("/book-import/catalog", json={"source_path": str(tmp_path)})

    assert response.status_code == 200
    payload = response.json()
    filenames = [item["filename"] for section in payload["sections"] for item in section["items"]]
    assert "notes.txt" in filenames
    assert "sidecar.yaml" in filenames
    assert "manifest.json" in filenames
