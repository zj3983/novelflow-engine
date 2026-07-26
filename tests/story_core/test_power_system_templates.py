from __future__ import annotations

from dataclasses import replace

import pytest

from packages.story_core.genre_types import (
    EASTERN_FANTASY,
    GAME_WEBNOVEL,
    GENERIC_WEBNOVEL,
    GenrePlugin,
    ROMANCE,
    RULES_MYSTERY,
    SUSPENSE,
    URBAN,
    XIANXIA,
    XUANHUAN,
)
from packages.story_core.power_system_templates import POWER_SYSTEM_TEMPLATES, copy_power_system_template


BUILTIN_PLUGINS = (
    GENERIC_WEBNOVEL,
    GAME_WEBNOVEL,
    XUANHUAN,
    XIANXIA,
    URBAN,
    ROMANCE,
    SUSPENSE,
    RULES_MYSTERY,
)

REQUIRED_TEMPLATE_KEYS = {
    "system_form",
    "required_sections",
    "progression_shape",
    "branching_rules",
    "resource_rules",
    "cost_rules",
    "conflict_rules",
    "ledger_fields",
    "quality_checks",
}

REQUIRED_SECTIONS = {
    "origin",
    "stages",
    "paths",
    "skills",
    "resources",
    "costs",
    "counters",
    "boundaries",
    "continuity_ledger",
}

EXPECTED_SYSTEM_FORMS = {
    "generic_webnovel": "自适应超凡体系",
    "game_webnovel": "等级职业体系",
    "xuanhuan": "境界血脉体系",
    "xianxia": "修真因果体系",
    "urban": "都市异能体系",
    "romance": "血脉契约共鸣体系",
    "suspense": "超凡调查体系",
    "rules_mystery": "规则权限污染体系",
}


def _default_plugin(plugin_id: str) -> GenrePlugin:
    return GenrePlugin(
        plugin_id=plugin_id,
        name=plugin_id,
        keywords=(),
        core_promises=(),
        ledger_fields=(),
        rulebook={},
        quality_checks=(),
    )


def test_template_registry_contains_exactly_the_canonical_builtin_ids():
    assert set(POWER_SYSTEM_TEMPLATES) == set(EXPECTED_SYSTEM_FORMS)


def test_every_builtin_type_has_complete_power_system_template():
    for plugin in BUILTIN_PLUGINS:
        template = plugin.power_system_template

        assert REQUIRED_TEMPLATE_KEYS <= template.keys()
        assert REQUIRED_SECTIONS <= set(template["required_sections"])
        assert template["system_form"] == EXPECTED_SYSTEM_FORMS[plugin.plugin_id]


def test_game_template_requires_six_classes_and_fixed_milestones():
    template = GAME_WEBNOVEL.power_system_template

    assert template["minimum_path_count"] == 6
    assert template["fixed_milestones"] == [1, 10, 20, 30, 60]


def test_other_templates_require_two_paths_and_at_least_three_stages():
    for plugin in BUILTIN_PLUGINS:
        if plugin is GAME_WEBNOVEL:
            continue

        template = plugin.power_system_template
        assert template["minimum_path_count"] == 2
        assert len(template["progression_shape"]["stages"]) >= 3


def test_genre_plugin_power_template_defaults_to_empty_dict():
    assert EASTERN_FANTASY.power_system_template == {}


def test_genre_plugin_instances_do_not_share_default_power_template():
    first = _default_plugin("first")
    second = _default_plugin("second")

    assert first.power_system_template == second.power_system_template == {}
    assert first.power_system_template is not second.power_system_template

    first.power_system_template["marker"] = True
    assert second.power_system_template == {}


def test_independent_template_copies_are_isolated_under_nested_mutation():
    first = replace(
        GENERIC_WEBNOVEL,
        power_system_template=copy_power_system_template("generic_webnovel"),
    )
    second = replace(
        GENERIC_WEBNOVEL,
        power_system_template=copy_power_system_template("generic_webnovel"),
    )
    marker = "独立副本标记"

    first.power_system_template["progression_shape"]["stages"][0]["name"] = marker
    first.power_system_template["required_sections"].append(marker)

    assert second.power_system_template["progression_shape"]["stages"][0]["name"] == "起步阶段"
    assert marker not in second.power_system_template["required_sections"]
    assert (
        POWER_SYSTEM_TEMPLATES["generic_webnovel"]["progression_shape"]["stages"][0]["name"]
        == "起步阶段"
    )
    assert marker not in POWER_SYSTEM_TEMPLATES["generic_webnovel"]["required_sections"]


def test_plugin_templates_are_deep_copies_of_immutable_defaults():
    template = GENERIC_WEBNOVEL.power_system_template
    marker = "测试隔离字段"

    try:
        template["required_sections"].append(marker)
        template["progression_shape"]["stages"][0]["name"] = marker

        assert marker not in POWER_SYSTEM_TEMPLATES["generic_webnovel"]["required_sections"]
        assert POWER_SYSTEM_TEMPLATES["generic_webnovel"]["progression_shape"]["stages"][0]["name"] != marker
    finally:
        template["required_sections"].remove(marker)
        template["progression_shape"]["stages"][0]["name"] = "起步阶段"

    with pytest.raises(TypeError):
        POWER_SYSTEM_TEMPLATES["generic_webnovel"]["system_form"] = "被篡改"
