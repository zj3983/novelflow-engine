"""Tests for Task 5 (Round 8) — read API on RollingOutlineStore.

The writing_packet needs to surface the next-chapter outline (from the
rolling outline or the legacy outline) without forcing the caller to
walk the JSON file themselves. These tests pin down:

* `read_rolling_outline()` returns the full payload when present.
* `read_rolling_outline()` returns None when no rolling outline exists.
* `read_chapter(n)` returns the rolling chapter when present.
* `read_chapter(n)` returns None when no rolling chapter for that number.
* `read_chapter(n)` skips the legacy outline (rolling only).
"""
from __future__ import annotations

import json
from pathlib import Path

from packages.story_core.outline_rolling_store import RollingOutlineStore


def _write_payload(root: Path, payload: dict) -> Path:
    target = root / ".story-system" / "outline-generation" / "rolling_outline.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return target


def _stub_chapter(number: int) -> dict:
    return {
        "chapter_number": number,
        "title": f"第{number}章 stub 标题",
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
        "source": "generated",
    }


def test_read_rolling_outline_returns_full_payload_when_present(tmp_path: Path) -> None:
    _write_payload(
        tmp_path,
        {
            "schema_version": "rolling-outline/v1",
            "chapters": [_stub_chapter(148), _stub_chapter(149)],
        },
    )
    store = RollingOutlineStore(tmp_path)
    payload = store.read_rolling_outline()
    assert payload is not None
    assert payload["schema_version"] == "rolling-outline/v1"
    assert len(payload["chapters"]) == 2
    assert payload["chapters"][0]["chapter_number"] == 148


def test_read_rolling_outline_returns_none_when_missing(tmp_path: Path) -> None:
    store = RollingOutlineStore(tmp_path)
    assert store.read_rolling_outline() is None


def test_read_chapter_returns_matching_rolling_chapter(tmp_path: Path) -> None:
    _write_payload(
        tmp_path,
        {
            "schema_version": "rolling-outline/v1",
            "chapters": [_stub_chapter(148), _stub_chapter(149), _stub_chapter(150)],
        },
    )
    store = RollingOutlineStore(tmp_path)
    chapter = store.read_chapter(149)
    assert chapter is not None
    assert chapter["chapter_number"] == 149
    assert chapter["title"] == "第149章 stub 标题"


def test_read_chapter_returns_none_when_number_missing(tmp_path: Path) -> None:
    _write_payload(
        tmp_path,
        {
            "schema_version": "rolling-outline/v1",
            "chapters": [_stub_chapter(148)],
        },
    )
    store = RollingOutlineStore(tmp_path)
    assert store.read_chapter(200) is None


def test_read_chapter_does_not_fall_back_to_legacy_outline(tmp_path: Path) -> None:
    """Rolling chapter reader is rolling-only; legacy outline chapters are
    surfaced separately by FileProjectStore, not the rolling reader."""
    legacy = tmp_path / ".webnovel" / "outline.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        json.dumps(
            {
                "schema_version": "project-outline/v1",
                "overall": {"story": "x"},
                "arcs": [],
                "chapters": [{"chapter_number": 148, "title": "legacy 148"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = RollingOutlineStore(tmp_path)
    # No rolling outline on disk → both readers return None
    assert store.read_rolling_outline() is None
    assert store.read_chapter(148) is None


def test_read_chapter_handles_corrupt_payload_gracefully(tmp_path: Path) -> None:
    target = tmp_path / ".story-system" / "outline-generation" / "rolling_outline.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{not valid json", encoding="utf-8")
    store = RollingOutlineStore(tmp_path)
    assert store.read_rolling_outline() is None
    assert store.read_chapter(148) is None
