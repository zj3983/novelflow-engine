from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from packages.story_core import skill_packs
from packages.story_core.skill_packs import (
    extract_skill_instructions,
    import_skill_pack_from_path,
    import_skill_pack_from_zip,
    list_skill_packs,
    resolve_enabled_skill_ids,
    resolve_enabled_skill_module_ids,
    skill_module_key,
    skill_pack_prompt_context,
    uninstall_skill_module,
    uninstall_skill_pack,
)


def _write_pack(root: Path) -> Path:
    pack = root / "openwrite-like"
    (pack / "skills" / "writer").mkdir(parents=True)
    (pack / "manifest.json").write_text(
        json.dumps(
            {
                "skill_id": "plain-webnovel",
                "name": "Plain Webnovel",
                "version": "1.0.0",
                "author": "test",
                "description": "白描网文写作包",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (pack / "SKILL.md").write_text(
        "---\nname: plain-webnovel\ndescription: 根 skill\n---\n\n# Root\n\n按意图路由到子 skill。",
        encoding="utf-8",
    )
    (pack / "skills" / "writer" / "SKILL.md").write_text(
        "---\nname: writer\ndescription: 正文写作\n---\n\n# Writer\n\n对话写完整，动作写清楚。",
        encoding="utf-8",
    )
    (pack / "skills" / "dialogue" / "SKILL.md").parent.mkdir(parents=True)
    (pack / "skills" / "dialogue" / "SKILL.md").write_text(
        "---\nname: dialogue\ndescription: 对话质量\n---\n\n# Dialogue\n\n台词要像真人交换信息。",
        encoding="utf-8",
    )
    return pack


def test_import_openwrite_style_skill_pack(tmp_path: Path) -> None:
    source = _write_pack(tmp_path)
    registry = tmp_path / "registry"

    imported = import_skill_pack_from_path(source, root=registry)

    assert imported.skill_id == "plain-webnovel"
    assert imported.name == "Plain Webnovel"
    assert {module.module_id for module in imported.modules} == {"dialogue", "writer"}
    assert any("writer" in module.purposes for module in imported.modules)
    assert (registry / "plain-webnovel" / "SKILL.md").exists()
    assert [pack.skill_id for pack in list_skill_packs(registry)] == ["plain-webnovel"]


def test_skill_pack_prompt_context_is_trimmed_and_structured(tmp_path: Path, monkeypatch) -> None:
    source = _write_pack(tmp_path)
    registry = tmp_path / "registry"
    import_skill_pack_from_path(source, root=registry)
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(registry))

    context = skill_pack_prompt_context(["plain-webnovel"], purpose="writer")

    assert context[0]["skill_id"] == "plain-webnovel"
    assert "按意图路由" in context[0]["root_skill"]
    assert [module["module_id"] for module in context[0]["modules"]] == ["writer"]
    assert "对话写完整" in context[0]["modules"][0]["content"]

    dialogue_context = skill_pack_prompt_context(["plain-webnovel"], purpose="dialogue")
    assert [module["module_id"] for module in dialogue_context[0]["modules"]] == ["dialogue"]


def test_skill_pack_prompt_context_can_select_one_module_without_root_or_other_modules(
    tmp_path: Path, monkeypatch
) -> None:
    source = _write_pack(tmp_path)
    registry = tmp_path / "registry"
    import_skill_pack_from_path(source, root=registry)
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(registry))

    context = skill_pack_prompt_context(
        ["plain-webnovel"],
        enabled_module_ids=[skill_module_key("plain-webnovel", "writer")],
        purpose="writer",
    )

    assert context[0]["root_skill"] == ""
    assert [module["module_id"] for module in context[0]["modules"]] == ["writer"]
    dialogue_context = skill_pack_prompt_context(
        ["plain-webnovel"],
        enabled_module_ids=[skill_module_key("plain-webnovel", "writer")],
        purpose="dialogue",
    )
    assert dialogue_context == []


def test_skill_context_exposes_complete_actionable_instructions() -> None:
    source = (
        "---\nname: dialogue\n---\n\n"
        "# Dialogue\n\n"
        "## 工作流\n"
        "1. 先明确谁和谁、什么场景以及要达成什么。\n"
        "2. 让对白回应前一句，再说自己的决定。\n"
        "## 示例\n"
        "这段示例不应进入写手规则。\n"
    )

    instructions = extract_skill_instructions(source, limit=200)

    assert "先明确谁和谁" in instructions
    assert "让对白回应前一句" in instructions
    assert "这段示例不应进入写手规则" not in instructions
    assert not instructions.endswith("以")


def test_explicit_empty_module_selection_is_distinct_from_legacy_missing_selection() -> None:
    assert resolve_enabled_skill_module_ids({"enabled_skill_module_ids": []}, {}) == []
    assert resolve_enabled_skill_module_ids({}, {"enabled_skill_module_ids": ["legacy::writer"]}) == ["legacy::writer"]
    assert resolve_enabled_skill_module_ids({}, {}) is None


def test_uninstall_skill_module_removes_only_one_module_and_scrubs_selection(tmp_path: Path) -> None:
    source = _write_pack(tmp_path)
    registry = tmp_path / "registry"
    projects = tmp_path / "projects"
    project_root = projects / "p-one" / ".webnovel"
    project_root.mkdir(parents=True)
    project_payload = {
        "enabled_skill_ids": ["plain-webnovel"],
        "enabled_skill_module_ids": [
            skill_module_key("plain-webnovel", "writer"),
            skill_module_key("plain-webnovel", "dialogue"),
        ],
    }
    (project_root / "project.json").write_text(json.dumps(project_payload), encoding="utf-8")
    (project_root / "state.json").write_text(json.dumps(project_payload), encoding="utf-8")
    import_skill_pack_from_path(source, root=registry)

    result = uninstall_skill_module(
        "plain-webnovel",
        "writer",
        root=registry,
        projects_root=projects,
    )

    assert result["skill_id"] == "plain-webnovel"
    assert result["module_id"] == "writer"
    assert result["affected_project_count"] == 1
    assert (registry / "plain-webnovel" / "SKILL.md").exists()
    assert not (registry / "plain-webnovel" / "skills" / "writer").exists()
    assert (registry / "plain-webnovel" / "skills" / "dialogue").exists()
    saved = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    assert saved["enabled_skill_module_ids"] == [skill_module_key("plain-webnovel", "dialogue")]


def test_uninstall_skill_module_rejects_root_skill(tmp_path: Path) -> None:
    source = _write_pack(tmp_path)
    registry = tmp_path / "registry"
    import_skill_pack_from_path(source, root=registry)

    with pytest.raises(ValueError, match="skill_pack_root_module_cannot_uninstall"):
        uninstall_skill_module("plain-webnovel", "root", root=registry, projects_root=tmp_path / "projects")


def _pack_zip_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("pack/manifest.json", json.dumps({"skill_id": "zip-pack", "name": "Zip Pack"}))
        archive.writestr("pack/SKILL.md", "# Zip Pack\n\n从压缩包导入。")
    return buffer.getvalue()


def test_import_skill_pack_from_zip_rejects_oversized_upload(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skill_packs, "MAX_SKILL_ZIP_BYTES", 8)

    with pytest.raises(ValueError, match="skill_pack_zip_too_large"):
        import_skill_pack_from_zip(_pack_zip_bytes(), root=tmp_path / "registry")


def test_import_skill_pack_from_zip_rejects_uncompressed_bomb(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skill_packs, "MAX_SKILL_ZIP_UNCOMPRESSED_BYTES", 16)

    with pytest.raises(ValueError, match="skill_pack_zip_uncompressed_too_large"):
        import_skill_pack_from_zip(_pack_zip_bytes(), root=tmp_path / "registry")


def test_import_skill_pack_from_zip_rejects_too_many_members(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(skill_packs, "MAX_SKILL_ZIP_MEMBERS", 1)

    with pytest.raises(ValueError, match="skill_pack_zip_too_many_members"):
        import_skill_pack_from_zip(_pack_zip_bytes(), root=tmp_path / "registry")


def test_uninstall_skill_pack_removes_registry_pack_and_scrubs_project_refs(tmp_path: Path, monkeypatch) -> None:
    source = _write_pack(tmp_path)
    registry = tmp_path / "registry"
    projects = tmp_path / "projects"
    project_root = projects / "p-one"
    (project_root / ".webnovel").mkdir(parents=True)
    (project_root / "chapters").mkdir()
    (project_root / "chapters" / "chapter-1.md").write_text("正文仍然存在", encoding="utf-8")
    project_payload = {"title": "测试书", "enabled_skill_ids": ["plain-webnovel", "keep-me"]}
    state_payload = {"current_chapter": 1, "enabled_skill_ids": ["plain-webnovel"]}
    (project_root / ".webnovel" / "project.json").write_text(
        json.dumps(project_payload, ensure_ascii=False), encoding="utf-8"
    )
    (project_root / ".webnovel" / "state.json").write_text(
        json.dumps(state_payload, ensure_ascii=False), encoding="utf-8"
    )
    import_skill_pack_from_path(source, root=registry)

    result = uninstall_skill_pack("plain-webnovel", root=registry, projects_root=projects)

    assert result["skill_id"] == "plain-webnovel"
    assert result["affected_project_count"] == 1
    assert not (registry / "plain-webnovel").exists()
    assert json.loads((project_root / ".webnovel" / "project.json").read_text(encoding="utf-8"))["enabled_skill_ids"] == ["keep-me"]
    assert json.loads((project_root / ".webnovel" / "state.json").read_text(encoding="utf-8"))["enabled_skill_ids"] == []
    assert (project_root / "chapters" / "chapter-1.md").read_text(encoding="utf-8") == "正文仍然存在"


def test_explicit_empty_project_skill_selection_does_not_fallback_to_state() -> None:
    assert resolve_enabled_skill_ids(
        {"enabled_skill_ids": []},
        {"enabled_skill_ids": ["legacy-pack"]},
    ) == []
    assert resolve_enabled_skill_ids(
        {},
        {"enabled_skill_ids": ["legacy-pack"]},
    ) == ["legacy-pack"]
