"""Tests for the rolling chapter outline planner.

The plan rule: when a new chapter is about to be written,
the system must guarantee a usable outline exists for the
target chapter AND for at least one more chapter ahead. A
missing outline triggers a *rolling fill* of the next
``window`` chapters, skipping any chapters the operator
already marked manual.

The pure function under test
:func:`plan_rolling_window` answers one question only —
"which chapter numbers should the rolling fill generate?"
— so every test in this file exercises the function with
hand-built chapter lists and never touches the disk.
"""

from __future__ import annotations

import pytest

from packages.story_core.outline_rolling import (
    RollingPlanError,
    plan_rolling_window,
)


# --- Test fixtures ----------------------------------------------------------


def _chapter(
    number: int,
    *,
    source: str = "generated",
    title: str = "本章",
) -> dict:
    """Return a minimal outline-chapter dict for tests.

    The rolling planner only reads ``chapter_number`` and
    ``source``; ``title`` is a sanity-check marker so a
    future refactor that introspects more fields does not
    silently break this test file.
    """
    return {
        "chapter_number": number,
        "title": title or f"第{number}章",
        "source": source,
    }


# --- Happy paths ------------------------------------------------------------


def test_plan_rolling_window_returns_full_window_when_no_chapters_exist() -> None:
    """Target chapter 148 with no existing outline produces
    chapters 148 through 152 (inclusive, ``window=5``).
    """
    plan = plan_rolling_window(
        target_chapter=148,
        existing_chapters=[],
        volume_range=(140, 160),
    )
    assert plan == [148, 149, 150, 151, 152]


def test_plan_rolling_window_returns_empty_when_target_already_present() -> None:
    """If the target chapter already has an outline, the
    planner must NOT touch it. The function returns ``[]``
    so the orchestrator's caller knows the rolling fill is
    a no-op for this target.
    """
    plan = plan_rolling_window(
        target_chapter=148,
        existing_chapters=[_chapter(148), _chapter(149), _chapter(150), _chapter(151), _chapter(152)],
        volume_range=(140, 160),
    )
    assert plan == []


def test_plan_rolling_window_extends_partial_window_to_full() -> None:
    """When the target is present but the rolling window
    is short (only target + 1 more), the planner extends
    the window out to the full ``window=5`` chapters. This
    is the "<2 remaining" rule the plan pins: the system
    must keep at least ``min_remaining`` filled chapters
    ahead of the current target.
    """
    plan = plan_rolling_window(
        target_chapter=148,
        existing_chapters=[_chapter(148), _chapter(149), _chapter(150)],
        volume_range=(140, 160),
    )
    assert plan == [151, 152]


def test_plan_rolling_window_skips_manual_chapters_and_starts_above_them() -> None:
    """A chapter the operator marked ``source="manual"``
    must never be overwritten by the rolling fill. The
    planner starts the window *after* the manual chapter
    and treats the manual anchor as part of the existing
    rolling buffer.
    """
    plan = plan_rolling_window(
        target_chapter=148,
        existing_chapters=[
            _chapter(148, source="manual", title="人工章"),
        ],
        volume_range=(140, 160),
    )
    # The planner must NOT include 148; the rolling window
    # starts at 149 and continues to 152 (the manual
    # chapter is treated as already-filled).
    assert 148 not in plan
    assert plan == [149, 150, 151, 152]


def test_plan_rolling_window_triggers_next_batch_when_only_two_chapters_remain() -> None:
    """The "<2 remaining" pre-generation rule: the
    planner must keep the rolling window topped up. With
    five filled chapters starting at the target, the
    planner returns ``[]``; if the caller asks for a
    target outside the window (e.g. chapter 153 with the
    window ending at 152), the planner extends.
    """
    plan = plan_rolling_window(
        target_chapter=153,
        existing_chapters=[_chapter(n) for n in (148, 149, 150, 151, 152)],
        volume_range=(140, 200),
    )
    assert plan == [153, 154, 155, 156, 157]


def test_plan_rolling_window_respects_custom_window_size() -> None:
    """A ``window=3`` configuration returns at most three
    chapter numbers, never more, so a future tuning
    parameter does not silently break the contract.
    """
    plan = plan_rolling_window(
        target_chapter=10,
        existing_chapters=[],
        volume_range=(1, 20),
        window=3,
    )
    assert plan == [10, 11, 12]


# --- Volume boundaries ------------------------------------------------------


def test_plan_rolling_window_truncates_at_volume_upper_bound() -> None:
    """A window that would extend past the volume's last
    chapter is truncated. The user is asking for the next
    volume to be planned, not for the planner to invent
    cross-volume chapters.
    """
    plan = plan_rolling_window(
        target_chapter=158,
        existing_chapters=[],
        volume_range=(140, 160),
    )
    # 158..162 would overshoot 160; the planner stops at
    # 160 (the volume's end).
    assert plan == [158, 159, 160]


def test_plan_rolling_window_truncates_at_volume_lower_bound() -> None:
    """A target chapter *before* the volume's first
    chapter is rejected — the rolling fill cannot plan
    chapters that have already happened or that the
    volume range does not cover.
    """
    with pytest.raises(RollingPlanError) as exc_info:
        plan_rolling_window(
            target_chapter=120,
            existing_chapters=[],
            volume_range=(140, 160),
        )
    assert "out_of_volume" in str(exc_info.value)


def test_plan_rolling_window_rejects_zero_or_negative_window() -> None:
    """A window of zero or negative size would be a no-op
    or infinite loop; the function must reject the input
    loudly rather than silently return ``[]``.
    """
    with pytest.raises(RollingPlanError):
        plan_rolling_window(
            target_chapter=148,
            existing_chapters=[],
            volume_range=(140, 160),
            window=0,
        )


# --- Edge cases on existing chapters ----------------------------------------


def test_plan_rolling_window_treats_legacy_chapters_as_present() -> None:
    """The pre-Round-8 ``legacy`` source marker means a
    chapter is already on disk and the planner must not
    touch it. The function treats any chapter number
    present in ``existing_chapters`` as filled regardless
    of source.
    """
    plan = plan_rolling_window(
        target_chapter=148,
        existing_chapters=[
            _chapter(148, source="legacy"),
            _chapter(149, source="legacy"),
        ],
        volume_range=(140, 160),
    )
    assert plan == [150, 151, 152]


def test_plan_rolling_window_dedupes_existing_chapters_by_number() -> None:
    """A malformed outline file with duplicate chapter
    numbers must not confuse the planner. The function
    treats the chapter number as the canonical key and
    dedupes before computing the gap.
    """
    plan = plan_rolling_window(
        target_chapter=148,
        existing_chapters=[
            _chapter(148),
            _chapter(148),  # duplicate on disk
            _chapter(149),
        ],
        volume_range=(140, 160),
    )
    assert plan == [150, 151, 152]


def test_plan_rolling_window_ignores_chapters_with_invalid_number() -> None:
    """An outline file with a chapter whose ``chapter_number``
    is ``0`` or negative is corrupt; the planner must skip
    that row (it cannot anchor the window there) and
    continue with the well-formed ones. The corrupt row
    does NOT count as filled at any chapter number, so the
    buffer at the target is whatever the well-formed rows
    indicate.
    """
    plan = plan_rolling_window(
        target_chapter=148,
        existing_chapters=[
            {"chapter_number": 0, "title": "破损", "source": "generated"},
            _chapter(149),
            _chapter(150),
        ],
        volume_range=(140, 160),
    )
    # 148 is the target and is NOT in the well-formed
    # filled set, so the planner must include 148 in the
    # gap. 149 / 150 are already filled; 151 / 152 are
    # missing. The corrupt row at chapter_number=0 is
    # silently dropped — it cannot count as filled
    # anywhere.
    assert plan == [148, 151, 152]
