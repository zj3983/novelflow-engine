"""Rolling chapter outline planning.

The plan rule (Round 8, 滚动细纲补全): when a new chapter
is about to be written, the system must guarantee a usable
outline exists for the target chapter AND for the next
``window`` chapters ahead. A missing outline triggers a
*rolling fill* of the next ``window`` chapters, skipping any
chapters the operator already marked manual.

This module hosts the pure planning logic. It does not
touch the disk — :class:`RollingOutlineStore` in
:mod:`packages.story_core.outline_rolling_store` is the
side-effectful sibling that writes the result.
"""

from __future__ import annotations

from typing import Any, Iterable


class RollingPlanError(ValueError):
    """Raised when :func:`plan_rolling_window` is given an
    input it cannot satisfy.

    Examples: the target chapter is outside the volume
    range, the window size is non-positive, or the volume
    range itself is malformed.
    """


_DEFAULT_WINDOW = 5
_DEFAULT_MIN_REMAINING = 2


def _normalize_chapter_numbers(
    existing_chapters: Iterable[dict[str, Any]],
) -> set[int]:
    """Project ``existing_chapters`` to the set of valid
    chapter numbers the planner must treat as already on
    disk.

    Rows with a non-positive or non-integer
    ``chapter_number`` are dropped — the planner cannot
    anchor a window on a corrupt row, and silently
    including it would let a malformed outline push the
    rolling window into the wrong range.
    """
    numbers: set[int] = set()
    for chapter in existing_chapters or []:
        if not isinstance(chapter, dict):
            continue
        number = chapter.get("chapter_number")
        if isinstance(number, bool):
            continue
        if isinstance(number, int) and number > 0:
            numbers.add(number)
            continue
        if isinstance(number, str) and number.strip().isdigit():
            value = int(number.strip())
            if value > 0:
                numbers.add(value)
    return numbers


def _coerce_volume_range(
    volume_range: tuple[int, int] | None,
) -> tuple[int, int]:
    """Return a (start, end) tuple, raising if either
    bound is missing or the range is degenerate.

    A degenerate range (``start > end``) would make every
    target chapter "out of volume" so the planner raises
    immediately rather than silently returning ``[]``.
    """
    if (
        volume_range is None
        or not isinstance(volume_range, tuple)
        or len(volume_range) != 2
    ):
        raise RollingPlanError("rolling_plan_volume_range_required")
    start, end = volume_range
    if not isinstance(start, int) or not isinstance(end, int):
        raise RollingPlanError("rolling_plan_volume_range_not_int")
    if start <= 0 or end <= 0:
        raise RollingPlanError("rolling_plan_volume_range_non_positive")
    if start > end:
        raise RollingPlanError(
            f"rolling_plan_volume_range_inverted: {start} > {end}"
        )
    return start, end


def _coerce_positive_int(
    name: str, value: Any, *, allow_zero: bool = False
) -> int:
    """Validate that ``value`` is a non-negative integer.

    ``allow_zero=False`` (the default) requires strictly
    positive integers; the window size and target chapter
    use this. ``allow_zero=True`` is reserved for
    ``min_remaining`` (the planner treats zero as
    "no minimum buffer required").
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RollingPlanError(
            f"rolling_plan_{name}_not_int: {value!r}"
        )
    if allow_zero:
        if value < 0:
            raise RollingPlanError(
                f"rolling_plan_{name}_negative: {value}"
            )
    else:
        if value <= 0:
            raise RollingPlanError(
                f"rolling_plan_{name}_non_positive: {value}"
            )
    return value


def plan_rolling_window(
    *,
    target_chapter: int,
    existing_chapters: Iterable[dict[str, Any]] | None = None,
    volume_range: tuple[int, int] | None = None,
    window: int = _DEFAULT_WINDOW,
    min_remaining: int = _DEFAULT_MIN_REMAINING,
) -> list[int]:
    """Return the chapter numbers the rolling fill must
    generate so the next ``window`` chapters starting at
    ``target_chapter`` all have an outline.

    Parameters
    ----------
    target_chapter
        The chapter the caller is about to write.
    existing_chapters
        Iterable of outline-chapter dicts already on disk.
        Each dict must carry ``chapter_number`` and may
        carry ``source`` (``"generated"``,
        ``"manual"``, ``"legacy"``); any source marker
        counts as "filled" — the planner does not
        regenerate manual or legacy chapters.
    volume_range
        ``(start, end)`` inclusive bounds of the current
        volume. The planner will never suggest a chapter
        outside this range and will reject ``target_chapter``
        below ``start``.
    window
        How many chapters ahead of the target the planner
        tries to keep filled. Defaults to 5 (the production
        rolling fill size).
    min_remaining
        Unused at the planner level. Reserved for a future
        hook (e.g. "fill when fewer than N filled chapters
        remain after the target"); the buffer model below
        already covers the production need.

    Returns
    -------
    list[int]
        Sorted ascending list of chapter numbers to fill.
        Empty when the target chapter is already filled
        and the next ``window`` chapters ahead of it are
        all filled too. Raises :class:`RollingPlanError` on
        invalid input.
    """
    target_chapter = _coerce_positive_int("target", target_chapter)
    window = _coerce_positive_int("window", window)
    min_remaining = _coerce_positive_int(
        "min_remaining", min_remaining, allow_zero=True
    )
    del min_remaining  # reserved; buffer model below is the active rule
    start, end = _coerce_volume_range(volume_range)

    if target_chapter < start:
        raise RollingPlanError(
            f"rolling_plan_target_out_of_volume: "
            f"target={target_chapter} start={start}"
        )

    filled = _normalize_chapter_numbers(existing_chapters)

    # The buffer is the next ``window`` chapters starting at
    # the target. We count how many of them are already
    # filled and fill the rest, truncating at the volume's
    # end. Manual, legacy, and generated chapters all
    # count as filled — the planner never overwrites a
    # chapter the operator already has, regardless of
    # source.
    buffer: list[int] = []
    cursor = target_chapter
    while len(buffer) < window and cursor <= end:
        buffer.append(cursor)
        cursor += 1
    missing = [n for n in buffer if n not in filled]
    return missing


__all__ = ["RollingPlanError", "plan_rolling_window"]
