import pytest

from packages.story_core.prose_style_review import anti_ai_style_rules, sanitize_prose_style, review_prose_style


def test_anti_ai_style_rules_include_generation_and_revision_constraints():
    rules = anti_ai_style_rules()

    assert any("人物说话完整自然" in rule for rule in rules)
    assert all("一章分3到4个叙事段落" not in rule for rule in rules)
    assert any("动作、微表情和细微生理反应" in rule for rule in rules)
    assert any("不要把后台词写进正文和标题" in rule for rule in rules)
    assert any("不要把句子全部切短" in rule for rule in rules)
    assert all("固定文风" not in rule for rule in rules)
    assert all("走到门口" not in rule for rule in rules)
    assert any("不强制固定轮次" in rule for rule in rules)


def test_prose_style_review_flags_ai_cliche_and_meta_explanation():
    body = (
        "霎时间，他心中一紧，脸色一变，眸光一凝。"
        "与此同时，爽点已经兑现，读者会明白这一段节奏的意义。"
        "他五味杂陈，不由得身形一闪，开始推进下一阶段剧情。"
    )

    review = review_prose_style(body)

    assert not review["pass"]
    assert review["scores"]["cliche_terms"] < 8
    assert review["scores"]["meta_language"] < 8
    assert any("AI高频套话" in issue for issue in review["issues"])
    assert any("创作层术语" in issue for issue in review["issues"])
    assert any("动作、微表情和细微生理反应" in item for item in review["revision_plan"])


def test_prose_style_review_accepts_life_like_plain_prose():
    body = (
        "苏叶把鼠标推到一边，盯着屏幕右下角的余额看了两秒。"
        "风扇吱呀转着，吹不散屋里的泡面味。"
        "他没有急着点确认，只用指节敲了敲桌沿。"
        "交易行弹出手续费时，他才把那口气慢慢吐出来。"
    )

    review = review_prose_style(body)

    assert review["pass"]
    assert review["issues"] == []


def test_sanitize_prose_style_removes_safe_meta_language_without_changing_story_facts():
    body = "这一段爽点已经兑现，生成的节奏应该更快。夜烬看着交易行价格。"

    cleaned = sanitize_prose_style(body)

    assert "爽点" not in cleaned
    assert "生成" not in cleaned
    assert "节奏" not in cleaned
    assert "推进" in cleaned
    assert "夜烬" in cleaned


def test_sanitize_prose_style_replaces_stiff_threshold_wording():
    body = "夜烬没说阈值，只盯着柜台那条线。"

    cleaned = sanitize_prose_style(body)

    assert "阈值" not in cleaned
    assert "那条线" in cleaned


def test_prose_style_review_flags_mechanical_short_paragraph_texture():
    body = "\n\n".join(
        [
            "出租屋漏风。",
            "他看着账单。",
            "理由很直接。",
            "这意味着风险。",
            "不能全卖。",
            "也不能不卖。",
            "规则写得很清楚。",
            "数据异常。",
            "模型会报警。",
            "数字很干净。",
            "他继续操作。",
            "确认上架。",
            "提示音响起。",
            "风险也是。",
            "够了。",
            "他转身。",
            "夜风吹过。",
            "账本翻开。",
            "第一笔铜币落袋。",
            "风险还没散。",
        ]
    )

    review = review_prose_style(body)

    assert not review["pass"]
    assert review["scores"]["mechanical_texture"] < 8
    assert any("机械切段" in issue for issue in review["issues"])


def test_prose_style_review_flags_stiff_backend_language():
    body = (
        "夜烬站在灰狼坡外，准备确认边界。"
        "这次验证规则很重要，能够看清服务节点的可见性和底层逻辑。"
        "他要先完成边界验证，再判断模型是否稳定。"
    )

    review = review_prose_style(body)

    assert not review["pass"]
    assert review["scores"]["plain_tomato_language"] < 8
    assert any("后台硬词" in issue for issue in review["issues"])


def test_prose_style_review_flags_backend_terms_in_game_prose():
    body = (
        "新手区按负载分片和区域分片运行，任务完成后可登记后坡巡查资格。"
        "裂纹狼心进入配方验证，平台封存交割后等待现实结算。"
    )

    review = review_prose_style(body)

    assert not review["pass"]
    assert any("后台硬词" in issue for issue in review["issues"])


def test_prose_style_review_accepts_countdown_and_natural_claim_dialogue():
    body = "周围的玩家一起喊着：‘三、二、一——’\n\n有人急得大喊：‘别抢，我先打的！’"

    review = review_prose_style(body)

    assert not any("现代中文对话不自然" in issue for issue in review["issues"])


def test_prose_style_review_accepts_player_facing_game_terms():
    body = (
        "新手村开了好几条分线。夜烬接下任务，打完灰狼就能解锁后坡任务。"
        "他打开交易行，看见一条现成的求购单，确认价格后直接成交。"
    )

    review = review_prose_style(body)

    assert review["pass"]


def test_prose_style_review_gates_economy_checks_by_genre_context():
    body = "拍卖物已经成交，这笔成交款直接进入现实账户。"

    non_game = review_prose_style(body, genre_context={"novel_type": "xuanhuan"})
    web_game = review_prose_style(body, genre_context={"novel_type": "game_webnovel"})

    assert not any("经济边界" in issue for issue in non_game["issues"])
    assert any("经济边界" in issue for issue in web_game["issues"])


def test_prose_style_review_requires_fix_for_explicit_economy_boundary_violations():
    forbidden_currency_name = "\u4eba\u6c11\u5e01"
    body = (
        "夜烬卖出拍卖物，交易行成交所得直接现实结算，款项进了现实账户。\n\n"
        "【名称：裂纹狼心】【用途：锻造】信息已经完整显示，他又提交鉴定，等平台验货。\n\n"
        "求购单的游戏币已经冻结，立即出售显示成交以后，系统仍要求等待买家确认。\n\n"
        f"结算栏使用了{forbidden_currency_name}这个完整名称。"
    )

    review = review_prose_style(body, genre_context={"novel_type": "game_webnovel"})

    economy_issues = [issue for issue in review["issues"] if "经济边界" in issue]
    assert len(economy_issues) == 4
    assert all("必须修复" in issue for issue in economy_issues)
    assert review["scores"]["game_term_precision"] <= 4
    plans = "\n".join(review["revision_plan"])
    assert "交易行只进游戏钱包" in plans
    assert "已识别物不重复鉴定" in plans
    assert "资金冻结的求购单应立即成交" in plans
    assert "独立官方兑换" in plans
    assert forbidden_currency_name not in plans


def test_prose_style_review_accepts_valid_exchange_unidentified_item_and_isolated_terms():
    body = (
        "夜烬选中资金已经冻结的求购单，点下立即出售，裂纹狼心成交后游戏币进入游戏钱包。\n\n"
        "他退出交易行，打开独立官方兑换页面，确认兑换价、额度、手续费和预计到账，随后现实账户到账。\n\n"
        "那件披风仍是未鉴定状态，他把披风交给鉴定师。队伍频道里有人求购药草，也有人问奖励到账没有。"
    )

    review = review_prose_style(body, genre_context={"novel_type": "game_webnovel"})

    assert not any("经济边界" in issue for issue in review["issues"]), review


def test_prose_style_review_detects_ordered_economy_chains_across_adjacent_units():
    body = (
        "夜烬在交易行卖出拍卖物，成交提示跳了出来。\n\n"
        "紧接着，那笔款项直接到账现实账户。\n\n"
        "面板写着焰纹石用途是强化武器。\n\n"
        "他却把这颗材料交给鉴定师。\n\n"
        "求购单里的游戏币已经冻结。\n\n"
        "夜烬点下立即出售。\n\n"
        "成交以后，页面还让他继续等待买家确认。"
    )

    review = review_prose_style(body, genre_context={"novel_type": "game_webnovel"})

    economy_issues = [issue for issue in review["issues"] if "经济边界" in issue]
    assert len(economy_issues) == 3


def test_prose_style_review_ignores_negated_chains_and_appraisal_of_another_item():
    body = (
        "交易行里的求购已经成交。\n\n"
        "这笔钱并非直接进入现实账户，而是必须另走独立官方兑换。\n\n"
        "裂纹狼心用途是锻造；旁边的披风仍未鉴定，他把披风交给鉴定师。\n\n"
        "求购单里的游戏币已经冻结。\n\n"
        "夜烬点下立即出售。\n\n"
        "成交以后不用等待买家确认，游戏币马上进入游戏钱包。"
    )

    review = review_prose_style(body, genre_context={"novel_type": "game_webnovel"})

    assert not any("经济边界" in issue for issue in review["issues"]), review


@pytest.mark.parametrize(
    ("body", "issue_fragment"),
    [
        (
            "交易行里的求购已经成交。\n\n夜烬喝了口水。\n\n成交所得直接到账现实账户。",
            "交易与现实兑换混成了一步",
        ),
        (
            "焰纹石用途是强化武器。\n\n夜烬翻开下一页。\n\n他把这颗材料交给鉴定师。",
            "又被送去鉴定或验货",
        ),
        ("求购成交所得直接现实到账。", "交易与现实兑换混成了一步"),
        (
            "求购单里的资金被冻结了。\n\n夜烬点下立即出售。\n\n成交后仍需等待买家再次确认。",
            "仍在等待买家再次确认",
        ),
        ("夜烬把已经识别的裂纹狼心提交鉴定。", "又被送去鉴定或验货"),
        (
            "交易行里的求购已经成交。\n\n夜烬关掉设备。\n\n这笔求购所得直接到账现实账户。",
            "交易与现实兑换混成了一步",
        ),
        (
            "交易行里的求购已经成交。\n\n夜烬关掉设备。\n\n这笔成交款不是工资，而是交易所得，随后直接进入现实账户。",
            "交易与现实兑换混成了一步",
        ),
        (
            "A单求购资金已经冻结。\n\nA单求购随即成交。\n\nA单求购仍需等待买家确认。",
            "仍在等待买家再次确认",
        ),
        (
            "求购成交，游戏币到账。钱随后直接进入现实账户。",
            "交易与现实兑换混成了一步",
        ),
        (
            "甲玩家的求购单资金冻结。\n\n甲玩家的订单成交。\n\n甲玩家等待买家确认。",
            "仍在等待买家再次确认",
        ),
        (
            "求购成交，游戏币到账。钱很快就直接进入现实账户。",
            "交易与现实兑换混成了一步",
        ),
        (
            "甲玩家的A单求购资金已经冻结。\n\n甲玩家的A单求购成交。\n\n甲玩家的A单等待买家确认。",
            "仍在等待买家再次确认",
        ),
        (
            "甲玩家的A单求购资金已经冻结。\n\n该订单成交。\n\n同一订单等待买家确认。",
            "仍在等待买家再次确认",
        ),
        (
            "求购成交，游戏币到账。\n\n款项由求购平台归还，随后直接转入现实账户。",
            "交易与现实兑换混成了一步",
        ),
        (
            "夜烬看见甲玩家的A单求购资金已经冻结。\n\n甲玩家的A单求购成交。\n\n甲玩家的A单等待买家确认。",
            "仍在等待买家再次确认",
        ),
        (
            "求购成交，游戏币到账。\n\n那笔钱是卖材料赚来的，随后直接转入现实账户。",
            "交易与现实兑换混成了一步",
        ),
        (
            "他注意到夜烬的求购单资金已经冻结。\n\n夜烬的订单成交。\n\n夜烬还在等待买家确认。",
            "仍在等待买家再次确认",
        ),
        (
            "清风明月的求购单资金冻结。\n\n清风明月的订单成交。\n\n清风明月还在等待买家确认。",
            "仍在等待买家再次确认",
        ),
    ],
)
def test_prose_style_review_detects_explicit_economy_boundaries_in_three_paragraph_window(
    body: str,
    issue_fragment: str,
):
    review = review_prose_style(body, genre_context={"novel_type": "game_webnovel"})

    matching = [issue for issue in review["issues"] if issue_fragment in issue]
    assert matching, review
    assert all("必须修复" in issue for issue in matching)


@pytest.mark.parametrize(
    "body",
    [
        "交易行里的求购已经成交。\n\n夜烬抬头看了一眼。\n\n款项没有直接进入现实账户，必须另走独立官方兑换。",
        "求购单里的资金被冻结了。\n\n夜烬点下立即出售。\n\n系统没有要求等待买家确认。",
        "求购单成交后游戏币进入游戏钱包。\n\n他打开独立官方兑换页面。\n\n确认手续费和预计到账后，现实账户到账。",
        "裂纹狼心用途是锻造。\n\n旁边还有一件未鉴定披风。\n\n夜烬把披风交给鉴定师。",
        "裂纹狼心已经识别。\n\n夜烬取出披风，当前拿着的是披风。\n\n他把它提交鉴定。",
        "交易行里的拍卖物已经成交。\n\n夜烬去了城外。\n\n公会开始另一场战斗。\n\n现实账户收到的是项目尾款。",
        "交易行里的求购已经成交。\n\n夜烬退出游戏。\n\n公司奖金到账现实账户。",
        "交易行里的求购已经成交。\n\n夜烬退出游戏。\n\n现实账户弹出到账提醒，来源没有显示。",
        "交易行里的求购已经成交。\n\n夜烬抬头看了一眼。\n\n款项没有被交易行直接打进现实账户。",
        "交易行里的求购已经成交。\n\n夜烬抬头看了一眼。\n\n这笔钱不需要由交易行直接转入现实账户。",
        "裂纹狼心已经识别。\n\n夜烬换上了一把长剑。\n\n他把它提交鉴定。",
        "甲求购单资金冻结。\n\n乙求购单成交。\n\n丙求购单等待买家确认。",
        "求购成交，游戏币到账。\n\n夜烬放下头盔。\n\n那笔钱是报销款，随后直接转入现实账户。",
        "甲玩家的求购单资金冻结。\n\n乙玩家的普通订单成交。\n\n丙玩家等待买家确认。",
        "求购成交，游戏币到账。\n\n夜烬放下头盔。\n\n款项由朋友归还，随后直接转入现实账户。",
        "甲玩家的A单求购资金已经冻结。\n\n甲玩家的B单求购成交。\n\n甲玩家的C单等待买家确认。",
        "夜烬的求购单资金冻结。\n\n洛婶的订单成交。\n\n艾伦的订单等待买家确认。",
        "夜烬的求购单资金冻结。\n\n洛婶的订单成交。\n\n艾伦等待买家确认。",
        "夜烬有一张求购单，资金已经冻结。\n\n洛婶有一张订单显示成交。\n\n艾伦还在等待买家确认。",
    ],
)
def test_prose_style_review_accepts_negated_or_separated_three_paragraph_economy_flows(body: str):
    review = review_prose_style(body, genre_context={"novel_type": "game_webnovel"})

    assert not any("经济边界" in issue for issue in review["issues"]), review


def test_prose_style_review_does_not_apply_unrelated_negation_to_direct_settlement():
    body = "求购单已经成交。他不是买家，成交所得直接进入现实账户。"

    review = review_prose_style(body, genre_context={"novel_type": "game_webnovel"})

    assert any("交易与现实兑换混成了一步" in issue for issue in review["issues"]), review


def test_prose_style_review_flags_panel_followed_by_rule_explanation():
    body = "角色面板：等级Lv.1，法力60/60。\n\n这说明他的法力还很充足，规则就是这样。"

    review = review_prose_style(body)

    assert not review["pass"]
    assert any("面板后重复解释" in issue for issue in review["issues"])
    assert any("面板只保留" in item for item in review["revision_plan"])


def test_prose_style_review_flags_transaction_process_explanation():
    body = (
        "裂纹狼心提交鉴定后，系统给出一条求购匹配。"
        "求购方看不到卖家ID和掉落分片，平台验货以后直接封存交割。"
    )

    review = review_prose_style(body)

    assert not review["pass"]
    assert any("交易流程说明" in issue for issue in review["issues"])
    assert any("点击、反馈和物品变化" in item for item in review["revision_plan"])


def test_prose_style_review_flags_unnatural_staff_shorthand():
    body = "夜烬修杖花了十八铜，又握杖退到墙边，杖尖抵着地面。裂纹杖芯还在背包里。"

    review = review_prose_style(body)

    assert not review["pass"]
    assert review["scores"]["game_term_precision"] < 8
    assert any("装备称呼不自然" in issue for issue in review["issues"])
