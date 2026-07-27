from copy import deepcopy
import json

import pytest

import packages.story_core.world_blueprint_context as blueprint_context
from packages.story_core.power_systems import validate_power_system_spec
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


def test_select_world_context_keeps_only_named_relevant_entities_without_mutating_input():
    blueprint = {
        "locations": [
            {"name": "灰烬村", "description": "新手村"},
            {"title": "后坡", "description": "巡查区域"},
            {"name": "白河仓库", "description": "材料交易点"},
            {"name": "黑水沼泽", "description": "无关区域"},
            "不是实体",
        ],
        "factions": [
            {"name": "灰烬村守卫队", "description": "村落守卫"},
            {"title": "清道夫公会", "description": "委托方"},
            {"name": "白河商会", "description": "收购方"},
            {"name": "赤岩军团", "description": "无关势力"},
            {"description": "没有名称"},
        ],
    }
    original = deepcopy(blueprint)

    selected = select_world_context(
        blueprint,
        "从灰烬村前往后坡，向灰烬村守卫队提交清道夫公会委托，再去白河仓库联系白河商会。",
    )

    assert selected["locations"] == blueprint["locations"][:3]
    assert selected["factions"] == blueprint["factions"][:3]
    selected["locations"][0]["description"] = "只修改结果"
    selected["factions"][0]["description"] = "只修改结果"
    assert blueprint == original


def test_select_world_context_omits_unmatched_entities_and_non_chapter_blueprint_fields():
    selected = select_world_context(
        {
            "locations": [{"name": "黑水沼泽"}],
            "factions": [{"name": "赤岩军团"}],
            "monster_profiles": [{"name": "灰狼"}],
            "server_runtime": {"online": True},
            "current_arc": "开服篇",
            "opening_arc": {"goal": "开服"},
            "volume_plan": {"title": "第一卷"},
            "longform_framework": {"chapters": 300},
        },
        "提交灰烬村委托",
    )

    assert selected == {}


def test_select_world_context_matches_entity_title_when_name_is_also_present():
    location = {"name": "location-17", "title": "后坡", "description": "巡查区域"}

    selected = select_world_context({"locations": [location]}, "开启后坡巡查")

    assert selected == {"locations": [location]}


def test_select_world_context_ignores_invalid_duplicate_rules_without_spending_budget():
    selected = select_world_context(
        {
            "world_rules": [None, "", " 基础规则 ", "基础规则", 17],
            "quest_rules": ["", " 任务规则 ", "任务规则"],
            "economy_rules": [" 经济规则 "],
        },
        "提交任务并交易材料",
        max_rules=3,
    )

    assert selected == {
        "world_rules": ["基础规则"],
        "economy_rules": ["经济规则"],
        "quest_rules": ["任务规则"],
    }
    assert len(flatten_selected_rules(selected)) == 3


def test_select_world_context_dedupes_rules_across_modules_without_starving_next_rule():
    shared_rule = "shared verification rule"
    quest_rule = "quest-specific follow-up"

    selected = select_world_context(
        {
            "world_rules": [shared_rule],
            "economy_rules": [shared_rule],
            "quest_rules": [shared_rule, quest_rule],
        },
        "提交任务并交易材料",
        max_rules=2,
    )

    assert flatten_selected_rules(selected) == [shared_rule, quest_rule]
    assert sum(
        rule == shared_rule
        for rule in flatten_selected_rules(selected)
    ) == 1


def test_select_world_context_prefers_longest_entity_names_and_ignores_one_character_names():
    blackwater = {"name": "黑水王城", "description": "北境主城"}
    white_river = {"name": "白河村", "description": "河畔村落"}
    selected = select_world_context(
        {
            "locations": [
                {"name": "城"},
                {"name": "王城"},
                blackwater,
                white_river,
            ]
        },
        "从黑水王城出发，再前往白河村。",
    )

    assert selected == {"locations": [blackwater, white_river]}


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


def _structured_power_spec() -> dict:
    return {
        "name": "神域职业体系",
        "origin": ["觉醒石授予职业权能"],
        "stages": [
            {"name": "见习者", "level": 1, "entry": "创建角色", "change": "获得通用能力", "failure": "重新建号"},
            {"name": "正式职业", "level": 10, "entry": "完成转职任务", "change": "获得职业资源", "failure": "任务冷却"},
            {"name": "专精", "level": 20, "entry": "完成专精试炼", "change": "强化战斗方向", "failure": "材料损失"},
            {"name": "进阶职业", "level": 30, "entry": "完成分支任务", "change": "获得分支能力", "failure": "晋升延期"},
            {"name": "传承", "level": 60, "entry": "完成传承试炼", "change": "获得职业权柄", "failure": "传承反噬"},
        ],
        "paths": [
            {
                "name": "法师",
                "role": "远程输出",
                "core_resource": "法力",
                "weapons": ["法杖"],
                "armor": ["布甲"],
                "skill_categories": ["元素法术"],
                "combat_loop": "施法叠印记后引爆",
                "branches": ["元素法师", "秘术法师"],
                "advancement": ["收集元素核心"],
            },
            {
                "name": "战士",
                "role": "近战承伤",
                "core_resource": "怒气",
                "weapons": ["剑盾"],
                "branches": ["盾战士", "狂战士"],
                "advancement": ["完成战团试炼"],
            },
        ],
        "skills": ["技能由导师和技能书授予"],
        "equipment": ["装备受职业熟练度限制"],
        "resources": ["职业资源通过战斗恢复"],
        "advancement": ["晋升必须同时满足等级、任务和材料"],
        "costs": ["透支会造成虚弱"],
        "counters": ["沉默克制持续施法"],
        "boundaries": ["不得无条件跨越两个阶段"],
        "social_impact": ["公会按职业配置队伍"],
        "visibility": ["敌人只能看到公开等级"],
        "continuity_ledger": ["level", "class_path", "skills", "equipment", "resources", "conditions"],
    }


@pytest.mark.parametrize(
    "query",
    ["power", "combat", "class", "advancement", "level", "skill", "equipment", "职业", "进阶"],
)
def test_select_world_context_includes_compact_power_contract_for_relevant_queries(query):
    blueprint = {"power_system_spec": _structured_power_spec()}
    original = deepcopy(blueprint)

    selected = select_world_context(blueprint, query, max_rules=2)
    power = selected["power_system_spec"]

    assert [stage["level"] for stage in power["stages"]] == [1, 10, 20, 30, 60]
    assert power["paths"] == [
        {"name": "法师", "branches": ["元素法师", "秘术法师"], "advancement": ["收集元素核心"]},
        {"name": "战士", "branches": ["盾战士", "狂战士"], "advancement": ["完成战团试炼"]},
    ]
    assert {"advancement", "costs", "counters", "boundaries", "continuity_ledger"} <= set(power)
    assert not ({"social_impact", "visibility", "skills", "equipment", "attributes"} & set(power))
    assert len(json.dumps(power, ensure_ascii=False, separators=(",", ":"))) <= 5000
    assert len(flatten_selected_rules(selected)) <= 2
    assert blueprint == original
    power["stages"][0]["name"] = "外部修改"
    assert blueprint == original


def test_select_world_context_omits_structured_power_for_unrelated_or_legacy_projects():
    assert "power_system_spec" not in select_world_context(
        {"power_system_spec": _structured_power_spec()},
        "只写茶馆对话",
    )
    legacy = {"power_system": ["旧版力量规则"]}
    assert select_world_context(legacy, "职业升级") == {"power_system": ["旧版力量规则"]}


@pytest.mark.parametrize("query", ["classic sword tale", "classification notes"])
def test_english_power_relevance_does_not_match_inside_larger_words(query):
    selected = select_world_context(
        {"power_system_spec": _structured_power_spec()},
        query,
    )

    assert "power_system_spec" not in selected


def test_english_power_relevance_uses_tokens_while_chinese_keeps_substring_matching():
    blueprint = {"power_system_spec": _structured_power_spec()}

    assert "power_system_spec" in select_world_context(blueprint, "choose a CLASS-path")
    assert "power_system_spec" in select_world_context(blueprint, "准备职业晋升试炼")


def test_outline_power_context_reapplies_strict_budget_after_maximum_expansion():
    spec = _structured_power_spec()
    long_tail = "长" * 240
    spec["stages"] = [
        {
            "name": f"阶段{index}",
            "level": level,
            "entry": f"条件{index}{long_tail}",
            "change": f"变化{index}{long_tail}",
            "failure": f"失败{index}{long_tail}",
        }
        for index, level in enumerate(
            [1, 3, 5, 7, 9, 10, 12, 15, 18, 20, 24, 27, 30, 45, 60],
            start=1,
        )
    ]
    spec["paths"] = [
        {
            "name": f"路线{index:02d}",
            "branches": [f"路线{index:02d}分支甲", f"路线{index:02d}分支乙"],
            "advancement": [f"路线{index:02d}进阶{long_tail}" for _ in range(8)],
            "role": long_tail,
        }
        for index in range(64)
    ]
    spec["costs"] = [f"代价{index}{long_tail}" for index in range(16)]
    spec["counters"] = [f"克制{index}{long_tail}" for index in range(16)]
    spec["boundaries"] = [f"边界{index}{long_tail}" for index in range(16)]

    first = blueprint_context.outline_power_system_context(spec)
    second = blueprint_context.outline_power_system_context(spec)
    encoded = json.dumps(first, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    assert first == second
    assert len(encoded) <= 5000
    assert first["name"] == "神域职业体系"
    assert first["origin"]
    assert first["advancement"]
    levels = {stage["level"] for stage in first["stages"]}
    assert {1, 10, 20, 30, 60} <= levels
    retained_names = [path["name"] for path in first["paths"]]
    assert retained_names
    assert retained_names == [f"路线{index:02d}" for index in range(len(retained_names))]
    assert all(path.get("branches") for path in first["paths"])
    assert all(path.get("advancement") for path in first["paths"])
    assert all(field in first and first[field] for field in ("costs", "counters", "boundaries", "continuity_ledger"))


def test_outline_power_context_retains_oversized_xianxia_paths_without_advancement():
    spec = _structured_power_spec()
    long_tail = "cultivation-detail-" * 20
    spec["attributes"] = [{"name": "spiritual root", "effect": "determines affinity"}]
    spec["paths"] = [
        {
            "name": f"Dao Path {index:02d}",
            "branches": [
                f"Dao Path {index:02d} sword branch {long_tail}",
                f"Dao Path {index:02d} alchemy branch {long_tail}",
            ],
        }
        for index in range(64)
    ]
    validated = validate_power_system_spec(spec, novel_type_id="xianxia")

    power = blueprint_context.outline_power_system_context(validated)
    encoded = json.dumps(power, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    assert len(encoded) <= 5000
    assert power["paths"]
    assert [path["name"] for path in power["paths"]] == [
        f"Dao Path {index:02d}" for index in range(len(power["paths"]))
    ]
    assert all(path.get("branches") for path in power["paths"])
    assert all("advancement" not in path for path in power["paths"])


def test_outline_power_context_never_exceeds_budget_with_all_major_stages():
    spec = _structured_power_spec()
    long_tail = "major-stage-detail-" * 20
    spec["stages"] = [
        {
            "name": f"Major Stage {index:02d} {long_tail}",
            "level": (1, 10, 20, 30, 60)[index % 5],
            "entry": f"entry {index:02d} {long_tail}",
            "change": f"change {index:02d} {long_tail}",
            "failure": f"failure {index:02d} {long_tail}",
        }
        for index in range(64)
    ]
    spec["paths"] = [
        {
            "name": f"Major Path {index:02d}",
            "branches": [f"branch a {long_tail}", f"branch b {long_tail}"],
            "advancement": [f"advance {long_tail}"],
        }
        for index in range(64)
    ]
    for field in ("origin", "advancement", "costs", "counters", "boundaries"):
        spec[field] = [f"{field} {index:02d} {long_tail}" for index in range(64)]

    first = blueprint_context.outline_power_system_context(spec)
    second = blueprint_context.outline_power_system_context(spec)
    encoded = json.dumps(first, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    assert first == second
    assert len(encoded) <= 5000
    assert len(first["stages"]) >= 3
    assert len(first["paths"]) >= 1
    assert all(field in first and first[field] for field in (
        "origin",
        "advancement",
        "costs",
        "counters",
        "boundaries",
        "continuity_ledger",
    ))


def test_world_markdown_rendering_is_ordered_and_shows_quest_chain_stages_without_mutation():
    blueprint = {
        "premise": "现实与神域同时运转。",
        "world_rules": ["死亡会损失经验。"],
        "economy_rules": ["铜币价格必须有锚点。"],
        "quest_rules": ["任务必须先登记。"],
        "quest_network": {
            "active_chains": [
                {
                    "name": "灰烬村异常链",
                    "description": "从清道夫委托追查后坡异动。",
                    "stages": [
                        "清道夫委托",
                        {"name": "后坡巡查", "description": "确认污染来源。"},
                    ],
                }
            ]
        },
        "reality_bridge_rules": ["现实到账必须可核对。"],
        "locations": [{"name": "灰烬村", "description": "新手出生地。"}],
        "faction_rules": ["阵营声望必须来自行动。"],
        "factions": [{"name": "巡夜人", "goal": "封锁污染。"}],
    }
    original = deepcopy(blueprint)

    rendered = blueprint_context.render_world_markdown("神域", blueprint)

    assert rendered.splitlines()[0] == blueprint_context.MANAGED_MARKER
    assert "# 《神域》世界观" in rendered
    headings = [
        "## 世界背景",
        "## 世界规则",
        "## 经济体系",
        "## 任务体系",
        "## 任务网络",
        "## 现实桥接",
        "## 地点",
        "## 阵营",
    ]
    assert [rendered.index(heading) for heading in headings] == sorted(
        rendered.index(heading) for heading in headings
    )
    assert "灰烬村异常链" in rendered
    assert "从清道夫委托追查后坡异动。" in rendered
    assert "清道夫委托" in rendered
    assert "后坡巡查" in rendered
    assert blueprint == original


def test_power_markdown_renders_all_rule_groups_without_mutation():
    blueprint = {
        "power_system": ["所有玩家统一为见习者。"],
        "progression_rules": ["经验只来自可验证行动。"],
        "panel_rules": ["面板只显示玩家可见信息。"],
        "constraints": ["不存在无代价复活。"],
        "forbidden_breaks": ["不得跳过职业前置。"],
    }
    original = deepcopy(blueprint)

    rendered = blueprint_context.render_power_markdown("神域", blueprint)

    assert rendered.splitlines()[0] == blueprint_context.MANAGED_MARKER
    assert "# 《神域》力量体系" in rendered
    headings = ["## 力量与职业", "## 成长与战斗", "## 面板规则", "## 世界硬约束"]
    assert [rendered.index(heading) for heading in headings] == sorted(
        rendered.index(heading) for heading in headings
    )
    for rule in (
        "所有玩家统一为见习者。",
        "经验只来自可验证行动。",
        "面板只显示玩家可见信息。",
        "不存在无代价复活。",
        "不得跳过职业前置。",
    ):
        assert rule in rendered
    assert blueprint == original


def test_power_markdown_prefers_structured_spec_with_exact_order_and_nested_details():
    blueprint = {
        "power_system": ["旧版力量段落不得显示"],
        "power_system_spec": {
            "name": "神域职业体系",
            "origin": ["觉醒石连接神域权限"],
            "attributes": [{"name": "智力", "effect": "提高法术强度"}],
            "attribute_allocation": {
                "mode": "free",
                "points_per_level": 5,
                "starting_level": 1,
                "base_attributes": {"力量": 5, "敏捷": 5, "体质": 5, "智力": 5, "精神": 5, "幸运": 5},
                "allow_carry": True,
                "respec_rule": "每周可在主城重置一次，消耗洗点券。",
            },
            "stages": [
                {
                    "name": "正式职业",
                    "level": 10,
                    "entry": "完成导师试炼",
                    "change": "解锁职业资源",
                    "failure": "试炼冷却七日",
                }
            ],
            "paths": [
                {
                    "name": "法师",
                    "role": "远程元素输出",
                    "core_resource": "法力与元素印记",
                    "core_attributes": ["智力", "精神"],
                    "weapons": ["法杖", "魔典"],
                    "armor": ["布甲"],
                    "skill_categories": ["元素法术", "护盾法术"],
                    "combat_loop": "施法叠印记后引爆",
                    "strengths": ["远程爆发"],
                    "weaknesses": ["近身受限"],
                    "branches": ["烈焰法师", "冰霜法师"],
                    "transfer_task": "守住元素回廊",
                    "advancement": ["收集元素核心"],
                }
            ],
            "skills": ["导师和技能书授予技能"],
            "equipment": ["法杖增幅元素法术"],
            "resources": ["元素核心来自首领掉落"],
            "advancement": ["等级、任务和材料同时满足"],
            "costs": ["透支法力会造成虚弱"],
            "counters": ["沉默克制持续施法"],
            "boundaries": ["不得无条件跨越两个阶段"],
            "social_impact": ["公会按职业配置队伍"],
            "visibility": ["敌人只能看到公开等级"],
            "continuity_ledger": ["level", "class_path", "skills", "equipment"],
        },
    }
    original = deepcopy(blueprint)

    rendered = blueprint_context.render_power_markdown("神域", blueprint)

    headings = [
        "## 体系总览",
        "## 力量来源",
        "## 属性",
        "## 属性分配",
        "## 阶段与晋升",
        "## 职业与路线",
        "## 技能与装备",
        "## 资源与代价",
        "## 克制与边界",
        "## 社会影响",
        "## 信息可见性",
        "## 连续性账本",
    ]
    assert [rendered.index(heading) for heading in headings] == sorted(
        rendered.index(heading) for heading in headings
    )
    for concrete_text in (
        "神域职业体系", "正式职业", "完成导师试炼", "试炼冷却七日",
        "法师", "远程元素输出", "烈焰法师", "冰霜法师", "守住元素回廊",
    ):
        assert concrete_text in rendered
    assert "旧版力量段落不得显示" not in rendered
    assert "## 力量与职业" not in rendered
    assert "## 属性\n\n## 属性分配" not in rendered
    assert "### 每级点数\n\n- 5" in rendered
    assert "### 初始值" in rendered
    assert "**力量**：5" in rendered
    assert "### 洗点规则\n\n- 每周可在主城重置一次，消耗洗点券。" in rendered
    assert "\n".join(
        (
            "- **正式职业**",
            "  - **等级**：10",
            "  - **进入条件**：完成导师试炼",
            "  - **能力变化**：解锁职业资源",
            "  - **失败后果**：试炼冷却七日",
        )
    ) in rendered
    assert "\n".join(
        (
            "- **法师**",
            "  - **职责**：远程元素输出",
            "  - **核心属性**：智力；精神",
            "  - **核心资源**：法力与元素印记",
            "  - **武器**：法杖；魔典",
            "  - **护甲**：布甲",
            "  - **技能类别**：元素法术；护盾法术",
            "  - **战斗循环**：施法叠印记后引爆",
            "  - **强项**：远程爆发",
            "  - **弱项**：近身受限",
            "  - **分支**：烈焰法师；冰霜法师",
            "  - **转职任务**：守住元素回廊",
            "  - **晋升**：收集元素核心",
        )
    ) in rendered
    assert blueprint == original


def test_structured_power_markdown_escapes_dynamic_structure_syntax():
    blueprint = {
        "power_system_spec": {
            "name": "bad**\n## injected",
            "origin": ["[source] `code` <tag> # heading"],
            "attributes": [
                {
                    "name": "attr_name",
                    "effect": "line\n* effect",
                    "bad\n## key-injected": "value",
                }
            ],
            "stages": [
                {
                    "name": "stage**\n## injected",
                    "level": 10,
                    "entry": "[gate] `tick` <tag> _x_ \\ path",
                    "change": "change#value",
                    "failure": "failure\x00value",
                }
            ],
            "paths": [
                {
                    "name": "path**\n## injected",
                    "role": "role [tank]",
                    "core_attributes": ["power_one"],
                    "core_resource": "mana`pool`",
                    "weapons": ["staff*one"],
                    "armor": ["robe<cloth>"],
                    "skill_categories": ["burst#magic"],
                    "combat_loop": "cast\nthen burst",
                    "strengths": ["range[far]"],
                    "weaknesses": ["silence_weak"],
                    "branches": ["fire**mage", "ice`mage`"],
                    "transfer_task": "enter ## trial",
                    "advancement": ["rank > novice"],
                }
            ],
            "skills": ["skill [one]"],
            "equipment": ["gear `one`"],
            "resources": ["resource <one>"],
            "advancement": ["advance #one"],
            "costs": ["cost *one*"],
            "counters": ["counter _one_"],
            "boundaries": ["boundary > one"],
            "social_impact": ["guild [impact]"],
            "visibility": ["visible `rank`"],
            "continuity_ledger": ["level#value"],
        }
    }

    rendered = blueprint_context.render_power_markdown("神域", blueprint)

    assert rendered.count("\n## ") == 11
    assert "\n## injected" not in rendered
    assert "\n## key-injected" not in rendered
    assert "- **stage\\*\\* \\#\\# injected**" in rendered
    assert "- **path\\*\\* \\#\\# injected**" in rendered
    assert (
        "  - **进入条件**：\\[gate\\] \\`tick\\` \\<tag\\> "
        "\\_x\\_ \\\\ path"
    ) in rendered
    assert "  - **分支**：fire\\*\\*mage；ice\\`mage\\`" in rendered
    assert "  - **战斗循环**：cast then burst" in rendered


def test_sync_world_markdown_creates_and_refreshes_managed_files_without_mutation(tmp_path):
    blueprint = {
        "premise": "旧背景",
        "power_system": ["旧力量规则"],
    }
    original = deepcopy(blueprint)

    created = blueprint_context.sync_world_markdown(tmp_path, "神域", blueprint)

    world_path = tmp_path / "设定集" / "世界观.md"
    power_path = tmp_path / "设定集" / "力量体系.md"
    assert created["world"]["written"] is True
    assert created["power"]["written"] is True
    assert world_path.read_text(encoding="utf-8").startswith(blueprint_context.MANAGED_MARKER)
    assert power_path.read_text(encoding="utf-8").startswith(blueprint_context.MANAGED_MARKER)

    refreshed = blueprint_context.sync_world_markdown(
        tmp_path,
        "神域",
        {"premise": "新背景", "power_system": ["新力量规则"]},
    )

    assert refreshed["world"]["written"] is True
    assert refreshed["power"]["written"] is True
    assert "新背景" in world_path.read_text(encoding="utf-8")
    assert "新力量规则" in power_path.read_text(encoding="utf-8")
    assert blueprint == original


def test_sync_world_markdown_preserves_manual_files_unless_forced(tmp_path):
    settings_dir = tmp_path / "设定集"
    settings_dir.mkdir()
    world_path = settings_dir / "世界观.md"
    power_path = settings_dir / "力量体系.md"
    world_path.write_text("# 手写世界观\n\n不要覆盖。\n", encoding="utf-8")
    power_path.write_text("# 手写力量体系\n\n不要覆盖。\n", encoding="utf-8")

    skipped = blueprint_context.sync_world_markdown(
        tmp_path,
        "神域",
        {"premise": "托管背景", "power_system": ["托管规则"]},
    )

    assert skipped["world"]["written"] is False
    assert skipped["power"]["written"] is False
    assert world_path.read_text(encoding="utf-8").startswith("# 手写世界观")
    assert power_path.read_text(encoding="utf-8").startswith("# 手写力量体系")

    forced = blueprint_context.sync_world_markdown(
        tmp_path,
        "神域",
        {"premise": "托管背景", "power_system": ["托管规则"]},
        force=True,
    )

    assert forced["world"]["written"] is True
    assert forced["power"]["written"] is True
    assert world_path.read_text(encoding="utf-8").startswith(blueprint_context.MANAGED_MARKER)
    assert power_path.read_text(encoding="utf-8").startswith(blueprint_context.MANAGED_MARKER)


@pytest.mark.parametrize(
    "existing_content",
    [
        "# 旧世界观\n<!-- managed: world-blueprint/v1 -->\n旧背景\n",
        "# 旧世界观\n```markdown\n<!-- managed: world-blueprint/v1 -->\n```\n旧背景\n",
        "  <!-- managed: world-blueprint/v1 -->  \n# 手写世界观\n",
    ],
    ids=["second-line", "code-block", "indented-first-line"],
)
def test_sync_world_markdown_preserves_manual_files_that_only_reference_marker(
    tmp_path,
    existing_content,
):
    settings_dir = tmp_path / "设定集"
    settings_dir.mkdir()
    world_path = settings_dir / "世界观.md"
    world_path.write_text(existing_content, encoding="utf-8")

    result = blueprint_context.sync_world_markdown(
        tmp_path,
        "神域",
        {"premise": "刷新后的背景"},
    )

    assert result["world"]["written"] is False
    assert world_path.read_text(encoding="utf-8") == existing_content


def test_sync_world_markdown_refreshes_bom_prefixed_first_line_marker(tmp_path):
    settings_dir = tmp_path / "设定集"
    settings_dir.mkdir()
    world_path = settings_dir / "世界观.md"
    world_path.write_text(
        f"\ufeff{blueprint_context.MANAGED_MARKER}\n旧背景\n",
        encoding="utf-8",
    )

    result = blueprint_context.sync_world_markdown(
        tmp_path,
        "神域",
        {"premise": "刷新后的背景"},
    )

    assert result["world"]["written"] is True
    assert world_path.read_text(encoding="utf-8").startswith(blueprint_context.MANAGED_MARKER)
    assert "刷新后的背景" in world_path.read_text(encoding="utf-8")


def test_sync_world_markdown_does_not_treat_inline_marker_text_as_managed(tmp_path):
    settings_dir = tmp_path / "设定集"
    settings_dir.mkdir()
    world_path = settings_dir / "世界观.md"
    original = "# 手写世界观\n正文提到 <!-- managed: world-blueprint/v1 --> 但不是管理标记。\n"
    world_path.write_text(original, encoding="utf-8")

    result = blueprint_context.sync_world_markdown(
        tmp_path,
        "神域",
        {"premise": "不应写入"},
    )

    assert result["world"]["written"] is False
    assert world_path.read_text(encoding="utf-8") == original


def test_sync_world_markdown_force_overwrites_non_utf8_files_without_reading_them(tmp_path):
    settings_dir = tmp_path / "设定集"
    settings_dir.mkdir()
    world_path = settings_dir / "世界观.md"
    power_path = settings_dir / "力量体系.md"
    world_path.write_bytes("旧世界观".encode("utf-16"))
    power_path.write_bytes(b"\x80\x81\x82")

    result = blueprint_context.sync_world_markdown(
        tmp_path,
        "神域",
        {"premise": "新背景", "power_system": ["新力量规则"]},
        force=True,
    )

    assert result["world"]["written"] is True
    assert result["power"]["written"] is True
    assert world_path.read_text(encoding="utf-8").startswith(blueprint_context.MANAGED_MARKER)
    assert power_path.read_text(encoding="utf-8").startswith(blueprint_context.MANAGED_MARKER)


def test_sync_world_markdown_skips_non_utf8_unmanaged_files_without_failing(tmp_path):
    settings_dir = tmp_path / "设定集"
    settings_dir.mkdir()
    world_path = settings_dir / "世界观.md"
    power_path = settings_dir / "力量体系.md"
    world_bytes = "手写世界观".encode("utf-16")
    power_bytes = b"\x80\x81\x82"
    world_path.write_bytes(world_bytes)
    power_path.write_bytes(power_bytes)

    result = blueprint_context.sync_world_markdown(
        tmp_path,
        "神域",
        {"premise": "不应写入", "power_system": ["不应写入"]},
    )

    assert result["world"]["written"] is False
    assert result["power"]["written"] is False
    assert world_path.read_bytes() == world_bytes
    assert power_path.read_bytes() == power_bytes


def test_world_markdown_renders_non_list_active_chains_value():
    rendered = blueprint_context.render_world_markdown(
        "神域",
        {"quest_network": {"active_chains": "灰烬村异常链（旧格式）"}},
    )

    assert "## 任务网络" in rendered
    assert "进行中的任务链" in rendered
    assert "灰烬村异常链（旧格式）" in rendered


def test_world_markdown_renders_non_list_chain_stages_value():
    rendered = blueprint_context.render_world_markdown(
        "神域",
        {
            "quest_network": {
                "active_chains": [
                    {
                        "name": "灰烬村异常链",
                        "description": "追查村外异动。",
                        "stages": {"当前阶段": "调查后坡污染"},
                    }
                ]
            }
        },
    )

    assert "灰烬村异常链" in rendered
    assert "阶段" in rendered
    assert "调查后坡污染" in rendered
