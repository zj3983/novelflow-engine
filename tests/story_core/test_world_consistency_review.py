import pytest

from packages.story_core.world_consistency_review import review_world_event_consistency


def test_world_consistency_review_flags_visibility_overreach():
    world_events = [
        {
            "event_id": "c1-market-trace",
            "actor": "夜烬",
            "action": "匿名寄售少量低级材料。",
            "location": "交易行",
            "visible_to": ["交易行", "潜在买家"],
            "consequences": ["交易行只出现价格、数量、批次和时间戳。"],
            "state_delta": {"economy": {"market_trace": "low"}},
        }
    ]
    body = "夜烬刚把狼毒腺挂上交易行，白袍公会就立刻锁定他的坐标和现实身份。"

    review = review_world_event_consistency(body, world_events=world_events, scene_cards=[])

    assert not review["pass"]
    assert review["scores"]["visibility_boundary"] < 8
    assert any("可见性越界" in issue for issue in review["issues"])
    assert any("价格、数量、批次和时间戳" in item for item in review["revision_plan"])


def test_world_consistency_review_accepts_weak_trade_trace():
    world_events = [
        {
            "event_id": "c1-market-trace",
            "actor": "夜烬",
            "action": "匿名寄售少量低级材料。",
            "location": "交易行",
            "visible_to": ["交易行", "潜在买家"],
            "consequences": ["交易行只出现价格、数量、批次和时间戳。"],
            "state_delta": {"economy": {"market_trace": "low"}},
        }
    ]
    body = "交易行界面只跳出价格、数量、手续费和时间戳。夜烬看着到账提示，确认这只是一笔普通小额订单。"

    review = review_world_event_consistency(body, world_events=world_events, scene_cards=[])

    assert review["pass"]
    assert review["issues"] == []


def test_world_consistency_review_requires_fix_for_explicit_economy_boundary_violations():
    forbidden_currency_name = "\u4eba\u6c11\u5e01"
    body = (
        "拍卖物成交以后，交易行把卖出所得直接转入现实账户。\n\n"
        "【裂纹狼心】【用途：锻造材料】夜烬看完信息，又把裂纹狼心送去验货。\n\n"
        "求购单已有资金冻结，立即出售显示成交后，夜烬仍在等待买家再次确认。\n\n"
        f"结算说明里出现了{forbidden_currency_name}。"
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=[], chapter_number=4)

    economy_issues = [issue for issue in review["issues"] if "经济边界" in issue]
    assert len(economy_issues) == 4
    assert all("必须修复" in issue for issue in economy_issues)
    assert review["scores"]["systemic_consistency"] <= 4
    plans = "\n".join(review["revision_plan"])
    assert "交易行只进游戏钱包" in plans
    assert "已识别物不重复鉴定" in plans
    assert "资金冻结的求购单应立即成交" in plans
    assert "独立官方兑换" in plans
    assert forbidden_currency_name not in plans


def test_world_consistency_review_accepts_separated_exchange_and_isolated_terms():
    body = (
        "求购单的游戏币已经冻结。夜烬点下立即出售，裂纹狼心成交，游戏币进入游戏钱包。\n\n"
        "他关掉交易行，进入独立官方兑换页面，确认兑换价、额度、手续费和预计到账，随后现实账户到账。\n\n"
        "一件未鉴定披风交给鉴定师。远处有人喊求购，另一个人问任务奖励什么时候到账。"
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=[], chapter_number=4)

    assert not any("经济边界" in issue for issue in review["issues"]), review


def test_world_consistency_review_detects_ordered_economy_chains_across_adjacent_units():
    body = (
        "求购成交的提示刚刚亮起。卖出所得转入现实账户。\n\n"
        "裂纹狼心已显示正式名称。\n\n"
        "夜烬随后送这件物品去鉴定。\n\n"
        "一张求购单标着已付款。\n\n"
        "这张订单随即成交。\n\n"
        "随后页面仍要等买家再次确认。"
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=[], chapter_number=4)

    economy_issues = [issue for issue in review["issues"] if "经济边界" in issue]
    assert len(economy_issues) == 3


def test_world_consistency_review_ignores_negation_and_distant_unrelated_events():
    body = (
        "拍卖行显示装备已经成交。\n\n"
        "款项不能直接进入现实账户，必须进入独立官方兑换页面。\n\n"
        "裂纹狼心的用途是锻造；披风仍是未鉴定状态，夜烬把披风送去鉴定。\n\n"
        "求购单显示资金冻结。\n\n"
        "夜烬选择立即出售。\n\n"
        "系统提示无需等待买家确认。\n\n"
        "他离开市场去做了三天任务。\n\n"
        "公会在另一座城开会。\n\n"
        "现实账户直接到账的是他的旧工资。"
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=[], chapter_number=4)

    assert not any("经济边界" in issue for issue in review["issues"]), review


def test_world_consistency_review_does_not_treat_unrelated_frozen_funds_as_funded_buy_order():
    body = (
        "现实账户因为旧账显示资金冻结。\n\n"
        "夜烬随后看见一张普通求购单，点下立即出售，界面显示成交。\n\n"
        "这笔普通订单需要等待买家确认。"
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=[], chapter_number=4)

    assert not any("经济边界" in issue for issue in review["issues"]), review


@pytest.mark.parametrize(
    ("body", "issue_fragment"),
    [
        (
            "拍卖物已经成交。\n\n夜烬收起菜单。\n\n那笔款项直接打进现实账户。",
            "交易与现实兑换混成了一步",
        ),
        (
            "【名称：裂纹狼心】【用途：锻造】\n\n夜烬走到窗口旁。\n\n他送这颗材料去鉴定。",
            "又被送去鉴定或验货",
        ),
        ("求购成交所得直接现实到账。", "交易与现实兑换混成了一步"),
        (
            "求购单里的资金被冻结了。\n\n订单随即成交。\n\n页面仍让他等买家再次确认。",
            "仍在等待买家再次确认",
        ),
        ("把已经识别的裂纹狼心提交鉴定。", "又被送去鉴定或验货"),
        (
            "拍卖行显示装备成交。\n\n夜烬下线。\n\n这笔拍卖所得直接打进现实账户。",
            "交易与现实兑换混成了一步",
        ),
        (
            "第一条求购单资金冻结。\n\n第一条求购单成交。\n\n第一条求购单等待买家确认。",
            "仍在等待买家再次确认",
        ),
        (
            "拍卖物成交，游戏币进入钱包。\n\n夜烬看了眼时间。\n\n那笔钱随后直接打进现实账户。",
            "交易与现实兑换混成了一步",
        ),
        (
            "甲玩家的求购单资金冻结。\n\n甲玩家成交。\n\n甲玩家等待买家确认。",
            "仍在等待买家再次确认",
        ),
        (
            "苏叶的求购单资金冻结。\n\n洛婶的订单成交。\n\n艾伦等待买家确认。",
            "仍在等待买家再次确认",
        ),
    ],
)
def test_world_consistency_review_detects_explicit_economy_boundaries_in_three_paragraph_window(
    body: str,
    issue_fragment: str,
):
    review = review_world_event_consistency(body, world_events=[], scene_cards=[], chapter_number=4)

    matching = [issue for issue in review["issues"] if issue_fragment in issue]
    assert matching, review
    assert all("必须修复" in issue for issue in matching)


@pytest.mark.parametrize(
    "body",
    [
        "求购成交的提示亮起。\n\n夜烬关掉背包。\n\n款项不需要直接进入现实账户，必须另走独立官方兑换。",
        "求购单里的资金被冻结了。\n\n订单显示成交。\n\n系统没有要求等待买家确认。",
        "求购单成交，游戏币进入游戏钱包。\n\n夜烬进入独立官方兑换页面。\n\n确认额度和预计到账后，现实账户收到款项。",
        "裂纹狼心已经识别。\n\n披风仍是未鉴定状态。\n\n夜烬把披风送去鉴定。",
        "裂纹狼心已显示正式名称。\n\n夜烬拿起一块矿石，当前查看的是矿石。\n\n他把它提交鉴定。",
        "裂纹狼心已经识别。\n\n夜烬离开仓库。\n\n第二天他去了矿洞。\n\n回来后把它提交鉴定。",
        "拍卖物已经成交。\n\n夜烬退出游戏。\n\n公司薪水到账现实账户。",
        "拍卖物已经成交。\n\n夜烬退出游戏。\n\n现实账户收到到账提醒，但没有写明来源。",
        "拍卖物已经成交。\n\n夜烬收起菜单。\n\n款项没有被交易行直接打进现实账户。",
        "拍卖物已经成交。\n\n夜烬收起菜单。\n\n这笔钱不需要由交易行直接转入现实账户。",
        "裂纹狼心已识别。\n\n夜烬改拿一把长剑。\n\n他把它提交鉴定。",
        "甲求购单资金冻结。\n\n乙求购单成交。\n\n丙求购单等待买家确认。",
        "拍卖物成交，游戏币到账。\n\n夜烬退出游戏。\n\n那笔钱是公司退款，随后直接进入现实账户。",
        "甲玩家的求购单资金冻结。\n\n乙玩家的普通订单成交。\n\n丙玩家等待买家确认。",
    ],
)
def test_world_consistency_review_accepts_negated_or_separated_three_paragraph_economy_flows(body: str):
    review = review_world_event_consistency(body, world_events=[], scene_cards=[], chapter_number=4)

    assert not any("经济边界" in issue for issue in review["issues"]), review


def test_world_consistency_review_accepts_outsider_misread_alias():
    world_events = [
        {
            "event_id": "c2-outsider",
            "actor": "普通玩家",
            "action": "普通玩家觉得夜烬路线熟或运气好，无追查",
            "location": "灰烬村队尾",
            "visible_to": ["普通玩家"],
        }
    ]
    body = (
        "队尾另一个散人玩家看见夜烬从修理铺出来，顺嘴嘀咕：“这人路线挺熟啊，估计也就运气好。”"
        "旁边排队的人很快又转回自己的面板，没人追问。"
    )

    review = review_world_event_consistency(body, world_events=world_events, scene_cards=[])

    assert review["pass"]
    assert review["issues"] == []


def test_world_consistency_review_accepts_chapter_two_reaction_aliases():
    scene_cards = [
        {"scene_id": "reaction", "must_show": ["散人玩家抱怨灰狼毒腺掉率低", "洛婶按清单办事不理会夜烬频率"]}
    ]
    body = (
        "公共频道里有人抱怨毒腺掉率低，刷了半天还差好几份。"
        "洛婶只按清单收钱拿药，不问夜烬这一趟来得快不快，也不理会他刚交完委托又买药。"
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=scene_cards, chapter_number=2)

    assert review["pass"]
    assert review["issues"] == []


def test_world_consistency_review_accepts_chapter_two_goal_sequence_alias():
    scene_cards = [
        {"scene_id": "goal", "must_show": ["试打后坡→交委托→修买→探路卡住", "从野外试打转向村内结算与补给"]}
    ]
    body = (
        "他把这一趟在心里过了一遍：试打后坡只补两份毒腺，回村交委托，"
        "拿铜币修杖买药，再去登记牌前确认探路提示。走到最后一步，提示还是把他挡在坡口。"
        "后坡的野外试打结束后，他回到村内广场结算清道夫委托，三十铜到手，再去修理铺和药剂铺补给。"
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=scene_cards, chapter_number=2)

    assert review["pass"]
    assert review["issues"] == []


def test_world_consistency_review_flags_scene_card_meta_leak():
    scene_cards = [
        {
            "scene_id": "s1",
            "must_not_explain": ["爽点", "节奏", "visible_to", "state_delta"],
        }
    ]
    body = "这一段爽点已经兑现，visible_to 限制也说明了公会暂时看不见他。"

    review = review_world_event_consistency(body, world_events=[], scene_cards=scene_cards)

    assert not review["pass"]
    assert review["scores"]["surface_terms"] < 8
    assert any("场景卡禁写词" in issue for issue in review["issues"])


def test_world_consistency_review_flags_missing_scene_card_must_show_beats():
    scene_cards = [
        {
            "scene_id": "s1-character-create",
            "template_id": "character_creation",
            "location": "角色创建界面",
            "purpose": "建立游戏ID、职业选择和第一版角色面板。",
            "must_show": ["游戏ID", "职业选择", "角色面板", "生命/法力", "基础属性"],
        },
        {
            "scene_id": "s2-market",
            "template_id": "market_weak_trace",
            "location": "交易行",
            "purpose": "小额匿名寄售。",
            "must_show": ["价格", "数量", "批次", "手续费", "到账"],
        },
    ]
    body = "夜烬进入游戏后很快杀了几只狼，又把材料挂到了交易行。事情推进得很顺利。"

    review = review_world_event_consistency(body, world_events=[], scene_cards=scene_cards)

    assert not review["pass"]
    assert review["scores"]["scene_card_coverage"] < 8
    assert any("场景卡必写内容缺失" in issue for issue in review["issues"])
    assert any("职业选择" in item and "角色面板" in item for item in review["revision_plan"])


def test_world_consistency_review_accepts_scene_card_must_show_beats_when_surfaced():
    scene_cards = [
        {
            "scene_id": "s1-character-create",
            "template_id": "character_creation",
            "location": "角色创建界面",
            "purpose": "建立游戏ID、职业选择和第一版角色面板。",
            "must_show": ["游戏ID", "职业选择", "角色面板", "生命/法力", "基础属性"],
        },
        {
            "scene_id": "s2-market",
            "template_id": "market_weak_trace",
            "location": "交易行",
            "purpose": "小额匿名寄售。",
            "must_show": ["价格", "数量", "批次", "手续费", "到账"],
        },
    ]
    body = (
        "角色创建界面亮起，苏叶填下游戏ID夜烬，职业选择停在元素法师学徒。"
        "角色面板随即展开：生命、法力、力量、敏捷和精神这些基础属性都还很低。"
        "交易行界面显示价格、数量和批次，扣除手续费后，到账提示才慢半拍跳出来。"
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=scene_cards)

    assert review["scores"]["scene_card_coverage"] == 8
    assert not any("场景卡必写内容缺失" in issue for issue in review["issues"])


def test_world_consistency_review_accepts_npc_location_or_window_alias():
    scene_cards = [
        {
            "scene_id": "s4-c1-npc-service",
            "must_show": ["NPC地点或窗口", "服务内容", "价格/门槛"],
        }
    ]
    body = (
        "村口的任务牌旁边开着一个小柜台窗口，木牌上只写服务内容和门槛："
        "灰狼毒腺可以登记，补给价格另看柜台价牌。"
        "窗口后的NPC只管把牌子扶正，不问来源，也不知道谁的背包里有多少材料。"
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=scene_cards, chapter_number=1)

    assert review["scores"]["scene_card_coverage"] == 8
    assert not any("场景卡必写内容缺失" in issue for issue in review["issues"])


def test_world_consistency_review_accepts_natural_job_and_bank_arrival_wording():
    body = (
        "苏叶以前在游戏工作室做职业玩家兼道具估价，后来转去交易平台审核装备截图和价格。"
        "担保订单成交后，手机弹出银行通知：尾号账户收入1764.00元。"
        "他随即补上房租，又付清信用卡最低还款。"
    )
    scene_cards = [
        {"scene_id": "reality", "must_show": ["现实职业/技能来源"]},
        {"scene_id": "payoff", "must_show": ["真实到账", "现实急账处理"]},
    ]

    review = review_world_event_consistency(
        body=body,
        world_events=[],
        scene_cards=scene_cards,
        chapter_number=1,
    )

    assert not any("场景卡必写内容缺失" in issue for issue in review["issues"])


def test_world_consistency_review_accepts_natural_payout_and_urgent_bill_wording():
    scene_cards = [
        {
            "scene_id": "s6-c1-next-step-hook",
            "must_show": ["真实到账", "现实急账处理"],
        }
    ]
    body = (
        "平台扣除服务费后实际到账1764.00元。苏叶先补上房租，又付了信用卡最低还款，"
        "两笔急账处理完，银行卡可用余额停在332.60元。"
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=scene_cards, chapter_number=1)

    assert not any("场景卡必写内容缺失" in issue for issue in review["issues"])


def test_world_consistency_review_accepts_test_work_and_guaranteed_platform_aliases():
    scene_cards = [
        {
            "scene_id": "s2-c1-reality-entry",
            "must_show": ["现实职业/技能来源"],
        },
        {
            "scene_id": "s6-c1-next-step-hook",
            "must_show": ["担保交易"],
        },
    ]
    body = (
        "苏叶以前在游戏外包公司做数值和流程测试，专门从掉落、任务条件和怪物行为里找问题。"
        "他把裂纹狼心交给持牌担保平台，匿名鉴定后完成交割。"
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=scene_cards, chapter_number=1)

    assert not any("场景卡必写内容缺失" in issue for issue in review["issues"])


def test_world_consistency_review_accepts_event_action_alias_surface():
    world_events = [
        {
            "event_id": "c1-reality-entry",
            "actor": "主角",
            "action": "在现实压力下登录游戏，决定用游戏内身份试探机会。",
            "location": "现实出租屋",
            "prose_priority": 9,
        },
        {
            "event_id": "c1-small-verify",
            "actor": "夜烬",
            "action": "通过低级怪物和任务材料小额验证千倍爆率。",
            "location": "灰烬村外",
            "prose_priority": 8,
        },
    ]
    body = (
        "出租屋里，催租短信压在手机屏幕上，苏叶拿起头盔登录《界域》。"
        "角色创建界面亮起，他输入游戏ID夜烬，选择元素法师学徒。"
        "村外的灰狼扑上来，他用火苗术击杀后听见掉落提示音，背包里多出材料。"
        "这个结果让他确认千倍爆率不是错觉。"
    )

    review = review_world_event_consistency(body, world_events=world_events, scene_cards=[])

    assert review["scores"]["event_coverage"] == 8
    assert not any("推演事件未被正文场景化" in issue for issue in review["issues"])


def test_world_consistency_review_accepts_semantic_scene_card_surface():
    scene_cards = [
        {
            "scene_id": "s1-c1-reality-entry",
            "must_show": ["现实职业/技能来源", "为什么登录游戏", "主角风险偏好"],
        },
        {
            "scene_id": "s2-c1-character-create",
                "must_show": ["初始身份", "角色面板", "武器/基础技能"],
        },
        {
            "scene_id": "s3-c1-small-verify",
            "must_show": ["低级怪物", "掉落反馈", "背包变化", "小额验证"],
        },
        {
            "scene_id": "s4-c1-npc-service",
            "must_show": ["NPC地点", "服务内容", "信息边界"],
        },
    ]
    body = (
        "苏叶以前做风控测试员，每天对着数据模型算概率、盯异常流水。房租催缴和停职通知压在桌上，"
            "他决定登录游戏低调变现，先隔离风险。角色创建界面里，他确认初始身份为见习冒险者（未转职），选择新手法杖和基础火球术。"
            "面板在视野右侧展开：【等级：1】【经验：0/100】【生命：120/120】【法力：80/80】"
            "【身份：见习冒险者（未转职）】【主武器：新手法杖】【基础技能：基础火球术】。他先试一次，击杀灰狼后听见掉落提示音，"
        "背包里的毒腺数量跳到3，确认不是错觉。灰烬村药剂铺的柜台后，洛婶写着收购解毒剂主料；"
        "她不问来源，但交易记录会留下流水。"
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=scene_cards)

    assert review["scores"]["scene_card_coverage"] == 8
    assert not any("场景卡必写内容缺失" in issue for issue in review["issues"])
