from packages.story_core.genre_types.game_webnovel import GAME_WEBNOVEL, select_game_language_cards


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
            "ordered_actions": ["查看掉落", "打开求购单", "确认一口价并成交"],
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
        for marker in ("交易行", "求购单", "挂单", "立即出售", "成交", "手续费", "游戏币到账")
    )
    assert all(marker not in text for marker in ("官方兑换", "兑换价", "现实账户", "鉴定"))


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


def test_language_cards_select_server_language_for_login_scene():
    ids = _ids({"chapter_goal": "开服登录，创建角色并进入新手村分线"})

    assert ids == ["base", "login_server"]


def test_language_cards_return_only_base_for_unrelated_plan():
    cards = select_game_language_cards({"chapter_goal": "苏叶在出租屋处理晚饭"})

    assert [card.card_id for card in cards] == ["base"]


def test_language_card_selection_never_exceeds_limit():
    cards = select_game_language_cards(
        {
            "chapter_goal": "登录服务器，接任务，拉怪，拾取战利品，上架拍卖，再组队进副本",
        },
        max_cards=3,
    )

    assert len(cards) == 3
    assert cards[0].card_id == "base"


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


def test_complex_opening_prioritizes_login_combat_loot_and_trade_cards():
    cards = select_game_language_cards(
        {
            "writing_taskbook": {
                "scenes": [
                    {"key": "entry_login", "title": "现实压力与登录建号"},
                    {"key": "small_verification", "title": "低级怪小验证", "must_show": ["怪物面板", "异常掉落"]},
                    {"key": "decision_hook", "title": "暗中吃下第一笔", "goal": "完成匿名担保交易"},
                ]
            }
        },
        max_cards=5,
    )
    ids = [card.card_id for card in cards]

    assert ids[0] == "base"
    assert {"login_server", "combat", "loot_inventory", "trade"}.issubset(ids)

    trade = next(card for card in cards if card.card_id == "trade")
    assert "担保交易" not in "\n".join((*trade.preferred, *trade.avoid, trade.example))
    assert "匿名交割" not in "\n".join((*trade.preferred, *trade.avoid, trade.example))


def test_economy_rules_separate_market_appraisal_and_official_exchange():
    rules = GAME_WEBNOVEL.rulebook["economy_rules"]
    text = "\n".join(rules)
    forbidden_currency = "\u4eba\u6c11\u5e01"

    assert "交易行只使用游戏币结算" in text
    assert "已识别的可交易物品不走鉴定" in text
    assert "独立的官方兑换渠道" in text
    assert all(marker in text for marker in ("现实货币", "现实账户"))
    assert forbidden_currency not in text
