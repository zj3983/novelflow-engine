from packages.story_core.orchestrator import _merge_writing_review_quality, _review_chapter_body, _sanitize_chapter_output
from packages.story_core.progression_lead_review import review_progression_lead
from packages.story_core.world_consistency_review import review_world_event_consistency


def test_progression_lead_review_rejects_first_chapter_service_loop():
    body = (
        "《天启之门》开服，苏叶登录后用夜烬建号，职业是元素法师学徒。"
        "灰狼倒下时，混沌之种闪了一下，提示掉落判定×1000，背包里多了灰狼毒腺和粗糙狼皮。"
        "他回村交清道夫委托，任务完成，获得：30铜。"
        "随后他去修理铺扣除：30铜，把法杖修满，又去药剂铺问初级法力药水，什么价。"
    )

    review = review_progression_lead(chapter_number=1, body=body, event_plan={}, world_facts=[])

    assert not review["pass"]
    assert review["scores"]["opening_scope"] == 5
    assert review["metrics"]["service_closure_count"] >= 3
    assert any("服务闭环" in issue for issue in review["issues"])


def test_progression_lead_review_accepts_opening_that_turns_drops_into_route_lead():
    body = (
        "《天启之门》开服，苏叶登录，游戏ID夜烬，职业是元素法师学徒。"
        "第一只灰狼倒下时，提示【混沌之种：未解析】【掉落判定×1000】。"
        "普通玩家还在坡下等毒腺，他的背包已经亮红。"
        "他只拿出十份毒腺交清道夫委托，任务完成，获得30铜。"
        "排队的人只当他运气好，没人知道他背包底下还压着多余材料。"
        "他用十二铜修好法杖，剩下的钱袋收进衣内。"
        "下一轮他要凑够五十铜，去职业导师木牌前兑换基础技能书。"
    )

    review = review_progression_lead(chapter_number=1, body=body, event_plan={}, world_facts=[])

    assert review["pass"]
    assert review["scores"]["progression_payoff"] == 8
    assert review["metrics"]["progression_payoff_count"] >= 2
    assert review["metrics"]["concrete_payoff_count"] >= 2
    assert review["metrics"]["outsider_misread_count"] >= 1


def test_progression_lead_review_does_not_treat_trade_notice_as_closure():
    body = (
        "《天启之门》开服公告写着材料处理功能将在开服次日夜间开放测试，提现相关说法同步公示。"
        "苏叶登录游戏，游戏ID夜烬。第一只灰狼倒下时，混沌之种闪了一下，掉落判定×1000。"
        "普通玩家还在等毒腺，夜烬已经拿到灰狼毒腺和粗糙狼皮，但他没有寄售，没有成交，也没有到账。"
        "他只把材料压进背包，下一步准备再刷一轮，先凑出清道夫委托和后坡入口的前置。"
        "旁边玩家只当他运气好，没人知道背包里多出来的材料。"
    )

    review = review_progression_lead(chapter_number=1, body=body, event_plan={}, world_facts=[])

    assert review["metrics"]["trade_closure_count"] == 0
    assert not any("交易闭环" in issue for issue in review["issues"])


def test_chapter_body_review_includes_progression_lead_review():
    body = (
        "《天启之门》开服，苏叶在出租屋里戴上旧头盔，游戏ID夜烬，职业是元素法师学徒。"
        "【等级：Lv.1】【职业：元素法师学徒】【经验：0/100】【生命：100/100】【法力：60/60】【货币：0铜】"
        "灰狼倒下时，混沌之种闪了一下，提示掉落判定×1000，背包里多了灰狼毒腺和粗糙狼皮。"
        "他回村交清道夫委托，任务完成，获得：30铜。"
        "他去修理铺扣除：30铜，把法杖修满，又买两瓶药水。"
    ) * 30

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["普通玩家只觉得他运气好。"], "next_focus": "继续抢路线。"},
        world_facts=["长期核心：混沌之种、千倍爆率、进度领先钩子。"],
    )

    assert "progression_lead_review" in review
    assert not review["progression_lead_review"]["pass"]
    assert any("服务闭环" in issue for issue in review["issues"])


def test_quality_report_exposes_progression_lead_review():
    quality = {"ok": True, "issues": []}
    writing_review = {
        "pass": False,
        "issues": ["第一章提前办完服务闭环。"],
        "scores": {"progression_lead_opening_scope": 5},
        "progression_lead_review": {"pass": False, "issues": ["第一章提前办完服务闭环。"]},
    }

    merged = _merge_writing_review_quality(quality, writing_review)

    assert merged["ok"] is False
    assert "progression_lead_review" in merged


def test_first_chapter_sanitizer_does_not_rewrite_service_closure_or_add_hook():
    body = (
        "《天启之门》开服，苏叶登录，游戏ID夜烬，职业是元素法师学徒。"
        "【等级：Lv.1】【职业：元素法师学徒】【经验：0/100】【货币：0铜】"
        "灰狼倒下时，混沌之种闪了一下，提示掉落判定×1000。"
        "他回村交清道夫委托，任务完成，获得：30铜。"
        "他去修理铺扣除：30铜，把法杖修满，又买药水。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1)

    assert "任务完成" in cleaned
    assert "获得：30铜" in cleaned
    assert "修理铺" in cleaned
    assert "买药水" in cleaned
    assert "技能书" not in cleaned
    assert "后坡" not in cleaned


def test_first_chapter_sanitizer_leaves_missing_npc_window_for_review():
    body = (
        "《天启之门》开服，苏叶登录，游戏ID夜烬，职业是元素法师学徒。"
        "角色面板：【等级：Lv.1】【职业：元素法师学徒】【经验：0/100】【生命：100/100】【法力：60/60】【货币：0铜】"
        "灰狼倒下时，混沌之种闪了一下，提示掉落判定×1000，背包里多了灰狼毒腺。"
        "夜烬说：“先不卖。”"
    )
    scene_cards = [
        {
            "scene_id": "s4-c1-npc-service",
            "must_show": ["NPC地点", "服务内容", "信息边界"],
        }
    ]

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=scene_cards)
    review = review_world_event_consistency(cleaned, world_events=[], scene_cards=scene_cards)

    assert "柜台窗口" not in cleaned
    assert "夜烬" in cleaned
    assert "夜烬说" in cleaned
    assert review["scores"]["scene_card_coverage"] < 8
    assert any("场景卡必写内容缺失" in issue for issue in review["issues"])


def test_first_chapter_sanitizer_does_not_add_reality_skill_source():
    body = "苏叶看了一眼余额，戴上旧头盔进入《天启之门》。游戏ID夜烬。"
    scene_cards = [
        {
            "scene_id": "s1-c1-reality-entry",
            "must_show": ["现实职业/技能来源", "为什么登录游戏", "主角风险偏好"],
        }
    ]

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=scene_cards)

    assert cleaned == body
    assert "外包测试员" not in cleaned
    assert "照表点功能" not in cleaned


def test_first_chapter_sanitizer_leaves_missing_progression_and_misread_for_review():
    body = (
        "苏叶进入《天启之门》，职业是元素法师学徒。"
        "第一次击杀灰狼后，混沌之种提示掉落判定×1000，背包里多了灰狼毒腺八份。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])
    review = review_progression_lead(chapter_number=1, body=cleaned, event_plan={}, world_facts=[])

    assert "夜烬" not in cleaned
    assert "清道夫委托" not in cleaned
    assert "后坡入口" not in cleaned
    assert "只当他运气好" not in cleaned
    assert review["pass"] is False


def test_first_chapter_sanitizer_does_not_delete_damage_or_currency_events():
    body = (
        "《天启之门》开服，苏叶登录，游戏ID夜烬。"
        "灰狼倒下时，伤害数字从15跳到12，混沌之种提示掉落判定×1000。"
        "他看见面板写着当前货币：0铜，奖励三十铜还挂在任务牌后面。"
        "修理匠问他要不要买两瓶药水，他摇头，又往职业导师门口看了一眼。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1)
    review = review_progression_lead(chapter_number=1, body=cleaned, event_plan={}, world_facts=[])

    assert "跳出的数值" in cleaned
    assert "货币栏还是空的" in cleaned
    assert "奖励三十铜" in cleaned
    assert "买两瓶" in cleaned
    assert "清道夫委托" not in cleaned
