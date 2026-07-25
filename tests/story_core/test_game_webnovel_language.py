import inspect

from packages.story_core.genre_types import game_webnovel
from packages.story_core.genre_types.game_webnovel import GAME_WEBNOVEL, select_game_language_cards
from packages.story_core.web_game_economy import appraisal_rules, exchange_rules, market_rules


def _ids(plan: dict[str, object]) -> list[str]:
    return [card.card_id for card in select_game_language_cards(plan)]


def _card(plan: dict[str, object], card_id: str):
    return next(card for card in select_game_language_cards(plan) if card.card_id == card_id)


def test_language_cards_select_quest_and_combat_for_gray_wolf_task():
    ids = _ids(
        {
            "chapter_goal": "接下清理灰狼任务，在灰狼坡拉怪并完成第一次战斗",
            "ordered_actions": ["接任务", "寻找刷新点", "击杀灰狼"],
        }
    )

    assert ids == ["base", "combat", "quest"]


def test_language_cards_select_loot_and_trade_for_sale_scene():
    ids = _ids(
        {
            "chapter_goal": "把可交易的裂纹狼心放进交易行",
            "ordered_actions": ["查看掉落", "按一口价挂单", "等待买家购买"],
        }
    )

    assert ids == ["base", "trade", "loot_inventory"]


def test_trade_card_uses_only_in_game_market_language():
    card = _card(
        {
            "chapter_goal": "在交易行查看求购单，把裂纹狼心挂单或立即出售",
            "ordered_actions": ["确认成交", "扣除手续费", "游戏币到账"],
        },
        "trade",
    )
    text = "\n".join((*card.preferred, *card.avoid, card.example))

    assert all(
        marker in card.preferred
        for marker in ("交易行", "求购单", "挂单", "立即出售", "一口价", "成交", "手续费", "游戏币到账")
    )
    assert all(marker not in text for marker in ("官方兑换", "兑换价", "现实账户", "现实结算", "鉴定", "验货"))
    listing_path, instant_sale_path = card.example.split("；")
    assert all(marker in listing_path for marker in ("一口价", "挂单", "等待买家"))
    assert "求购" not in listing_path
    assert all(marker in instant_sale_path for marker in ("求购单", "立即出售", "直接成交"))
    assert "一口价" not in instant_sale_path


def test_currency_exchange_card_uses_separate_official_channel_language():
    card = _card(
        {
            "chapter_goal": "成交后进入官方兑换渠道",
            "ordered_actions": ["查看兑换价", "确认兑换额度", "现实账户预计到账"],
        },
        "currency_exchange",
    )
    text = "\n".join((*card.preferred, *card.avoid, card.example))

    assert all(marker in card.preferred for marker in ("兑换价", "额度", "手续费", "预计到账", "现实账户"))
    assert all(marker not in text for marker in ("求购", "鉴定", "拍卖物直接现实结算"))


def test_selling_then_official_exchange_selects_market_exchange_pair():
    ids = _ids({"chapter_goal": "卖出裂纹狼心，随后官方兑换"})

    assert ids == ["base", "trade", "currency_exchange"]


def test_language_cards_select_server_language_for_login_scene():
    ids = _ids({"chapter_goal": "开服登录，创建角色并进入新手村分线"})

    assert ids == ["base", "login_server"]


def test_language_cards_return_only_base_for_unrelated_plan():
    cards = select_game_language_cards({"chapter_goal": "苏叶在出租屋处理晚饭"})

    assert [card.card_id for card in cards] == ["base"]


def test_language_card_selection_hard_caps_requested_limit_at_three():
    plan = {
        "chapter_goal": "登录服务器，接任务，拉怪，拾取战利品，上架拍卖，再组队进副本",
    }
    cards = select_game_language_cards(plan, max_cards=5)
    default_cards = select_game_language_cards(plan)

    assert len(cards) == 3
    assert [card.card_id for card in cards] == [card.card_id for card in default_cards]
    assert [card.card_id for card in cards] == ["base", "loot_inventory", "login_server"]


def test_language_card_selection_ignores_forbidden_scene_terms():
    ids = _ids(
        {
            "chapter_goal": "在灰狼坡拉怪并脱战回蓝",
            "must_avoid": ["不要打开交易行", "不要上架出售", "不要进入副本"],
        }
    )

    assert "combat" in ids
    assert "trade" not in ids
    assert "group_dungeon" not in ids


def test_language_cards_select_equipment_progression_for_repair_scene():
    ids = _ids({"chapter_goal": "回村修理法杖，再查看新技能的冷却时间"})

    assert ids == ["base", "equipment_progression"]


def test_language_cards_select_guild_social_for_raid_recruitment():
    ids = _ids({"chapter_goal": "公会频道招募固定团成员，准备今晚开荒"})

    assert ids == ["base", "guild_social"]


def test_complex_opening_prioritizes_market_exchange_pair():
    cards = select_game_language_cards(
        {
            "writing_taskbook": {
                "scenes": [
                    {"key": "entry_login", "title": "现实压力与登录建号"},
                    {"key": "small_verification", "title": "低级怪小验证", "must_show": ["怪物面板", "异常掉落"]},
                    {"key": "decision_hook", "title": "分开完成两步结算", "goal": "卖出裂纹狼心，随后进入官方兑换渠道"},
                ]
            }
        },
        max_cards=5,
    )
    ids = [card.card_id for card in cards]

    assert ids == ["base", "trade", "currency_exchange"]


def test_legacy_input_markers_live_only_in_the_economy_compatibility_module():
    source = inspect.getsource(game_webnovel)
    legacy_markers = (
        "\u62c5\u4fdd\u4ea4\u6613",
        "\u533f\u540d\u4ea4\u5272",
    )

    assert all(marker not in source for marker in legacy_markers)


def test_economy_rules_separate_market_appraisal_and_official_exchange():
    rules = GAME_WEBNOVEL.rulebook["economy_rules"]
    text = "\n".join(rules)
    forbidden_currency = "\u4eba\u6c11\u5e01"
    boundary_rules = (*market_rules(), *appraisal_rules(), *exchange_rules())

    assert rules[: len(boundary_rules)] == boundary_rules
    assert all(marker in text for marker in ("游戏币", "已识别物品不重复鉴定", "官方兑换渠道", "现实账户"))
    assert forbidden_currency not in text
