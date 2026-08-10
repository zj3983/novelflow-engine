"""Integration tests for the rolling-outline flow inside
:class:`FileProjectStore`.

The plan rule: when the user clicks "生成下一章", the
backend must check whether the target chapter's outline
exists. If not, it triggers a rolling fill BEFORE the
body generation starts. A failed rolling fill must
stop the body generation — the user must see the failure
and retry, not a half-written candidate.

These tests are integration-level: they exercise the
file-project store end-to-end on a real ``tmp_path`` so
the read-write-validate cycle is real, not mocked.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.outline_rolling_planner import (
    RollingOutlineFailed,
    RollingOutlineStatus,
)


# --- Test doubles -----------------------------------------------------------


def _valid_chapter_payload(chapter_number: int) -> dict[str, Any]:
    """Return a minimal valid rolling-fill chapter payload."""
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


def _seed_file_project(
    project_root: Path,
    *,
    outline_chapters: list[dict[str, Any]] | None = None,
    state_chapters: int = 0,
) -> FileProjectStore:
    """Create a file-project store with a minimal project
    layout so the rolling-fill integration can run.

    ``outline_chapters`` seeds ``.webnovel/outline.json``,
    the legacy project outline. The rolling fill reads
    this file as a "filled" signal but never writes to
    it. A new ``rolling_outline.json`` lives under
    ``.story-system/outline-generation/`` — the
    integration tests assert against that separate file.
    """
    webnovel = project_root / ".webnovel"
    webnovel.mkdir(parents=True, exist_ok=True)
    story_system = project_root / ".story-system"
    story_system.mkdir(parents=True, exist_ok=True)
    (webnovel / "project.json").write_text(
        json.dumps(
            {
                "project_id": "file:rolling-fixture",
                "title": "滚动细纲测试",
                "character_profiles": [],
                "enabled_skill_ids": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (webnovel / "state.json").write_text(
        json.dumps(
            {
                "story_id": "s-rolling",
                "current_chapter": state_chapters,
                "characters": [],
                "world_facts": [],
                "chapter_summaries": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if outline_chapters is not None:
        (webnovel / "outline.json").write_text(
            json.dumps(
                {
                    "schema_version": "project-outline/v1",
                    "chapters": list(outline_chapters),
                    "arcs": [],
                    "overall": {"story": ""},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return FileProjectStore(project_root)


def _rolling_outline_path(project_root: Path) -> Path:
    return (
        project_root
        / ".story-system"
        / "outline-generation"
        / "rolling_outline.json"
    )


# --- ensure_rolling_outline behaviour --------------------------------------


def test_ensure_rolling_outline_writes_full_window_when_outline_missing(
    tmp_path: Path,
) -> None:
    """A project whose target chapter has no outline
    gets a 5-chapter rolling fill written to disk.
    """
    store = _seed_file_project(
        tmp_path, outline_chapters=[], state_chapters=147
    )

    status = store.ensure_rolling_outline(
        target_chapter=148,
        generator=lambda number: _valid_chapter_payload(number),
    )

    assert isinstance(status, RollingOutlineStatus)
    assert status.kind == "filled"
    assert sorted(status.chapter_numbers) == [148, 149, 150, 151, 152]
    on_disk = json.loads(
        _rolling_outline_path(tmp_path).read_text(encoding="utf-8")
    )
    numbers = [int(c["chapter_number"]) for c in on_disk["chapters"]]
    assert numbers == [148, 149, 150, 151, 152]
    # The legacy outline is NOT created or modified by
    # the rolling fill — it was never seeded and the
    # fill writes to a separate file.
    legacy_path = tmp_path / ".webnovel" / "outline.json"
    if legacy_path.exists():
        legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        assert legacy.get("chapters") == []


def test_ensure_rolling_outline_returns_present_when_target_already_has_outline(
    tmp_path: Path,
) -> None:
    """A project whose target chapter already has an
    outline (in either the legacy or rolling file)
    produces a ``present`` status without invoking the
    generator. The plan rule: "已有细纲的新章节：直接
    进入正文生成".
    """
    chapters = [
        {
            "chapter_number": n,
            "title": f"第{n}章",
            "chapter_goal": "…",
            "source": "generated",
        }
        for n in range(148, 153)
    ]
    store = _seed_file_project(
        tmp_path, outline_chapters=chapters, state_chapters=147
    )

    generator_called = False

    def _should_not_run(number: int) -> dict[str, Any]:
        nonlocal generator_called
        generator_called = True
        return _valid_chapter_payload(number)

    status = store.ensure_rolling_outline(
        target_chapter=148,
        generator=_should_not_run,
    )

    assert status.kind == "present"
    assert status.chapter_numbers == []
    assert generator_called is False


def test_ensure_rolling_outline_raises_and_does_not_touch_disk_on_failure(
    tmp_path: Path,
) -> None:
    """A generator that returns an invalid payload must
    raise ``RollingOutlineFailed`` and leave the on-disk
    rolling outline byte-identical. The plan rule:
    "补全失败时正文生成停止".
    """
    store = _seed_file_project(
        tmp_path, outline_chapters=[], state_chapters=147
    )
    rolling_path = _rolling_outline_path(tmp_path)
    pre_rolling_bytes = (
        rolling_path.read_bytes() if rolling_path.exists() else b""
    )

    def _bad_generator(number: int) -> dict[str, Any]:
        return {
            "chapter_number": number,
            "title": f"第{number}章",
            # Missing the required ``hook`` field.
            "chapter_goal": f"第{number}章目标",
            "core_conflict": f"第{number}章冲突",
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

    with pytest.raises(RollingOutlineFailed):
        store.ensure_rolling_outline(
            target_chapter=148,
            generator=_bad_generator,
        )
    # The rolling outline file is byte-identical to the
    # pre-call snapshot.
    post_rolling_bytes = (
        rolling_path.read_bytes() if rolling_path.exists() else b""
    )
    assert post_rolling_bytes == pre_rolling_bytes


def test_ensure_rolling_outline_uses_state_current_chapter_when_target_omitted(
    tmp_path: Path,
) -> None:
    """When the caller does not pass ``target_chapter``,
    the store uses the project's
    ``current_chapter + 1`` from the legacy state so
    the rolling fill kicks in at the right chapter
    without the caller having to compute it.
    """
    store = _seed_file_project(
        tmp_path, outline_chapters=[], state_chapters=147
    )

    status = store.ensure_rolling_outline(
        generator=lambda number: _valid_chapter_payload(number),
    )

    assert status.target_chapter == 148
    assert sorted(status.chapter_numbers) == [148, 149, 150, 151, 152]


def test_ensure_rolling_outline_default_generator_produces_stub_payloads(
    tmp_path: Path,
) -> None:
    """When the caller does not pass a generator, the
    store uses a deterministic stub so smoke runs and
    legacy callers without a real model binding still
    work. The plan rule: "本次只调整规划与写作衔接，
    不新增 Agent" — the default generator is the
    minimal v1 fallback, not a real model.
    """
    store = _seed_file_project(
        tmp_path, outline_chapters=[], state_chapters=147
    )

    status = store.ensure_rolling_outline(target_chapter=148)

    assert status.kind == "filled"
    # The default generator produces a well-formed
    # chapter so the batch validates successfully.
    on_disk = json.loads(
        _rolling_outline_path(tmp_path).read_text(encoding="utf-8")
    )
    numbers = [int(c["chapter_number"]) for c in on_disk["chapters"]]
    assert numbers == [148, 149, 150, 151, 152]
    # The default generator tags every row with
    # ``source = "generated"`` so the rolling fill can
    # refresh them in a future pass.
    sources = {int(c["chapter_number"]): c.get("source") for c in on_disk["chapters"]}
    assert all(sources[n] == "generated" for n in (148, 149, 150, 151, 152))
