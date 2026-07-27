import pytest

from packages.story_core.attribute_evidence import (
    has_character_attribute_allocation,
    has_positive_attribute_allocation_confirmation,
    parse_count,
)


def test_attribute_allocation_accepts_modifier_between_action_and_points():
    assert has_character_attribute_allocation("夜烬把刚拿到的五点全部加到智力上", "智力", 5)


def test_attribute_allocation_accepts_completed_real_chapter_action():
    body = (
        "夜烬现在靠火球术刷怪，没必要把点数分散到别处，便把五点全加到了智力上。\n\n"
        "他点下确认，两行新的提示随即跳了出来：【智力：5→10。】【可用属性点：0。】"
    )

    assert has_character_attribute_allocation(body, "智力", 5)


def test_attribute_allocation_keeps_plain_all_to_form_supported():
    assert has_character_attribute_allocation("夜烬把五点全加到智力上", "智力", 5)


@pytest.mark.parametrize("verb", ("加到了", "分配到了", "投入到了"))
def test_attribute_allocation_accepts_only_supported_completed_forms(verb: str):
    assert has_character_attribute_allocation(f"夜烬把五点{verb}智力上", "智力", 5)


@pytest.mark.parametrize("verb", ("分配到", "投入到", "投入了"))
def test_attribute_allocation_rejects_unapproved_completed_forms(verb: str):
    assert not has_character_attribute_allocation(f"夜烬把五点{verb}智力上", "智力", 5)


def test_attribute_allocation_rejects_negated_action_with_modifier_before_points():
    assert not has_character_attribute_allocation("夜烬没有把刚拿到的五点全部加到智力上", "智力", 5)


def test_attribute_allocation_default_rejects_explicit_bystander_subject():
    assert not has_character_attribute_allocation("《神域》里，短发玩家把五点加到智力上", "智力", 5)


def test_attribute_allocation_rejects_bystander_subject_after_protagonist_mention():
    assert not has_character_attribute_allocation(
        "夜烬看着短发玩家把五点加到智力上", "智力", 5, protagonist_aliases={"苏叶", "夜烬"}
    )


def test_attribute_allocation_keeps_protagonist_as_actor_after_bounded_scene_transition():
    assert has_character_attribute_allocation(
        "夜烬看了短发玩家一眼，随后把五点加到智力上", "智力", 5, protagonist_aliases={"苏叶", "夜烬"}
    )


@pytest.mark.parametrize("modifier", ("直接", "果断", "又", "重新", "干脆", "索性", "还是"))
def test_attribute_allocation_accepts_protagonist_subject_with_common_modifier(modifier: str):
    subject = "他" if modifier == "果断" else "夜烬"
    assert has_character_attribute_allocation(
        f"{subject}{modifier}把五点加到智力上",
        "智力",
        5,
        protagonist_aliases={"苏叶", "夜烬"},
    )


def test_attribute_allocation_accepts_confirmation_in_adjacent_paragraph():
    body = "夜烬把五点全部加到智力上。\n\n他点下确认，可用属性点归零。"

    assert has_positive_attribute_allocation_confirmation(body)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", 0),
        ("十", 10),
        ("十一", 11),
        ("二十", 20),
        ("二十五", 25),
        ("一百", 100),
        ("100", 100),
    ],
)
def test_parse_count_supports_common_chinese_and_arabic_numbers(text: str, expected: int):
    assert parse_count(text) == expected


def test_attribute_allocation_accepts_character_action_that_mentions_rules():
    assert has_character_attribute_allocation("夜烬按规则把五点加到智力上", "智力", 5)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("十", 10), ("十一", 11), ("二十", 20), ("二十五", 25), ("一百", 100)],
)
def test_attribute_allocation_matches_common_chinese_number_actions(text: str, expected: int):
    assert has_character_attribute_allocation(f"夜烬把{text}点加到智力上", "智力", expected)
