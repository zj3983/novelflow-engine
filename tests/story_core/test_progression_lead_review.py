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
        "他没有提交清道夫委托，也没有去交易行。"
        "他只是盯着职业导师门口的元素回廊前置牌：十份毒腺可换试炼资格。"
        "这意味着下一章他能比别人快一步摸到技能书和元素回廊入口。"
    )

    review = review_progression_lead(chapter_number=1, body=body, event_plan={}, world_facts=[])

    assert review["pass"]
    assert review["scores"]["progression_payoff"] == 8
    assert review["metrics"]["progression_payoff_count"] >= 2


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


def test_first_chapter_sanitizer_removes_service_closure_and_adds_lead_hook():
    body = (
        "《天启之门》开服，苏叶登录，游戏ID夜烬，职业是元素法师学徒。"
        "【等级：Lv.1】【职业：元素法师学徒】【经验：0/100】【货币：0铜】"
        "灰狼倒下时，混沌之种闪了一下，提示掉落判定×1000。"
        "他回村交清道夫委托，任务完成，获得：30铜。"
        "他去修理铺扣除：30铜，把法杖修满，又买药水。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1)

    assert "任务完成" not in cleaned
    assert "获得：30铜" not in cleaned
    assert "修理铺" not in cleaned
    assert "买药水" not in cleaned
    assert "元素回廊" in cleaned
    assert "下一道门" in cleaned


def test_first_chapter_sanitizer_adds_npc_window_when_scene_card_requires_it():
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

    assert "柜台窗口" in cleaned
    assert "夜烬低声道" in cleaned
    assert review["scores"]["scene_card_coverage"] == 8
    assert not any("场景卡必写内容缺失" in issue for issue in review["issues"])


def test_first_chapter_sanitizer_adds_reality_skill_source_when_scene_card_requires_it():
    body = "苏叶看了一眼余额，戴上旧头盔进入《天启之门》。游戏ID夜烬。"
    scene_cards = [
        {
            "scene_id": "s1-c1-reality-entry",
            "must_show": ["现实职业/技能来源", "为什么登录游戏", "主角风险偏好"],
        }
    ]

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=scene_cards)

    assert "外包测试员" in cleaned
    assert "项目日志" in cleaned
    assert "规则漏洞" in cleaned
