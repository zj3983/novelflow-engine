"""Tests for :class:`RollingOutlineStore`.

The plan rule: "保存采用原子更新，并保留旧大纲备份" —
every rolling fill must write a complete batch atomically
(an all-or-nothing write) and keep a backup of the
previous outline so a future operator can recover if
something else later turns out to be wrong.

The store is the side-effectful sibling of
:mod:`packages.story_core.outline_rolling` — it owns the
disk format and the atomic-write protocol. Every test in
this file uses a real ``tmp_path`` so the atomic write,
backup, and restore behaviours are exercised end-to-end.

The store uses a SEPARATE file
(``.story-system/outline-generation/rolling_outline.json``)
rather than mutating ``.webnovel/outline.json`` so the
legacy ``ProjectOutline`` Pydantic schema stays
untouched. The legacy outline is read as a "filled"
signal so a chapter the initial planning pass already
produced is never overwritten by a later rolling fill.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from packages.story_core.outline_rolling import (
    RollingValidationError,
    validate_rolling_batch,
)
from packages.story_core.outline_rolling_store import (
    RollingOutlineStore,
    RollingOutlineStoreError,
)


# --- Test fixtures ----------------------------------------------------------


def _seed_legacy_outline(
    project_root: Path,
    *,
    chapters: list[dict] | None = None,
) -> dict:
    """Write a minimal ``.webnovel/outline.json`` so the
    store can read the legacy chapter numbers.
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
    return payload


def _seed_rolling_outline(
    project_root: Path,
    *,
    chapters: list[dict] | None = None,
) -> Path:
    """Write a pre-existing rolling outline so the store
    has a backup candidate for the next batch.
    """
    payload = {
        "schema_version": "rolling-outline/v1",
        "chapters": list(chapters or []),
    }
    target = (
        project_root
        / ".story-system"
        / "outline-generation"
        / "rolling_outline.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def _chapter(number: int) -> dict:
    """Return a minimal valid rolling-fill chapter payload."""
    return {
        "chapter_number": number,
        "title": f"第{number}章",
        "chapter_goal": f"第{number}章目标",
        "core_conflict": f"第{number}章冲突",
        "cast": [{"name": "林昭", "role": "protagonist", "this_chapter_role": "行动"}],
        "scenes": [
            {"location": "灰狼坡", "action": "补齐毒腺", "result": "任务 16/16"},
            {"location": "灰烬村", "action": "提交任务", "result": "升级"},
        ],
        "gain": "升级到 Lv.3",
        "cost": "灰狼毒腺 8 份",
        "foreshadowing": ["第二章异常"],
        "hook": "流霜打断狼王",
        "state_delta": "level=Lv.3",
    }


def _chapter_contracts() -> dict:
    return {
        "payoff_contract": {
            "need": "林修必须拿到替换镜芯",
            "pressure": "买家只给他一夜验货",
            "hidden_advantage": "他能恢复物品上次完整运行状态",
            "concrete_reward": "修复订单并获得父亲失踪线索",
        },
        "chapter_sop": {
            "opening_carry": "接上铜镜第一次亮起",
            "mid_feedback": "镜面恢复一段旧影像",
            "turn": "影像中的人认出了林修",
            "ending_hook": "镜中人叫出林修父亲的名字",
        },
    }


# --- Happy path -------------------------------------------------------------


def test_rolling_store_writes_new_chapters_and_marks_them_generated(
    tmp_path: Path,
) -> None:
    """A fresh project (no legacy or rolling outline)
    accepts the batch and writes a new
    ``rolling_outline.json`` whose ``chapters`` list
    contains the batch in order, tagged with
    ``source = "generated"``.
    """
    store = RollingOutlineStore(tmp_path)
    chapters = [_chapter(148), _chapter(149), _chapter(150)]

    written = store.apply_rolling_batch(
        chapters=chapters,
        expected_chapter_numbers=[148, 149, 150],
        volume_range=(140, 160),
    )

    assert sorted(written) == [148, 149, 150]
    on_disk = json.loads(
        _seed_rolling_outline.__wrapped__ if False
        else (tmp_path / ".story-system" / "outline-generation" / "rolling_outline.json").read_text(encoding="utf-8")
    )
    numbers = [int(c["chapter_number"]) for c in on_disk["chapters"]]
    assert numbers == [148, 149, 150]
    sources = [c.get("source") for c in on_disk["chapters"]]
    assert all(source == "generated" for source in sources)
    # The legacy outline is NOT created or modified.
    assert not (tmp_path / ".webnovel" / "outline.json").exists()


def test_disabled_rolling_store_drops_partial_contract_fields(tmp_path: Path) -> None:
    chapter = _chapter(148)
    chapter["payoff_contract"] = {"need": "模型夹带的局部字段"}

    RollingOutlineStore(tmp_path).apply_rolling_batch(
        chapters=[chapter],
        expected_chapter_numbers=[148],
        volume_range=(140, 160),
        require_chapter_contracts=False,
    )

    persisted = RollingOutlineStore(tmp_path).read_chapter(148)
    assert "payoff_contract" not in persisted
    assert "chapter_sop" not in persisted


def test_enabled_rolling_store_requires_and_persists_full_contracts(
    tmp_path: Path,
) -> None:
    partial = _chapter(148)
    partial["payoff_contract"] = {"need": "林修必须拿到替换镜芯"}
    store = RollingOutlineStore(tmp_path)

    with pytest.raises(RollingValidationError, match="chapter_contract_missing"):
        store.apply_rolling_batch(
            chapters=[partial],
            expected_chapter_numbers=[148],
            volume_range=(140, 160),
            require_chapter_contracts=True,
        )

    complete = {**_chapter(148), **_chapter_contracts()}
    store.apply_rolling_batch(
        chapters=[complete],
        expected_chapter_numbers=[148],
        volume_range=(140, 160),
        require_chapter_contracts=True,
    )

    persisted = store.read_chapter(148)
    assert persisted["payoff_contract"] == complete["payoff_contract"]
    assert persisted["chapter_sop"] == complete["chapter_sop"]


def test_rolling_store_does_not_modify_legacy_outline(tmp_path: Path) -> None:
    """The legacy ``.webnovel/outline.json`` is read-only
    from the store's perspective. The store never
    overwrites legacy rows, even when the new rolling
    chapters' numbers overlap the legacy range.
    """
    _seed_legacy_outline(
        tmp_path,
        chapters=[
            {
                "chapter_number": n,
                "title": f"第{n}章",
                "chapter_goal": "…",
                "source": "legacy",
            }
            for n in range(1, 15)
        ],
    )
    pre_legacy = json.loads(
        (tmp_path / ".webnovel" / "outline.json").read_text(encoding="utf-8")
    )
    store = RollingOutlineStore(tmp_path)
    store.apply_rolling_batch(
        chapters=[_chapter(15), _chapter(16)],
        expected_chapter_numbers=[15, 16],
        volume_range=(1, 50),
    )
    post_legacy = json.loads(
        (tmp_path / ".webnovel" / "outline.json").read_text(encoding="utf-8")
    )
    # Legacy outline is byte-identical to the pre-call
    # snapshot.
    assert post_legacy == pre_legacy
    # The new rolling chapters landed in the rolling
    # outline, not the legacy one.
    rolling = json.loads(
        (tmp_path / ".story-system" / "outline-generation" / "rolling_outline.json").read_text(encoding="utf-8")
    )
    numbers = [int(c["chapter_number"]) for c in rolling["chapters"]]
    assert numbers == [15, 16]


def test_rolling_store_treats_legacy_chapters_as_already_filled(
    tmp_path: Path,
) -> None:
    """A batch whose chapters are already in the legacy
    outline is a no-op. The plan rule: "已存在或人工修
    改的细纲不会被覆盖".
    """
    _seed_legacy_outline(
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
    store = RollingOutlineStore(tmp_path)
    written = store.apply_rolling_batch(
        chapters=[_chapter(148), _chapter(149), _chapter(150)],
        expected_chapter_numbers=[148, 149, 150],
        volume_range=(140, 160),
    )
    assert written == []
    # No rolling outline was written.
    assert not (tmp_path / ".story-system" / "outline-generation" / "rolling_outline.json").exists()


def test_rolling_store_writes_rolling_fill_log(tmp_path: Path) -> None:
    """Every successful batch writes a JSON log to
    ``.story-system/outline-generation/rolling_fill_log.json``
    that records the chapter numbers filled, the volume
    range, and the timestamp.
    """
    store = RollingOutlineStore(tmp_path)
    store.apply_rolling_batch(
        chapters=[_chapter(148), _chapter(149)],
        expected_chapter_numbers=[148, 149],
        volume_range=(140, 160),
    )

    log_path = (
        tmp_path
        / ".story-system"
        / "outline-generation"
        / "rolling_fill_log.json"
    )
    assert log_path.is_file()
    log = json.loads(log_path.read_text(encoding="utf-8"))
    assert log["last_chapter_numbers"] == [148, 149]
    assert log["last_status"] == "filled"
    assert isinstance(log["rows"], list)
    latest = log["rows"][-1]
    assert latest["chapter_numbers"] == [148, 149]
    assert latest["volume_range"] == [140, 160]
    assert latest["status"] == "filled"
    assert "filled_at" in latest


# --- Backup behaviour -------------------------------------------------------


def test_rolling_store_creates_backup_before_overwrite(tmp_path: Path) -> None:
    """A batch that overwrites an existing rolling
    outline must copy the previous outline to
    ``.story-system/outline-generation/backup/{ts}.json``
    before the new write.
    """
    _seed_rolling_outline(
        tmp_path,
        chapters=[
            _chapter(148),
        ],
    )
    store = RollingOutlineStore(tmp_path)
    store.apply_rolling_batch(
        chapters=[_chapter(149), _chapter(150)],
        expected_chapter_numbers=[149, 150],
        volume_range=(140, 160),
    )

    backup_dir = tmp_path / ".story-system" / "outline-generation" / "backup"
    assert backup_dir.is_dir()
    backups = sorted(backup_dir.glob("*.json"))
    assert len(backups) >= 1
    # The backup must preserve the previous chapter so
    # the operator can recover if a later change is
    # wrong.
    backup_payload = json.loads(backups[0].read_text(encoding="utf-8"))
    backup_numbers = [int(c["chapter_number"]) for c in backup_payload["chapters"]]
    assert 148 in backup_numbers


# --- Atomic write -----------------------------------------------------------


def test_rolling_store_uses_atomic_write_so_outline_is_never_partial(
    tmp_path: Path,
) -> None:
    """The store writes to a temp file inside the same
    directory and then renames it onto the target. The
    on-disk outline is therefore either the old content
    or the new content — never a half-written file the
    orchestrator could mistake for either.
    """
    store = RollingOutlineStore(tmp_path)
    store.apply_rolling_batch(
        chapters=[_chapter(148), _chapter(149)],
        expected_chapter_numbers=[148, 149],
        volume_range=(140, 160),
    )

    target = (
        tmp_path / ".story-system" / "outline-generation" / "rolling_outline.json"
    )
    # No leftover ``.tmp`` file in the same directory
    # would be a sign of a non-atomic write that crashed
    # mid-rename.
    siblings = list(target.parent.iterdir())
    leftovers = [p for p in siblings if p.name.startswith(".rolling_outline.json")]
    assert leftovers == [], (
        f"atomic write left leftover temp files: {leftovers}"
    )
    # The on-disk file is fully valid JSON (not a half
    # write).
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["chapters"]


# --- Validation failures ----------------------------------------------------


def test_rolling_store_rejects_batch_with_wrong_chapter_number(
    tmp_path: Path,
) -> None:
    """A batch whose chapter number does not match the
    expected list is rejected wholesale.
    """
    _seed_rolling_outline(tmp_path, chapters=[_chapter(148)])
    pre_rolling = json.loads(
        (
            tmp_path
            / ".story-system"
            / "outline-generation"
            / "rolling_outline.json"
        ).read_text(encoding="utf-8")
    )

    bad_chapter = _chapter(150)  # claims 150 but slot 0 is 149
    with pytest.raises(RollingValidationError):
        store = RollingOutlineStore(tmp_path)
        store.apply_rolling_batch(
            chapters=[bad_chapter],
            expected_chapter_numbers=[149],
            volume_range=(140, 160),
        )

    post_rolling = json.loads(
        (
            tmp_path
            / ".story-system"
            / "outline-generation"
            / "rolling_outline.json"
        ).read_text(encoding="utf-8")
    )
    assert post_rolling == pre_rolling


def test_rolling_store_rejects_partial_success_keeping_disk_unchanged(
    tmp_path: Path,
) -> None:
    """A batch where the second chapter fails validation
    must not leave the first chapter partially written.
    """
    _seed_rolling_outline(tmp_path, chapters=[_chapter(148)])
    pre_rolling = json.loads(
        (
            tmp_path
            / ".story-system"
            / "outline-generation"
            / "rolling_outline.json"
        ).read_text(encoding="utf-8")
    )

    good = _chapter(149)
    bad = _chapter(150)
    del bad["hook"]  # break the second chapter
    with pytest.raises(RollingValidationError):
        store = RollingOutlineStore(tmp_path)
        store.apply_rolling_batch(
            chapters=[good, bad],
            expected_chapter_numbers=[149, 150],
            volume_range=(140, 160),
        )

    post_rolling = json.loads(
        (
            tmp_path
            / ".story-system"
            / "outline-generation"
            / "rolling_outline.json"
        ).read_text(encoding="utf-8")
    )
    assert post_rolling == pre_rolling


def test_rolling_store_rejects_batch_with_chapter_outside_volume(
    tmp_path: Path,
) -> None:
    """A batch that includes a chapter past the volume's
    end is rejected.
    """
    store = RollingOutlineStore(tmp_path)
    with pytest.raises(RollingValidationError):
        store.apply_rolling_batch(
            chapters=[_chapter(161)],  # past (140, 160)
            expected_chapter_numbers=[161],
            volume_range=(140, 160),
        )


# --- Edge cases -------------------------------------------------------------


def test_rolling_store_writes_outline_when_no_previous_file(tmp_path: Path) -> None:
    """A project that has never had a rolling outline on
    disk gets a fresh file written from scratch. The
    store does not require a pre-existing outline to
    bootstrap the file.
    """
    store = RollingOutlineStore(tmp_path)
    store.apply_rolling_batch(
        chapters=[_chapter(1), _chapter(2)],
        expected_chapter_numbers=[1, 2],
        volume_range=(1, 10),
    )
    target = (
        tmp_path / ".story-system" / "outline-generation" / "rolling_outline.json"
    )
    assert target.is_file()
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert [int(c["chapter_number"]) for c in on_disk["chapters"]] == [1, 2]


def test_rolling_store_idempotent_for_already_present_rolling_chapters(
    tmp_path: Path,
) -> None:
    """Re-applying a batch whose chapters are already in
    the rolling outline is a no-op.
    """
    seeded = []
    for n in (148, 149, 150):
        chapter = _chapter(n)
        chapter["source"] = "generated"
        seeded.append(chapter)
    _seed_rolling_outline(tmp_path, chapters=seeded)
    store = RollingOutlineStore(tmp_path)
    written = store.apply_rolling_batch(
        chapters=[_chapter(148), _chapter(149), _chapter(150)],
        expected_chapter_numbers=[148, 149, 150],
        volume_range=(140, 160),
    )
    assert written == []
    on_disk = json.loads(
        (
            tmp_path
            / ".story-system"
            / "outline-generation"
            / "rolling_outline.json"
        ).read_text(encoding="utf-8")
    )
    numbers = [int(c["chapter_number"]) for c in on_disk["chapters"]]
    assert numbers == [148, 149, 150]
    # The pre-existing ``generated`` source marker is
    # preserved.
    sources = {int(c["chapter_number"]): c.get("source") for c in on_disk["chapters"]}
    assert all(sources[n] == "generated" for n in (148, 149, 150))


def test_rolling_store_rejects_when_path_is_readonly(tmp_path: Path) -> None:
    """A read-only project root makes the atomic write
    fail. The store surfaces the I/O error as
    :class:`RollingOutlineStoreError` so the caller can
    distinguish a permission failure from a validation
    failure.
    """
    if os.name == "nt":
        pytest.skip(
            "read-only project root is platform-specific; covered on POSIX"
        )
    store = RollingOutlineStore(tmp_path)
    tmp_path.chmod(0o400)
    try:
        with pytest.raises(RollingOutlineStoreError):
            store.apply_rolling_batch(
                chapters=[_chapter(1)],
                expected_chapter_numbers=[1],
                volume_range=(1, 10),
            )
    finally:
        tmp_path.chmod(0o700)
