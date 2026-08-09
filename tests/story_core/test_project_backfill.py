from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.project_backfill import (
    ChapterEvidence,
    ProjectBackfillPatch,
    ProjectEvidenceIndex,
    build_backfill_patch,
    build_evidence_index,
    chapter_hashes,
)


def _write_canonical_chapter(
    project_root: Path,
    chapter_number: int,
    *,
    title: str,
    body_bytes: bytes,
    metadata: dict[str, object] | None = None,
) -> None:
    markdown_path = project_root / "chapters" / f"{chapter_number:04d}-{title}.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_bytes(body_bytes)

    payload: dict[str, object] = {
        "schema_version": "chapter/v2",
        "chapter_number": chapter_number,
        "chapter_title": title,
        "body_path": markdown_path.relative_to(project_root).as_posix(),
        "body_sha256": hashlib.sha256(body_bytes).hexdigest(),
    }
    payload.update(metadata or {})
    chapter_path = project_root / ".story-system" / "chapters" / f"{chapter_number:04d}.json"
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    chapter_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _chapter_files(project_root: Path) -> dict[str, bytes]:
    paths = [
        *(project_root / ".story-system" / "chapters").glob("*.json"),
        *(project_root / "chapters").glob("*.md"),
    ]
    return {
        path.relative_to(project_root).as_posix(): path.read_bytes()
        for path in sorted(paths)
    }


def test_build_evidence_index_reads_three_complete_chapters_without_mutation(tmp_path: Path) -> None:
    for chapter_number in range(1, 4):
        _write_canonical_chapter(
            tmp_path,
            chapter_number,
            title=f"第{chapter_number}章",
            body_bytes=f"第{chapter_number}章正文。\r\n第二行。".encode(),
            metadata={"chapter_summary": {"summary": f"第{chapter_number}章摘要"}},
        )
    before = _chapter_files(tmp_path)

    index = build_evidence_index(tmp_path)

    assert isinstance(index, ProjectEvidenceIndex)
    assert [item.chapter_number for item in index.chapters] == [1, 2, 3]
    assert [item.title for item in index.chapters] == ["第1章", "第2章", "第3章"]
    assert [item.summary for item in index.chapters] == [
        "第1章摘要",
        "第2章摘要",
        "第3章摘要",
    ]
    assert all(isinstance(item, ChapterEvidence) and item.body and item.body_hash for item in index.chapters)
    assert _chapter_files(tmp_path) == before


def test_build_evidence_index_reads_optional_structured_fields(tmp_path: Path) -> None:
    _write_canonical_chapter(
        tmp_path,
        1,
        title="落锁",
        body_bytes="林修关上店门。".encode(),
        metadata={
            "chapter_summary": {
                "summary": "林修保住了维修铺。",
                "character_updates": [{"name": "林修", "change": "决定追查旧账"}],
                "foreshadowing": [{"text": "柜台下的铜钥匙", "status": "open"}],
            },
            "updated_story": {
                "timeline": [{"chapter_number": 1, "summary": "维修铺暂时停业"}],
            },
        },
    )

    chapter = build_evidence_index(tmp_path).chapters[0]

    assert chapter.timeline == ({"chapter_number": 1, "summary": "维修铺暂时停业"},)
    assert chapter.character_updates == ({"name": "林修", "change": "决定追查旧账"},)
    assert chapter.foreshadowing == ({"text": "柜台下的铜钥匙", "status": "open"},)


def test_build_evidence_index_sorts_chapters_numerically(tmp_path: Path) -> None:
    for chapter_number in (10, 2, 1):
        _write_canonical_chapter(
            tmp_path,
            chapter_number,
            title=str(chapter_number),
            body_bytes=f"正文{chapter_number}".encode(),
        )

    assert [item.chapter_number for item in build_evidence_index(tmp_path).chapters] == [1, 2, 10]


def test_missing_optional_fields_are_empty_collections(tmp_path: Path) -> None:
    _write_canonical_chapter(tmp_path, 1, title="空白", body_bytes="只有正文。".encode())

    chapter = build_evidence_index(tmp_path).chapters[0]

    assert chapter.summary == ""
    assert chapter.timeline == ()
    assert chapter.character_updates == ()
    assert chapter.foreshadowing == ()


def test_chapter_hashes_use_raw_canonical_markdown_bytes(tmp_path: Path) -> None:
    raw_body = b"first line\r\nsecond line\r\n"
    _write_canonical_chapter(tmp_path, 1, title="Raw", body_bytes=raw_body)

    assert chapter_hashes(tmp_path) == {1: hashlib.sha256(raw_body).hexdigest()}


def test_evidence_data_structures_are_immutable(tmp_path: Path) -> None:
    _write_canonical_chapter(tmp_path, 1, title="冻结", body_bytes="正文。".encode())
    index = build_evidence_index(tmp_path)

    with pytest.raises(FrozenInstanceError):
        index.project_root = Path("elsewhere")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        index.chapters[0].title = "被修改"  # type: ignore[misc]
    assert isinstance(index.chapters, tuple)


def test_hybrid_import_hashes_discovered_markdown_and_detects_changes(tmp_path: Path) -> None:
    store = FileProjectStore(tmp_path)
    title = "第1章 混合导入"
    markdown_path = store.chapter_store.paths(1, title)["markdown"]
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    original = "Markdown才是现有章节文件。\r\n".encode()
    markdown_path.write_bytes(original)
    chapter_path = tmp_path / ".story-system" / "chapters" / "0001.json"
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    chapter_path.write_text(
        json.dumps(
            {
                "schema_version": "imported-continuation-chapter/v1",
                "chapter_number": 1,
                "chapter_title": title,
                "body": "JSON中的导入正文。",
                "chapter_summary": {"summary": "导入摘要", "facts": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first = build_evidence_index(tmp_path).chapters[0]
    assert first.body_hash == hashlib.sha256(original).hexdigest()

    changed = "Markdown被人工修改。\r\n".encode()
    markdown_path.write_bytes(changed)
    second = build_evidence_index(tmp_path).chapters[0]
    assert second.body_hash == hashlib.sha256(changed).hexdigest()
    assert second.body_hash != first.body_hash


def test_legacy_json_only_chapter_hashes_stable_utf8_body(tmp_path: Path) -> None:
    body = "只有旧版JSON正文。"
    chapter_path = tmp_path / ".story-system" / "chapters" / "0001.json"
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    chapter_path.write_text(
        json.dumps(
            {
                "schema_version": "chapter/v1",
                "chapter_number": 1,
                "chapter_title": "旧章",
                "body": body,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert chapter_hashes(tmp_path) == {
        1: hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    assert build_evidence_index(tmp_path).chapters[0].body_hash


def test_character_evidence_uses_confirmed_facts_and_actual_snapshot_not_planned_moves(
    tmp_path: Path,
) -> None:
    _write_canonical_chapter(
        tmp_path,
        147,
        title="污染暗语",
        body_bytes="林修压住阵心裂口。".encode(),
        metadata={
            "character_moves": [
                {"name": "林修", "action": "计划中尚未发生的动作"},
            ],
            "chapter_summary": {
                "summary": "林修暂时稳住阵心。",
                "facts": ["林修的右手已经失去知觉。"],
            },
            "updated_story": {
                "characters": [
                    {
                        "name": "林修",
                        "role": "protagonist",
                        "current_state": {"injury": "右手失去知觉"},
                    }
                ]
            },
        },
    )

    evidence = build_evidence_index(tmp_path).chapters[0]
    plain = evidence.to_dict()
    serialized = json.dumps(plain, ensure_ascii=False)

    assert "计划中尚未发生的动作" not in serialized
    assert "林修的右手已经失去知觉" in serialized
    assert "右手失去知觉" in serialized
    assert plain["character_updates"][0]["source"] == "updated_story.characters"


def test_character_snapshot_evidence_only_keeps_changes_from_adjacent_snapshot(tmp_path: Path) -> None:
    shared = {"name": "林修", "current_state": {"realm": "筑基"}}
    _write_canonical_chapter(
        tmp_path,
        1,
        title="前章",
        body_bytes="前章正文。".encode(),
        metadata={"updated_story": {"characters": [shared]}},
    )
    _write_canonical_chapter(
        tmp_path,
        2,
        title="后章",
        body_bytes="后章正文。".encode(),
        metadata={
            "updated_story": {
                "characters": [
                    shared,
                    {"name": "沈墨璃", "current_state": {"trust": "提高"}},
                ]
            }
        },
    )

    first, second = build_evidence_index(tmp_path).chapters

    assert [item["name"] for item in first.character_updates] == ["林修"]
    assert [item["name"] for item in second.character_updates] == ["沈墨璃"]


def test_nested_evidence_is_immutable_and_can_be_converted_to_plain_dict(tmp_path: Path) -> None:
    _write_canonical_chapter(
        tmp_path,
        1,
        title="冻结证据",
        body_bytes="正文。".encode(),
        metadata={
            "updated_story": {
                "characters": [
                    {"name": "林修", "current_state": {"injury": "未愈"}},
                ]
            }
        },
    )
    index = build_evidence_index(tmp_path)
    character = index.chapters[0].character_updates[0]

    with pytest.raises(TypeError):
        character["name"] = "改名"  # type: ignore[index]
    with pytest.raises(TypeError):
        character["character"]["current_state"]["injury"] = "痊愈"  # type: ignore[index]

    plain = index.to_dict()
    plain["chapters"][0]["character_updates"][0]["character"]["current_state"]["injury"] = "痊愈"
    assert json.loads(json.dumps(plain, ensure_ascii=False))["chapters"][0]["chapter_number"] == 1


def test_confirmed_fact_records_all_named_characters_deterministically(tmp_path: Path) -> None:
    _write_canonical_chapter(
        tmp_path,
        1,
        title="共同事实",
        body_bytes="正文。".encode(),
        metadata={
            "chapter_summary": {"facts": ["沈墨璃替林修守住出口。"]},
            "updated_story": {
                "characters": [
                    {"name": "林修"},
                    {"name": "沈墨璃"},
                ]
            },
        },
    )

    facts = [
        item
        for item in build_evidence_index(tmp_path).chapters[0].to_dict()["character_updates"]
        if item["source"] == "chapter_summary.facts"
    ]

    assert facts == [
        {
            "source": "chapter_summary.facts",
            "name": "林修",
            "names": ["林修", "沈墨璃"],
            "fact": "沈墨璃替林修守住出口。",
        }
    ]


def _backfill_evidence() -> ProjectEvidenceIndex:
    chapters = []
    for chapter_number in range(1, 148):
        character_updates = ()
        foreshadowing = ()
        if chapter_number == 1:
            character_updates = (
                {
                    "source": "updated_story.characters",
                    "name": "林修",
                    "character": {
                        "name": "林修",
                        "current_state": {"injury": "旧伤未愈"},
                    },
                },
            )
        if chapter_number == 12:
            foreshadowing = ({"text": "柜台下的铜钥匙", "status": "open"},)
        if chapter_number == 147:
            character_updates = (
                {
                    "source": "updated_story.characters",
                    "name": "林修",
                    "character": {
                        "name": "林修",
                        "realm": "炼气三层",
                        "current_state": {"injury": "右手失去知觉"},
                    },
                },
            )
            foreshadowing = ({"text": "柜台下的铜钥匙", "status": "reinforced"},)
        chapters.append(
            ChapterEvidence(
                chapter_number=chapter_number,
                title=f"第{chapter_number}章",
                body_hash=f"hash-{chapter_number}",
                body="林修继续经营维修铺。" if chapter_number in {1, 147} else "正文。",
                summary="",
                timeline=(),
                character_updates=character_updates,
                foreshadowing=foreshadowing,
            )
        )
    return ProjectEvidenceIndex(project_root=Path("example"), chapters=tuple(chapters))


def _generated_backfill() -> dict[str, object]:
    return {
        "story_core": {"title": "万界维修工", "logline": "林修修复万界器物。"},
        "master_outline": {"overall": {}, "arcs": [], "chapters": []},
        "world_blueprint": {"setting": "诸界相连的维修世界"},
        "characters": [
            {
                "name": "林修",
                "aliases": ["林师傅"],
                "entity_type": "character",
                "first_appearance_chapter": 9,
                "realm": "炼气九层",
                "current_state": {"injury": "已经痊愈"},
            }
        ],
        "relationships": [],
        "foreshadowing": [],
        "continuity": {"current_chapter": 3, "timeline": []},
    }


def _direct_character_evidence() -> ProjectEvidenceIndex:
    chapters = []
    for chapter in _backfill_evidence().chapters:
        updates = ()
        if chapter.chapter_number == 12:
            updates = (
                {
                    "name": "林修",
                    "current_state": {"injury": "旧伤未愈"},
                    "realm": "炼气二层",
                },
            )
        if chapter.chapter_number == 147:
            updates = (
                {
                    "name": "林修",
                    "current_state": {"injury": "右手失去知觉"},
                    "realm": "炼气三层",
                },
            )
        chapters.append(replace(chapter, character_updates=updates))
    return ProjectEvidenceIndex(project_root=Path("direct"), chapters=tuple(chapters))


def test_build_backfill_patch_has_exactly_seven_sections_and_forces_current_chapter() -> None:
    patch = build_backfill_patch(_backfill_evidence(), _generated_backfill(), "玄幻")

    assert isinstance(patch, ProjectBackfillPatch)
    assert list(patch.to_dict()) == [
        "story_core",
        "master_outline",
        "world_blueprint",
        "characters",
        "relationships",
        "foreshadowing",
        "continuity",
    ]
    assert patch.to_dict()["continuity"]["current_chapter"] == 147


def test_build_backfill_patch_requires_all_sections() -> None:
    generated = _generated_backfill()
    generated.pop("relationships")

    with pytest.raises(ValueError, match="missing_backfill_section:relationships"):
        build_backfill_patch(_backfill_evidence(), generated, "玄幻")


def test_non_game_genre_recursively_strips_game_only_fields_but_keeps_equipment() -> None:
    generated = _generated_backfill()
    generated["world_blueprint"] = {
        "game_panel": {"level": 8},
        "nested": {
            "game_state": {"hp": 10},
            "inventory_slots": 20,
            "inventory": ["玄铁"],
            "equipment": {"weapon": "断剑"},
        },
    }
    generated["characters"][0]["player_state"] = {"level": 8}  # type: ignore[index]

    serialized = json.dumps(
        build_backfill_patch(
            _backfill_evidence(),
            generated,
            {"genre": "玄幻", "plugin": "xuanhuan"},
        ).to_dict(),
        ensure_ascii=False,
    )

    assert "game_panel" not in serialized
    assert "game_state" not in serialized
    assert "player_state" not in serialized
    assert "inventory_slots" not in serialized
    assert '"inventory": ["玄铁"]' in serialized
    assert '"equipment": {"weapon": "断剑"}' in serialized


def test_character_aliases_merge_to_canonical_name_and_evidence_wins_recent_state() -> None:
    generated = _generated_backfill()
    generated["characters"].append(  # type: ignore[union-attr]
        {
            "name": "林师傅",
            "aliases": ["阿修"],
            "kind": "person",
            "occupation": "维修工",
            "first_appearance_chapter": 6,
        }
    )

    characters = build_backfill_patch(_backfill_evidence(), generated, "玄幻").to_dict()["characters"]

    assert list(characters) == ["林修"]
    assert characters["林修"]["aliases"] == ["林师傅", "阿修"]
    assert characters["林修"]["occupation"] == "维修工"
    assert characters["林修"]["first_appearance_chapter"] == 1
    assert characters["林修"]["realm"] == "炼气三层"
    assert characters["林修"]["current_state"] == {"injury": "右手失去知觉"}


def test_character_first_appearance_strictly_uses_evidence_not_earlier_model_claim() -> None:
    generated = _generated_backfill()
    generated["characters"][0]["first_appearance_chapter"] = 2  # type: ignore[index]

    characters = build_backfill_patch(
        _direct_character_evidence(),
        generated,
        "玄幻",
    ).to_dict()["characters"]

    assert characters["林修"]["first_appearance_chapter"] == 12


def test_direct_character_evidence_from_latest_chapter_overrides_model_state() -> None:
    characters = build_backfill_patch(
        _direct_character_evidence(),
        _generated_backfill(),
        "玄幻",
    ).to_dict()["characters"]

    assert characters["林修"]["realm"] == "炼气三层"
    assert characters["林修"]["current_state"] == {"injury": "右手失去知觉"}


def test_character_evidence_uses_chapter_numbers_when_index_order_is_reversed() -> None:
    evidence = _direct_character_evidence()
    reversed_evidence = ProjectEvidenceIndex(
        project_root=evidence.project_root,
        chapters=tuple(reversed(evidence.chapters)),
    )

    characters = build_backfill_patch(
        reversed_evidence,
        _generated_backfill(),
        "玄幻",
    ).to_dict()["characters"]

    assert characters["林修"]["first_appearance_chapter"] == 12
    assert characters["林修"]["realm"] == "炼气三层"


def test_build_evidence_index_flows_into_backfill_with_nested_mappingproxy(
    tmp_path: Path,
) -> None:
    _write_canonical_chapter(
        tmp_path,
        1,
        title="维修铺开门",
        body_bytes="林修检查柜台。".encode(),
        metadata={
            "updated_story": {
                "characters": [
                    {
                        "name": "林修",
                        "entity_type": "character",
                        "current_state": {"injury": "右手发麻"},
                    }
                ]
            }
        },
    )
    generated = _generated_backfill()
    generated["characters"][0]["first_appearance_chapter"] = 1  # type: ignore[index]

    patch = build_backfill_patch(build_evidence_index(tmp_path), generated, "玄幻")

    assert patch.to_dict()["characters"]["林修"]["current_state"] == {
        "injury": "右手发麻"
    }


def test_relationship_without_chapter_numbers_keeps_zero_as_unknown() -> None:
    generated = _generated_backfill()
    generated["characters"].append(  # type: ignore[union-attr]
        {"name": "李澄", "entity_type": "character"}
    )
    generated["relationships"] = [
        {"source": "林修", "target": "李澄", "relation_type": "朋友"}
    ]

    relationship = build_backfill_patch(
        _backfill_evidence(), generated, "玄幻"
    ).to_dict()["relationships"][0]

    assert relationship["first_chapter"] == 0
    assert relationship["last_changed_chapter"] == 0


def test_relationship_rejects_negative_chapter_before_normalization() -> None:
    generated = _generated_backfill()
    generated["characters"].append(  # type: ignore[union-attr]
        {"name": "李澄", "entity_type": "character"}
    )
    generated["relationships"] = [
        {
            "source": "林修",
            "target": "李澄",
            "relation_type": "朋友",
            "first_chapter": -1,
        }
    ]

    with pytest.raises(ValueError, match="relationship_chapter_out_of_range"):
        build_backfill_patch(_backfill_evidence(), generated, "玄幻")


def test_character_entity_type_wins_over_merchant_role_and_human_roles_are_kept() -> None:
    generated = _generated_backfill()
    generated["characters"].extend(  # type: ignore[union-attr]
        [
            {"name": "钱掌柜", "entity_type": "character", "role": "merchant"},
            {"name": "周师父", "role": "师父"},
            {"name": "玄门商号", "entity_type": "vendor_entity", "role": "店主"},
        ]
    )

    characters = build_backfill_patch(
        _backfill_evidence(), generated, "玄幻"
    ).to_dict()["characters"]

    assert "钱掌柜" in characters
    assert "周师父" in characters
    assert "玄门商号" not in characters


def test_foreshadowing_evidence_payoff_overrides_model_and_is_order_independent() -> None:
    evidence = _backfill_evidence()
    chapters = []
    for chapter in evidence.chapters:
        entries = chapter.foreshadowing
        if chapter.chapter_number == 147:
            entries = (
                {
                    "text": "柜台下的铜钥匙",
                    "status": "reinforced",
                    "payoff_plan": "在旧账册真相揭晓时回收",
                },
            )
        chapters.append(replace(chapter, foreshadowing=entries))
    reversed_evidence = ProjectEvidenceIndex(
        project_root=evidence.project_root,
        chapters=tuple(reversed(chapters)),
    )
    generated = _generated_backfill()
    generated["foreshadowing"] = [
        {
            "text": "柜台下的铜钥匙",
            "first_chapter": 80,
            "last_touched_chapter": 90,
            "status": "open",
            "payoff_plan": "模型臆造的错误回收方式",
        }
    ]

    entry = build_backfill_patch(
        reversed_evidence, generated, "玄幻"
    ).to_dict()["foreshadowing"][0]

    assert entry["first_chapter"] == 12
    assert entry["last_touched_chapter"] == 147
    assert entry["status"] == "reinforced"
    assert entry["payoff_plan"] == "在旧账册真相揭晓时回收"


def test_canonical_character_name_uses_evidence_then_explicit_name_not_array_order() -> None:
    generated = _generated_backfill()
    generated["characters"] = [
        {
            "name": "林师傅",
            "aliases": ["林修"],
            "entity_type": "character",
        },
        {"name": "林修", "aliases": ["林师傅"], "entity_type": "character"},
        {"name": "阿澄", "aliases": ["李澄"], "entity_type": "character"},
        {
            "name": "李澄",
            "canonical_name": "李澄",
            "aliases": ["阿澄"],
            "entity_type": "character",
        },
    ]
    generated["relationships"] = [
        {"source": "林师傅", "target": "阿澄", "relation_type": "朋友"}
    ]

    patch = build_backfill_patch(_backfill_evidence(), generated, "玄幻").to_dict()

    assert set(patch["characters"]) == {"林修", "李澄"}
    assert patch["relationships"][0]["source"] == "林修"
    assert patch["relationships"][0]["target"] == "李澄"


def test_non_character_entities_are_not_emitted_as_characters() -> None:
    generated = _generated_backfill()
    generated["characters"].extend(  # type: ignore[union-attr]
        [
            {"name": "白河仓库收购方", "entity_type": "organization", "role": "merchant"},
            {"name": "旧城维修铺", "kind": "location"},
            {"name": "裂纹仙器", "entity_type": "item"},
            {"name": "诸界商会", "entity_type": "组织"},
            {"name": "李澄", "role": "配角"},
        ]
    )

    characters = build_backfill_patch(_backfill_evidence(), generated, "玄幻").to_dict()["characters"]

    assert list(characters) == ["林修", "李澄"]
    assert "诸界商会" not in characters


def test_foreshadowing_uses_evidence_chapters_and_rejects_unseen_out_of_range_entry() -> None:
    generated = _generated_backfill()
    generated["foreshadowing"] = [
        {
            "text": "柜台下的铜钥匙",
            "first_chapter": 90,
            "last_touched_chapter": 100,
            "status": "open",
        }
    ]
    patch = build_backfill_patch(_backfill_evidence(), generated, "玄幻").to_dict()

    assert patch["foreshadowing"][0]["first_chapter"] == 12
    assert patch["foreshadowing"][0]["last_touched_chapter"] == 147

    generated["foreshadowing"] = [
        {
            "text": "正文从未出现的线索",
            "first_chapter": 148,
            "last_touched_chapter": 148,
            "status": "open",
        }
    ]
    with pytest.raises(ValueError, match="foreshadowing_chapter_out_of_range"):
        build_backfill_patch(_backfill_evidence(), generated, "玄幻")


def test_backfill_does_not_mutate_evidence_and_serializes_to_json() -> None:
    evidence = _backfill_evidence()
    before = evidence.to_dict()

    plain = build_backfill_patch(evidence, _generated_backfill(), "玄幻").to_dict()

    assert evidence.to_dict() == before
    assert json.loads(json.dumps(plain, ensure_ascii=False))["continuity"]["current_chapter"] == 147
