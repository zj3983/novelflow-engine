"""Tests for the role-specific context builders.

The director and writer see different views over the same project.
The director reads the structural context (volume, outline,
continuity ledger, plot threads, foreshadowing, concise relevant
character cards) so it can decide *what* happens next. The writer
reads the operational context (approved director artifact, the
previous chapter tail, the full cards for characters and entities
in scope, scene world rules, selected craft modules) so it can
decide *how* to render the chapter. Neither view leaks material
that does not belong to the role.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.story_core.agents.contracts import DirectorArtifact
from packages.story_core.context.director_context import build_director_context
from packages.story_core.context.writer_context import build_writer_context


# --- Project fixture --------------------------------------------------------


def _write(project: Path, relpath: str, payload: dict) -> None:
    path = project / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _build_sample_project(project: Path) -> None:
    """Build a tiny but complete project so both contexts can be tested.

    Layout (under ``.story-system``):

    * ``outline.json`` — book-level outline (multiple chapters, multiple volumes)
    * ``volume.json`` — current volume (chapter range and theme)
    * ``world-rules.json`` — general world rules + scene-tagged rules
    * ``characters/<id>.json`` — four characters (two active, one minor, one retired)
    * ``entities/<id>.json`` — active entity (location)
    * ``entities/retired/<id>.json`` — retired entity
    * ``inventory.json`` — current inventory snapshot
    * ``foreshadowing.json`` — list of unresolved foreshadowing
    * ``chapters/0006.json`` — previous chapter (summary + tail)
    * ``chapters/0007.json`` — target chapter outline stub
    * ``reviews/0006.json`` — review history for previous chapter
    * ``craft-modules/<id>.json`` — two craft modules, one enabled
    """
    book_outline = {
        "schema_version": "outline/v1",
        "title": "测试书",
        "volumes": [
            {
                "id": "vol-1",
                "title": "第一卷",
                "chapter_range": [1, 5],
                "summary": "主角入门。",
            },
            {
                "id": "vol-2",
                "title": "第二卷",
                "chapter_range": [6, 10],
                "summary": "主角下山历练。",
            },
        ],
        "chapters": [
            {"number": 1, "title": "第一章", "summary": "入门"},
            {"number": 2, "title": "第二章", "summary": "受戒"},
            {"number": 3, "title": "第三章", "summary": "得法"},
            {"number": 4, "title": "第四章", "summary": "出关"},
            {"number": 5, "title": "第五章", "summary": "下山"},
            {"number": 6, "title": "第六章", "summary": "入林遇妖"},
            {"number": 7, "title": "第七章", "summary": "主角应对第一波妖物"},
            {"number": 8, "title": "第八章", "summary": "退守驿站"},
        ],
    }
    _write(project, "outline.json", book_outline)

    _write(
        project,
        "volume.json",
        {
            "schema_version": "volume/v1",
            "id": "vol-2",
            "title": "第二卷",
            "chapter_range": [6, 10],
            "summary": "主角下山历练。",
        },
    )

    _write(
        project,
        "world-rules.json",
        {
            "schema_version": "world-rules/v1",
            "global": ["时间倒流不可逆。", "灵力以丹田为核心。"],
            "by_scene": {
                "妖林": ["妖物受月相影响。", "林中有旧神龛。"],
                "驿站": ["驿兵不听令于宗门。"],
            },
        },
    )

    _write(
        project,
        "characters/lin-zhao.json",
        {
            "id": "char-lin-zhao",
            "name": "林照",
            "role": "主角",
            "location": "妖林",
            "current_state": "刚下山，体力未满",
            "lifecycle": "active",
            "summary": "入门三年的少年剑客，主修灵剑。",
            "behavioral_notes": "习惯先问再答，忌空话。",
            "relationships": [{"name": "周执事", "type": "师徒"}],
            "knowledge_boundary": ["不知妖林深处有旧神龛"],
        },
    )
    _write(
        project,
        "characters/zhou-zhishi.json",
        {
            "id": "char-zhou-zhishi",
            "name": "周执事",
            "role": "师父",
            "location": "宗门",
            "current_state": "闭关",
            "lifecycle": "active",
            "summary": "宗门执事，主角师父。",
            "behavioral_notes": "话少而准。",
            "relationships": [{"name": "林照", "type": "师徒"}],
            "knowledge_boundary": ["知晓旧神龛"],
        },
    )
    _write(
        project,
        "characters/luo-shen.json",
        {
            "id": "char-luo-shen",
            "name": "罗婶",
            "role": "驿兵",
            "location": "驿站",
            "current_state": "值班",
            "lifecycle": "active",
            "summary": "驿站守卫，负责登记进出。",
            "behavioral_notes": "记性好，爱盘问。",
            "relationships": [],
            "knowledge_boundary": ["熟悉驿站周边妖物出没规律"],
        },
    )
    _write(
        project,
        "characters/old-farmer.json",
        {
            "id": "char-old-farmer",
            "name": "老农",
            "role": "过客",
            "location": "山下",
            "current_state": "种田",
            "lifecycle": "retired",
            "summary": "第一章出现的过客，不再活跃。",
            "behavioral_notes": "无。",
            "relationships": [],
            "knowledge_boundary": [],
        },
    )

    _write(
        project,
        "entities/yao-lin.json",
        {
            "id": "loc-yao-lin",
            "kind": "location",
            "name": "妖林",
            "lifecycle": "active",
            "summary": "山下妖物出没的密林，月圆时最危险。",
            "extensions": {"scene_rules": ["妖物受月相影响。", "林中有旧神龛。"]},
        },
    )
    _write(
        project,
        "entities/retired/old-temple.json",
        {
            "id": "loc-old-temple",
            "kind": "location",
            "name": "旧神龛",
            "lifecycle": "retired",
            "summary": "已被废弃，下章不再使用。",
        },
    )

    _write(
        project,
        "inventory.json",
        {
            "schema_version": "inventory/v1",
            "items": [
                {"id": "sword-lingjian", "name": "灵剑", "owner": "林照"},
                {"id": "token-luo", "name": "路引", "owner": "林照"},
            ],
        },
    )

    _write(
        project,
        "foreshadowing.json",
        {
            "schema_version": "foreshadowing/v1",
            "unresolved": [
                {"id": "fs-1", "text": "旧神龛的来历", "planted_chapter": 5},
                {"id": "fs-2", "text": "周执事的旧伤", "planted_chapter": 4},
            ],
        },
    )

    _write(
        project,
        "chapters/0006.json",
        {
            "schema_version": "chapter/v1",
            "number": 6,
            "title": "入林遇妖",
            "summary": "入林遇妖：主角进入妖林，遇到第一只妖物，险胜但受伤。",
            "tail": "林照按住左肩上的伤口，靠在一棵老槐后喘息。",
            "continuity_ledger": [
                {"id": "fact-1", "subject": "林照", "field": "left_shoulder", "value": "抓伤"},
            ],
        },
    )

    _write(
        project,
        "chapters/0007.json",
        {
            "schema_version": "chapter/v1",
            "number": 7,
            "title": "林照应对第一波妖物",
            "outline": "主角需要在天黑前离开妖林深处。",
        },
    )

    _write(
        project,
        "reviews/0006.json",
        {
            "schema_version": "review/v1",
            "chapter_number": 6,
            "issues": ["节奏偏快", "对话可以更克制"],
        },
    )

    _write(
        project,
        "craft-modules/dialogue-natural.json",
        {
            "id": "dialogue-natural",
            "purpose": "dialogue",
            "stages": ["writer"],
            "priority": 50,
            "max_chars": 800,
            "enabled_by_default": True,
            "content": "对话先回应，再表态。",
        },
    )
    _write(
        project,
        "craft-modules/exposition-marker.json",
        {
            "id": "exposition-marker",
            "purpose": "exposition",
            "stages": ["writer"],
            "priority": 40,
            "max_chars": 600,
            "enabled_by_default": False,
            "content": "避免说明性段落。",
        },
    )


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    project = tmp_path / "story"
    project.mkdir()
    (project / ".story-system").mkdir()
    _build_sample_project(project / ".story-system")
    return project


# --- Director context ------------------------------------------------------


def test_director_context_contains_volume_and_outline(sample_project: Path) -> None:
    ctx = build_director_context(
        project=sample_project,
        chapter_number=7,
        reader=None,
    )
    assert ctx.chapter_number == 7
    assert ctx.volume["id"] == "vol-2"
    assert ctx.volume["chapter_range"] == [6, 10]
    # Nearby chapter outline covers chapter 7 (and the surrounding 2).
    outline_numbers = [entry["number"] for entry in ctx.nearby_outline]
    assert 7 in outline_numbers
    assert 6 in outline_numbers
    assert 8 in outline_numbers
    # Whole book outline should not be inlined.
    assert ctx.book_outline_summary == "测试书"


def test_director_context_includes_previous_summary_and_ledger(sample_project: Path) -> None:
    ctx = build_director_context(
        project=sample_project,
        chapter_number=7,
        reader=None,
    )
    assert "入林遇妖" in ctx.previous_chapter_summary
    assert any(item["subject"] == "林照" for item in ctx.continuity_ledger)


def test_director_context_includes_unresolved_foreshadowing(sample_project: Path) -> None:
    ctx = build_director_context(
        project=sample_project,
        chapter_number=7,
        reader=None,
    )
    planted = {item["id"] for item in ctx.foreshadowing}
    assert "fs-1" in planted
    assert "fs-2" in planted


def test_director_context_does_not_include_craft_modules(sample_project: Path) -> None:
    ctx = build_director_context(
        project=sample_project,
        chapter_number=7,
        reader=None,
    )
    # The director decides *what* happens; it should not see the
    # writer's craft module text. Persisted bodies of craft modules
    # leak if they're inlined here.
    dumped = ctx.model_dump_json()
    assert "对话先回应" not in dumped
    assert "避免说明性段落" not in dumped


def test_director_context_character_cards_are_concise(sample_project: Path) -> None:
    ctx = build_director_context(
        project=sample_project,
        chapter_number=7,
        reader=None,
    )
    # Only the active characters that the chapter actually needs
    # show up. The retired 老农 is dropped; the only relevant
    # active characters for a 妖林 chapter are 林照, 周执事 (mentor
    # who set up the mission), and 驿兵 罗婶 (next destination).
    names = {card["name"] for card in ctx.character_cards}
    assert "林照" in names
    assert "周执事" in names
    assert "老农" not in names
    # Concise cards expose identity + role + state but not the
    # full behavioral notes; the writer reads those.
    sample = next(card for card in ctx.character_cards if card["name"] == "林照")
    for key in ("id", "name", "role", "location", "current_state", "lifecycle"):
        assert key in sample
    assert "behavioral_notes" not in sample


# --- Writer context --------------------------------------------------------


def _make_director_artifact(sample_project: Path) -> DirectorArtifact:
    return DirectorArtifact.model_validate(
        {
            "schema_version": "director-artifact/v1",
            "chapter_number": 7,
            "chapter_goal": "天黑前离开妖林深处并到达驿站",
            "opening_state": "林照左肩受伤，靠在老槐后喘息。",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "妖林",
                    "action": "主角起身继续前进",
                    "result": "发现旧神龛的线索",
                },
                {
                    "order": 2,
                    "location": "驿站",
                    "action": "主角决定向驿站求援",
                    "result": "带着伤口抵达驿站",
                },
            ],
            "ending_state": "主角进入驿站，由罗婶接应。",
            "entity_requirements": [
                {"kind": "character", "name": "林照"},
                {"kind": "character", "name": "周执事"},
                {"kind": "character", "name": "罗婶"},
                {"kind": "location", "name": "妖林"},
            ],
        }
    )


def test_writer_context_includes_director_artifact(sample_project: Path) -> None:
    artifact = _make_director_artifact(sample_project)
    ctx = build_writer_context(
        project=sample_project,
        chapter_number=7,
        director_artifact=artifact,
        reader=None,
    )
    assert ctx.director_artifact.chapter_number == 7
    assert ctx.director_artifact.chapter_goal.startswith("天黑前")


def test_writer_context_includes_previous_tail_and_full_character_cards(
    sample_project: Path,
) -> None:
    artifact = _make_director_artifact(sample_project)
    ctx = build_writer_context(
        project=sample_project,
        chapter_number=7,
        director_artifact=artifact,
        reader=None,
    )
    assert "林照按住左肩" in ctx.previous_tail
    names = {card["name"] for card in ctx.character_cards}
    assert names == {"林照", "周执事", "罗婶"}
    # Full character cards carry behavioral notes, knowledge
    # boundary, and relationships — not just the director's
    # concise summary.
    for card in ctx.character_cards:
        assert "behavioral_notes" in card
        assert "knowledge_boundary" in card
        assert "relationships" in card


def test_writer_context_includes_scene_world_rules(sample_project: Path) -> None:
    artifact = _make_director_artifact(sample_project)
    ctx = build_writer_context(
        project=sample_project,
        chapter_number=7,
        director_artifact=artifact,
        reader=None,
    )
    # 妖林 rules are referenced by the director's scene_beats; the
    # 驿站 rules come from the 2nd beat (主角决定向驿站求援).
    flattened_rules = " ".join(ctx.world_rules)
    assert "妖物受月相影响" in flattened_rules
    assert "林中有旧神龛" in flattened_rules
    assert "驿兵不听令于宗门" in flattened_rules


def test_writer_context_includes_active_entity_cards(sample_project: Path) -> None:
    artifact = _make_director_artifact(sample_project)
    ctx = build_writer_context(
        project=sample_project,
        chapter_number=7,
        director_artifact=artifact,
        reader=None,
    )
    entity_names = {card["name"] for card in ctx.entity_cards}
    assert "妖林" in entity_names
    # The retired 旧神龛 entity must not leak into the writer view.
    assert "旧神龛" not in entity_names


def test_writer_context_includes_only_enabled_craft_modules(sample_project: Path) -> None:
    artifact = _make_director_artifact(sample_project)
    ctx = build_writer_context(
        project=sample_project,
        chapter_number=7,
        director_artifact=artifact,
        reader=None,
    )
    module_ids = {module["id"] for module in ctx.craft_modules}
    # ``exposition-marker`` is ``enabled_by_default=False`` and the
    # project hasn't opted in, so it must be excluded.
    assert "dialogue-natural" in module_ids
    assert "exposition-marker" not in module_ids


def test_writer_context_excludes_book_outline_and_unrelated_cards(
    sample_project: Path,
) -> None:
    artifact = _make_director_artifact(sample_project)
    ctx = build_writer_context(
        project=sample_project,
        chapter_number=7,
        director_artifact=artifact,
        reader=None,
    )
    # The writer's view must not contain the full book outline.
    assert ctx.book_outline is None
    # The retired 老农 must not appear in the writer view either.
    names = {card["name"] for card in ctx.character_cards}
    assert "老农" not in names
    # And raw review history (with subjective issues) must not
    # leak into the writer view.
    dumped = ctx.model_dump_json()
    assert "节奏偏快" not in dumped
    assert "对话可以更克制" not in dumped
