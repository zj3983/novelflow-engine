"""Tests for the rolling-outline planner.

The plan rule: "如果不存在，调用现有大纲规划能力，一次
生成从目标章开始的5章滚动细纲" — when the next
chapter's outline is missing, the planner drives an
LLM call (or a stub in tests) to generate the next
window of chapters, validates each, and writes the
batch atomically.

The planner is the orchestrator-facing entry point. It
composes :func:`plan_rolling_window` and
:class:`RollingOutlineStore` so the orchestrator only has
to call ``ensure_rolling_outline(target_chapter)`` and
get back a single status envelope.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pytest

from packages.story_core.outline_rolling import (
    RollingPlanError,
    plan_rolling_window,
)
from packages.story_core.outline_rolling_planner import (
    RollingOutlineFailed,
    RollingOutlinePlanner,
    RollingOutlineStatus,
)


# --- Test doubles -----------------------------------------------------------


def _stub_chapter(chapter_number: int) -> dict[str, Any]:
    """Return a minimal valid chapter payload for
    ``chapter_number``. The stub matches the shape
    :func:`validate_rolling_chapter` accepts so the
    planner can persist the batch without a real model
    call.
    """
    return {
        "chapter_number": chapter_number,
        "title": f"第{chapter_number}章",
        "chapter_goal": f"第{chapter_number}章目标",
        "core_conflict": f"第{chapter_number}章冲突",
        "cast": [
            {"name": "林昭", "role": "protagonist", "this_chapter_role": "行动"}
        ],
        "scenes": [
            {"location": "灰狼坡", "action": "补齐毒腺", "result": "16/16"},
            {"location": "灰烬村", "action": "提交任务", "result": "升级"},
        ],
        "gain": "升级到 Lv.3",
        "cost": "灰狼毒腺 8 份",
        "foreshadowing": [],
        "hook": "流霜打断狼王",
        "state_delta": "level=Lv.3",
    }


@dataclass
class _RecordingGenerator:
    """A stub chapter generator that records the chapter
    numbers it was asked to fill and returns canned
    payloads. The tests assert the planner only invokes
    the generator for the gap, in order, with the right
    chapter number.
    """

    payload_factory: Callable[[int], dict[str, Any]] = _stub_chapter
    requests: list[int] = None
    call_count: int = 0

    def __post_init__(self) -> None:
        if self.requests is None:
            self.requests = []

    def __call__(self, chapter_number: int) -> dict[str, Any]:
        self.call_count += 1
        self.requests.append(chapter_number)
        return self.payload_factory(chapter_number)


def _seed_outline(
    project_root: Path,
    *,
    chapters: list[dict] | None = None,
) -> None:
    """Write a minimal ``.webnovel/outline.json`` so the
    planner has something to read. Tests that need an
    empty project just skip this helper.
    """
    payload = {
        "schema_version": "project-outline/v1",
        "chapters": list(chapters or []),
        "arcs": [],
        "overall": {"story": ""},
    }
    target = project_root / ".webnovel" / "outline.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# --- Happy paths ------------------------------------------------------------


def test_planner_returns_present_when_target_outline_already_exists(
    tmp_path: Path,
) -> None:
    """A project whose target chapter already has an
    outline produces a ``present`` status without
    calling the generator. The plan rule: "已有细纲的
    新章节：直接进入正文生成" — no rolling fill when
    the buffer is full.
    """
    _seed_outline(
        tmp_path,
        chapters=[
            {
                "chapter_number": n,
                "title": f"第{n}章",
                "chapter_goal": "…",
                "source": "generated",
            }
            for n in range(148, 153)
        ],
    )
    generator = _RecordingGenerator()
    planner = RollingOutlinePlanner(generator=generator)

    status = planner.ensure_rolling_outline(
        project_root=tmp_path,
        target_chapter=148,
        volume_range=(140, 160),
    )

    assert status.kind == "present"
    assert status.chapter_numbers == []
    assert generator.call_count == 0


def test_planner_fills_window_when_target_outline_missing(tmp_path: Path) -> None:
    """A project with no outline gets a fresh 5-chapter
    rolling fill. The generator is called for the target
    through target + window, and the batch lands on
    disk with the right chapter numbers.
    """
    _seed_outline(tmp_path, chapters=[])
    generator = _RecordingGenerator()
    planner = RollingOutlinePlanner(generator=generator)

    status = planner.ensure_rolling_outline(
        project_root=tmp_path,
        target_chapter=148,
        volume_range=(140, 160),
    )

    assert status.kind == "filled"
    assert sorted(status.chapter_numbers) == [148, 149, 150, 151, 152]
    assert generator.requests == [148, 149, 150, 151, 152]
    # The rolling outline lives in a separate file
    # under ``.story-system/outline-generation/`` so the
    # legacy ``.webnovel/outline.json`` stays untouched.
    rolling_path = (
        tmp_path
        / ".story-system"
        / "outline-generation"
        / "rolling_outline.json"
    )
    on_disk = json.loads(rolling_path.read_text(encoding="utf-8"))
    numbers = [int(c["chapter_number"]) for c in on_disk["chapters"]]
    assert numbers == [148, 149, 150, 151, 152]
    # The legacy outline is NOT modified by the rolling
    # fill — the file may pre-exist (empty chapters) but
    # its content is byte-identical to the pre-call
    # snapshot.
    legacy_path = tmp_path / ".webnovel" / "outline.json"
    if legacy_path.exists():
        legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        assert legacy.get("chapters") == []


def test_planner_extends_partial_window_to_full(tmp_path: Path) -> None:
    """A project with the target + 2 more chapters
    (window = 3/5) gets the missing 2 chapters filled
    so the rolling buffer is topped up.
    """
    _seed_outline(
        tmp_path,
        chapters=[
            {
                "chapter_number": n,
                "title": f"第{n}章",
                "chapter_goal": "…",
                "source": "legacy",
            }
            for n in (148, 149, 150)
        ],
    )
    generator = _RecordingGenerator()
    planner = RollingOutlinePlanner(generator=generator)

    status = planner.ensure_rolling_outline(
        project_root=tmp_path,
        target_chapter=148,
        volume_range=(140, 160),
    )

    assert status.kind == "filled"
    assert status.chapter_numbers == [151, 152]
    # The generator must only be invoked for the missing
    # chapters, not for the ones already on disk.
    assert generator.requests == [151, 152]


# --- Failure modes ----------------------------------------------------------


def test_planner_raises_when_generator_returns_invalid_payload(
    tmp_path: Path,
) -> None:
    """A generator that returns a payload missing
    required fields is rejected wholesale. The plan
    rule: "细纲返回缺字段、章节号错位或越过当前卷范围时，
    拒绝保存" — the on-disk outline must not change.
    """
    _seed_outline(tmp_path, chapters=[])

    def _bad_generator(chapter_number: int) -> dict[str, Any]:
        # Missing the required ``hook`` field.
        return {
            "chapter_number": chapter_number,
            "title": f"第{chapter_number}章",
            "chapter_goal": f"第{chapter_number}章目标",
            "core_conflict": f"第{chapter_number}章冲突",
            "cast": [
                {"name": "林昭", "role": "protagonist", "this_chapter_role": "行动"}
            ],
            "scenes": [
                {"location": "灰狼坡", "action": "补齐毒腺", "result": "16/16"},
                {"location": "灰烬村", "action": "提交任务", "result": "升级"},
            ],
            "gain": "升级到 Lv.3",
            "cost": "灰狼毒腺 8 份",
            "foreshadowing": [],
            "state_delta": "level=Lv.3",
        }

    generator = _RecordingGenerator(payload_factory=_bad_generator)
    planner = RollingOutlinePlanner(generator=generator)
    with pytest.raises(RollingOutlineFailed):
        planner.ensure_rolling_outline(
            project_root=tmp_path,
            target_chapter=148,
            volume_range=(140, 160),
        )
    # No outline was written.
    on_disk = json.loads(
        (tmp_path / ".webnovel" / "outline.json").read_text(encoding="utf-8")
    )
    assert on_disk["chapters"] == []


def test_planner_raises_when_generator_returns_wrong_chapter_number(
    tmp_path: Path,
) -> None:
    """A generator that returns a payload claiming the
    wrong chapter number is rejected. The plan rule:
    "章节号错位时拒绝保存".
    """
    _seed_outline(tmp_path, chapters=[])

    def _wrong_number(chapter_number: int) -> dict[str, Any]:
        return _stub_chapter(chapter_number + 1)  # off by one

    generator = _RecordingGenerator(payload_factory=_wrong_number)
    planner = RollingOutlinePlanner(generator=generator)
    with pytest.raises(RollingOutlineFailed):
        planner.ensure_rolling_outline(
            project_root=tmp_path,
            target_chapter=148,
            volume_range=(140, 160),
        )


def test_planner_raises_when_target_outside_volume(tmp_path: Path) -> None:
    """A target chapter below the volume's start is
    rejected. The plan rule: "细纲返回…越过当前卷范围
    时拒绝保存".
    """
    _seed_outline(tmp_path, chapters=[])
    generator = _RecordingGenerator()
    planner = RollingOutlinePlanner(generator=generator)
    with pytest.raises(RollingPlanError):
        planner.ensure_rolling_outline(
            project_root=tmp_path,
            target_chapter=120,
            volume_range=(140, 160),
        )


# --- Volume boundary -------------------------------------------------------


def test_planner_truncates_window_at_volume_end(tmp_path: Path) -> None:
    """A target near the volume's end gets only the
    chapters that fit in the volume. The planner must
    not invent cross-volume chapters.
    """
    _seed_outline(tmp_path, chapters=[])
    generator = _RecordingGenerator()
    planner = RollingOutlinePlanner(generator=generator)
    status = planner.ensure_rolling_outline(
        project_root=tmp_path,
        target_chapter=158,
        volume_range=(140, 160),
    )
    assert status.chapter_numbers == [158, 159, 160]
    assert generator.requests == [158, 159, 160]


# --- Status envelope ------------------------------------------------------


def test_planner_status_envelope_carries_volume_range(tmp_path: Path) -> None:
    """The :class:`RollingOutlineStatus` envelope the
    planner returns includes the volume range so the
    caller (e.g. the workbench) can show it in the UI
    without re-reading the project's config.
    """
    _seed_outline(tmp_path, chapters=[])
    generator = _RecordingGenerator()
    planner = RollingOutlinePlanner(generator=generator)
    status = planner.ensure_rolling_outline(
        project_root=tmp_path,
        target_chapter=148,
        volume_range=(140, 160),
    )
    assert status.volume_range == (140, 160)
    assert status.target_chapter == 148
