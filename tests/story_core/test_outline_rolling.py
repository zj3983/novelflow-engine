"""Tests for the rolling chapter outline planner.

The plan rule: when a new chapter is about to be written,
the system must guarantee a usable outline exists for the
target chapter AND for at least one more chapter ahead. A
missing outline triggers a *rolling fill* of the next
``window`` chapters, skipping any chapters the operator
already marked manual.

The pure functions under test answer two questions only:

* :func:`plan_rolling_window` — "which chapter numbers
  should the rolling fill generate?"
* :func:`validate_rolling_chapter` /
  :func:`validate_rolling_batch` — "is the LLM's output
  acceptable to write to disk?"

Both functions are pure: every test in this file exercises
them with hand-built payloads and never touches the disk.
"""

from __future__ import annotations

import pytest

from packages.story_core.outline_rolling import (
    RollingPlanError,
    RollingValidationError,
    plan_rolling_window,
    rolling_chapter_to_outline_entry,
    validate_rolling_batch,
    validate_rolling_chapter,
)


CHAPTER_CONTRACT = {
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


# --- Field validation -------------------------------------------------------


def _valid_chapter_payload(chapter_number: int) -> dict:
    """Return a minimal valid rolling-fill chapter payload.

    The shape mirrors the production outline shape; only
    the fields the validator actually inspects are
    populated, so a future refactor that adds fields does
    not silently break the existing tests.
    """
    return {
        "chapter_number": chapter_number,
        "title": f"第{chapter_number}章",
        "chapter_goal": f"第{chapter_number}章目标",
        "core_conflict": f"第{chapter_number}章冲突",
        "cast": [
            {"name": "林昭", "role": "protagonist", "this_chapter_role": "主角行动"},
        ],
        "scenes": [
            {
                "location": "灰狼坡",
                "action": "补齐毒腺",
                "result": "任务达到 16/16",
            },
            {
                "location": "灰烬村",
                "action": "提交任务",
                "result": "升级",
            },
        ],
        "gain": "升级到 Lv.3",
        "cost": "灰狼毒腺 8 份",
        "foreshadowing": ["第二章异常已结算"],
        "hook": "流霜打断狼王冲锋",
        "state_delta": "level=Lv.3",
    }


def test_validate_rolling_chapter_accepts_well_formed_payload() -> None:
    """A well-formed rolling-fill chapter payload is
    accepted without raising. This is the happy path that
    every other test in this section builds on.
    """
    validate_rolling_chapter(
        _valid_chapter_payload(148),
        expected_chapter_number=148,
        volume_range=(140, 160),
    )


def test_validate_rolling_chapter_rejects_missing_field() -> None:
    """A payload missing any required field is rejected
    with a code that names the missing field. The plan
    rule: "缺字段、章节号错位或越过当前卷范围时，拒绝
    保存" — every required field must be enforced
    individually so the operator can correct the right
    one in the next attempt.
    """
    payload = _valid_chapter_payload(148)
    del payload["core_conflict"]
    with pytest.raises(RollingValidationError) as exc_info:
        validate_rolling_chapter(
            payload,
            expected_chapter_number=148,
            volume_range=(140, 160),
        )
    assert "core_conflict" in str(exc_info.value)


def test_validate_rolling_chapter_rejects_wrong_chapter_number() -> None:
    """A payload whose ``chapter_number`` does not match
    the expected target is rejected. The plan rule: the
    rolling fill must not write a chapter at the wrong
    number — that would shift every subsequent outline
    reference.
    """
    payload = _valid_chapter_payload(149)  # claims 149
    with pytest.raises(RollingValidationError) as exc_info:
        validate_rolling_chapter(
            payload,
            expected_chapter_number=148,  # but caller asked for 148
            volume_range=(140, 160),
        )
    assert "chapter_number" in str(exc_info.value)


def test_validate_rolling_chapter_rejects_chapter_outside_volume() -> None:
    """A chapter number outside the volume range is
    rejected. The plan rule: "越过当前卷范围时拒绝保存"
    — the rolling fill must not invent cross-volume
    chapters.
    """
    payload = _valid_chapter_payload(161)
    with pytest.raises(RollingValidationError) as exc_info:
        validate_rolling_chapter(
            payload,
            expected_chapter_number=161,
            volume_range=(140, 160),
        )
    assert "out_of_volume" in str(exc_info.value) or "161" in str(exc_info.value)


def test_validate_rolling_chapter_rejects_empty_scenes() -> None:
    """A chapter with no scenes is rejected. The plan
    requires "2至4个主要场面"; a payload with zero scenes
    is not actionable and the writer would have to invent
    the whole scene plan.
    """
    payload = _valid_chapter_payload(148)
    payload["scenes"] = []
    with pytest.raises(RollingValidationError) as exc_info:
        validate_rolling_chapter(
            payload,
            expected_chapter_number=148,
            volume_range=(140, 160),
        )
    assert "scenes" in str(exc_info.value)


def test_validate_rolling_chapter_rejects_too_many_scenes() -> None:
    """A chapter with more than four scenes is rejected.
    The plan rule caps scenes at 2-4; five or more is
    beyond what the writer can execute in one chapter and
    usually means the planner split two chapters by
    accident.
    """
    payload = _valid_chapter_payload(148)
    payload["scenes"] = [
        {"location": f"L{i}", "action": "A", "result": "R"}
        for i in range(5)
    ]
    with pytest.raises(RollingValidationError) as exc_info:
        validate_rolling_chapter(
            payload,
            expected_chapter_number=148,
            volume_range=(140, 160),
        )
    assert "scenes" in str(exc_info.value)


def test_validate_rolling_chapter_rejects_incomplete_scene() -> None:
    """A scene with a missing location / action / result
    is rejected. The plan rule: each scene must specify
    the three fields so the writer knows where the
    protagonist is, what they do, and what changes.
    """
    payload = _valid_chapter_payload(148)
    payload["scenes"] = [
        {"location": "灰狼坡", "action": "补齐毒腺", "result": ""},
    ]
    with pytest.raises(RollingValidationError) as exc_info:
        validate_rolling_chapter(
            payload,
            expected_chapter_number=148,
            volume_range=(140, 160),
        )
    assert "scenes" in str(exc_info.value)


# --- Batch validation -------------------------------------------------------


def test_validate_rolling_batch_accepts_well_formed_chapters() -> None:
    """A well-formed batch of three chapters is accepted
    without raising. The batch validator runs the same
    per-chapter checks for every chapter and aggregates
    the results so the caller can fix the entire batch in
    one pass.
    """
    chapters = [
        _valid_chapter_payload(148),
        _valid_chapter_payload(149),
        _valid_chapter_payload(150),
    ]
    validate_rolling_batch(
        chapters,
        expected_chapter_numbers=[148, 149, 150],
        volume_range=(140, 160),
    )


def test_validate_rolling_batch_rejects_when_numbers_dont_match_order() -> None:
    """A batch whose ``chapter_number`` list does not
    match the expected list is rejected wholesale. The
    plan rule: the rolling fill must write each chapter
    at its expected number — silently reordering would
    shift every outline reference.
    """
    chapters = [
        _valid_chapter_payload(149),  # 149, 150, 148 — out of order
        _valid_chapter_payload(150),
        _valid_chapter_payload(148),
    ]
    with pytest.raises(RollingValidationError):
        validate_rolling_batch(
            chapters,
            expected_chapter_numbers=[148, 149, 150],
            volume_range=(140, 160),
        )


def test_validate_rolling_batch_collects_all_failures_not_just_first() -> None:
    """A batch with two broken chapters surfaces both
    failures in the same exception so the operator can
    fix everything in one pass instead of two.
    """
    chapters = [
        _valid_chapter_payload(148),  # well-formed
        _valid_chapter_payload(149),
        _valid_chapter_payload(150),
    ]
    # Break chapter 149 (scenes) and chapter 150 (number)
    chapters[1]["scenes"] = []
    chapters[2]["chapter_number"] = 999
    with pytest.raises(RollingValidationError) as exc_info:
        validate_rolling_batch(
            chapters,
            expected_chapter_numbers=[148, 149, 150],
            volume_range=(140, 160),
        )
    message = str(exc_info.value)
    # The error message must reference both broken
    # chapters so the operator can see what to fix.
    assert "149" in message or "scenes" in message
    assert "150" in message or "chapter_number" in message


def test_validate_rolling_batch_rejects_empty_chapters() -> None:
    """An empty batch is rejected — the caller is asking
    the validator to do nothing useful.
    """
    with pytest.raises(RollingPlanError):
        validate_rolling_batch(
            [],
            expected_chapter_numbers=[],
            volume_range=(140, 160),
        )


def test_rolling_validation_and_outline_adaptation_preserve_chapter_contracts() -> None:
    payload = {**_valid_chapter_payload(148), **CHAPTER_CONTRACT}

    validated = validate_rolling_chapter(
        payload,
        expected_chapter_number=148,
        volume_range=(140, 160),
        require_chapter_contracts=True,
    )
    adapted = rolling_chapter_to_outline_entry(validated)

    assert validated["payoff_contract"] == CHAPTER_CONTRACT["payoff_contract"]
    assert validated["chapter_sop"] == CHAPTER_CONTRACT["chapter_sop"]
    assert adapted["payoff_contract"] == CHAPTER_CONTRACT["payoff_contract"]
    assert adapted["chapter_sop"] == CHAPTER_CONTRACT["chapter_sop"]


def test_rolling_validation_remains_compatible_without_chapter_sop() -> None:
    validated = validate_rolling_chapter(
        _valid_chapter_payload(148),
        expected_chapter_number=148,
        volume_range=(140, 160),
    )

    assert "payoff_contract" not in validated
    assert "chapter_sop" not in validated


def test_disabled_rolling_validation_drops_returned_contract_fields() -> None:
    payload = _valid_chapter_payload(148)
    payload["payoff_contract"] = {"need": "模型夹带的局部字段"}
    payload["chapter_sop"] = {"turn": "模型夹带的局部字段"}

    validated = validate_rolling_chapter(
        payload,
        expected_chapter_number=148,
        volume_range=(148, 160),
        require_chapter_contracts=False,
    )

    assert "payoff_contract" not in validated
    assert "chapter_sop" not in validated


@pytest.mark.parametrize(
    "mutation,error_field",
    [
        (
            lambda payload: payload["payoff_contract"].pop("need"),
            "payoff_contract.need",
        ),
        (
            lambda payload: payload["chapter_sop"].update({"ending_hook": "留下悬念"}),
            "chapter_sop.ending_hook",
        ),
    ],
)
def test_enabled_rolling_contract_validation_rejects_partial_or_vague_values(
    mutation,
    error_field: str,
) -> None:
    payload = {
        **_valid_chapter_payload(148),
        "payoff_contract": dict(CHAPTER_CONTRACT["payoff_contract"]),
        "chapter_sop": dict(CHAPTER_CONTRACT["chapter_sop"]),
    }
    mutation(payload)

    with pytest.raises(RollingValidationError, match=error_field):
        validate_rolling_chapter(
            payload,
            expected_chapter_number=148,
            volume_range=(140, 160),
            require_chapter_contracts=True,
        )
