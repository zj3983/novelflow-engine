from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import scripts.upgrade_project_power_system as migration
from packages.story_core.power_systems import (
    legacy_power_summary,
    validate_power_system_spec,
)
from packages.story_core.world_blueprint_context import MANAGED_MARKER
from scripts.p_gou_power_system_data import build_power_system_spec
from scripts.upgrade_project_power_system import upgrade_project


CLASSES = ("战士", "法师", "游侠", "盗贼", "牧师", "召唤师")
BRANCHES = {
    "战士": ("守护骑士", "狂战士"),
    "法师": ("元素宗师", "奥术贤者"),
    "游侠": ("神射手", "荒野猎王"),
    "盗贼": ("影刃", "诡术师"),
    "牧师": ("圣愈者", "戒律祭司"),
    "召唤师": ("契约领主", "兽群主宰"),
}
BASE_ATTRIBUTES = {
    "力量": 5,
    "体质": 5,
    "敏捷": 5,
    "智力": 5,
    "精神": 5,
    "感知": 5,
}


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=4) + "\n").replace(
        "\n", "\r\n"
    ).encode("utf-8")


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    root = tmp_path / "p-gou-webgame-restored"
    metadata = root / ".webnovel"
    settings = root / "设定集"
    chapters = root / "chapters"
    outlines = root / "大纲"
    metadata.mkdir(parents=True)
    settings.mkdir()
    chapters.mkdir()
    outlines.mkdir()

    project = {
        "title": "苟在网游里成神",
        "untouched": {"prose": "原样保留", "amount": "售价120金币"},
        "world_blueprint": {
            "premise": "神域映照现实。",
            "power_system": [
                "所有玩家以Lv.1见习者进入神域。",
                "Lv.10正式转职，Lv.30选择分支，Lv.60取得传承。",
            ],
            "unrelated_rule": {"nested": [1, "保持不变"]},
        },
    }
    outline = {
        "schema_version": 1,
        "overall": {
            "growth_path": "Lv.10正式转职→Lv.30职业分支→Lv.60职业传承。",
            "money_rule": "一件装备售价120金币，法术伤害+15%。",
        },
        "arcs": [
            {
                "goal": "夜烬在Lv.10完成正式法系职业，并进入主城。",
                "unchanged": "Lv.10职业进阶需要通关元素回廊。",
            }
        ],
        "chapters": [
            {
                "title": "Lv.20大关卡，属性解锁",
                "goal": "冲刺Lv.20突破，完成第二次职业进阶节点",
                "turn": "智力+8，体质+3，法术伤害+15%",
            },
            {
                "title": "正式法系职业的精算打法重构",
                "goal": "系统重构Lv.10正式法系职业的技能循环",
            },
            {
                "goal": "流霜保持远程弓手路线，并推进猎人专精线索。",
            },
            {
                "chapter_number": 9,
                "title": "技能树试算",
                "description": "首次智力加点决定后续路线。",
                "goal": "Lv.5新增技能点的最优分配；计算当前学徒职业的能力极限",
                "turn": "智力加点比速度加点在现阶段收益高2.3倍",
                "payoff": "技能点全投智力，MP+12，法术伤害+5%",
            },
        ],
    }
    state = {
        "progression_ledger": {
            "protagonist": {
                "level": "Lv.2",
                "exp": "0/240",
                "keep": {"inventory": ["裂纹狼心"]},
                "attribute_point_awards": [
                    {"level": 2, "points": 3, "chapter": 1, "legacy": True},
                    {"level": 3, "points": 5, "chapter": 2},
                ],
                "attribute_allocations": [
                    {
                        "chapter": 1,
                        "allocations": {"智力": 4},
                        "remaining": 1,
                        "legacy": True,
                    },
                    {
                        "chapter": 2,
                        "allocations": {"精神": 5},
                        "remaining": 0,
                        "reason": "后续保留",
                    },
                ],
            },
            "unrelated_ledger": {"preserve": True},
        },
        "characters": [
            {
                "name": "苏叶",
                "role": "protagonist",
                "game_id": "夜烬",
                "game_panel": {
                    "level": "Lv.2",
                    "hp": "66/100",
                    "legacy_panel": "keep",
                },
                "game_state": {
                    "current": {
                        "level": "Lv.2",
                        "mp": "28/60",
                        "legacy_current": "keep",
                    },
                    "recent_changes": [{"chapter": 1, "fact": "原有记录"}],
                },
                "profile": {"keep": True},
            },
            {"name": "流霜", "role": "supporting", "game_panel": {"level": "Lv.2"}},
        ],
        "unrelated_state": {"preserve": [1, 2, 3]},
    }
    (metadata / "project.json").write_bytes(_json_bytes(project))
    (metadata / "outline.json").write_bytes(_json_bytes(outline))
    (metadata / "state.json").write_bytes(_json_bytes(state))
    (settings / "力量体系.md").write_text(
        f"{MANAGED_MARKER}\n\n# 旧力量体系\n", encoding="utf-8"
    )
    (settings / "世界观.md").write_text(
        "# 手写世界观\n\n绝不能覆盖。\n", encoding="utf-8"
    )
    (chapters / "0001.md").write_bytes(
        "\ufeff# 第一章 裂纹狼心\r\n\r\n"
        "灰狼尸体上方亮起白光。【击杀Lv.1灰狼，获得经验100。】【等级提升至Lv.2。】\r\n\r\n"
        "【底层协议校验通过。】\r\n".encode("utf-8")
    )
    (outlines / "第1卷-详细大纲.md").write_bytes(
        (
            "### 第 9 章：技能点精算，学徒的极限\r\n"
            "- 爽点: 智力加点比速度加点在现阶段收益高2.3倍\r\n"
            "- 本章变化: 技能点全投智力，MP+12，法术伤害+5%\r\n"
            "### 第 10 章：下一段\r\n"
            "- 爽点: 这一段必须保持原样。\r\n"
        ).encode("utf-8")
    )
    return root


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def test_migration_payload_builder_delegates_to_extracted_project_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert migration._build_power_system_spec() == build_power_system_spec()
    sentinel = {"sentinel": object()}
    monkeypatch.setattr(migration, "build_power_system_spec", lambda: sentinel)

    assert migration._build_power_system_spec() is sentinel


def test_power_system_builder_locks_complete_payload_content_and_insertion_order() -> None:
    serialized = json.dumps(
        build_power_system_spec(),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    assert len(serialized) == 10045
    assert hashlib.sha256(serialized).hexdigest() == (
        "ab71139269d0fb2ff285fdf41b9ddeecf1d893b1863dadf4d5e80a7f3408c03f"
    )


def test_power_system_builder_configures_free_attribute_allocation() -> None:
    spec = build_power_system_spec()

    assert spec["attribute_allocation"] == {
        "mode": "free",
        "points_per_level": 5,
        "starting_level": 1,
        "base_attributes": BASE_ATTRIBUTES,
        "allow_carry": True,
        "respec_rule": "仅在游戏明确提供洗点机会时重置",
    }


def test_upgrade_migrates_complete_system_and_preserves_unrelated_data(
    project_dir: Path,
) -> None:
    project_path = project_dir / ".webnovel" / "project.json"
    outline_path = project_dir / ".webnovel" / "outline.json"
    state_path = project_dir / ".webnovel" / "state.json"
    chapter_path = project_dir / "chapters" / "0001.md"
    detail_path = project_dir / "大纲" / "第1卷-详细大纲.md"
    world_path = project_dir / "设定集" / "世界观.md"
    original_project = _load(project_path)
    original_outline = _load(outline_path)
    original_project_bytes = project_path.read_bytes()
    original_outline_bytes = outline_path.read_bytes()
    original_state = _load(state_path)
    original_world = world_path.read_bytes()

    result = upgrade_project(project_dir)

    assert result["changed"] is True
    assert result["valid"] is True
    assert Path(result["backup_path"]).parent == project_dir / ".webnovel" / "backups"
    assert "project.json: power system upgraded" in result["changes"]
    assert "outline.json: contradictory progression wording updated" in result["changes"]
    assert "设定集/力量体系.md: refreshed" in result["changes"]

    migrated_project = _load(project_path)
    migrated_outline = _load(outline_path)
    blueprint = migrated_project["world_blueprint"]
    spec = validate_power_system_spec(
        blueprint["power_system_spec"], novel_type_id="game_webnovel"
    )

    assert migrated_project["untouched"] == original_project["untouched"]
    assert blueprint["premise"] == original_project["world_blueprint"]["premise"]
    assert blueprint["unrelated_rule"] == original_project["world_blueprint"]["unrelated_rule"]
    assert blueprint["power_system"] == legacy_power_summary(spec)
    assert tuple(path["name"] for path in spec["paths"]) == CLASSES
    assert {path["name"]: tuple(path["branches"]) for path in spec["paths"]} == BRANCHES
    assert tuple(stage["level"] for stage in spec["stages"]) == (1, 10, 20, 30, 60)
    assert tuple(stage["name"] for stage in spec["stages"]) == (
        "见习者",
        "正式职业",
        "职业专精",
        "进阶分支",
        "传承职业",
    )
    assert all(
        path[field]
        for path in spec["paths"]
        for field in (
            "role",
            "core_attributes",
            "core_resource",
            "weapons",
            "armor",
            "skill_categories",
            "combat_loop",
            "strengths",
            "weaknesses",
            "transfer_task",
            "advancement",
        )
    )
    mage = next(path for path in spec["paths"] if path["name"] == "法师")
    mage_text = json.dumps(mage, ensure_ascii=False)
    assert all(
        token in mage_text
        for token in ("元素法师", "元素专精", "元素宗师", "元素权柄传承")
    )
    ranger = next(path for path in spec["paths"] if path["name"] == "游侠")
    ranger_text = json.dumps(ranger, ensure_ascii=False)
    assert "远程弓手" in ranger_text
    assert "猎人专精" in ranger_text
    assert spec["attribute_allocation"]["base_attributes"] == BASE_ATTRIBUTES

    assert "职业专精节点" in migrated_outline["chapters"][0]["goal"]
    assert "第二次职业进阶" not in json.dumps(migrated_outline, ensure_ascii=False)
    assert migrated_outline["arcs"][0]["goal"] == "夜烬在Lv.10完成元素法师，并进入主城。"
    assert migrated_outline["chapters"][1]["title"] == original_outline["chapters"][1]["title"]
    assert migrated_outline["chapters"][1]["goal"] == "系统重构Lv.10元素法师的技能循环"
    assert migrated_outline["overall"]["money_rule"] == original_outline["overall"]["money_rule"]
    assert migrated_outline["arcs"][0]["unchanged"] == original_outline["arcs"][0]["unchanged"]
    assert migrated_outline["chapters"][2] == original_outline["chapters"][2]

    power_markdown = (project_dir / "设定集" / "力量体系.md").read_text(
        encoding="utf-8"
    )
    assert power_markdown.startswith(MANAGED_MARKER)
    assert "元素宗师" in power_markdown
    assert world_path.read_bytes() == original_world

    migrated_state = _load(state_path)
    protagonist = migrated_state["progression_ledger"]["protagonist"]
    assert protagonist["level"] == "Lv.2"
    assert protagonist["attributes"] == {**BASE_ATTRIBUTES, "智力": 10}
    assert protagonist["unallocated_attribute_points"] == 0
    assert protagonist["attribute_point_awards"] == [
        {"level": 3, "points": 5, "chapter": 2},
        {"level": 2, "points": 5, "chapter": 1},
    ]
    assert protagonist["attribute_allocations"] == [
        {
            "chapter": 2,
            "allocations": {"精神": 5},
            "remaining": 0,
            "reason": "后续保留",
        },
        {
            "chapter": 1,
            "allocations": {"智力": 5},
            "remaining": 0,
            "reason": "强化基础火球术",
        },
    ]
    assert protagonist["keep"] == original_state["progression_ledger"]["protagonist"]["keep"]
    assert migrated_state["unrelated_state"] == original_state["unrelated_state"]
    assert migrated_state["progression_ledger"]["unrelated_ledger"] == original_state["progression_ledger"]["unrelated_ledger"]

    protagonist_card = migrated_state["characters"][0]
    for state_slice in (
        protagonist_card["game_panel"],
        protagonist_card["game_state"]["current"],
    ):
        assert state_slice["attributes"] == {**BASE_ATTRIBUTES, "智力": 10}
        assert state_slice["unallocated_attribute_points"] == 0
        assert state_slice["attribute_point_awards"] == protagonist["attribute_point_awards"]
        assert state_slice["attribute_allocations"] == protagonist["attribute_allocations"]
    assert protagonist_card["game_panel"]["legacy_panel"] == "keep"
    assert protagonist_card["game_state"]["current"]["legacy_current"] == "keep"
    assert migrated_state["characters"][1] == original_state["characters"][1]

    chapter = chapter_path.read_text(encoding="utf-8-sig")
    assert chapter.count("【获得5点自由属性。】") == 1
    assert "夜烬现在靠火球术刷怪" in chapter
    assert "把五点全加到了智力上" in chapter
    assert "他点下确认" in chapter
    assert "【智力：5→10。】" in chapter
    assert "【可用属性点：0。】" in chapter
    assert "光标" not in chapter

    chapter_nine = migrated_outline["chapters"][3]
    chapter_nine_text = json.dumps(chapter_nine, ensure_ascii=False)
    assert "后续构筑效率验证" in chapter_nine_text
    assert "属性点已在升级时获得" in chapter_nine_text
    assert "技能点用于技能学习或强化" in chapter_nine_text
    assert "技能点全投智力" not in chapter_nine_text
    assert "智力加点比速度加点" not in chapter_nine_text
    assert "首次智力加点" not in chapter_nine_text
    detailed_outline = detail_path.read_text(encoding="utf-8")
    assert "后续构筑效率验证" in detailed_outline
    assert "属性点已在升级时获得" in detailed_outline
    assert "技能点用于技能学习或强化" in detailed_outline
    assert "技能点全投智力" not in detailed_outline
    assert "智力加点比速度加点" not in detailed_outline
    assert "首次智力加点" not in detailed_outline
    assert "### 第 10 章：下一段\n- 爽点: 这一段必须保持原样。\n" in detailed_outline
    assert detail_path.read_bytes().count(b"\n") == detail_path.read_bytes().count(b"\r\n")
    assert chapter_path.read_bytes().count(b"\n") == chapter_path.read_bytes().count(b"\r\n")

    backup = Path(result["backup_path"])
    assert (backup / "project.json").read_bytes() == original_project_bytes
    assert (backup / "outline.json").read_bytes() == original_outline_bytes
    assert (backup / "state.json").read_bytes() == _json_bytes(original_state)
    assert (backup / "chapters" / "0001.md").read_bytes() == (
        "\ufeff# 第一章 裂纹狼心\r\n\r\n"
        "灰狼尸体上方亮起白光。【击杀Lv.1灰狼，获得经验100。】【等级提升至Lv.2。】\r\n\r\n"
        "【底层协议校验通过。】\r\n".encode("utf-8")
    )
    assert (backup / "大纲" / "第1卷-详细大纲.md").read_bytes() == (
        (
            "### 第 9 章：技能点精算，学徒的极限\r\n"
            "- 爽点: 智力加点比速度加点在现阶段收益高2.3倍\r\n"
            "- 本章变化: 技能点全投智力，MP+12，法术伤害+5%\r\n"
            "### 第 10 章：下一段\r\n"
            "- 爽点: 这一段必须保持原样。\r\n"
        ).encode("utf-8")
    )


def test_upgrade_skips_unmanaged_power_markdown(project_dir: Path) -> None:
    power_path = project_dir / "设定集" / "力量体系.md"
    original = "# 手写力量体系\n\n保留作者判断。\n".encode("utf-8")
    power_path.write_bytes(original)

    result = upgrade_project(project_dir)

    assert power_path.read_bytes() == original
    assert "设定集/力量体系.md: skipped unmanaged" in result["changes"]


def test_upgrade_is_idempotent_and_does_not_create_second_backup(project_dir: Path) -> None:
    first = upgrade_project(project_dir)
    after_first = {
        path: path.read_bytes()
        for path in (
            project_dir / ".webnovel" / "project.json",
            project_dir / ".webnovel" / "outline.json",
            project_dir / ".webnovel" / "state.json",
            project_dir / "设定集" / "力量体系.md",
            project_dir / "chapters" / "0001.md",
            project_dir / "大纲" / "第1卷-详细大纲.md",
        )
    }

    second = upgrade_project(project_dir)

    assert first["changed"] is True
    assert second == {"changed": False, "valid": True, "backup_path": None, "changes": []}
    assert {path: path.read_bytes() for path in after_first} == after_first
    assert len(list((project_dir / ".webnovel" / "backups").glob("power-system-*"))) == 1


def test_check_reports_expected_changes_without_writes_or_backup(project_dir: Path) -> None:
    before = {
        path: path.read_bytes()
        for path in (
            project_dir / ".webnovel" / "project.json",
            project_dir / ".webnovel" / "outline.json",
            project_dir / ".webnovel" / "state.json",
            project_dir / "设定集" / "力量体系.md",
            project_dir / "chapters" / "0001.md",
            project_dir / "大纲" / "第1卷-详细大纲.md",
        )
    }

    result = upgrade_project(project_dir, check=True)

    assert result["changed"] is True
    assert result["valid"] is True
    assert result["backup_path"] is None
    assert result["changes"]
    assert {path: path.read_bytes() for path in before} == before
    assert not (project_dir / ".webnovel" / "backups").exists()


def test_replacement_failure_rolls_back_new_state_chapter_and_detail_targets(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets = (
        project_dir / ".webnovel" / "project.json",
        project_dir / ".webnovel" / "outline.json",
        project_dir / ".webnovel" / "state.json",
        project_dir / "设定集" / "力量体系.md",
        project_dir / "chapters" / "0001.md",
        project_dir / "大纲" / "第1卷-详细大纲.md",
    )
    before = {path: (path.exists(), path.read_bytes()) for path in targets}
    real_replace = migration.os.replace
    writes = 0

    def fail_after_state_write(source: str | Path, destination: str | Path) -> None:
        nonlocal writes
        destination_path = Path(destination)
        if destination_path in targets:
            writes += 1
            if destination_path.name == "0001.md":
                raise OSError("injected chapter replacement failure")
        real_replace(source, destination)

    monkeypatch.setattr(migration.os, "replace", fail_after_state_write)

    result = upgrade_project(project_dir, backup=False)

    assert writes >= 5
    assert result["changed"] is False
    assert result["valid"] is False
    assert "injected chapter replacement failure" in result["changes"][0]
    assert {
        path: (path.exists(), path.read_bytes() if path.exists() else b"")
        for path in targets
    } == before
    assert not list(project_dir.rglob(".*.tmp"))


def test_rejects_wrong_project_directory_before_writes_or_backup(
    project_dir: Path, tmp_path: Path
) -> None:
    wrong_project_dir = tmp_path / "another-project"
    project_dir.rename(wrong_project_dir)
    before = {
        path.relative_to(wrong_project_dir): path.read_bytes()
        for path in wrong_project_dir.rglob("*")
        if path.is_file()
    }

    result = upgrade_project(wrong_project_dir)

    assert result["valid"] is False
    assert result["changed"] is False
    assert result["backup_path"] is None
    assert "p-gou-webgame-restored" in result["changes"][0]
    assert {
        path.relative_to(wrong_project_dir): path.read_bytes()
        for path in wrong_project_dir.rglob("*")
        if path.is_file()
    } == before
    assert not (wrong_project_dir / ".webnovel" / "backups").exists()


def test_check_cli_rejects_wrong_project_directory_without_side_effects(
    project_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wrong_project_dir = tmp_path / "copied-project"
    project_dir.rename(wrong_project_dir)
    project_bytes = (wrong_project_dir / ".webnovel" / "project.json").read_bytes()

    exit_code = migration.main([str(wrong_project_dir), "--check"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code != 0
    assert output["valid"] is False
    assert output["changed"] is False
    assert "p-gou-webgame-restored" in output["changes"][0]
    assert (wrong_project_dir / ".webnovel" / "project.json").read_bytes() == project_bytes
    assert not (wrong_project_dir / ".webnovel" / "backups").exists()


def test_rejects_conflicting_project_id_before_writes_or_backup(
    project_dir: Path,
) -> None:
    project_path = project_dir / ".webnovel" / "project.json"
    project = _load(project_path)
    assert isinstance(project, dict)
    project["project_id"] = "some-other-project"
    project_path.write_bytes(_json_bytes(project))
    before = {
        path.relative_to(project_dir): path.read_bytes()
        for path in project_dir.rglob("*")
        if path.is_file()
    }

    result = upgrade_project(project_dir)

    assert result["valid"] is False
    assert result["changed"] is False
    assert result["backup_path"] is None
    assert "project_id" in result["changes"][0]
    assert "p-gou-webgame-restored" in result["changes"][0]
    assert {
        path.relative_to(project_dir): path.read_bytes()
        for path in project_dir.rglob("*")
        if path.is_file()
    } == before
    assert not (project_dir / ".webnovel" / "backups").exists()


def test_no_backup_option_writes_without_backup(project_dir: Path) -> None:
    result = upgrade_project(project_dir, backup=False)

    assert result["changed"] is True
    assert result["backup_path"] is None
    assert not (project_dir / ".webnovel" / "backups").exists()


def test_outline_without_targeted_conflicts_keeps_exact_bytes(project_dir: Path) -> None:
    outline_path = project_dir / ".webnovel" / "outline.json"
    original = b'{"clean":"Lv.20 completes a specialization trial","amount":"120 gold"}'
    outline_path.write_bytes(original)

    result = upgrade_project(project_dir)

    assert result["valid"] is True
    assert outline_path.read_bytes() == original
    assert not any(change.startswith("outline.json:") for change in result["changes"])


def test_outline_cleanup_only_edits_allowlisted_narrative_fields(project_dir: Path) -> None:
    outline_path = project_dir / ".webnovel" / "outline.json"
    outline = _load(outline_path)
    protected = "Lv.20第二次职业进阶，Lv.10正式法系职业"
    outline.update(
        {
            "author_note": protected,
            "dialogue": protected,
            "quote_excerpt": protected,
            "negative_instruction": f"不要改写：{protected}",
            "world_rule": protected,
            "raw_source": protected,
            "metadata": {"text": protected},
            "beats": [
                "Lv.20第二次职业进阶",
                {"summary": "主角在Lv.10成为正式法系职业"},
            ],
            "key_events": [
                {"description": "Lv.20再次转职被改为既有职业强化"},
            ],
        }
    )
    outline_path.write_bytes(_json_bytes(outline))

    result = upgrade_project(project_dir)
    migrated = _load(outline_path)

    assert result["valid"] is True
    assert migrated["beats"] == [
        "Lv.20职业专精",
        {"summary": "主角在Lv.10成为元素法师"},
    ]
    assert migrated["key_events"][0]["description"] == "Lv.20职业专精被改为既有职业强化"
    for key in (
        "author_note",
        "dialogue",
        "quote_excerpt",
        "negative_instruction",
        "world_rule",
        "raw_source",
    ):
        assert migrated[key] == outline[key]
    assert migrated["metadata"] == outline["metadata"]


def test_replacement_failure_rolls_back_every_target_and_cleans_temps(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets = (
        project_dir / ".webnovel" / "project.json",
        project_dir / ".webnovel" / "outline.json",
        project_dir / ".webnovel" / "state.json",
        project_dir / "设定集" / "力量体系.md",
        project_dir / "chapters" / "0001.md",
        project_dir / "大纲" / "第1卷-详细大纲.md",
    )
    before = {path: (path.exists(), path.read_bytes()) for path in targets}
    real_replace = migration.os.replace
    calls = 0

    def fail_second_replace(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert len(list(project_dir.rglob(".*.tmp"))) == len(targets)
        if calls == 2:
            raise OSError("injected second replacement failure")
        real_replace(source, destination)

    monkeypatch.setattr(migration.os, "replace", fail_second_replace)

    result = upgrade_project(project_dir, backup=False)

    assert calls >= 3
    assert result["changed"] is False
    assert result["valid"] is False
    assert result["backup_path"] is None
    assert "injected second replacement failure" in result["changes"][0]
    assert {
        path: (path.exists(), path.read_bytes() if path.exists() else b"")
        for path in targets
    } == before
    assert not list(project_dir.rglob(".*.tmp"))


def test_commit_and_rollback_failure_reports_persistent_change(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets = (
        project_dir / ".webnovel" / "project.json",
        project_dir / ".webnovel" / "outline.json",
        project_dir / "设定集" / "力量体系.md",
    )
    before = {path: path.read_bytes() for path in targets}
    real_replace = migration.os.replace
    calls = 0

    def fail_commit_and_rollback(source: str | Path, destination: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls in {2, 3}:
            raise OSError(f"injected replacement failure {calls}")
        real_replace(source, destination)

    monkeypatch.setattr(migration.os, "replace", fail_commit_and_rollback)

    result = upgrade_project(project_dir, backup=False)

    assert result["valid"] is False
    assert result["changed"] is True
    assert result["rollback_failed"] is True
    assert result["state"] == "indeterminate"
    assert targets[0].read_bytes() != before[targets[0]]
    assert targets[1].read_bytes() == before[targets[1]]
    assert targets[2].read_bytes() == before[targets[2]]
    assert not list(project_dir.rglob(".*.tmp"))


def test_commit_rollback_and_cleanup_failures_preserve_primary_error(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_replace = migration.os.replace
    real_unlink = Path.unlink
    replace_calls = 0
    locked_temps: set[Path] = set()

    def fail_commit_and_rollback(source: str | Path, destination: str | Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        source_path = Path(source)
        if replace_calls == 2:
            locked_temps.add(source_path)
            raise OSError("PRIMARY COMMIT FAILURE")
        if replace_calls == 3:
            locked_temps.add(source_path)
            raise OSError("ROLLBACK RESTORE FAILURE")
        real_replace(source, destination)

    def fail_locked_cleanup(self: Path, missing_ok: bool = False) -> None:
        if self in locked_temps:
            raise PermissionError("LOCKED TEMP CLEANUP FAILURE")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(migration.os, "replace", fail_commit_and_rollback)
    monkeypatch.setattr(Path, "unlink", fail_locked_cleanup)

    result = upgrade_project(project_dir, backup=False)

    assert result["valid"] is False
    assert result["changed"] is True
    assert result["rollback_failed"] is True
    assert result["cleanup_failed"] is True
    assert result["state"] == "indeterminate"
    assert "PRIMARY COMMIT FAILURE" in result["changes"][0]
    assert "ROLLBACK RESTORE FAILURE" in " ".join(result["rollback_errors"])
    assert "LOCKED TEMP CLEANUP FAILURE" in " ".join(result["cleanup_errors"])
    assert set(map(Path, result["residual_temp_paths"])) == locked_temps
    assert all(path.exists() for path in locked_temps)

    monkeypatch.setattr(Path, "unlink", real_unlink)
    for path in locked_temps:
        path.unlink(missing_ok=True)


def test_cleanup_failure_after_successful_commit_reports_valid_changed_state(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_replace = migration.os.replace
    real_unlink = Path.unlink
    residuals: set[Path] = set()

    def replace_but_leave_residual(source: str | Path, destination: str | Path) -> None:
        source_path = Path(source)
        content = source_path.read_bytes()
        real_replace(source_path, destination)
        source_path.write_bytes(content)
        residuals.add(source_path)

    def fail_residual_cleanup(self: Path, missing_ok: bool = False) -> None:
        if self in residuals:
            raise PermissionError("RESIDUAL TEMP LOCKED")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(migration.os, "replace", replace_but_leave_residual)
    monkeypatch.setattr(Path, "unlink", fail_residual_cleanup)

    result = upgrade_project(project_dir, backup=False)

    assert result["changed"] is True
    assert result["valid"] is True
    assert result["rollback_failed"] is False
    assert result["cleanup_failed"] is True
    assert result["state"] == "changed"
    assert result["residual_temp_paths"]
    assert "RESIDUAL TEMP LOCKED" in " ".join(result["cleanup_errors"])

    monkeypatch.setattr(Path, "unlink", real_unlink)
    for path in residuals:
        path.unlink(missing_ok=True)


def test_cli_returns_nonzero_when_cleanup_failed(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        migration,
        "upgrade_project",
        lambda *args, **kwargs: {
            "changed": True,
            "valid": True,
            "backup_path": None,
            "changes": ["error: cleanup failed"],
            "rollback_failed": False,
            "cleanup_failed": True,
            "state": "changed",
            "rollback_errors": [],
            "cleanup_errors": ["locked"],
            "residual_temp_paths": ["temp"],
        },
    )

    exit_code = migration.main([str(project_dir), "--no-backup"])

    assert exit_code != 0
    assert json.loads(capsys.readouterr().out)["cleanup_failed"] is True


def test_second_backup_write_failure_publishes_no_partial_backup(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_write = migration._write_fsynced_file
    calls = 0

    def fail_second_write(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second backup write failure")
        real_write(path, content)

    monkeypatch.setattr(migration, "_write_fsynced_file", fail_second_write)

    result = upgrade_project(project_dir)

    backups = project_dir / ".webnovel" / "backups"
    assert result["valid"] is False
    assert result["changed"] is False
    assert result["backup_path"] is None
    assert not backups.exists() or not list(backups.iterdir())
    assert not list(project_dir.rglob(".power-system-*.tmp"))


def test_rejects_canonical_file_symlink_escape_before_external_change(
    project_dir: Path, tmp_path: Path
) -> None:
    project_path = project_dir / ".webnovel" / "project.json"
    external = tmp_path / "external-project.json"
    external.write_bytes(project_path.read_bytes())
    project_path.unlink()
    try:
        os.symlink(external, project_path)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlink creation unavailable: {exc}")
    before = external.read_bytes()

    result = upgrade_project(project_dir)

    assert result["valid"] is False
    assert result["changed"] is False
    assert "path_escape: project_json" in result["changes"][0]
    assert external.read_bytes() == before
    assert not (project_dir / ".webnovel" / "backups").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_rejects_settings_junction_escape_before_external_change(
    project_dir: Path, tmp_path: Path
) -> None:
    settings = project_dir / "设定集"
    original_settings = project_dir / "设定集-original"
    external = tmp_path / "external-settings"
    external.mkdir()
    external_power = external / "力量体系.md"
    external_power.write_text(f"{MANAGED_MARKER}\nexternal\n", encoding="utf-8")
    settings.rename(original_settings)
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(settings), str(external)],
        capture_output=True,
        check=False,
    )
    if created.returncode != 0:
        original_settings.rename(settings)
        pytest.skip("junction creation unavailable")
    before = external_power.read_bytes()
    try:
        result = upgrade_project(project_dir)
    finally:
        os.rmdir(settings)
        original_settings.rename(settings)

    assert result["valid"] is False
    assert result["changed"] is False
    assert "path_escape: power_markdown" in result["changes"][0]
    assert external_power.read_bytes() == before
    assert not (project_dir / ".webnovel" / "backups").exists()


def test_malformed_json_is_invalid_and_atomic(project_dir: Path) -> None:
    project_path = project_dir / ".webnovel" / "project.json"
    outline_path = project_dir / ".webnovel" / "outline.json"
    power_path = project_dir / "设定集" / "力量体系.md"
    outline_path.write_bytes(b'{"broken":')
    before = {path: path.read_bytes() for path in (project_path, outline_path, power_path)}

    result = upgrade_project(project_dir)

    assert result["changed"] is False
    assert result["valid"] is False
    assert result["backup_path"] is None
    assert result["changes"] and result["changes"][0].startswith("error:")
    assert {path: path.read_bytes() for path in before} == before
    assert not (project_dir / ".webnovel" / "backups").exists()


def test_cli_emits_json_and_returns_nonzero_for_invalid_project(
    project_dir: Path, tmp_path: Path
) -> None:
    script = (
        Path(__file__).parents[1] / "scripts" / "upgrade_project_power_system.py"
    ).resolve()
    absolute_project_dir = project_dir.resolve()
    valid = subprocess.run(
        [
            sys.executable,
            str(script),
            str(absolute_project_dir),
            "--check",
            "--no-backup",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    invalid = subprocess.run(
        [sys.executable, str(script), str(absolute_project_dir / "missing")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert valid.returncode == 0
    assert json.loads(valid.stdout)["valid"] is True
    assert invalid.returncode != 0
    assert json.loads(invalid.stdout)["valid"] is False


def test_migration_does_not_mutate_spec_between_calls(project_dir: Path) -> None:
    upgrade_project(project_dir)
    first = deepcopy(_load(project_dir / ".webnovel" / "project.json"))

    upgrade_project(project_dir, check=True)

    assert _load(project_dir / ".webnovel" / "project.json") == first
