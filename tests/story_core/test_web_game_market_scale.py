from packages.story_core.web_game_review import review_web_game_chapter, web_game_review_rules


def test_micro_low_tier_trade_overreaction_is_rejected():
    body = (
        "《天启之门》开服第一晚，夜烬在灰烬村外刷了十几个低级材料，只换到几枚铜币。"
        "交易行检查立刻触发风控记录，商人盯上这笔异常交易，白袍公会也开始注意他的批次。"
    )

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"world_reactions": ["交易行检查小额材料批次。"]},
        world_facts=["网游开服，新手村低级材料以铜币计价。"],
    )

    assert review["pass"] is False
    assert any("小额低级材料交易反应过度" in issue for issue in review["issues"])


def test_micro_low_tier_trade_can_be_ordinary_noise():
    body = (
        "《天启之门》开服第一晚，夜烬在灰烬村外刷了十几个低级材料，只换到几枚铜币。"
        "交易行只扣了手续费，留下匿名流水和到账时间，没有触发风控记录，也没有公会注意。"
        "他真正担心的是木杖耐久、背包格子和下一轮补给成本。"
    )

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"world_reactions": ["小额交易按普通行情处理。"]},
        world_facts=["网游开服，新手村低级材料以铜币计价。"],
    )

    assert not any("小额低级材料交易反应过度" in issue for issue in review["issues"])


def test_prompt_rules_include_market_scale_threshold():
    rules = "\n".join(web_game_review_rules())

    assert "十几个低级材料" in rules
    assert "交易行检查" in rules
    assert "补给、耐久、背包" in rules or "耐久、补给、背包" in rules
