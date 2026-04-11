from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app


client = TestClient(app)


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


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
    assert "FOCUS" in draft["outline"]
    assert draft["characters"] == ["Lin Yue", "Su Wan"]


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
