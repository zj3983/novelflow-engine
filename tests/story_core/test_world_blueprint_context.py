from copy import deepcopy

import pytest

from packages.story_core.world_blueprint_context import (
    flatten_selected_rules,
    merge_world_blueprint,
    select_world_context,
)


def test_merge_world_blueprint_preserves_unpatched_modules_without_mutating_inputs():
    current = {
        "world_rules": ["旧规则"],
        "economy_rules": ["铜币价格必须有锚点。"],
        "quest_network": {
            "active_chains": [{"name": "灰烬村异常链", "stages": ["清道夫委托"]}]
        },
    }
    patch = {"world_rules": ["新规则"]}
    original_current = deepcopy(current)
    original_patch = deepcopy(patch)

    merged = merge_world_blueprint(current, patch)

    assert merged == {
        "world_rules": ["新规则"],
        "economy_rules": ["铜币价格必须有锚点。"],
        "quest_network": {
            "active_chains": [{"name": "灰烬村异常链", "stages": ["清道夫委托"]}]
        },
    }
    assert current == original_current
    assert patch == original_patch

    merged["economy_rules"].append("仅修改结果。")
    merged["quest_network"]["active_chains"][0]["stages"].append("仅修改结果。")
    assert current == original_current


def test_merge_world_blueprint_treats_non_dict_values_as_empty_dicts():
    assert merge_world_blueprint(["invalid"], {"premise": "新世界"}) == {"premise": "新世界"}
    assert merge_world_blueprint({"premise": "旧世界"}, "invalid") == {"premise": "旧世界"}
    assert merge_world_blueprint(None, None) == {}


@pytest.mark.parametrize(
    ("field", "relevance_text"),
    [
        ("power_system", "主角第一次参加战斗。"),
        ("progression_rules", "主角终于升级。"),
        ("economy_rules", "主角前往交易行。"),
        ("quest_rules", "主角接受委托。"),
        ("faction_rules", "公会派人接触主角。"),
        ("panel_rules", "主角检查角色面板。"),
        ("reality_bridge_rules", "主角提现支付房租。"),
    ],
)
def test_select_world_context_selects_rule_modules_by_chinese_keywords(field, relevance_text):
    blueprint = {
        "power_system": ["战斗规则"],
        "progression_rules": ["成长规则"],
        "economy_rules": ["交易规则"],
        "quest_rules": ["任务规则"],
        "faction_rules": ["势力规则"],
        "panel_rules": ["面板规则"],
        "reality_bridge_rules": ["现实规则"],
    }

    selected = select_world_context(blueprint, relevance_text)

    assert selected[field] == blueprint[field]
    assert set(selected) == {field}


def test_select_world_context_does_not_match_faction_rules_for_english_npc_only():
    blueprint = {"faction_rules": ["势力规则"]}

    selected = select_world_context(blueprint, "NPC")

    assert selected == {}


def test_select_world_context_keeps_trade_rules_but_omits_unrelated_quest_network():
    blueprint = {
        "premise": "两个世界的价值可以受限流转。",
        "world_rules": ["基础一", "基础二", "基础三"],
        "power_system": ["战斗规则"],
        "economy_rules": [f"交易规则{i}" for i in range(1, 6)],
        "quest_rules": ["任务必须登记。"],
        "reality_bridge_rules": [f"现实规则{i}" for i in range(1, 6)],
        "quest_network": {
            "active_chains": [
                {
                    "name": "灰烬村异常链",
                    "description": "清道夫委托会解锁后坡巡查。",
                    "stages": ["完成清道夫委托", "后坡巡查"],
                }
            ]
        },
    }

    selected = select_world_context(
        blueprint,
        "在交易行出售材料，把现实到账提现后支付房租。",
    )

    assert selected["premise"] == blueprint["premise"]
    assert selected["world_rules"] == ["基础一", "基础二"]
    assert selected["economy_rules"]
    assert selected["reality_bridge_rules"]
    assert "power_system" not in selected
    assert "quest_rules" not in selected
    assert "quest_network" not in selected
    assert len(flatten_selected_rules(selected)) <= 8


def test_select_world_context_keeps_only_the_matching_active_quest_chain():
    blueprint = {
        "quest_rules": ["委托完成后才能领取后续任务。"],
        "quest_network": {
            "active_chains": [
                {
                    "name": "灰烬村异常链",
                    "description": "清道夫委托完成后，守卫会开放新的调查入口。",
                    "stages": ["完成清道夫委托", "取得后坡巡查路线"],
                },
                {
                    "name": "沼泽异常链",
                    "description": "完成沼泽委托后，药剂师追查毒腺短缺。",
                    "stages": ["完成沼泽委托", "调查沼泽"],
                },
            ],
            "reward_rules": ["奖励必须受任务难度约束。"],
        },
    }
    original = deepcopy(blueprint)

    selected = select_world_context(
        blueprint,
        "完成清道夫委托后，守卫交出后坡巡查路线。",
    )

    assert selected["quest_rules"] == blueprint["quest_rules"]
    assert selected["quest_network"] == {
        "active_chains": [blueprint["quest_network"]["active_chains"][0]]
    }
    assert blueprint == original

    selected["quest_network"]["active_chains"][0]["stages"].append("仅修改结果")
    assert blueprint == original


def test_select_world_context_ignores_generic_completion_text_shared_by_unrelated_chains():
    blueprint = {
        "quest_network": {
            "active_chains": [
                {
                    "name": "东门巡查链",
                    "description": "完成任务后去东门巡查。",
                },
                {
                    "name": "西桥采集链",
                    "description": "完成任务后去西桥采集。",
                },
            ]
        }
    }

    selected = select_world_context(blueprint, "完成任务后再回来")

    assert selected == {}


def test_select_world_context_matches_full_chain_name_without_quest_gate_words():
    chain = {
        "name": "沼泽异常链",
        "description": "药剂师追查毒腺短缺。",
    }
    blueprint = {"quest_network": {"active_chains": [chain]}}

    selected = select_world_context(blueprint, "继续追查沼泽异常链")

    assert selected == {"quest_network": {"active_chains": [chain]}}


def test_select_world_context_prefers_the_most_specific_matching_chain_name():
    shorter_chain = {"name": "沼泽异常链", "description": "调查沼泽异动。"}
    specific_chain = {"name": "黑水沼泽异常链", "description": "调查黑水污染。"}
    fuzzy_chain = {"name": "污染调查线", "description": "黑水沼泽出现异常。"}
    blueprint = {
        "quest_network": {
            "active_chains": [shorter_chain, specific_chain, fuzzy_chain]
        }
    }

    selected = select_world_context(blueprint, "继续追查黑水沼泽异常链")

    assert selected == {"quest_network": {"active_chains": [specific_chain]}}


def test_select_world_context_keeps_unrelated_full_chain_name_matches():
    swamp_chain = {"name": "沼泽异常链"}
    mine_chain = {"name": "矿洞失踪链"}
    blueprint = {"quest_network": {"active_chains": [swamp_chain, mine_chain]}}

    selected = select_world_context(
        blueprint,
        "追查沼泽异常链，同时调查矿洞失踪链。",
    )

    assert selected == {
        "quest_network": {"active_chains": [swamp_chain, mine_chain]}
    }


def test_select_world_context_matches_two_character_npc_link_identifier():
    chain = {
        "name": "药铺支线",
        "description": "询问药材来路。",
        "npc_links": ["洛婶"],
    }
    blueprint = {"quest_network": {"active_chains": [chain]}}

    selected = select_world_context(blueprint, "去找洛婶")

    assert selected == {"quest_network": {"active_chains": [chain]}}


@pytest.mark.parametrize("short_name", ["洛婶", "铁栓"])
def test_select_world_context_matches_short_name_from_production_npc_links(short_name):
    chain = {
        "name": "村内协作链",
        "npc_links": ["药剂师洛婶", "仓库管理员铁栓"],
    }
    blueprint = {"quest_network": {"active_chains": [chain]}}

    selected = select_world_context(blueprint, f"去找{short_name}")

    assert selected == {"quest_network": {"active_chains": [chain]}}


def test_select_world_context_does_not_derive_generic_npc_role_short_names():
    blueprint = {
        "quest_network": {
            "active_chains": [
                {"name": "东门巡逻链", "npc_links": ["东门守卫"]},
                {"name": "西门巡逻链", "npc_links": ["守卫"]},
            ]
        }
    }

    selected = select_world_context(blueprint, "去找守卫")

    assert selected == {}


@pytest.mark.parametrize(
    ("identifier_key", "identifier"),
    [("name", "后坡"), ("npc", "洛婶"), ("npc_name", "铁栓")],
)
def test_select_world_context_matches_name_like_identifiers_in_stage_dicts(
    identifier_key,
    identifier,
):
    chain = {
        "name": "村外线索链",
        "stages": [{identifier_key: identifier, "description": "推进调查。"}],
    }
    blueprint = {"quest_network": {"active_chains": [chain]}}

    selected = select_world_context(blueprint, f"去找{identifier}")

    assert selected == {"quest_network": {"active_chains": [chain]}}


def test_select_world_context_ignores_non_dict_active_chain_entries():
    chain = {
        "name": "灰烬村异常链",
        "description": "追查村外的异常痕迹。",
    }
    blueprint = {
        "quest_network": {
            "active_chains": ["灰烬村异常链", 17, chain],
        }
    }

    selected = select_world_context(blueprint, "继续追查灰烬村异常链任务")

    assert selected == {"quest_network": {"active_chains": [chain]}}


def test_select_world_context_round_robins_long_matching_rule_modules():
    blueprint = {
        "economy_rules": [f"交易规则{i}" for i in range(1, 8)],
        "reality_bridge_rules": [f"现实规则{i}" for i in range(1, 8)],
    }

    selected = select_world_context(
        blueprint,
        "交易所得提现到现实余额。",
        max_rules=4,
    )

    assert selected["economy_rules"] == ["交易规则1", "交易规则2"]
    assert selected["reality_bridge_rules"] == ["现实规则1", "现实规则2"]
    assert len(flatten_selected_rules(selected)) == 4


@pytest.mark.parametrize("max_rules", ["8", None, True, -1])
def test_select_world_context_rejects_invalid_max_rules(max_rules):
    with pytest.raises(ValueError):
        select_world_context({"world_rules": ["基础规则"]}, "", max_rules=max_rules)


def test_select_world_context_accepts_zero_max_rules():
    selected = select_world_context(
        {"premise": "保留前提", "world_rules": ["基础规则"]},
        "",
        max_rules=0,
    )

    assert selected == {"premise": "保留前提"}


def test_flatten_selected_rules_uses_rule_field_order():
    selected = {
        "reality_bridge_rules": ["现实"],
        "quest_rules": ["任务"],
        "world_rules": ["基础一", "基础二"],
        "economy_rules": ["经济"],
        "power_system": ["力量"],
        "progression_rules": ["成长"],
        "faction_rules": ["势力"],
        "panel_rules": ["面板"],
    }

    assert flatten_selected_rules(selected) == [
        "基础一",
        "基础二",
        "力量",
        "成长",
        "经济",
        "任务",
        "势力",
        "面板",
        "现实",
    ]
