from __future__ import annotations

import json
import re
from pathlib import Path

from packages.story_core.skill_packs import (
    extract_skill_instructions,
    get_skill_pack,
    list_skill_packs,
    resolve_enabled_skill_ids,
    skill_pack_prompt_context,
)


PACKS_DIR = Path(__file__).resolve().parents[2] / "data" / "skill-packs"
PACK_DIR = PACKS_DIR / "commercial-shuangwen"
GENRE_MARKERS = {
    "通用": "审核",
    "game_webnovel": "公会",
    "xuanhuan": "石碑",
    "xianxia": "玉简",
    "urban": "保证金",
    "science_fiction": "维修窗",
}
GENRE_CATEGORY_MARKERS = (
    "宏观循环：",
    "章节细纲：",
    "正面反击：",
    "章末钩子正例：",
    "章末钩子反例：",
    "动作替代心理正例：",
    "抽象心理反例：",
)


def _enable_local_packs(monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(PACKS_DIR))


def _joined_instructions(context: list[dict[str, object]]) -> str:
    return "\n".join(
        str(module["instructions"])
        for pack_context in context
        for module in pack_context["modules"]  # type: ignore[index,union-attr]
    )


def _genre_blocks(source: str) -> dict[str, str]:
    headings = list(re.finditer(r"^## \[([^\]]+)\]\s*$", source, flags=re.MULTILINE))
    return {
        match.group(1): source[match.end() : headings[index + 1].start() if index + 1 < len(headings) else None]
        for index, match in enumerate(headings)
    }


def test_commercial_shuangwen_pack_has_exact_stage_modules(monkeypatch) -> None:
    _enable_local_packs(monkeypatch)

    pack = get_skill_pack("commercial-shuangwen")

    assert pack is not None
    assert pack.skill_id == "commercial-shuangwen"
    assert pack.name == "商业爽文推进"
    assert {module.module_id: module.purposes for module in pack.modules} == {
        "chapter-sop": ["chapter_plan"],
        "genre-examples": ["outline", "chapter_plan", "writer"],
        "plot-engine": ["outline"],
        "review-checklist": ["reviewer"],
        "writer-execution": ["writer"],
    }


def test_pack_contract_limits_scope_and_disables_automatic_actions() -> None:
    manifest = json.loads((PACK_DIR / "manifest.json").read_text(encoding="utf-8"))
    root_skill = (PACK_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert manifest["enabled_by_default"] is False
    assert manifest["scope"] == "narrative_method"
    assert manifest["can_invent_canon"] is False
    assert manifest["requests_automatic_revision"] is False
    assert "只提供叙事方法" in root_skill
    assert "不得虚构正典事实" in root_skill
    assert "不得请求自动修订" in root_skill


def test_outline_extraction_keeps_the_concrete_macro_loop(monkeypatch) -> None:
    _enable_local_packs(monkeypatch)

    context = skill_pack_prompt_context(
        ["commercial-shuangwen"],
        purpose="outline",
        include_examples=True,
        genre_id="xuanhuan",
    )
    instructions = _joined_instructions(context)

    assert "设局/需求" in instructions
    assert "降维打击" in instructions
    assert "打压/拉仇恨" in instructions
    assert "震惊与收割" in instructions
    assert "主角与读者已知" in instructions
    assert "对手错误认知" in instructions
    assert "误判如何驱动冲突" in instructions
    assert "纠错与回报" in instructions


def test_plot_engine_structure_outputs_operational_information_gap_fields(monkeypatch) -> None:
    _enable_local_packs(monkeypatch)
    pack = get_skill_pack("commercial-shuangwen")
    assert pack is not None
    plot_engine = next(module for module in pack.modules if module.module_id == "plot-engine")
    structure = plot_engine.content.split("## 结构示例", 1)[1]

    for marker in ("主角与读者已知", "对手错误认知", "误判如何驱动冲突", "纠错与回报"):
        assert marker in structure


def test_xuanhuan_context_keeps_only_general_and_xuanhuan_examples(monkeypatch) -> None:
    _enable_local_packs(monkeypatch)

    context = skill_pack_prompt_context(
        ["commercial-shuangwen"],
        purpose="writer",
        include_examples=True,
        genre_id="xuanhuan",
    )
    instructions = _joined_instructions(context)

    assert "玄幻" in instructions
    assert "石碑" in instructions
    assert "game_webnovel" not in instructions
    assert "网游" not in instructions
    assert "玩家" not in instructions
    assert "副本" not in instructions


def test_every_module_keeps_complete_examples_and_required_sections(monkeypatch) -> None:
    _enable_local_packs(monkeypatch)
    pack = get_skill_pack("commercial-shuangwen")
    assert pack is not None

    for module in pack.modules:
        assert "## 规则" in module.content or "### 规则" in module.content
        assert "## 正例" in module.content or "### 正例" in module.content
        assert "## 反例" in module.content or "### 反例" in module.content
        assert "## 结构示例" in module.content or "### 结构示例" in module.content

    chapter_sop = next(module for module in pack.modules if module.module_id == "chapter-sop")
    instructions = extract_skill_instructions(
        chapter_sop.content,
        limit=5000,
        include_examples=True,
    )
    assert "正例有效，因为" in instructions
    assert "反例失败，因为" in instructions
    assert "担保人" in instructions
    assert "可执行的问题" in instructions
    assert instructions.count("。") >= 10


def test_every_genre_block_contains_all_useful_example_categories() -> None:
    source = (PACK_DIR / "skills" / "genre-examples" / "SKILL.md").read_text(encoding="utf-8")
    blocks = _genre_blocks(source)

    assert set(blocks) == set(GENRE_MARKERS)
    for genre, domain_marker in GENRE_MARKERS.items():
        block = blocks[genre]
        assert domain_marker in block
        for category in GENRE_CATEGORY_MARKERS:
            assert category in block, f"{genre} missing {category}"


def test_genre_category_examples_are_complete_sentences() -> None:
    source = (PACK_DIR / "skills" / "genre-examples" / "SKILL.md").read_text(encoding="utf-8")

    for genre, block in _genre_blocks(source).items():
        category_lines = [
            line.removeprefix("- ").strip()
            for line in block.splitlines()
            if any(line.removeprefix("- ").strip().startswith(marker) for marker in GENRE_CATEGORY_MARKERS)
        ]
        assert len(category_lines) == len(GENRE_CATEGORY_MARKERS), genre
        assert all(line.endswith("。") for line in category_lines), genre
        assert "有效，因为" in block
        assert "失败，因为" in block


def test_installed_pack_is_not_enabled_implicitly(monkeypatch) -> None:
    _enable_local_packs(monkeypatch)

    assert "commercial-shuangwen" in {pack.skill_id for pack in list_skill_packs()}
    assert resolve_enabled_skill_ids({}, {}) == []
    assert skill_pack_prompt_context([], purpose="writer", include_examples=True) == []
