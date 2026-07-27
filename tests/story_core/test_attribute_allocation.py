from copy import deepcopy

import pytest

from packages.story_core.attribute_allocation import normalize_attribute_allocation_rule


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
