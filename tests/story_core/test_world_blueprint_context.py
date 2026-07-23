from copy import deepcopy

import pytest

import packages.story_core.world_blueprint_context as blueprint_context
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
