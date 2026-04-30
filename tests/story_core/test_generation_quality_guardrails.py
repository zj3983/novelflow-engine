from packages.story_core.agent_base import compact_list
from packages.story_core.models import NovelProject
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import (
    _apply_ledger_updates,
    _extract_economy_anchors,
    _extract_equipment_ledger_updates,
    _extract_system_anchors,
    _normalize_chapter_summary,
    _normalize_web_game_terms,
    _review_chapter_body,
)
from packages.story_core.world_enrichment import _merge_enrichment


def test_compact_list_treats_single_string_as_one_item():
    assert compact_list("混沌之种已经完成首次验证。", max_items=5) == ["混沌之种已经完成首次验证。"]


def test_chapter_summary_string_fields_are_not_split_into_characters():
    summary = _normalize_chapter_summary(
        {
            "summary": "苏叶完成首次小额变现。",
            "facts": "混沌之种已经完成首次验证。",
            "unresolved_threads": "白袍公会是否会继续追查交易行异常？",
            "next_focus": "扩大刷怪收益。",
            "chapter_title": "蛰伏与首金",
        },
        1,
    )

    assert summary["facts"] == ["混沌之种已经完成首次验证。"]
    assert summary["unresolved_threads"] == ["白袍公会是否会继续追查交易行异常？"]


def test_economy_anchors_capture_price_fee_and_balance_for_continuity():
    body = (
        "市场价目前是10-11铜币/个，他定价8铜币。"
        "【确认寄售：灰鼠毒腺 × 49，单价 8铜币】"
        "【扣除手续费 5%，到账铜币：372】"
        "【当前余额：850铜币】"
    )

    anchors = _extract_economy_anchors(body)

    assert any("10-11铜币" in anchor for anchor in anchors)
    assert any("单价 8铜币" in anchor or "定价8铜币" in anchor for anchor in anchors)
    assert any("手续费 5%" in anchor for anchor in anchors)
    assert any("850铜币" in anchor for anchor in anchors)


def test_system_anchors_capture_class_equipment_and_npc_continuity():
    body = (
        "【职业倾向：元素法师（学徒）】夜烬打开武器栏。"
        "【粗糙的学徒法杖】耐久度：62%。"
        "药剂师洛婶在药剂铺柜台后报价，只收未污染毒腺，库存告急但看不到玩家面板。"
    )

    anchors = _extract_system_anchors(body)

    assert any("职业锚点" in anchor and "元素法师" in anchor for anchor in anchors)
    assert any("装备锚点" in anchor and "法杖" in anchor for anchor in anchors)
    assert any("NPC锚点" in anchor and "洛婶" in anchor for anchor in anchors)


def test_ledger_updates_are_mirrored_into_structured_game_ledger():
    story = StoryState(
        story_id="s-ledger",
        outline="网游开服。",
        genre="网游",
        style="升级流",
        progression_ledger={
            "protagonist": {"level": 1, "class_path": "法师学徒"},
            "economy": {"currency": "0金币0银币0铜币"},
            "equipment": {"weapon": "新手法杖", "durability": "正常"},
            "pressure": {},
            "level": 2,
            "exp": "45/200",
            "currency": "0金币21银币0铜币",
            "inventory": ["灰鼠毒腺×0"],
            "guild_attention": 1,
        },
    )

    _apply_ledger_updates(
        story,
        {"protagonist": {"class_path": "元素法师学徒"}, "equipment": {"weapon": "粗糙的学徒法杖", "durability": "62%"}},
    )

    assert story.progression_ledger["protagonist"]["level"] == 2
    assert story.progression_ledger["protagonist"]["exp"] == "45/200"
    assert story.progression_ledger["protagonist"]["class_path"] == "元素法师学徒"
    assert story.progression_ledger["economy"]["currency"] == "0金币21银币0铜币"
    assert story.progression_ledger["equipment"]["weapon"] == "粗糙的学徒法杖"
    assert story.progression_ledger["equipment"]["durability"] == "62%"
    assert story.progression_ledger["pressure"]["guild_attention"] == 1


def test_revised_body_ledger_extraction_captures_current_currency_level_and_exp():
    body = (
        "【当前等级：2。经验：45/200。】"
        "【当前资产：0金币 3银币 50铜币。】"
        "法杖耐久降至86%，短剑只是临时工具。"
    )

    updates = _extract_equipment_ledger_updates(body)

    assert updates["protagonist"]["level"] == 2
    assert updates["protagonist"]["exp"] == "45/200"
    assert updates["economy"]["currency"] == "0金币3银币50铜币"
    assert updates["currency"] == "0金币3银币50铜币"
    assert updates["equipment"]["durability"] == "86%"


def test_revised_body_ledger_uses_latest_balance_surface():
    body = (
        "【角色状态】等级：3 经验：120/400 货币：0金币 4银币 20铜币。"
        "他补给之后再次成交。余额栏跳动：0金币 5银币 8铜币。"
    )

    updates = _extract_equipment_ledger_updates(body)

    assert updates["economy"]["currency"] == "0金币5银币8铜币"
    assert updates["currency"] == "0金币5银币8铜币"


def test_opening_review_rejects_short_fanqie_style_chapter():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里看着账单登录全沉浸VRMMO。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常。"
        "他激活混沌之种，确认千倍爆率生效。"
        "他通过交易行匿名寄售材料，注意到手续费、流水和风控异常提示。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在争抢新手村资源。"
    ) * 20

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "继续低调变现。"},
    )

    assert review["pass"] is False
    assert any("字数偏少" in issue for issue in review["issues"])


def test_opening_review_rejects_1000_times_wording_mixed_with_qianbei():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里看着账单登录全沉浸VRMMO。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常。"
        "他激活混沌之种，系统显示1000倍爆率，随后旁白又写千倍爆率。"
        "他通过交易行匿名寄售材料，注意到手续费、流水和风控异常提示。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在争抢新手村资源。"
    ) * 35

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "继续低调变现。"},
    )

    assert review["pass"] is False
    assert any("千倍爆率写法不统一" in issue for issue in review["issues"])


def test_review_rejects_decimal_game_currency_denominations():
    body = (
        "《天启之门》开服后，夜烬在灰烬村交易行匿名寄售毒腺。"
        "药剂师洛婶在药剂铺报价回收毒腺，提醒他别一次砸盘。"
        "交易行提示实际到账：银币0.18，铜币42，余额栏跳动。"
        "白袍公会外围只记录价格、数量批次和时间戳。"
    ) * 35

    review = _review_chapter_body(
        2,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"]},
        ["网游币制默认使用 1金币=100银币=10000铜币。"],
    )

    assert review["pass"] is False
    assert any("游戏币显示不应出现小数" in issue for issue in review["issues"])


def test_web_game_term_normalizer_keeps_formula_but_unifies_reader_terms():
    body = "系统显示1000倍爆率，旁白写放大了1000倍，但公式仍是掉落判定×1000。"

    normalized = _normalize_web_game_terms(body)

    assert "1000倍爆率" not in normalized
    assert "放大了1000倍" not in normalized
    assert "千倍爆率" in normalized
    assert "掉落判定×1000" in normalized


def test_opening_review_rejects_overpacked_first_chapter_pacing():
    body = (
        "《天启之门》开服当晚，苏叶登录游戏，旧头盔异常触发混沌之种。"
        "他立刻出村刷怪，灰狼连续掉落狼皮和狼牙。"
        "随后他回村进入交易行，拆单寄售材料。"
        "赵胖子这个商人当场登场试探价格，白袍公会外围也开始追查交易行异常。"
        "苏叶意识到公会、商人、NPC和风控都已经压了过来。"
    ) * 35

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "继续低调变现。"},
    )

    assert review["pass"] is False
    assert any("第一章节奏过载" in issue for issue in review["issues"])


def test_opening_review_allows_world_channel_and_signpost_without_direct_pursuit():
    body = (
        "《天启之门》全沉浸开服当晚，苏叶在出租屋里看着账单登录游戏。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常，角色创建界面确认游戏ID：夜烬。"
        "夜烬在灰烬村看见世界频道里白袍、赤焰和星河争抢资源点，但那只是开服生态背景。"
        "他出村小范围刷怪，验证混沌之种和千倍爆率后，回到村口交易行拆单寄售低级材料。"
        "药剂师洛婶在药剂铺报价回收毒腺，提醒解毒剂材料缺口大，别一次砸盘。"
        "交易行只留下匿名寄售、手续费、价格、数量批次和时间戳，没有暴露坐标或现实身份。"
    ) * 28

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"], "next_focus": "继续低调变现。"},
        ["第1章冲突模式：现实压力、规则验证、交易行弱线索。"],
    )

    assert "第一章节奏过载：登录、金手指、刷怪、回村交易、商人登场和公会追查被压进同一章。" not in review["issues"]


def test_opening_review_allows_protagonist_pricing_strategy_without_merchant_scene():
    body = (
        "《天启之门》全沉浸开服当晚，苏叶在出租屋里看着账单登录游戏。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常，角色创建界面确认游戏ID：夜烬。"
        "夜烬在灰烬村看见世界频道里公会招募和商会收货，那只是开服生态背景。"
        "他出村小范围刷怪，验证混沌之种和千倍爆率后，回到村口交易行拆单寄售低级材料。"
        "药剂师洛婶在药剂铺报价回收毒腺，提醒解毒剂材料缺口大，别一次砸盘。"
        "夜烬选择主动压价一铜币走匿名批次，交易行只留下手续费、价格、数量批次和时间戳。"
    ) * 28

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"], "next_focus": "继续低调变现。"},
        ["第1章冲突模式：现实压力、规则验证、交易行弱线索。"],
    )

    assert not any("第一章节奏过载" in issue for issue in review["issues"])


def test_opening_review_allows_negated_coordinate_locking():
    body = (
        "《天启之门》全沉浸开服当晚，苏叶在出租屋里看着账单登录游戏。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常，角色创建界面确认游戏ID：夜烬。"
        "夜烬在灰烬村接任务后出村小范围刷怪，验证混沌之种和千倍爆率。"
        "他回到交易行拆单寄售低级材料，药剂师洛婶报价回收狼牙并提醒别一次砸盘。"
        "白袍公会外围只记录价格波动、数量批次和时间戳，没有锁定坐标，也没有锁定身份。"
    ) * 28

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"], "next_focus": "继续低调变现。"},
        ["第1章冲突模式：现实压力、规则验证、交易行弱线索。"],
    )

    assert not any("第一章节奏过载" in issue for issue in review["issues"])
    assert not any("暴露坐标/身份" in issue for issue in review["issues"])


def test_opening_review_allows_resource_point_clearance_as_world_ecology():
    body = (
        "《天启之门》全沉浸开服当晚，苏叶在出租屋里看着账单登录游戏。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常，角色创建界面确认游戏ID：夜烬。"
        "夜烬进入灰烬村，世界频道里白袍公会提醒黑水沼泽东侧清场，赤焰和星河在频道里吵资源点。"
        "他在低密度灰鼠坡小范围刷怪，验证混沌之种和千倍爆率后，回到交易行拆单寄售。"
        "药剂师洛婶报价回收毒腺，提醒低级材料不要砸盘。"
        "交易行只留下匿名流水、手续费、价格、数量批次和时间戳，没有坐标或现实身份。"
    ) * 28

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录时间戳。"], "next_focus": "下一次验证。"},
        ["第1章冲突模式：现实压力、规则验证、交易行弱线索。"],
    )

    assert not any("第一章节奏过载" in issue for issue in review["issues"])


def test_second_chapter_rejects_rushing_element_corridor_completion():
    body = (
        "夜烬打开角色面板，等级1，经验30/100，职业：元素法师学徒，货币15铜币。"
        "他在灰烬村交易行分批寄售毒腺，药剂师洛婶提醒元素回廊前置需要材料。"
        "白袍公会外围只记录价格、数量批次和时间戳，没有锁定坐标或现实身份。"
        "夜烬随后去了职业导师艾伦面前，系统提示：元素回廊前置材料已提交，进度：10/10。"
        "【系统提示】任务完成。等级提升！当前等级：2。"
    ) * 30

    review = _review_chapter_body(
        2,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"], "next_focus": "继续低调变现。"},
        ["第2章必须承接第一章账本：夜烬等级1、经验30/100、职业元素法师学徒、货币15铜、库存毒腺×8狼皮×5。"],
    )

    assert review["pass"] is False
    assert any("第二章推进过快" in issue for issue in review["issues"])


def test_game_world_enrichment_seeds_core_character_profiles():
    project = NovelProject(
        project_id="p-character-profiles",
        title="苟在网游里成神",
        seed_outline="网游开服，主角靠千倍爆率低调发育，交易行变现，被商人与公会逐步注意。",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )

    enriched = _merge_enrichment(project, {})
    names = {profile["name"] for profile in enriched.character_profiles}

    assert {"苏叶", "赵胖子", "药剂师洛婶", "职业导师艾伦", "白袍公会外围队长"}.issubset(names)
