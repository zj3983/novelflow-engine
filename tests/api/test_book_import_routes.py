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
    invalid = Path("Z:/does/not/exist")
    if invalid.exists():
        invalid = Path("ZZ:/does/not/exist")

    response = client.post("/book-import/scan", json={"source_path": str(invalid)})
    assert response.status_code in {400, 404}

    detail = response.json().get("detail", "")
    assert isinstance(detail, str)
    assert "source_path" in detail or "not_found" in detail or "exist" in detail

