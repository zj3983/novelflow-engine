"""Tests for Round 8 Task 5b: writing_packet shape changes.

The packet no longer carries ``chapter_direction_options`` (the three-card
"next chapter direction" UI is being replaced by a rolling outline). It
gains:

* ``next_chapter_outline``: the rolling chapter for the target, or the
  legacy outline chapter if no rolling chapter exists, or None.
* ``rolling_fill``: a status object describing the rolling fill state
  for the target chapter. ``present`` when an outline exists,
  ``missing`` when one is needed, ``failed`` when the last fill failed.
* ``next_chapter_outline_source``: ``"rolling"`` | ``"legacy"`` | ``None``
  so the frontend can show the right badge ("✎ 人工" vs generated).

Backward compatibility: old clients that still read
``chapter_direction_options`` from the packet should see an empty
object, not a 500.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.story_core.file_project_store import FileProjectStore


def _make_minimal_file_project(
    root: Path,
    *,
    state: dict | None = None,
    project: dict | None = None,
) -> FileProjectStore:
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir()
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": project or {"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps(
            project or {"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(
            state or {"story_id": "s-file", "current_chapter": 0, "world_facts": []},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return FileProjectStore(root)


def _write_rolling_outline(root: Path, chapters: list[dict]) -> None:
    target = root / ".story-system" / "outline-generation" / "rolling_outline.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {"schema_version": "rolling-outline/v1", "chapters": chapters},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _stub_rolling_chapter(number: int, *, source: str = "generated") -> dict:
    return {
        "chapter_number": number,
        "title": f"第{number}章 标题",
        "chapter_goal": f"第{number}章目标",
        "core_conflict": f"第{number}章冲突",
        "cast": [{"name": "夜烬", "role": "protagonist"}],
        "scenes": [
            {"location": "断崖", "action": "夜烬跃下", "result": "拾到新技能"},
            {"location": "山洞", "action": "对话NPC", "result": "解锁新任务"},
        ],
        "gain": "习得新技能",
        "cost": "损失一格血量",
        "foreshadowing": [f"第{number}章伏笔"],
        "hook": f"第{number}章钩子",
        "state_delta": {"hp": -1, "skill": "+1"},
        "source": source,
    }


def test_writing_packet_does_not_emit_chapter_direction_options(tmp_path: Path) -> None:
    """The legacy three-card direction picker is gone.

    Backward-compat: the field is still on the packet, but its ``options``
    list is always empty (the new "rolling outline" replaces the picker).
    """
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "断香炉",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
            "character_profiles": [],
        },
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": [], "characters": []},
    )
    packet = store.writing_packet()
    options = packet.get("chapter_direction_options")
    if options is not None:
        assert options.get("options") == []


def test_writing_packet_emits_rolling_fill_status_present_when_rolling_outline_exists(
    tmp_path: Path,
) -> None:
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "断香炉",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
            "character_profiles": [],
        },
        state={"story_id": "s-file", "current_chapter": 1, "world_facts": [], "characters": []},
    )
    # No rolling file → next chapter is 2, no outline
    _write_rolling_outline(tmp_path / "novel", [_stub_rolling_chapter(2)])
    packet = store.writing_packet(chapter_number=2)
    rolling_fill = packet.get("rolling_fill")
    assert rolling_fill is not None
    assert rolling_fill["status"] == "present"
    assert rolling_fill["source"] == "rolling"
    assert rolling_fill["chapter_number"] == 2


def test_writing_packet_emits_rolling_fill_status_missing_when_no_outline(
    tmp_path: Path,
) -> None:
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "断香炉",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
            "character_profiles": [],
        },
        state={"story_id": "s-file", "current_chapter": 1, "world_facts": [], "characters": []},
    )
    packet = store.writing_packet(chapter_number=2)
    rolling_fill = packet.get("rolling_fill")
    assert rolling_fill is not None
    assert rolling_fill["status"] == "missing"
    assert rolling_fill["chapter_number"] == 2
    assert packet.get("next_chapter_outline") is None
    assert packet.get("next_chapter_outline_source") is None


def test_writing_packet_emits_next_chapter_outline_from_rolling_file(tmp_path: Path) -> None:
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "断香炉",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
            "character_profiles": [],
        },
        state={"story_id": "s-file", "current_chapter": 1, "world_facts": [], "characters": []},
    )
    _write_rolling_outline(tmp_path / "novel", [_stub_rolling_chapter(2)])
    packet = store.writing_packet(chapter_number=2)
    outline = packet.get("next_chapter_outline")
    assert outline is not None
    assert outline["chapter_number"] == 2
    assert outline["title"] == "第2章 标题"
    assert packet.get("next_chapter_outline_source") == "rolling"
    assert packet["outline_context"]["chapter"]["chapter_goal"] == "第2章目标"
    assert packet["scene_cards"][0]["source"] == "rolling_outline.chapter"


def test_generation_state_uses_rolling_outline_for_target_chapter(tmp_path: Path) -> None:
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "断香炉",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
            "character_profiles": [],
        },
        state={
            "story_id": "s-file",
            "current_chapter": 1,
            "world_facts": [],
            "characters": [],
        },
    )
    _write_rolling_outline(tmp_path / "novel", [_stub_rolling_chapter(2)])

    payload = store._story_state_payload_for_direction(
        store.state(), store.project(), 2
    )

    chapter = payload["outline_context"]["chapter"]
    assert chapter["chapter_goal"] == "第2章目标"
    assert chapter["cast"] == ["夜烬"]


def test_writing_packet_falls_back_to_legacy_outline_when_no_rolling_chapter(
    tmp_path: Path,
) -> None:
    """When the rolling file is missing the target chapter, fall back to
    the legacy outline (if it has one). This preserves the v1 behavior
    for projects that haven't been migrated to the rolling format yet.
    """
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "断香炉",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
            "character_profiles": [],
        },
        state={"story_id": "s-file", "current_chapter": 1, "world_facts": [], "characters": []},
    )
    # Write a legacy outline with chapter 2
    (tmp_path / "novel" / ".webnovel" / "outline.json").write_text(
        json.dumps(
            {
                "schema_version": "project-outline/v1",
                "overall": {"story": "x"},
                "arcs": [],
                "chapters": [
                    {
                        "chapter_number": 2,
                        "title": "legacy 2",
                        "goal": "legacy 2 目标",
                        "payoff": "legacy 2 payoff",
                        "ending_hook": "legacy 2 hook",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    packet = store.writing_packet(chapter_number=2)
    outline = packet.get("next_chapter_outline")
    assert outline is not None
    assert outline["title"] == "legacy 2"
    assert packet.get("next_chapter_outline_source") == "legacy"


def test_writing_packet_legacy_outline_chapter_does_not_set_rolling_fill_present(
    tmp_path: Path,
) -> None:
    """A legacy-only chapter should not be reported as "present" in the
    rolling-fill status. The frontend can still display the legacy
    outline body, but the rolling_fill field should reflect that this
    is NOT a rolling outline (status=legacy).
    """
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "断香炉",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
            "character_profiles": [],
        },
        state={"story_id": "s-file", "current_chapter": 1, "world_facts": [], "characters": []},
    )
    (tmp_path / "novel" / ".webnovel" / "outline.json").write_text(
        json.dumps(
            {
                "schema_version": "project-outline/v1",
                "overall": {"story": "x"},
                "arcs": [],
                "chapters": [{"chapter_number": 2, "title": "legacy 2"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    packet = store.writing_packet(chapter_number=2)
    rolling_fill = packet.get("rolling_fill")
    assert rolling_fill is not None
    assert rolling_fill["status"] == "legacy"
    assert rolling_fill["source"] == "legacy"
