from copy import deepcopy

import pytest

from packages.story_core.attribute_allocation import (
    apply_attribute_allocation,
    attribute_allocation_rule_from_story,
    award_attribute_points,
    normalize_attribute_allocation_rule,
    parse_level,
)


def free_attribute_rule() -> dict[str, object]:
    return {
        "mode": "free",
        "points_per_level": 5,
        "starting_level": 1,
        "base_attributes": {
            "力量": 5,
            "敏捷": 5,
            "体质": 5,
            "智力": 5,
            "精神": 5,
            "幸运": 5,
        },
        "allow_carry": True,
        "respec_rule": "  每周可在主城重置一次，消耗洗点券。  ",
        "ignored": "must not be retained",
    }


def test_normalizes_enabled_free_attribute_rule_to_a_safe_copy() -> None:
    source = free_attribute_rule()
    before = deepcopy(source)

    result = normalize_attribute_allocation_rule(source)

    assert result == {
        "mode": "free",
        "points_per_level": 5,
        "starting_level": 1,
        "base_attributes": {
            "力量": 5,
            "敏捷": 5,
            "体质": 5,
            "智力": 5,
            "精神": 5,
            "幸运": 5,
        },
        "allow_carry": True,
        "respec_rule": "每周可在主城重置一次，消耗洗点券。",
    }
    result["base_attributes"]["力量"] = 99
    assert source == before


def test_returns_empty_mapping_when_starting_level_exceeds_supported_range() -> None:
    rule = free_attribute_rule()
    rule["starting_level"] = 1_000_001

    assert normalize_attribute_allocation_rule(rule) == {}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda rule: rule.update(mode="fixed"),
        lambda rule: rule.update(points_per_level=0),
        lambda rule: rule.update(starting_level=False),
        lambda rule: rule.update(base_attributes={"": 5}),
        lambda rule: rule.update(base_attributes={"力量": 10_001}),
        lambda rule: rule.update(allow_carry="yes"),
        lambda rule: rule.update(respec_rule="   "),
    ],
)
def test_returns_empty_mapping_for_disabled_or_invalid_attribute_rules(mutate) -> None:
    rule = free_attribute_rule()
    mutate(rule)

    assert normalize_attribute_allocation_rule(rule) == {}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2, 2),
        ("Lv.2", 2),
        ("2\u7ea7", 2),
        (True, None),
        ("not a level", None),
    ],
)
def test_parse_level_accepts_existing_level_formats(value, expected) -> None:
    assert parse_level(value) == expected


def test_parse_level_rejects_an_overlong_numeric_string_without_raising() -> None:
    assert parse_level("9" * 5_000) is None


def test_rule_is_read_only_from_the_structured_story_power_spec() -> None:
    rule = free_attribute_rule()
    story = type(
        "Story",
        (),
        {
            "world_context": {
                "power_system_spec": {"attribute_allocation": rule},
                "attribute_allocation": {"mode": "fixed"},
            }
        },
    )()

    assert attribute_allocation_rule_from_story(story) == normalize_attribute_allocation_rule(rule)


def test_award_attribute_points_records_each_new_level_and_is_idempotent() -> None:
    ledger = {"protagonist": {"level": "Lv.3"}}
    rule = free_attribute_rule()

    award_attribute_points(ledger, rule, previous_level="Lv.1", current_level="Lv.3", chapter_number=7)
    award_attribute_points(ledger, rule, previous_level="Lv.1", current_level="Lv.3", chapter_number=7)

    protagonist = ledger["protagonist"]
    assert protagonist["attributes"] == rule["base_attributes"]
    assert protagonist["unallocated_attribute_points"] == 10
    assert protagonist["attribute_point_awards"] == [
        {"level": 2, "points": 5, "chapter": 7},
        {"level": 3, "points": 5, "chapter": 7},
    ]


def test_award_attribute_points_uses_starting_level_when_old_level_is_missing() -> None:
    ledger = {"protagonist": {"level": "Lv.2"}}
    rule = free_attribute_rule()

    award_attribute_points(ledger, rule, previous_level=None, current_level="Lv.2", chapter_number=3)

    assert ledger["protagonist"]["unallocated_attribute_points"] == 5
    assert ledger["protagonist"]["attribute_point_awards"] == [
        {"level": 2, "points": 5, "chapter": 3}
    ]


def test_award_attribute_points_ignores_level_downgrades_without_mutation() -> None:
    ledger = {
        "protagonist": {
            "level": "Lv.2",
            "attributes": {"\u667a\u529b": 5},
            "unallocated_attribute_points": 5,
            "attribute_point_awards": [{"level": 2, "points": 5, "chapter": 3}],
        }
    }
    before = deepcopy(ledger)

    award_attribute_points(ledger, free_attribute_rule(), previous_level="Lv.3", current_level="Lv.2", chapter_number=4)

    assert ledger == before


def test_apply_attribute_allocation_updates_ledger_atomically_and_is_idempotent() -> None:
    ledger = {
        "protagonist": {
            "attributes": {"\u667a\u529b": 5},
            "unallocated_attribute_points": 5,
        }
    }
    directive = {"allocations": {"\u667a\u529b": 5}, "reason": "\u6cd5\u5e08\u8def\u7ebf", "remaining": 0}

    assert apply_attribute_allocation(ledger, directive, free_attribute_rule(), chapter_number=8) is True
    assert apply_attribute_allocation(ledger, directive, free_attribute_rule(), chapter_number=8) is True
    assert ledger["protagonist"]["attributes"] == {"\u667a\u529b": 10}
    assert ledger["protagonist"]["unallocated_attribute_points"] == 0
    assert ledger["protagonist"]["attribute_allocations"] == [
        {
            "chapter": 8,
            "allocations": {"\u667a\u529b": 5},
            "remaining": 0,
            "reason": "\u6cd5\u5e08\u8def\u7ebf",
        }
    ]


@pytest.mark.parametrize(
    "directive",
    [
        {"allocations": {"\u667a\u529b": 6}},
        {"allocations": {"\u667a\u529b": -1}},
        {"allocations": {"\u667a\u529b": 0}},
        {"allocations": {"\u667a\u529b": True}},
        {"allocations": {"\u672a\u77e5": 1}},
        {"allocations": {"\u667a\u529b": 1}, "remaining": 5},
    ],
)
def test_apply_attribute_allocation_rejects_invalid_directives_without_mutation(directive) -> None:
    ledger = {
        "protagonist": {
            "attributes": {"\u667a\u529b": 5},
            "unallocated_attribute_points": 5,
        }
    }
    before = deepcopy(ledger)

    assert apply_attribute_allocation(ledger, directive, free_attribute_rule(), chapter_number=8) is False
    assert ledger == before


def test_apply_attribute_allocation_rejects_ledger_only_attributes_without_mutation() -> None:
    rule = free_attribute_rule()
    rule["base_attributes"].pop("\u5e78\u8fd0")
    ledger = {
        "protagonist": {
            "attributes": {"\u667a\u529b": 5, "\u5e78\u8fd0": 99},
            "unallocated_attribute_points": 5,
        }
    }
    before = deepcopy(ledger)

    assert apply_attribute_allocation(
        ledger,
        {"allocations": {"\u5e78\u8fd0": 1}},
        rule,
        chapter_number=8,
    ) is False
    assert ledger == before
