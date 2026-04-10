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


def test_book_import_bootstrap_rejects_file_path(tmp_path: Path):
    file_path = tmp_path / "not_a_dir"
    _write(file_path, "just a file")

    response = client.post("/book-import/bootstrap", json={"source_path": str(file_path)})
    assert response.status_code == 404
    detail = response.json().get("detail", "")
    assert "source_path_not_found" in detail
