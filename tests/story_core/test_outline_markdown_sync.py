# -*- coding: utf-8 -*-
"""outline_markdown_sync 双向同步测试。"""
from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from pathlib import Path

import pytest

from packages.story_core.elastic_outline import validate_outline_for_project
from packages.story_core.outline_markdown_sync import (
    export_outline_to_markdown,
    import_markdown_outline,
    sync_outline_if_stale,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_PROJECT = REPO_ROOT / "data" / "exported-projects" / "p-gou-webgame-restored"


# ---------------------------------------------------------------------------
# 小样本 fixture
# ---------------------------------------------------------------------------

OVERVIEW_SAMPLE = """# 总纲

## 故事一句话
一个小人物逆袭成神的故事。

## 核心主线
- **主线目标**：主角低调发育成神
- **主要阻力**：系统预警与大公会追踪
- **主线三问**（贯穿全书）：
  1. 金手指上限是多少？

## 主角成长线
- **起点状态**：Lv.1 萌新
- **关键跃迁节点**：Lv.10→Lv.30→Lv.MAX
- **终局定位**：唯一神级存在

## 分卷纲要

### 第1卷：起点（第1-2章，Lv.1→5）
- **阶段目标**：验证能力边界
- **核心冲突**：苟活 vs 预警系统
- **卷末高潮**：完美脱身
- **卷末钩子**：解析模式待启动
- **现实线**：账单压力缓解

## 伏笔表
| 伏笔 | 埋设 | 回收 |
|------|------|------|
| 灰种子 | 第1章 | 第6卷 |
"""

VOLUME_SAMPLE = """# 第 1 卷：起点

> 章节范围: 第 1 - 2 章

## 卷摘要
卷摘要内容。

### 第 1 章：开局【已写】
- 目标: 进入游戏
- 阻力: 资金见底
- 代价: 血掉到78
- 时间锚点: 开服第1天 夜
- 章内时间跨度: 约1小时
- 与上章时间差: -（首章）
- 倒计时状态: 无
- 爽点: 验证爽点 - 掉率异常
- Strand: Quest
- 反派层级: 无
- 视角/主角: 苏叶/夜烬
- 关键实体: 灰狼坡
- 本章变化: 确认异常
- 章末未闭合问题: 能不能撑住？
- 钩子: 渴望钩 - 倍率数字

### 第 2 章：市场红线
- 目标: 完成任务
- 阻力: 价格压制
- 代价: 耐久降至4/10
- 时间锚点: 开服第1天 深夜
- 章内时间跨度: 约2小时
- 与上章时间差: 紧接
- 倒计时状态: 无
- 爽点: 精算爽点 - 预判预警
- Strand: Quest
- 反派层级: 无
- 视角/主角: 夜烬
- 关键实体: 交易行
- 本章变化: 确认检测机制
- 章末未闭合问题: 预警何时触发？
- 钩子: 悬念钩 - 触发规模
"""

# 与上面相同，但混入孤立 \r 与 CRLF，模拟真实文件的混合换行。
VOLUME_SAMPLE_MIXED_ENDINGS = VOLUME_SAMPLE.replace(
    "- 目标: 进入游戏\n", "- 目标: 进入游戏\r\n"
).replace("- 阻力: 资金见底\n", "- 阻力: 资金见底\r- 阻力: 资金见底\n", 1).replace(
    "- 阻力: 资金见底\r- 阻力: 资金见底\n- 代价", "- 阻力: 资金见底\r- 代价"
)


def _make_project(tmp_path: Path, *, mixed_endings: bool = False) -> Path:
    root = tmp_path / "novel"
    outline_dir = root / "大纲"
    outline_dir.mkdir(parents=True)
    (outline_dir / "总纲.md").write_text(OVERVIEW_SAMPLE, encoding="utf-8")
    volume_text = VOLUME_SAMPLE_MIXED_ENDINGS if mixed_endings else VOLUME_SAMPLE
    (outline_dir / "第1卷-详细大纲.md").write_text(volume_text, encoding="utf-8", newline="")
    # 纯人类规划文档：不参与同步，绝不改动。
    (outline_dir / "第1卷-节拍表.md").write_text("# 节拍表\n人类专属\n", encoding="utf-8")
    (outline_dir / "爽点规划.md").write_text("# 爽点规划\n人类专属\n", encoding="utf-8")
    webnovel = root / ".webnovel"
    webnovel.mkdir()
    (webnovel / "state.json").write_text(
        json.dumps({"current_chapter": 0}, ensure_ascii=False), encoding="utf-8"
    )
    return root


# ---------------------------------------------------------------------------
# 真实项目解析（只读 fixture）
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not REAL_PROJECT.is_dir(), reason="真实项目目录不存在")
def test_import_real_project_markdown() -> None:
    outline = import_markdown_outline(REAL_PROJECT)
    assert outline is not None
    assert outline["schema_version"] == "project-outline/v1"
    assert len(outline["chapters"]) == 14
    assert len(outline["arcs"]) == 8
    assert outline["arcs"][0]["title"] == "新手区争先"
    assert outline["arcs"][-1]["title"] == "神域重启"

    overall = outline["overall"]
    for key in ("story", "protagonist_goal", "main_conflict", "growth_path", "ending_direction"):
        assert str(overall.get(key) or "").strip(), key

    arc_ids = [arc["id"] for arc in outline["arcs"]]
    assert arc_ids == [
        "vol-1",
        "vol-2",
        "vol-3",
        "vol-4",
        "vol-5",
        "vol-6",
        "vol-7",
        "vol-8",
    ]
    first_arc = outline["arcs"][0]
    assert first_arc["title"] == "新手区争先"
    assert (first_arc["start_chapter"], first_arc["end_chapter"]) == (1, 50)
    for key in ("goal", "obstacle", "payoff", "reality_line_payoff"):
        assert first_arc[key].strip(), key

    first = outline["chapters"][0]
    assert first["chapter_number"] == 1
    for key in ("title", "goal", "obstacle", "action", "turn", "payoff", "ending_hook"):
        assert str(first.get(key) or "").strip(), key
    assert "苏叶" in first["cast"]
    assert "夜烬" not in first["cast"]

    last = outline["chapters"][-1]
    assert last["chapter_number"] == 14

    validated = validate_outline_for_project(outline, current_chapter=2)
    assert len(validated["chapters"]) == 14


# ---------------------------------------------------------------------------
# round-trip 稳定性
# ---------------------------------------------------------------------------


def test_import_parses_sample_with_mixed_line_endings(tmp_path: Path) -> None:
    root = _make_project(tmp_path, mixed_endings=True)
    outline = import_markdown_outline(root)
    assert outline is not None
    assert len(outline["chapters"]) == 2
    first = outline["chapters"][0]
    assert first["goal"] == "进入游戏"
    assert first["title"] == "开局"
    assert first["cast"] == ["苏叶", "夜烬"]
    arc = outline["arcs"][0]
    assert arc["id"] == "vol-1"
    assert arc["goal"] == "验证能力边界"
    # 未设置同步元数据时按 elastic 默认推导。
    assert outline["overall"]["core_ending_chapter"] == 2
    assert outline["overall"]["extension_ceiling_chapter"] == 2


def test_round_trip_export_then_import_deep_equal(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    json1 = import_markdown_outline(root)
    assert json1 is not None

    result = export_outline_to_markdown(root, json1)
    assert result == "ok"

    json2 = import_markdown_outline(root)
    assert json2 == json1  # 核心正确性要求：deep-equal

    # 再次导出应是完全 no-op（内容不变 → 不重写文件）。
    overview_path = root / "大纲" / "总纲.md"
    volume_path = root / "大纲" / "第1卷-详细大纲.md"
    before = {p: p.read_bytes() for p in (overview_path, volume_path)}
    assert export_outline_to_markdown(root, json2) == "ok"
    for path, content in before.items():
        assert path.read_bytes() == content

    # md-only 字段仍在 md 中。
    volume_text = volume_path.read_text(encoding="utf-8")
    for field in ("代价", "时间锚点", "章内时间跨度", "与上章时间差", "倒计时状态", "Strand", "反派层级", "关键实体", "钩子"):
        assert f"- {field}:" in volume_text
    assert "- 代价: 血掉到78" in volume_text
    assert "渴望钩 - 倍率数字" in volume_text
    overview_text = overview_path.read_text(encoding="utf-8")
    assert "卷末钩子" in overview_text  # md 独有 bullet 保留

    # 无关文件绝不改动。
    assert (root / "大纲" / "第1卷-节拍表.md").read_text(encoding="utf-8") == "# 节拍表\n人类专属\n"
    assert (root / "大纲" / "爽点规划.md").read_text(encoding="utf-8") == "# 爽点规划\n人类专属\n"


def test_long_form_outline_fields_round_trip_through_markdown(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    outline = import_markdown_outline(root)
    assert outline is not None
    outline["overall"].update(
        theme_statement="力量不能代替选择。",
        foreground_story="主角处理眼前冲突并建立自己的位置。",
        background_story="幕后势力借每次冲突推进长期计划。",
        book_objective="主角公开真相并改变旧秩序。",
        ending_image="旧门重新打开，主角把钥匙交给后来者。",
    )
    outline["arcs"][0].update(
        emotional_curve="先压后扬，卷尾留下余震。",
        key_results=["取得立足身份", "赢得关键盟友", "拿到后台线索"],
        hook_plan="本卷留下的旧印记在第三卷回收。",
        irreversible_change="主角公开站队，不能再退回旁观位置。",
    )

    assert export_outline_to_markdown(root, outline) == "ok"
    restored = import_markdown_outline(root)

    assert restored is not None
    assert restored["overall"]["theme_statement"] == "力量不能代替选择。"
    assert restored["overall"]["background_story"].startswith("幕后势力")
    assert restored["arcs"][0]["key_results"] == ["取得立足身份", "赢得关键盟友", "拿到后台线索"]
    assert restored["arcs"][0]["irreversible_change"].startswith("主角公开")


def test_export_preserves_md_only_content_and_unknown_sections(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    json1 = import_markdown_outline(root)
    assert json1 is not None
    export_outline_to_markdown(root, json1)
    overview_text = (root / "大纲" / "总纲.md").read_text(encoding="utf-8")
    # 伏笔表、主线三问等非映射内容原样保留。
    assert "## 伏笔表" in overview_text
    assert "| 灰种子 | 第1章 | 第6卷 |" in overview_text
    assert "主线三问" in overview_text
    # 同步元数据小节被自动维护，保证 overall 全字段 round-trip。
    assert "同步元数据" in overview_text


# ---------------------------------------------------------------------------
# json → md 合并
# ---------------------------------------------------------------------------


def test_export_merges_json_changes_into_markdown(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    json1 = import_markdown_outline(root)
    assert json1 is not None

    changed = deepcopy(json1)
    changed["chapters"][0]["title"] = "全新的开局标题"
    changed["chapters"][0]["goal"] = "新的目标"
    assert export_outline_to_markdown(root, changed) == "ok"

    volume_text = (root / "大纲" / "第1卷-详细大纲.md").read_text(encoding="utf-8")
    assert "### 第 1 章：全新的开局标题" in volume_text
    assert "- 目标: 新的目标" in volume_text
    # json 不拥有的字段保持原值。
    assert "- 代价: 血掉到78" in volume_text
    assert "- 钩子: 渴望钩 - 倍率数字" in volume_text
    assert "- Strand: Quest" in volume_text
    # 未修改的第 2 章原样保留。
    assert "### 第 2 章：市场红线" in volume_text

    # 合并后的 md 再 import，应与 changed 一致（round-trip 仍然稳定）。
    json2 = import_markdown_outline(root)
    assert json2 == changed


def test_export_updates_overview_overall_fields(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    json1 = import_markdown_outline(root)
    assert json1 is not None

    changed = deepcopy(json1)
    changed["overall"]["protagonist_goal"] = "改写后的主线目标"
    changed["arcs"][0]["goal"] = "改写后的阶段目标"
    assert export_outline_to_markdown(root, changed) == "ok"

    overview_text = (root / "大纲" / "总纲.md").read_text(encoding="utf-8")
    assert "- **主线目标**：改写后的主线目标" in overview_text
    assert "- **阶段目标**：改写后的阶段目标" in overview_text
    # 其他 bullet 与章节范围保持不变。
    assert "- **主要阻力**：系统预警与大公会追踪" in overview_text
    assert "（第1-2章，Lv.1→5）" in overview_text
    assert import_markdown_outline(root) == changed


# ---------------------------------------------------------------------------
# sync_outline_if_stale 方向判断
# ---------------------------------------------------------------------------


def _write_json(root: Path, outline: dict) -> Path:
    json_path = root / ".webnovel" / "outline.json"
    json_path.write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path


def test_sync_skips_without_markdown_or_json(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert sync_outline_if_stale(empty).startswith("skipped")

    root = _make_project(tmp_path / "case2")
    assert sync_outline_if_stale(root) == "skipped:no-outline-json"


def test_sync_imports_when_markdown_newer(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    outline = import_markdown_outline(root)
    assert outline is not None
    json_path = _write_json(root, outline)
    # 让 md 明确比 json 新。
    past = time.time() - 100
    os.utime(json_path, (past, past))
    now = time.time()
    for md in (root / "大纲").glob("*.md"):
        os.utime(md, (now, now))

    action = sync_outline_if_stale(root)
    assert action.startswith("imported:"), action
    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved == outline
    # 平手策略：紧接着再 sync 应该是 no-op，不会立刻 export 回写。
    assert sync_outline_if_stale(root) == "no-op:already-in-sync"
    # 节拍表等无关文件全程未被触碰。
    assert (root / "大纲" / "第1卷-节拍表.md").read_text(encoding="utf-8") == "# 节拍表\n人类专属\n"


def test_sync_preserves_visible_attribute_allocation_plan_when_markdown_is_newer(
    tmp_path: Path,
) -> None:
    root = _make_project(tmp_path)
    outline = import_markdown_outline(root)
    assert outline is not None
    outline["chapters"][0]["level_target"] = "Lv.2"
    outline["chapters"][0]["attribute_allocation_decision"] = {
        "mode": "allocate",
        "allocations": {"智力": 5},
        "remaining": 0,
        "reason": "强化基础火球术",
    }
    json_path = _write_json(root, outline)

    assert export_outline_to_markdown(root, outline) == "ok"
    volume_path = root / "大纲" / "第1卷-详细大纲.md"
    volume_text = volume_path.read_text(encoding="utf-8")
    assert "- 等级目标: Lv.2" in volume_text
    assert "- 属性点安排: 分配：智力+5；剩余：0；原因：强化基础火球术" in volume_text

    past = time.time() - 100
    os.utime(json_path, (past, past))
    now = time.time()
    for md in (root / "大纲").glob("*.md"):
        os.utime(md, (now, now))

    assert sync_outline_if_stale(root).startswith("imported:")
    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved["chapters"][0]["level_target"] == "Lv.2"
    assert saved["chapters"][0]["attribute_allocation_decision"] == {
        "mode": "allocate",
        "allocations": {"智力": 5},
        "remaining": 0,
        "reason": "强化基础火球术",
    }


def test_import_rejects_malformed_attribute_allocation_plan(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    volume_path = root / "大纲" / "第1卷-详细大纲.md"
    volume_text = volume_path.read_text(encoding="utf-8")
    volume_path.write_text(
        volume_text.replace("- 目标:", "- 属性点安排: 智力随便加\n- 目标:", 1),
        encoding="utf-8",
    )

    assert import_markdown_outline(root) is None


def test_attribute_allocation_reason_preserves_full_width_semicolons(
    tmp_path: Path,
) -> None:
    root = _make_project(tmp_path)
    outline = import_markdown_outline(root)
    assert outline is not None
    outline["chapters"][0]["attribute_allocation_decision"] = {
        "mode": "carry",
        "allocations": {},
        "remaining": 5,
        "reason": "等转职后再决定；现在不急着分配",
    }

    assert export_outline_to_markdown(root, outline) == "ok"
    imported = import_markdown_outline(root)
    assert imported is not None
    assert imported["chapters"][0]["attribute_allocation_decision"]["reason"] == (
        "等转职后再决定；现在不急着分配"
    )


def test_integer_level_target_round_trips_as_integer(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    outline = import_markdown_outline(root)
    assert outline is not None
    outline["chapters"][0]["level_target"] = 2

    assert export_outline_to_markdown(root, outline) == "ok"
    imported = import_markdown_outline(root)
    assert imported is not None
    assert imported["chapters"][0]["level_target"] == 2


def test_json_export_removes_malformed_markdown_attribute_allocation(
    tmp_path: Path,
) -> None:
    root = _make_project(tmp_path)
    outline = import_markdown_outline(root)
    assert outline is not None
    volume_path = root / "大纲" / "第1卷-详细大纲.md"
    volume_text = volume_path.read_text(encoding="utf-8")
    volume_path.write_text(
        volume_text.replace("- 目标:", "- 属性点安排: 智力随便加\n- 目标:", 1),
        encoding="utf-8",
    )

    assert export_outline_to_markdown(root, outline) == "ok"
    assert "属性点安排: 智力随便加" not in volume_path.read_text(encoding="utf-8")
    assert import_markdown_outline(root) == outline


def test_sync_exports_when_json_newer(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    outline = import_markdown_outline(root)
    assert outline is not None
    changed = deepcopy(outline)
    changed["chapters"][1]["title"] = "第二章新标题"
    json_path = _write_json(root, changed)
    past = time.time() - 100
    for md in (root / "大纲").glob("*.md"):
        os.utime(md, (past, past))

    action = sync_outline_if_stale(root)
    assert action.startswith("exported:"), action
    volume_text = (root / "大纲" / "第1卷-详细大纲.md").read_text(encoding="utf-8")
    assert "### 第 2 章：第二章新标题" in volume_text
    assert sync_outline_if_stale(root) == "no-op:already-in-sync"


def test_sync_import_validation_failure_keeps_json(tmp_path: Path) -> None:
    root = _make_project(tmp_path)
    outline = import_markdown_outline(root)
    assert outline is not None
    json_path = _write_json(root, outline)
    past = time.time() - 100
    os.utime(json_path, (past, past))

    # 破坏 md：删掉分卷纲要（arcs 为空 → import 返回 None）。
    overview_path = root / "大纲" / "总纲.md"
    text = overview_path.read_text(encoding="utf-8")
    overview_path.write_text(text[: text.index("## 分卷纲要")], encoding="utf-8")
    now = time.time()
    for md in (root / "大纲").glob("*.md"):
        os.utime(md, (now, now))

    before = json_path.read_bytes()
    action = sync_outline_if_stale(root)
    assert action.startswith("error:"), action
    assert json_path.read_bytes() == before  # json 未被动过
