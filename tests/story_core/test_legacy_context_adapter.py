"""Tests for the legacy ``.webnovel/`` project adapter.

The new modular agent migration uses canonical paths under
``.story-system/`` (outline, volume, characters/*.json, etc.).
Real projects still ship data under ``.webnovel/`` so the adapter
translates the legacy shape into the canonical view on the fly.
"""

from __future__ import annotations

import json

from packages.story_core.context.legacy_adapter import (
    legacy_active_characters,
    legacy_enabled_skill_ids,
    legacy_outline_view,
    legacy_previous_chapter,
    legacy_project_view,
    legacy_state_view,
    legacy_volume_view,
)


def _write(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def test_legacy_outline_view_translates_chapter_key_and_composes_summary(tmp_path):
    _write(
        tmp_path / ".webnovel" / "outline.json",
        {
            "schema_version": "project-outline/v1",
            "chapters": [
                {"chapter_number": 1, "title": "初章", "goal": "上山", "obstacle": "雨", "action": "行"},
                {"chapter_number": 2, "title": "次章"},
                {"not_a_chapter": "ignored"},
            ],
            "arcs": [
                {"id": "vol-1", "title": "第一卷", "start_chapter": 1, "end_chapter": 50},
            ],
            "overall": {"story": "概述"},
        },
    )
    view = legacy_outline_view(tmp_path / ".story-system")
    assert view is not None
    chapters = view["chapters"]
    assert len(chapters) == 2
    assert chapters[0]["number"] == 1
    assert chapters[0]["title"] == "初章"
    # ``summary`` composes from title + goal + obstacle + action.
    assert "上山" in chapters[0]["summary"]
    assert "雨" in chapters[0]["summary"]
    # The chapter with only a title still gets a summary string.
    assert chapters[1]["number"] == 2
    assert "次章" in chapters[1]["summary"]


def test_legacy_outline_view_returns_none_when_legacy_file_missing(tmp_path):
    assert legacy_outline_view(tmp_path / ".story-system") is None


def test_legacy_state_view_reads_state_json(tmp_path):
    _write(
        tmp_path / ".webnovel" / "state.json",
        {
            "story_id": "s-1",
            "current_chapter": 3,
            "chapter_summaries": [
                {"chapter_number": 1, "summary": "开场", "next_focus": "上山"},
            ],
        },
    )
    state = legacy_state_view(tmp_path / ".story-system")
    assert state is not None
    assert state["current_chapter"] == 3
    assert state["chapter_summaries"][0]["summary"] == "开场"


def test_legacy_project_view_reads_project_json(tmp_path):
    _write(
        tmp_path / ".webnovel" / "project.json",
        {
            "title": "测试项目",
            "character_profiles": [
                {"name": "林昭", "role": "protagonist"},
            ],
            "enabled_skill_ids": ["craft_modules/dialogue"],
        },
    )
    project = legacy_project_view(tmp_path / ".story-system")
    assert project is not None
    assert project["title"] == "测试项目"
    assert legacy_enabled_skill_ids(tmp_path / ".story-system") == [
        "craft_modules/dialogue"
    ]


def test_legacy_volume_view_picks_arc_for_chapter(tmp_path):
    _write(
        tmp_path / ".webnovel" / "outline.json",
        {
            "chapters": [],
            "arcs": [
                {"id": "vol-1", "title": "第一卷", "start_chapter": 1, "end_chapter": 50},
                {"id": "vol-2", "title": "第二卷", "start_chapter": 51, "end_chapter": 100},
            ],
        },
    )
    view = legacy_volume_view(tmp_path / ".story-system", chapter_number=7)
    assert view is not None
    assert view["id"] == "vol-1"
    assert view["chapter_range"] == [1, 50]

    view = legacy_volume_view(tmp_path / ".story-system", chapter_number=80)
    assert view is not None
    assert view["id"] == "vol-2"

    # No arcs at all returns None.
    view = legacy_volume_view(tmp_path / ".story-system", chapter_number=200)
    assert view is None


def test_legacy_active_characters_annotates_lifecycle(tmp_path):
    _write(
        tmp_path / ".webnovel" / "state.json",
        {
            "characters": [
                {"name": "林昭"},
                {"name": "苏婉"},
            ]
        },
    )
    chars = legacy_active_characters(tmp_path / ".story-system")
    assert len(chars) == 2
    assert all(card.get("lifecycle") == "active" for card in chars)
    assert {c["name"] for c in chars} == {"林昭", "苏婉"}


def test_legacy_active_characters_prefers_canonical_characters_dir(tmp_path):
    canonical = tmp_path / ".story-system" / "characters"
    _write(canonical / "linzhao.json", {"name": "林昭", "lifecycle": "active"})
    _write(
        tmp_path / ".webnovel" / "state.json",
        {"characters": [{"name": "苏婉"}]},
    )
    chars = legacy_active_characters(tmp_path / ".story-system")
    names = [c["name"] for c in chars]
    assert names == ["林昭"]


def test_legacy_previous_chapter_uses_state_summary(tmp_path):
    _write(
        tmp_path / ".webnovel" / "state.json",
        {
            "chapter_summaries": [
                {"chapter_number": 1, "summary": "首章摘要", "next_focus": "次章钩子"},
            ]
        },
    )
    prev = legacy_previous_chapter(tmp_path / ".story-system", chapter_number=2)
    assert prev is not None
    assert prev["summary"] == "首章摘要"
    # ``tail`` defaults to ``next_focus`` so the writer context
    # gets a usable opening hook.
    assert prev["tail"] == "次章钩子"


def test_legacy_previous_chapter_returns_none_for_first_chapter(tmp_path):
    assert legacy_previous_chapter(tmp_path / ".story-system", chapter_number=1) is None
