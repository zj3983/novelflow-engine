from packages.story_core.orchestrator import _review_chapter_body
from packages.story_core.web_game_review import review_web_game_chapter, web_game_review_rules


def test_web_game_review_rejects_first_chapter_missing_initial_identity_and_panel():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里完成登录，游戏ID夜烬进入灰烬村。"
        "他是前外包风控测试员，盯着交易行手续费和匿名流水，准备用低级材料做一次小额验证。"
        "旧头盔闪过灰色日志，混沌之种提示千倍爆率已激活。"
        "药剂师洛婶在药剂铺按七铜币回收毒腺，提醒他材料别一次砸盘。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在频道里争抢新手村资源。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"npc_beats": ["洛婶报价。"], "world_reactions": ["交易行商人记录弱线索。"]},
        world_facts=["身份规则：第一章必须写出初始身份、武器/基础技能选择，并在角色面板里记录身份。"],
    )

    assert review["pass"] is False
    assert any("初始身份" in issue for issue in review["issues"])
    assert any("角色面板" in issue for issue in review["issues"])


def test_web_game_review_allows_first_chapter_initial_identity_panel_and_single_npc():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里完成登录，游戏ID夜烬进入角色创建界面。"
        "角色创建界面确认初始身份都是见习冒险者（未转职），他在新手武器里选择新手法杖，并拿到基础火球术。"
        "【角色面板】游戏ID：夜烬；等级：1；身份：见习冒险者（未转职）；经验：0/100；"
        "生命：100/100；法力：80/80；基础属性：力量5，体质6，敏捷7，智力11，精神10，幸运1；"
        "主武器：新手法杖；基础技能：火球术未解锁；货币：0金币0银币0铜币。"
        "他是前外包风控测试员，盯着交易行手续费和匿名流水，准备用低级材料做一次小额验证。"
        "旧头盔闪过灰色日志，混沌之种提示千倍爆率已激活。"
        "药剂师洛婶在药剂铺柜台后报价回收毒腺，说明库存缺口和价格边界，提醒他别一次砸盘。"
        "交易行只显示价格、数量、批次和时间戳，白袍公会、赤焰公会、星河商会和散人玩家只能看到弱线索。"
    ) * 20

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"npc_beats": ["洛婶报价。"], "world_reactions": ["交易行商人记录弱线索。"]},
        world_facts=["身份规则：第一章必须写出初始身份、武器/基础技能选择，并在角色面板里记录身份。"],
    )

    assert review["pass"] is True, review


def test_opening_review_requires_initial_identity_and_panel():
    body = (
        "《天启之门》全沉浸VRMMO开服当晚，苏叶在出租屋里看着房租账单登录游戏。"
        "角色创建界面确认游戏ID：夜烬。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常。"
        "他激活隐藏天赋混沌之种，确认千倍爆率生效。"
        "药剂师洛婶在药剂铺回收毒腺并提醒解毒剂任务缺材料。"
        "他通过交易行匿名寄售材料，注意到手续费、流水和风控异常提示。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在争抢新手村资源。"
    ) * 35

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "继续低调变现。"},
    )

    assert review["pass"] is False
    assert any("初始身份" in issue for issue in review["issues"])
    assert any("角色面板" in issue for issue in review["issues"])


def test_web_game_prompt_rules_include_initial_identity_and_panel():
    rules = "\n".join(web_game_review_rules())

    assert "初始身份" in rules
    assert "角色面板" in rules
