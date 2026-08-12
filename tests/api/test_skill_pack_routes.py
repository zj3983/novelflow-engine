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


def test_commercial_shuangwen_pack_list_reports_missing_required_modules(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = tmp_path / "registry"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(registry))
    source = tmp_path / "commercial-shuangwen"
    (source / "skills" / "plot-engine").mkdir(parents=True)
    (source / "manifest.json").write_text(
        json.dumps(
            {
                "skill_id": "commercial-shuangwen",
                "name": "Commercial Shuangwen",
                "version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )
    (source / "SKILL.md").write_text("# Commercial Shuangwen\n", encoding="utf-8")
    (source / "skills" / "plot-engine" / "SKILL.md").write_text(
        "---\nname: plot-engine\npurposes: outline\n---\n\n# Plot Engine\n",
        encoding="utf-8",
    )
    assert client.post(
        "/skill-packs/import",
        json={"source_path": str(source)},
    ).status_code == 200

    response = client.get("/skill-packs")

    assert response.status_code == 200
    status = response.json()[0]["narrative_enhancement_status"]
    assert status["status"] == "incomplete"
    assert status["reason"] == "missing_required_modules"
    assert status["missing_module_ids"] == [
        "chapter-sop",
        "genre-examples",
        "review-checklist",
        "writer-execution",
    ]


def test_commercial_shuangwen_pack_list_reports_module_purpose_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = tmp_path / "registry"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(registry))
    source = tmp_path / "commercial-shuangwen"
    (source / "manifest.json").parent.mkdir(parents=True)
    (source / "manifest.json").write_text(
        json.dumps({"skill_id": "commercial-shuangwen", "name": "Commercial Shuangwen"}),
        encoding="utf-8",
    )
    (source / "SKILL.md").write_text("# Commercial Shuangwen\n", encoding="utf-8")
    purposes = {
        "plot-engine": "outline",
        "chapter-sop": "chapter_plan",
        "writer-execution": "writer,reviewer",
        "review-checklist": "reviewer",
        "genre-examples": "outline,chapter_plan,writer",
    }
    for module_id, module_purposes in purposes.items():
        module_root = source / "skills" / module_id
        module_root.mkdir(parents=True)
        (module_root / "SKILL.md").write_text(
            f"---\nname: {module_id}\npurposes: {module_purposes}\n---\n\n# {module_id}\n",
            encoding="utf-8",
        )
    assert client.post(
        "/skill-packs/import",
        json={"source_path": str(source)},
    ).status_code == 200

    response = client.get("/skill-packs")

    assert response.status_code == 200
    status = response.json()[0]["narrative_enhancement_status"]
    assert status["status"] == "incomplete"
    assert status["reason"] == "invalid_module_purposes"
    assert status["missing_module_ids"] == []
    assert status["purpose_mismatches"] == [
        {
            "module_id": "writer-execution",
            "required_purposes": ["writer"],
            "actual_purposes": ["reviewer", "writer"],
            "missing_purposes": [],
            "unexpected_purposes": ["reviewer"],
        }
    ]


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


def test_skill_pack_delete_uninstalls_pack_and_clears_project_selection(tmp_path: Path, monkeypatch) -> None:
    registry = tmp_path / "registry"
    projects = tmp_path / "projects"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(registry))
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(projects))
    source = tmp_path / "pack"
    source.mkdir()
    (source / "manifest.json").write_text(
        json.dumps({"skill_id": "delete-me", "name": "Delete Me"}), encoding="utf-8"
    )
    (source / "SKILL.md").write_text("# Delete Me\n", encoding="utf-8")
    assert client.post("/skill-packs/import", json={"source_path": str(source)}).status_code == 200

    project_root = projects / "p-one" / ".webnovel"
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps({"enabled_skill_ids": ["delete-me"]}), encoding="utf-8"
    )
    (project_root / "state.json").write_text(
        json.dumps({"enabled_skill_ids": ["delete-me"], "current_chapter": 2}), encoding="utf-8"
    )

    response = client.delete("/skill-packs/delete-me")

    assert response.status_code == 200
    assert response.json()["affected_project_count"] == 1
    assert client.get("/skill-packs/delete-me").status_code == 404
    assert json.loads((project_root / "project.json").read_text(encoding="utf-8"))["enabled_skill_ids"] == []
    assert json.loads((project_root / "state.json").read_text(encoding="utf-8"))["current_chapter"] == 2


def test_skill_module_delete_keeps_pack_and_other_modules(tmp_path: Path, monkeypatch) -> None:
    registry = tmp_path / "registry"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(registry))
    source = tmp_path / "pack"
    (source / "skills" / "writer").mkdir(parents=True)
    (source / "skills" / "dialogue").mkdir(parents=True)
    (source / "manifest.json").write_text(
        json.dumps({"skill_id": "module-delete", "name": "Module Delete"}), encoding="utf-8"
    )
    (source / "SKILL.md").write_text("# Root\n", encoding="utf-8")
    (source / "skills" / "writer" / "SKILL.md").write_text("---\nname: writer\n---\nwriter", encoding="utf-8")
    (source / "skills" / "dialogue" / "SKILL.md").write_text("---\nname: dialogue\n---\ndialogue", encoding="utf-8")
    assert client.post("/skill-packs/import", json={"source_path": str(source)}).status_code == 200

    response = client.delete("/skill-packs/module-delete/modules/writer")

    assert response.status_code == 200
    assert response.json()["module_id"] == "writer"
    detail = client.get("/skill-packs/module-delete").json()
    assert detail["module_count"] == 1
    assert detail["modules"][0]["module_id"] == "dialogue"


def test_skill_root_module_delete_is_rejected(tmp_path: Path, monkeypatch) -> None:
    registry = tmp_path / "registry"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(registry))
    source = tmp_path / "pack"
    source.mkdir()
    (source / "manifest.json").write_text(
        json.dumps({"skill_id": "root-delete", "name": "Root Delete"}), encoding="utf-8"
    )
    (source / "SKILL.md").write_text("# Root\n", encoding="utf-8")
    assert client.post("/skill-packs/import", json={"source_path": str(source)}).status_code == 200

    response = client.delete("/skill-packs/root-delete/modules/root")

    assert response.status_code == 400
    assert response.json()["detail"] == "skill_pack_root_module_cannot_uninstall"
