from copy import deepcopy

import pytest

from packages.story_core.attribute_allocation import (
    apply_attribute_allocation,
    attribute_allocation_context,
    attribute_allocation_rule_from_story,
    award_attribute_points,
    normalize_attribute_allocation_rule,
    parse_level,
    plan_handles_attribute_points,
    planned_level_target,
    rebuild_attribute_progression,
    validate_attribute_allocation_decision,
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


@pytest.mark.parametrize("value", [1_000_001, "9999999"])
def test_parse_level_rejects_values_above_the_supported_level_bound(value) -> None:
    assert parse_level(value) is None


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


def test_award_attribute_points_rejects_an_excessive_level_jump_without_mutation() -> None:
    ledger = {"protagonist": {"level": "Lv.1"}}
    before = deepcopy(ledger)

    award_attribute_points(ledger, free_attribute_rule(), previous_level=1, current_level=1_000_000, chapter_number=4)

    assert ledger == before


def test_award_attribute_points_does_not_initialize_damaged_attributes_without_a_new_award() -> None:
    ledger = {"protagonist": {"level": "Lv.1", "attributes": "damaged"}}
    before = deepcopy(ledger)

    award_attribute_points(ledger, free_attribute_rule(), previous_level=1, current_level=1, chapter_number=4)

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


def test_apply_attribute_allocation_rejects_damaged_existing_attributes_without_mutation() -> None:
    ledger = {
        "protagonist": {
            "attributes": "damaged",
            "unallocated_attribute_points": 5,
        }
    }
    before = deepcopy(ledger)

    assert apply_attribute_allocation(
        ledger,
        {"allocations": {"\u667a\u529b": 1}, "remaining": 4},
        free_attribute_rule(),
        chapter_number=8,
    ) is False


    assert ledger == before


def test_rebuild_attribute_progression_replays_each_chapter_award_before_allocations() -> None:
    rule = free_attribute_rule()
    strength, intelligence, luck = (
        list(rule["base_attributes"])[index] for index in (0, 3, 5)
    )
    baseline = {
        "level": "Lv.2",
        "attributes": {**rule["base_attributes"], strength: 5, intelligence: 10},
        "unallocated_attribute_points": 0,
        "attribute_point_awards": [{"level": 2, "points": 5, "chapter": 2}],
        "attribute_allocations": [
            {"chapter": 2, "allocations": {intelligence: 5}, "remaining": 0, "reason": "new build"}
        ],
    }
    future = [
        (
            3,
            {
                "attribute_point_awards": [
                    {"level": 2, "points": 5, "chapter": 2},
                    {"level": 3, "points": 5, "chapter": 3},
                ],
                "attribute_allocations": [
                    {"chapter": 2, "allocations": {strength: 5}, "remaining": 0, "reason": "old build"},
                    {"chapter": 3, "allocations": {intelligence: 2}, "remaining": 3, "reason": "spell"},
                ],
            },
        ),
        (
            4,
            {
                "attribute_point_awards": [
                    {"level": 2, "points": 5, "chapter": 2},
                    {"level": 3, "points": 5, "chapter": 3},
                ],
                "attribute_allocations": [
                    {"chapter": 3, "allocations": {intelligence: 2}, "remaining": 3, "reason": "spell"},
                    {"chapter": 4, "allocations": {luck: 3}, "remaining": 0, "reason": "drop"},
                ],
            },
        ),
    ]
    before = deepcopy((baseline, future))

    rebuilt = rebuild_attribute_progression(rule, 2, baseline, future)

    assert (baseline, future) == before
    assert rebuilt[2]["attributes"][strength] == 5
    assert rebuilt[2]["attributes"][intelligence] == 10
    assert rebuilt[3]["attributes"][intelligence] == 12
    assert rebuilt[3]["unallocated_attribute_points"] == 3
    assert rebuilt[4]["attributes"][luck] == 8
    assert rebuilt[4]["unallocated_attribute_points"] == 0
    assert [item["chapter"] for item in rebuilt[4]["attribute_point_awards"]] == [2, 3]
    assert [item["chapter"] for item in rebuilt[4]["attribute_allocations"]] == [2, 3, 4]


def test_rebuild_attribute_progression_rejects_future_overspend_without_mutating_inputs() -> None:
    rule = free_attribute_rule()
    intelligence, luck = (list(rule["base_attributes"])[index] for index in (3, 5))
    baseline = {
        "attributes": {**rule["base_attributes"], intelligence: 10},
        "unallocated_attribute_points": 0,
        "attribute_point_awards": [{"level": 2, "points": 5, "chapter": 2}],
        "attribute_allocations": [
            {"chapter": 2, "allocations": {intelligence: 5}, "remaining": 0, "reason": "new build"}
        ],
    }
    future = [
        (
            3,
            {
                "attribute_point_awards": [{"level": 2, "points": 5, "chapter": 2}],
                "attribute_allocations": [
                    {"chapter": 3, "allocations": {luck: 1}, "remaining": 0, "reason": "illegal"}
                ],
            },
        )
    ]
    before = deepcopy((baseline, future))

    with pytest.raises(ValueError, match="^attribute_rebase_invalid_allocation:3$"):
        rebuild_attribute_progression(rule, 2, baseline, future)

    assert (baseline, future) == before


def test_attribute_context_uses_base_attributes_without_mutating_ledger() -> None:
    story = type(
        "Story",
        (),
        {
            "world_context": {"power_system_spec": {"attribute_allocation": free_attribute_rule()}},
            "progression_ledger": {"protagonist": {"level": "Lv.1", "unallocated_attribute_points": 2}},
        },
    )()
    before = deepcopy(story.progression_ledger)

    context = attribute_allocation_context(story)

    assert context["attributes"] == free_attribute_rule()["base_attributes"]
    assert context["available_points"] == 2
    assert story.progression_ledger == before


def test_attribute_context_ignores_future_outline_levels_and_uses_current_plan_level() -> None:
    story = type(
        "Story",
        (),
        {
            "world_context": {"power_system_spec": {"attribute_allocation": free_attribute_rule()}},
            "progression_ledger": {"protagonist": {"level": "Lv.1"}},
            "outline": "终章升到Lv.60",
        },
    )()

    assert planned_level_target({"event_plan": {"level": "Lv.2"}, "outline": "Lv.60"}) == 2
    assert attribute_allocation_context(story)["available_points"] == 0


@pytest.mark.parametrize(
    ("plan", "expected"),
    [
        ({"event_plan": {"attribute_allocation_level_target": 2}}, 2),
        ({"event_plan": {"level": "Lv.2"}}, 2),
        ({"event_plan": {"state_delta": {"protagonist": {"level": "Lv.2"}}}}, 2),
        ({"state_delta": {"protagonist": {"level": "Lv.2"}}}, 2),
        ({"scene_cards": [{"state_delta": {"protagonist": {"level": "Lv.2"}}}]}, 2),
    ],
)
def test_planned_level_target_reads_only_explicit_current_protagonist_paths(plan, expected) -> None:
    assert planned_level_target(plan) == expected


def test_planned_level_target_ignores_enemy_future_and_cyclic_nodes() -> None:
    plan = {
        "event_plan": {
            "enemy": {"level": "Lv.60"},
            "future_hook": {"level": "Lv.60"},
        },
        "scene_cards": [{"monster": {"level": "Lv.60"}}],
    }
    plan["event_plan"]["cycle"] = plan

    assert planned_level_target(plan) is None


def test_planned_level_target_checks_at_most_six_scene_cards() -> None:
    plan = {"scene_cards": [{} for _ in range(6)] + [{"state_delta": {"protagonist": {"level": "Lv.2"}}}]}

    assert planned_level_target(plan) is None


def test_attribute_point_handling_ignores_future_forbidden_and_cyclic_plan_data() -> None:
    plan = {
        "event_plan": {
            "chapter_end_hook": {"content": "下一章分配属性点"},
            "next_focus": "未来加点路线",
            "must_not_write": "禁止分配属性点",
            "avoid": "避免加点",
            "future": {"turn": "打开面板分配属性点"},
        },
        "scene_cards": [
            {"purpose": "不要分配属性点", "must_show": ["禁止加点"]},
        ],
    }
    plan["event_plan"]["cycle"] = plan

    assert plan_handles_attribute_points(plan) is False


def test_attribute_point_handling_detects_current_action_only() -> None:
    assert plan_handles_attribute_points({"event_plan": {"turn": "打开面板分配属性点"}}) is True


def test_attribute_context_uses_flat_legacy_ledger_level_for_planned_allocation() -> None:
    story = type(
        "Story",
        (),
        {
            "world_context": {"power_system_spec": {"attribute_allocation": free_attribute_rule()}},
            "progression_ledger": {"level": "Lv.2", "unallocated_attribute_points": 0},
        },
    )()

    context = attribute_allocation_context(
        story,
        {
            "event_plan": {
                "level": "Lv.3",
                "attribute_allocation_decision": {"mode": "allocate", "allocations": {"智力": 5}, "remaining": 0},
            }
        },
    )

    assert context["chapter_decision"] == {
        "mode": "allocate",
        "allocations": {"智力": 5},
        "remaining": 0,
    }


def test_attribute_context_uses_flat_legacy_available_points_for_carry() -> None:
    story = type(
        "Story",
        (),
        {
            "world_context": {"power_system_spec": {"attribute_allocation": free_attribute_rule()}},
            "progression_ledger": {"level": "Lv.2", "unallocated_attribute_points": 5},
        },
    )()

    context = attribute_allocation_context(
        story,
        {"event_plan": {"attribute_allocation_decision": {"mode": "carry", "remaining": 5, "reason": "留给转职"}}},
    )

    assert context["available_points"] == 5
    assert context["chapter_decision"] == {"mode": "carry", "remaining": 5, "reason": "留给转职"}


def test_attribute_context_keeps_three_latest_valid_allocation_records() -> None:
    story = type(
        "Story",
        (),
        {
            "world_context": {"power_system_spec": {"attribute_allocation": free_attribute_rule()}},
            "progression_ledger": {
                "protagonist": {
                    "attribute_allocations": [
                        {"chapter": 1},
                        {"chapter": 2},
                        "damaged",
                        {"chapter": 3},
                    ]
                }
            },
        },
    )()

    assert [item["chapter"] for item in attribute_allocation_context(story)["latest_allocations"]] == [1, 2, 3]


def test_validate_allocation_decision_accepts_exact_spend_and_carry_rules() -> None:
    rule = free_attribute_rule()

    assert validate_attribute_allocation_decision(
        {"mode": "allocate", "allocations": {"智力": 5}, "remaining": 0}, rule, 5
    ) == {"mode": "allocate", "allocations": {"智力": 5}, "remaining": 0}
    assert validate_attribute_allocation_decision(
        {"mode": "carry", "remaining": 5, "reason": "留给转职"}, rule, 5
    ) == {"mode": "carry", "remaining": 5, "reason": "留给转职"}


@pytest.mark.parametrize(
    "decision",
    [
        {"mode": "allocate", "allocations": {"智力": 6}, "remaining": 0},
        {"mode": "allocate", "allocations": {"未知": 1}, "remaining": 4},
        {"mode": "allocate", "allocations": {"智力": 5}, "remaining": 1},
    ],
)
def test_validate_allocation_decision_rejects_invalid_spend(decision) -> None:
    assert validate_attribute_allocation_decision(decision, free_attribute_rule(), 5) == {}


def test_validate_allocation_decision_rejects_carry_when_rule_disallows_it() -> None:
    rule = free_attribute_rule()
    rule["allow_carry"] = False

    assert validate_attribute_allocation_decision(
        {"mode": "carry", "remaining": 5, "reason": "留给转职"}, rule, 5
    ) == {}
