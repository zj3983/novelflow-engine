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
            "must_show": ["职业选择", "角色面板", "基础属性"],
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
        "他决定登录游戏低调变现，先隔离风险。角色创建界面里，他在职业列表中点向法师，选择元素法师学徒。"
        "面板在视野右侧展开：【等级：1】【经验：0/100】【生命：120/120】【法力：80/80】"
        "【力量：5 敏捷：6 智力：12 体质：7】。他先试一次，击杀灰狼后听见掉落提示音，"
        "背包里的毒腺数量跳到3，确认不是错觉。灰烬村药剂铺的柜台后，洛婶写着收购解毒剂主料；"
        "她不问来源，但交易记录会留下流水。"
    )

    review = review_world_event_consistency(body, world_events=[], scene_cards=scene_cards)

    assert review["scores"]["scene_card_coverage"] == 8
    assert not any("场景卡必写内容缺失" in issue for issue in review["issues"])
