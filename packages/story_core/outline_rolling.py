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

from packages.story_core.outline_planning import apply_chapter_contract_policy


class RollingPlanError(ValueError):
    """Raised when the planning helpers are given an
    input they cannot satisfy.

    Examples: the target chapter is outside the volume
    range, the window size is non-positive, or the volume
    range itself is malformed.
    """


class RollingValidationError(ValueError):
    """Raised when a rolling-fill chapter payload is
    unacceptable for writing to disk.

    The message names the failing chapter number and the
    field that broke, so the operator can fix the entire
    batch in one pass.
    """


_DEFAULT_WINDOW = 5
_DEFAULT_MIN_REMAINING = 2
_REQUIRED_CHAPTER_FIELDS: tuple[str, ...] = (
    "chapter_number",
    "title",
    "chapter_goal",
    "core_conflict",
    "cast",
    "scenes",
    "gain",
    "cost",
    "foreshadowing",
    "hook",
    "state_delta",
)
_REQUIRED_SCENE_FIELDS: tuple[str, ...] = (
    "location",
    "action",
    "result",
)
_MIN_SCENES = 2
_MAX_SCENES = 4


def rolling_chapter_to_outline_entry(payload: Any) -> dict[str, Any]:
    """Adapt one rolling chapter to the legacy outline chapter shape.

    Rolling outlines are the chapter-level source of truth, while some
    generation contexts still consume the older ``goal/action/payoff``
    fields. Keeping the conversion here gives both paths the same view.
    """
    if not isinstance(payload, dict):
        return {}
    try:
        chapter_number = int(payload.get("chapter_number") or 0)
    except (TypeError, ValueError):
        return {}
    if chapter_number <= 0:
        return {}

    raw_cast = payload.get("cast") if isinstance(payload.get("cast"), list) else []
    cast_names = [
        str(item.get("name") or "").strip()
        for item in raw_cast
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]
    scenes = payload.get("scenes") if isinstance(payload.get("scenes"), list) else []
    action_parts: list[str] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        location = str(scene.get("location") or "").strip()
        action = str(scene.get("action") or "").strip()
        result = str(scene.get("result") or "").strip()
        beat = "，".join(part for part in (action, result) if part)
        if location and beat:
            beat = f"{location}：{beat}"
        elif location:
            beat = location
        if beat:
            action_parts.append(beat)

    chapter_goal = str(payload.get("chapter_goal") or "").strip()
    return {
        **payload,
        "number": chapter_number,
        "chapter_number": chapter_number,
        "summary": chapter_goal,
        "goal": chapter_goal,
        "obstacle": str(payload.get("core_conflict") or "").strip(),
        "action": "；".join(action_parts),
        "payoff": str(payload.get("gain") or "").strip(),
        "turn": str(payload.get("cost") or "").strip(),
        "ending_hook": str(payload.get("hook") or "").strip(),
        "cast_cards": raw_cast,
        "cast": cast_names,
    }


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


def _coerce_non_empty_str(payload: dict[str, Any], field: str) -> str:
    """Return ``payload[field]`` as a non-empty string,
    raising :class:`RollingValidationError` if missing or
    blank.

    The plan rule requires a "本章目标" / "核心冲突" /
    etc. — every one of those fields is a required
    non-empty string, so the helper centralises the
    validation.
    """
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RollingValidationError(
            f"rolling_chapter_field_blank: {field}"
        )
    return value.strip()


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


def validate_rolling_chapter(
    payload: Any,
    *,
    expected_chapter_number: int,
    volume_range: tuple[int, int],
    require_chapter_contracts: bool = False,
) -> dict[str, Any]:
    """Validate one rolling-fill chapter payload.

    The function returns the validated payload (after a
    shallow copy) so callers can pass the result straight
    into the storage layer. Raises
    :class:`RollingValidationError` with a code that
    names the failing field; the plan rule forbids
    silently saving a payload that is incomplete, has the
    wrong chapter number, or sits outside the volume
    range.
    """
    if not isinstance(payload, dict):
        raise RollingValidationError(
            f"rolling_chapter_not_dict: {type(payload).__name__}"
        )
    start, end = _coerce_volume_range(volume_range)
    expected_chapter_number = _coerce_positive_int(
        "expected_chapter_number", expected_chapter_number
    )

    for field in _REQUIRED_CHAPTER_FIELDS:
        if field not in payload:
            raise RollingValidationError(
                f"rolling_chapter_missing_field: {field}"
            )

    chapter_number = payload.get("chapter_number")
    if not isinstance(chapter_number, int) or isinstance(chapter_number, bool):
        raise RollingValidationError(
            f"rolling_chapter_chapter_number_not_int: "
            f"{type(chapter_number).__name__}"
        )
    if chapter_number != expected_chapter_number:
        raise RollingValidationError(
            f"rolling_chapter_chapter_number_mismatch: "
            f"got {chapter_number} expected {expected_chapter_number}"
        )
    if chapter_number < start or chapter_number > end:
        raise RollingValidationError(
            f"rolling_chapter_out_of_volume: "
            f"chapter={chapter_number} range=({start},{end})"
        )

    for field in (
        "title",
        "chapter_goal",
        "core_conflict",
        "gain",
        "cost",
        "hook",
        "state_delta",
    ):
        _coerce_non_empty_str(payload, field)

    cast = payload.get("cast")
    if not isinstance(cast, list) or not cast:
        raise RollingValidationError(
            "rolling_chapter_cast_invalid: must be non-empty list"
        )
    for entry in cast:
        if not isinstance(entry, dict):
            raise RollingValidationError(
                f"rolling_chapter_cast_entry_not_dict: "
                f"{type(entry).__name__}"
            )

    # ``foreshadowing`` is a list of strings (foreshadowing
    # IDs / names the chapter touches). An empty list is
    # valid when the chapter is foreshadowing-free, but a
    # non-list or a list with a non-string entry is not.
    foreshadowing = payload.get("foreshadowing")
    if not isinstance(foreshadowing, list):
        raise RollingValidationError(
            "rolling_chapter_foreshadowing_not_list: "
            f"got={type(foreshadowing).__name__}"
        )
    for entry in foreshadowing:
        if not isinstance(entry, str) or not entry.strip():
            raise RollingValidationError(
                f"rolling_chapter_foreshadowing_entry_invalid: "
                f"got={entry!r}"
            )

    scenes = payload.get("scenes")
    if not isinstance(scenes, list):
        raise RollingValidationError(
            "rolling_chapter_scenes_not_list: must be a list"
        )
    if len(scenes) < _MIN_SCENES:
        raise RollingValidationError(
            f"rolling_chapter_scenes_too_few: "
            f"min={_MIN_SCENES} got={len(scenes)}"
        )
    if len(scenes) > _MAX_SCENES:
        raise RollingValidationError(
            f"rolling_chapter_scenes_too_many: "
            f"max={_MAX_SCENES} got={len(scenes)}"
        )
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise RollingValidationError(
                f"rolling_chapter_scene_not_dict: index={index}"
            )
        for field in _REQUIRED_SCENE_FIELDS:
            if not scene.get(field) or not str(scene.get(field) or "").strip():
                raise RollingValidationError(
                    f"rolling_chapter_scene_field_blank: "
                    f"index={index} field={field}"
                )

    try:
        return apply_chapter_contract_policy(
            payload,
            require_chapter_contracts=require_chapter_contracts,
            chapter_number=chapter_number,
        )
    except ValueError as exc:
        raise RollingValidationError(str(exc)) from exc


def validate_rolling_batch(
    chapters: Iterable[Any],
    *,
    expected_chapter_numbers: list[int],
    volume_range: tuple[int, int],
    require_chapter_contracts: bool = False,
) -> list[dict[str, Any]]:
    """Validate an entire rolling-fill batch in one pass.

    The function collects every per-chapter failure
    (rather than short-circuiting on the first one) so the
    operator sees the full list of corrections in a
    single error message. The plan rule: "部分章节生成
    成功、部分失败时不写入" — the caller is expected to
    abort the whole write when this function raises.
    """
    chapter_list = list(chapters)
    if not chapter_list:
        raise RollingPlanError("rolling_batch_empty")

    failures: list[str] = []
    validated: list[dict[str, Any]] = []
    for index, payload in enumerate(chapter_list):
        if not isinstance(expected_chapter_numbers, list) or index >= len(
            expected_chapter_numbers
        ):
            failures.append(
                f"chapter_index={index} expected_number_missing"
            )
            continue
        expected = expected_chapter_numbers[index]
        try:
            validated.append(
                validate_rolling_chapter(
                    payload,
                    expected_chapter_number=expected,
                    volume_range=volume_range,
                    require_chapter_contracts=require_chapter_contracts,
                )
            )
        except RollingValidationError as exc:
            failures.append(
                f"chapter_number={expected} {exc}"
            )

    # Order check: the batch must write each chapter at
    # its expected number, in the order the caller asked
    # for. A chapter whose ``chapter_number`` already
    # passed validation is the *number* the payload
    # declared; ``expected_chapter_numbers`` is the slot
    # in the batch. They should agree; if they do not
    # (e.g. a 150 in slot 0 of a [148, 149, 150] batch)
    # the batch is malformed and the planner refuses to
    # write it.
    actual_numbers = [int(p.get("chapter_number") or 0) for p in validated]
    if actual_numbers != list(expected_chapter_numbers):
        failures.append(
            f"rolling_batch_chapter_number_order_mismatch: "
            f"expected={list(expected_chapter_numbers)} "
            f"actual={actual_numbers}"
        )

    if failures:
        raise RollingValidationError(
            "rolling_batch_validation_failed: " + "; ".join(failures)
        )
    return validated


__all__ = [
    "RollingPlanError",
    "RollingValidationError",
    "plan_rolling_window",
    "rolling_chapter_to_outline_entry",
    "validate_rolling_batch",
    "validate_rolling_chapter",
]
