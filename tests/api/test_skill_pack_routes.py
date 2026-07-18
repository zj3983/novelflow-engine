from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import app


client = TestClient(app)


def test_skill_pack_import_and_list(tmp_path: Path, monkeypatch) -> None:
    registry = tmp_path / "registry"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(registry))
    source = tmp_path / "pack"
    (source / "skills" / "dialogue").mkdir(parents=True)
    (source / "manifest.json").write_text(
        json.dumps({"skill_id": "dialogue-pack", "name": "Dialogue Pack", "version": "1.0.0"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (source / "SKILL.md").write_text("# Dialogue Pack\n", encoding="utf-8")
    (source / "skills" / "dialogue" / "SKILL.md").write_text(
        "---\nname: dialogue\ndescription: 对话\n---\n\n说完整的人话。",
        encoding="utf-8",
    )

    imported = client.post("/skill-packs/import", json={"source_path": str(source)})

    assert imported.status_code == 200
    assert imported.json()["skill_id"] == "dialogue-pack"
    listed = client.get("/skill-packs")
    assert listed.status_code == 200
    assert listed.json()[0]["modules"][0]["module_id"] == "dialogue"


def test_skill_pack_import_rejects_path_outside_allowed_roots(tmp_path: Path, monkeypatch) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("NOVEL_AUTOGROWTH_ALLOWED_FS_ROOTS", str(allowed))
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(tmp_path / "registry"))
    outside = tmp_path / "outside-pack"
    outside.mkdir()
    (outside / "SKILL.md").write_text("# Outside Pack\n", encoding="utf-8")

    response = client.post("/skill-packs/import", json={"source_path": str(outside)})

    assert response.status_code == 403
    assert "path_outside_allowed_roots" in response.json()["detail"]
