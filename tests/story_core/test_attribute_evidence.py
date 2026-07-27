import time

import pytest

from packages.story_core.attribute_evidence import (
    character_attribute_carry_choice_evidence,
    has_character_attribute_carry_choice_and_reason,
    has_character_attribute_allocation,
    has_positive_attribute_allocation_confirmation,
    parse_count,
    real_character_attribute_allocation_point_values,
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


@pytest.mark.parametrize("verb", ("投入到", "投入了"))
def test_attribute_allocation_generic_detection_rejects_unapproved_invest_forms(verb: str):
    assert not has_character_attribute_allocation(f"夜烬把五点{verb}智力上")


@pytest.mark.parametrize("verb", ("投入到", "投入了"))
def test_attribute_allocation_confirmation_rejects_unapproved_invest_forms(verb: str):
    body = f"夜烬把五点{verb}智力上。随后他点下确认，可用属性点归零。"

    assert not has_positive_attribute_allocation_confirmation(body)


def test_attribute_allocation_confirmation_keeps_completed_invest_form_supported():
    body = "夜烬把五点投入到了智力上。随后他点下确认，可用属性点归零。"

    assert has_character_attribute_allocation(body)
    assert has_positive_attribute_allocation_confirmation(body)


def test_attribute_allocation_rejects_negated_action_with_modifier_before_points():
    assert not has_character_attribute_allocation("夜烬没有把刚拿到的五点全部加到智力上", "智力", 5)


def test_attribute_allocation_rejects_quoted_conditional_hypothesis():
    body = "短发玩家说：‘如果夜烬把五点加到智力上，确认后智力就会从五变成十，可用属性点归零。’"

    assert not has_character_attribute_allocation(body, "智力", 5, protagonist_aliases={"夜烬"})
    assert not has_positive_attribute_allocation_confirmation(body, protagonist_aliases={"夜烬"})


def test_attribute_allocation_accepts_real_action_after_quoted_hypothesis():
    body = (
        "短发玩家说：‘如果夜烬把五点加到智力上，确认后智力就会从五变成十。’"
        "夜烬没有接话，转身打开面板，把五点加到智力上。随后他点下确认，可用属性点归零。"
    )

    assert has_character_attribute_allocation(body, "智力", 5, protagonist_aliases={"夜烬"})
    assert has_positive_attribute_allocation_confirmation(body, protagonist_aliases={"夜烬"})


def test_attribute_allocation_accepts_actual_turn_after_same_sentence_condition():
    body = "“如果保留五点会更灵活”，夜烬还是把五点加到智力上。随后他点下确认，可用属性点归零。"

    assert has_character_attribute_allocation(body, "智力", 5, protagonist_aliases={"夜烬"})
    assert has_positive_attribute_allocation_confirmation(body, protagonist_aliases={"夜烬"})


@pytest.mark.parametrize(
    "body",
    [
        "如果夜烬把五点加到智力上，确认后智力就会从五变成十。",
        "如果拿到五点，夜烬就把五点加到智力上。",
        "如果拿到五点，夜烬会把五点加到智力上。",
        "如果拿到五点，夜烬把五点加到智力上。",
        "如果拿到五点，夜烬还是把五点加到智力上。",
    ],
)
def test_attribute_allocation_rejects_conditional_clause_or_conditional_continuation(body: str):
    assert not has_character_attribute_allocation(body, "智力", 5, protagonist_aliases={"夜烬"})


@pytest.mark.parametrize(
    "body",
    [
        "若是拿到五点，夜烬把五点加到智力上。",
        "若要拿到五点，夜烬把五点加到智力上。",
        "若有五点，夜烬把五点加到智力上。",
        "若他拿到五点，夜烬把五点加到智力上。",
        "若玩家拿到五点，夜烬把五点加到智力上。",
    ],
)
def test_attribute_allocation_rejects_explicit_ruo_conditions(body: str):
    assert not has_character_attribute_allocation(body, "智力", 5, protagonist_aliases={"夜烬"})


@pytest.mark.parametrize(
    ("body", "aliases"),
    [
        ("若尘把五点加到智力上。", {"若尘"}),
        ("夜烬若有所思了片刻，还是把五点加到智力上。", {"夜烬"}),
    ],
)
def test_attribute_allocation_keeps_non_conditional_ruo_words_as_real_narration(body: str, aliases: set[str]):
    assert has_character_attribute_allocation(body, "智力", 5, protagonist_aliases=aliases)


def test_attribute_allocation_rejects_english_single_quoted_and_unclosed_actions():
    quoted = "短发玩家说：'夜烬把五点加到智力上，确认后可用属性点归零。'"
    unclosed = "短发玩家说：'夜烬把五点加到智力上，确认后可用属性点归零。"

    assert not has_character_attribute_allocation(quoted, "智力", 5, protagonist_aliases={"夜烬"})
    assert not has_character_attribute_allocation(unclosed, "智力", 5, protagonist_aliases={"夜烬"})


def test_attribute_allocation_does_not_treat_apostrophes_as_quotes():
    body = "Players' choice并不重要，I don't care，夜烬把五点加到智力上。"

    assert has_character_attribute_allocation(body, "智力", 5, protagonist_aliases={"夜烬"})


def test_attribute_allocation_lists_real_action_point_values_without_parsing_attribute_names():
    body = "夜烬把五点加到幸运上。接着他把一点加到敏捷上。"

    assert real_character_attribute_allocation_point_values(body, protagonist_aliases={"夜烬"}) == [5, 1]


def test_attribute_allocation_quote_scan_handles_long_text_promptly():
    body = ("'如果拿到五点，夜烬把五点加到智力上。'\n" * 600) + "夜烬把五点加到智力上。"
    started = time.perf_counter()

    assert has_character_attribute_allocation(body, "智力", 5, protagonist_aliases={"夜烬"})
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    "body",
    [
        "短发玩家说：‘夜烬决定留着，因为等转职以后再分配。’",
        "如果拿到五点，夜烬决定留着，因为等转职以后再分配。",
    ],
)
def test_attribute_carry_rejects_quoted_or_conditional_choices(body: str):
    assert has_character_attribute_carry_choice_and_reason(
        body, "留给转职", protagonist_aliases={"夜烬"}
    ) == (False, False)


def test_attribute_carry_accepts_real_protagonist_choice_and_reason():
    body = "夜烬看着可用属性点还剩五点，决定留着，因为等转职以后再分配。"

    assert has_character_attribute_carry_choice_and_reason(
        body, "留给转职", protagonist_aliases={"夜烬"}
    ) == (True, True)


def test_attribute_carry_binds_remaining_to_the_real_protagonist_choice():
    body = "夜烬看着可用属性点还剩五点，决定留着，因为等转职以后再分配。短发玩家说：‘我还剩四点。’"

    assert character_attribute_carry_choice_evidence(
        body, "留给转职", protagonist_aliases={"夜烬"}
    ) == (True, True, 5)


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
