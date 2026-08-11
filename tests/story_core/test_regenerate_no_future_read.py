"""Tests for Round 8 Task 9: regenerate_chapter must not read future outlines.

The plan rule (验收: 旧章重写不读取未来细纲):

* ``regenerate_chapter(N)`` must use ONLY the outline for chapter N
  and the history up to N-1. It must NOT trigger a rolling fill
  to generate outlines for future chapters (N+1, N+2, ...).

This file pins the behaviour down at two layers:

* ``ensure_rolling_outline`` is the only path that writes new rolling
  chapters. ``regenerate_chapter`` must not call it under any
  circumstance — even when the target chapter's outline is missing,
  even when a "future" outline would normally be required for the
  planner. A sentinel-raise monkeypatch proves this.

* The test also covers the symmetric case: when chapter N has no
  outline, ``regenerate_chapter`` either uses the legacy outline
  row (if one exists) or raises — it does NOT silently trigger a
  fill that would also write chapters N+1..N+5 to disk.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.outline_rolling_store import RollingOutlineStore


def _make_minimal_file_project(
    root: Path,
    *,
    state: dict | None = None,
    project: dict | None = None,
    chapter: dict | None = None,
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
    if chapter is not None:
        (root / ".story-system" / "chapters" / f"{chapter['chapter_number']:04d}.json").write_text(
            json.dumps(chapter, ensure_ascii=False),
            encoding="utf-8",
        )
    return FileProjectStore(root)


def _stub_chapter_payload(number: int) -> dict:
    return {
        "chapter_number": number,
        "chapter_title": f"第{number}章 stub",
        "body": "Long body text content " * 300,  # >= 4200 chars to pass length gate
        "chapter_summary": {
            "summary": f"Summary {number}",
            "facts": [f"fact-{number}"],
            "next_focus": "继续",
        },
    }


class _FakeEngine:
    """A trivial engine that returns a handcrafted chapter."""

    def __init__(self) -> None:
        self.calls = 0

    def generate_next_chapter(self, story):  # used by both generate_next_chapter and regenerate_chapter
        self.calls += 1
        return SimpleNamespace(
            chapter_number=story.current_chapter + 1,
            chapter_title="stub",
            body="Long body text content " * 300,  # >= 4200 chars to pass length gate
            cadence="manual",
            next_outline="continue",
            updated_story=story.model_copy(update={"current_chapter": story.current_chapter + 1}),
            chapter_summary={"summary": "ok", "facts": [], "next_focus": "continue"},
            quality_report={"ok": True},
        )

    def regenerate_chapter(self, story, *, chapter_number, **kwargs):  # used by regenerate
        self.calls += 1
        return SimpleNamespace(
            chapter_number=chapter_number,
            chapter_title="regen stub",
            body="Regen body text content " * 300,  # >= 4200 chars to pass length gate
            cadence="manual",
            next_outline="continue",
            updated_story=story,
            chapter_summary={"summary": "regen", "facts": [], "next_focus": "continue"},
            quality_report={"ok": True},
        )


def test_regenerate_chapter_does_not_call_ensure_rolling_outline(tmp_path: Path) -> None:
    """The headline acceptance: ``regenerate_chapter`` is a pure
    rewrite — it must not trigger the rolling planner, even if
    the target chapter's outline is missing AND future chapters
    have no outline either.

    A sentinel ``ensure_rolling_outline`` raises immediately if
    called. The test passes only if ``regenerate_chapter``
    completes without the planner being touched.
    """
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "断香炉",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
            "character_profiles": [],
        },
        state={"story_id": "s-file", "current_chapter": 3, "world_facts": [], "characters": []},
        chapter=_stub_chapter_payload(1),
    )
    # Sentinel: any call to ensure_rolling_outline raises.
    def sentinel(*args, **kwargs):
        raise AssertionError(
            "regenerate_chapter must NOT call ensure_rolling_outline"
        )
    with patch.object(FileProjectStore, "ensure_rolling_outline", sentinel):
        engine = _FakeEngine()
        result = store.regenerate_chapter(1, engine=engine)
    assert result["chapter_number"] == 1
    # The rolling outline file is still empty (no fill was triggered).
    rolling = RollingOutlineStore(tmp_path / "novel").read_rolling_outline()
    assert rolling is None or rolling.get("chapters") == []


def test_regenerate_chapter_uses_existing_outline_for_target_only(tmp_path: Path) -> None:
    """A legacy outline row for chapter 1 exists, but the rolling
    outline is missing. ``regenerate_chapter(1)`` must use the
    legacy row and NOT trigger any fill.
    """
    store = _make_minimal_file_project(
        tmp_path / "novel",
        project={
            "project_id": "p-file",
            "title": "断香炉",
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
            "character_profiles": [],
        },
        state={"story_id": "s-file", "current_chapter": 3, "world_facts": [], "characters": []},
        chapter=_stub_chapter_payload(1),
    )
    # Write the legacy outline AFTER the project dir exists.
    (tmp_path / "novel" / ".webnovel" / "outline.json").write_text(
        json.dumps(
            {
                "schema_version": "project-outline/v1",
                "overall": {"story": "x"},
                "arcs": [],
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "legacy 1",
                        "goal": "legacy 1 目标",
                        "payoff": "legacy 1 payoff",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # No rolling outline exists; verify regenerate doesn't try to create one.
    with patch.object(
        FileProjectStore,
        "ensure_rolling_outline",
        side_effect=AssertionError("must not be called"),
    ):
        engine = _FakeEngine()
        result = store.regenerate_chapter(1, engine=engine)
    assert result["chapter_number"] == 1
    # No rolling outline on disk after the call.
    rolling = RollingOutlineStore(tmp_path / "novel").read_rolling_outline()
    assert rolling is None or rolling.get("chapters") == []


def test_generate_next_chapter_requires_outline_without_auto_fill(tmp_path: Path) -> None:
    """Body generation stops before the engine when its fine outline is missing."""
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
    with patch.object(
        FileProjectStore,
        "ensure_rolling_outline",
        side_effect=AssertionError("body generation must not auto-fill outlines"),
    ):
        with pytest.raises(ValueError, match="chapter_outline_required:1"):
            store.generate_next_chapter(engine=_FakeEngine(), persist=False)
