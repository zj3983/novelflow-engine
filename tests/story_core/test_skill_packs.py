from __future__ import annotations

import json
from pathlib import Path

from packages.story_core.skill_packs import import_skill_pack_from_path, list_skill_packs, skill_pack_prompt_context


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
