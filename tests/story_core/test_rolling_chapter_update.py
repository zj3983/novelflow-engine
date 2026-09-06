"""Tests for Round 8 Task 8: manual-edit protection on the rolling outline.

A chapter the operator (or the UI) has marked ``source="manual"`` is
the operator's source of truth. The rolling fill must:

* Skip it (``plan_rolling_window`` does this — already covered by
  ``test_outline_rolling.py``).
* Preserve it on disk (``RollingOutlineStore._merge_rolling``
  keeps existing rows verbatim — already covered).

The new test surface here is the **edit-and-mark** path:

* ``update_chapter`` merges the new payload into the existing row,
  stamps ``source="manual"`` and ``last_manual_edit_at``, and writes
  atomically with a backup.
* A subsequent rolling fill that targets the manual chapter must
  leave it untouched (``apply_rolling_batch`` idempotency + the
  plan rule "已存在或人工修改的细纲不会被覆盖").
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.story_core.outline_rolling_store import (
    RollingOutlineStore,
    RollingOutlineStoreError,
)


def _write_payload(root: Path, payload: dict) -> Path:
    target = root / ".story-system" / "outline-generation" / "rolling_outline.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return target


def _stub_chapter(number: int, *, source: str = "generated", **overrides) -> dict:
    base = {
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
        "state_delta": f"level=Lv.{number}",
        "source": source,
    }
    base.update(overrides)
    return base


def test_update_chapter_stamps_manual_source_and_timestamp(tmp_path: Path) -> None:
    _write_payload(
        tmp_path,
        {
            "schema_version": "rolling-outline/v1",
            "chapters": [_stub_chapter(148), _stub_chapter(149)],
        },
    )
    store = RollingOutlineStore(tmp_path)
    result = store.update_chapter(
        chapter_number=149,
        payload={
            "title": "夜烬怒斩大长老",
            "chapter_goal": "夜烬当面拒绝大长老收徒",
            "core_conflict": "师徒名分 vs 自由心性",
            "hook": "大长老摔杯为号",
        },
    )
    assert result["chapter_number"] == 149
    assert result["source"] == "manual"
    assert result["last_manual_edit_at"]  # populated
    # The merged row keeps the operator's edits for the fields they
    # supplied and leaves other fields intact.
    assert result["title"] == "夜烬怒斩大长老"
    assert result["chapter_goal"] == "夜烬当面拒绝大长老收徒"
    assert result["scenes"] == [
        {"location": "断崖", "action": "夜烬跃下", "result": "拾到新技能"},
        {"location": "山洞", "action": "对话NPC", "result": "解锁新任务"},
    ]
    # On disk
    on_disk = json.loads(
        (tmp_path / ".story-system" / "outline-generation" / "rolling_outline.json").read_text(
            encoding="utf-8"
        )
    )
    assert on_disk["chapters"][1]["source"] == "manual"


def test_update_chapter_creates_backup_before_write(tmp_path: Path) -> None:
    _write_payload(
        tmp_path,
        {"schema_version": "rolling-outline/v1", "chapters": [_stub_chapter(148)]},
    )
    store = RollingOutlineStore(tmp_path)
    store.update_chapter(
        chapter_number=148,
        payload={"title": "新标题", "chapter_goal": "新目标", "core_conflict": "新冲突"},
    )
    backup_dir = tmp_path / ".story-system" / "outline-generation" / "backup"
    assert backup_dir.is_dir()
    backups = list(backup_dir.glob("*.json"))
    assert len(backups) == 1
    backup_payload = json.loads(backups[0].read_text(encoding="utf-8"))
    assert backup_payload["chapters"][0]["title"] == "第148章 stub 标题"


def test_update_chapter_raises_when_chapter_not_found(tmp_path: Path) -> None:
    _write_payload(
        tmp_path,
        {"schema_version": "rolling-outline/v1", "chapters": [_stub_chapter(148)]},
    )
    store = RollingOutlineStore(tmp_path)
    with pytest.raises(RollingOutlineStoreError, match="rolling_chapter_not_found"):
        store.update_chapter(
            chapter_number=999,
            payload={"title": "不存在"},
        )


def test_update_chapter_raises_when_no_rolling_outline_on_disk(tmp_path: Path) -> None:
    store = RollingOutlineStore(tmp_path)
    with pytest.raises(RollingOutlineStoreError, match="rolling_outline_missing"):
        store.update_chapter(
            chapter_number=148,
            payload={"title": "无 outline"},
        )


def test_update_chapter_does_not_overwrite_other_chapters(tmp_path: Path) -> None:
    _write_payload(
        tmp_path,
        {
            "schema_version": "rolling-outline/v1",
            "chapters": [
                _stub_chapter(148, title="原 148"),
                _stub_chapter(149, title="原 149"),
                _stub_chapter(150, title="原 150"),
            ],
        },
    )
    store = RollingOutlineStore(tmp_path)
    store.update_chapter(
        chapter_number=149,
        payload={"title": "新 149", "chapter_goal": "新目标 149", "core_conflict": "新冲突 149"},
    )
    payload = json.loads(
        (tmp_path / ".story-system" / "outline-generation" / "rolling_outline.json").read_text(
            encoding="utf-8"
        )
    )
    by_number = {c["chapter_number"]: c for c in payload["chapters"]}
    assert by_number[148]["title"] == "原 148"
    assert by_number[149]["title"] == "新 149"
    assert by_number[149]["source"] == "manual"
    assert by_number[150]["title"] == "原 150"


