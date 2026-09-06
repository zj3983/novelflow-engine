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
