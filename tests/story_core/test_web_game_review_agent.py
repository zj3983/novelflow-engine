import pytest

from packages.story_core.web_game_review import review_web_game_chapter, web_game_review_rules
from packages.story_core.orchestrator import _merge_writing_review_quality, _opening_writer_rules


def test_web_game_review_requires_panel_before_first_monster_fight():
    body = (
        "《天启之门》开服后，夜烬走到灰狼坡。"
        "第一只灰狼从石头后扑出来，他抬手放出火球，随后击杀了灰狼。"
    ) * 20

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"ordered_actions": ["夜烬第一次和灰狼正式交战"]},
        world_facts=["这是夜烬第一次遇见灰狼。"],
    )

    assert any("怪物面板" in issue for issue in review["issues"])
    assert any("正文中明确写出“怪物面板”" in item for item in review["revision_plan"])


def test_web_game_review_accepts_compact_first_monster_panel():
    body = (
        "《天启之门》开服后，夜烬走到灰狼坡。"
        "【灰狼】【等级：1】【生命：80/80】【攻击方式：扑咬】"
        "灰狼从石头后扑出来，他抬手放出火球，随后击杀了灰狼。"
    ) * 20

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"ordered_actions": ["夜烬第一次和灰狼正式交战"]},
        world_facts=["这是夜烬第一次遇见灰狼。"],
    )

    assert not any("怪物面板" in issue for issue in review["issues"])


def test_web_game_review_accepts_plain_text_monster_panel_without_brackets():
    body = (
        "《神域》开服后，夜烬走到灰狼坡。正式交战前，他凝神查看怪物面板。"
        "名称：灰狼，等级：1，生命：80/80，攻击方式：扑咬。"
        "灰狼从石头后扑出来，他抬手放出基础火球术，随后击杀了灰狼。"
    ) * 20

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"ordered_actions": ["夜烬第一次和灰狼正式交战"]},
        world_facts=["这是夜烬第一次遇见灰狼。"],
    )

    assert not any("怪物面板" in issue for issue in review["issues"])


def test_web_game_review_requires_fix_for_explicit_economy_boundary_violations():
    forbidden_currency_name = "\u4eba\u6c11\u5e01"
    body = (
        "《神域》里，夜烬把裂纹狼心卖给求购单，交易行把成交所得直接打进现实账户。\n\n"
        "裂纹狼心的正式名称和锻造用途已经显示出来，他还是把它提交鉴定，平台又安排验货。\n\n"
        "这张求购单的资金已经冻结，立即出售也显示成交，系统却让他继续等待买家再次确认。\n\n"
        f"界面还把结算单位完整写成{forbidden_currency_name}。"
    )

    review = review_web_game_chapter(chapter_number=4, body=body, event_plan={}, world_facts=[])

    economy_issues = [issue for issue in review["issues"] if "经济边界" in issue]
    assert len(economy_issues) == 4
    assert all("必须修复" in issue for issue in economy_issues)
    plans = "\n".join(review["revision_plan"])
    assert "交易行只进游戏钱包" in plans
    assert "已识别物不重复鉴定" in plans
    assert "资金冻结的求购单应立即成交" in plans
    assert "独立官方兑换" in plans
    assert forbidden_currency_name not in plans


def test_web_game_review_accepts_separated_exchange_and_conservative_economy_terms():
    body = (
        "《神域》里，夜烬选中一张已经冻结游戏币的求购单，立即出售裂纹狼心，成交后游戏币进入游戏钱包。\n\n"
        "他随后离开交易行，打开独立的官方兑换页面，确认兑换价、额度、手续费和预计到账，现实账户很快收到款项。\n\n"
        "背包里的未知矿石只显示未鉴定，他把矿石交给鉴定师。另一个玩家在聊天栏里问了一句求购，柜台旁也有人提到账。"
    )

    review = review_web_game_chapter(chapter_number=4, body=body, event_plan={}, world_facts=[])

    assert not any("经济边界" in issue for issue in review["issues"]), review


def test_web_game_review_detects_ordered_economy_chains_across_adjacent_units():
    body = (
        "《神域》里，交易行显示那件拍卖物已经成交。\n\n"
        "下一秒，卖出所得直接打进现实账户。\n\n"
        "【名称：裂纹狼心】【用途：锻造材料】\n\n"
        "夜烬看完面板，还是把它提交鉴定。\n\n"
        "另一张求购单显示资金已经冻结。\n\n"
        "夜烬点下立即出售，界面显示成交。\n\n"
        "系统却让他等待买家再次确认。"
    )

    review = review_web_game_chapter(chapter_number=4, body=body, event_plan={}, world_facts=[])

    economy_issues = [issue for issue in review["issues"] if "经济边界" in issue]
    assert len(economy_issues) == 3


def test_web_game_review_ignores_negated_economy_chains_and_other_unidentified_item():
    body = (
        "《神域》的交易行显示求购单已经成交。\n\n"
        "款项不会直接进入现实账户，必须另走独立官方兑换。\n\n"
        "裂纹狼心的用途是锻造；旁边的披风仍未鉴定，他把披风交给鉴定师。\n\n"
        "另一张求购单显示资金已经冻结。\n\n"
        "夜烬点下立即出售，界面显示成交。\n\n"
        "成交以后不再等待买家确认，游戏币直接进入游戏钱包。"
    )

    review = review_web_game_chapter(chapter_number=4, body=body, event_plan={}, world_facts=[])

    assert not any("经济边界" in issue for issue in review["issues"]), review


def test_web_game_review_does_not_let_earlier_exchange_hide_direct_market_settlement():
    body = (
        "《神域》里，夜烬先退出官方兑换页面再打开交易行，"
        "求购单成交后，卖出所得直接转入现实账户。"
    )

    review = review_web_game_chapter(chapter_number=4, body=body, event_plan={}, world_facts=[])

    assert any("交易与现实兑换混成了一步" in issue for issue in review["issues"]), review


@pytest.mark.parametrize(
    ("body", "issue_fragment"),
    [
        (
            "交易行显示求购单已经成交。\n\n夜烬顺手关掉了背包。\n\n卖出所得直接转入现实账户。",
            "交易与现实兑换混成了一步",
        ),
        (
            "裂纹狼心已显示正式名称。\n\n夜烬看了一眼门外。\n\n他把它提交鉴定。",
            "又被送去鉴定或验货",
        ),
        ("求购成交所得直接现实到账。", "交易与现实兑换混成了一步"),
        (
            "求购单里的资金被冻结了。\n\n夜烬点下立即出售，界面显示成交。\n\n系统要求等待买家再次确认。",
            "仍在等待买家再次确认",
        ),
        ("夜烬把已经识别的裂纹狼心提交鉴定。", "又被送去鉴定或验货"),
        (
            "交易行显示求购单成交。\n\n夜烬摘下头盔。\n\n这笔成交款直接进入现实账户。",
            "交易与现实兑换混成了一步",
        ),
        (
            "甲求购单资金冻结。\n\n甲求购单随即成交。\n\n甲求购单仍要求等待买家确认。",
            "仍在等待买家再次确认",
        ),
    ],
)
def test_web_game_review_detects_explicit_economy_boundaries_in_three_paragraph_window(
    body: str,
    issue_fragment: str,
):
    review = review_web_game_chapter(
        chapter_number=4,
        body=f"网游《神域》里，{body}",
        event_plan={},
        world_facts=[],
    )

    matching = [issue for issue in review["issues"] if issue_fragment in issue]
    assert matching, review
    assert all("必须修复" in issue for issue in matching)


@pytest.mark.parametrize(
    "body",
    [
        "交易行显示求购单已经成交。\n\n夜烬停了一会儿。\n\n款项没有直接进入现实账户，必须另走独立官方兑换。",
        "求购单里的资金被冻结了。\n\n夜烬立即出售，界面显示成交。\n\n系统没有要求等待买家确认。",
        "交易行成交后游戏币进入游戏钱包。\n\n他打开独立官方兑换页面。\n\n确认兑换价和手续费后，现实账户到账。",
        "裂纹狼心用途是锻造。\n\n旁边的披风仍未鉴定。\n\n他把披风交给鉴定师。",
        "裂纹狼心已识别。\n\n夜烬随后拿起披风，当前查看的是披风。\n\n他把它提交鉴定。",
        "交易行显示求购单成交。\n\n夜烬离开市场。\n\n两天后他完成了另一项任务。\n\n现实账户到账的是旧工资。",
        "交易行显示求购单成交。\n\n夜烬退出游戏。\n\n公司工资到账现实账户。",
        "交易行显示求购单成交。\n\n夜烬退出游戏。\n\n现实账户出现一笔到账通知，没有注明交易来源。",
        "交易行显示求购单成交。\n\n夜烬停了一会儿。\n\n款项没有被交易行直接打进现实账户。",
        "交易行显示求购单成交。\n\n夜烬停了一会儿。\n\n这笔钱不需要由交易行直接转入现实账户。",
        "裂纹狼心已经识别。\n\n夜烬换成了一把长剑。\n\n他把它提交鉴定。",
        "甲求购单资金冻结。\n\n乙求购单随即成交。\n\n丙求购单仍要求等待买家确认。",
    ],
)
def test_web_game_review_accepts_negated_or_separated_three_paragraph_economy_flows(body: str):
    review = review_web_game_chapter(
        chapter_number=4,
        body=f"网游《神域》里，{body}",
        event_plan={},
        world_facts=[],
    )

    assert not any("经济边界" in issue for issue in review["issues"]), review


def test_web_game_review_rejects_login_after_disconnected_broadband_without_network_source():
    body = (
        "家里的宽带已经断网两天，路由器指示灯全灭。"
        "苏叶戴上全沉浸头盔，登录《天启之门》，系统显示网络延迟十二毫秒。"
    )

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"ordered_actions": ["苏叶登录游戏"]},
        world_facts=[],
    )

    assert any("有效联网方式" in issue for issue in review["issues"])


def test_opening_writer_rules_do_not_embed_one_projects_balance():
    rules = "\n".join(_opening_writer_rules(1))

    assert "27.60" not in rules
    assert "项目写作包" in rules
    assert "禁止寄售成功" not in rules
    assert "交易、到账和现实付款是否发生，必须服从本书大纲" in rules


def test_web_game_review_requires_skills_and_traits_for_elite_panel():
    body = (
        "《天启之门》里，夜烬在矿洞遇见灰狼精英。"
        "【灰狼精英】【等级：5】【生命：600/600】【攻击方式：扑咬】"
        "灰狼精英随即发动攻击。"
    ) * 20

    review = review_web_game_chapter(
        chapter_number=4,
        body=body,
        event_plan={"ordered_actions": ["首次挑战灰狼精英"]},
        world_facts=["灰狼精英是本章新敌人。"],
    )

    assert any("技能和特性" in issue for issue in review["issues"])


def test_web_game_review_rejects_three_level_solo_kill_with_only_skill_claims():
    body = (
        "【游戏ID：夜烬】【等级：Lv.5】【生命：100/100】"
        "【腐沼鳄（精英）】【等级：Lv.8】【生命：400/400】"
        "【攻击方式：扑咬】【技能：扫尾】【特性：厚皮】"
        "夜烬只靠走位和计算避开攻击，最后单独击杀了腐沼鳄，法力耗尽。"
    )

    review = review_web_game_chapter(
        chapter_number=20,
        body=body,
        event_plan={"ordered_actions": ["夜烬单刷腐沼鳄"]},
    )

    assert any("高出3级" in issue and "缺少成立条件" in issue for issue in review["issues"])


def test_web_game_review_accepts_three_level_kill_with_established_reason_and_cost():
    body = (
        "【游戏ID：夜烬】【等级：Lv.5】【生命：100/100】"
        "任务说明早已写明缚鳄索能压制腐沼鳄，夜烬和三名队友使用任务道具后开怪。"
        "【腐沼鳄（精英）】【等级：Lv.8】【生命：400/400】"
        "【攻击方式：扑咬】【技能：扫尾】【特性：厚皮】"
        "四人耗尽药水才将它击杀。"
    )

    review = review_web_game_chapter(
        chapter_number=20,
        body=body,
        event_plan={"special_combat_conditions": ["任务道具缚鳄索", "四人组队"]},
    )

    assert not any("高出3级" in issue for issue in review["issues"])


def test_web_game_review_rejects_real_name_as_game_identity():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里完成登录。"
        "进入灰烬村后，交易行寄售界面直接显示卖家苏叶，论坛玩家也说苏叶在低价出货。"
        "白袍公会外围把苏叶这个现实姓名写进观察名单。"
    ) * 30

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"world_reactions": ["交易行商人盯盘。"]},
        world_facts=["网游角色必须区分现实姓名和游戏ID。"],
    )

    assert review["pass"] is False
    assert any("现实姓名和游戏ID" in issue for issue in review["issues"])


def test_web_game_review_rejects_missing_named_npc_service_node():
    body = (
        "夜烬在灰烬村刷完狼皮后，只看见系统提示跳出来。"
        "他没有去药剂铺、职业大厅、仓库或村长那里办理任何任务和服务。"
        "交易行价格轻微波动，商人玩家开始盯时间戳。"
    ) * 35

    review = review_web_game_chapter(
        chapter_number=2,
        body=body,
        event_plan={"npc_beats": ["通过NPC服务节点制造任务门槛。"]},
        world_facts=["NPC硬规则：灰烬村村长、药剂师洛婶、职业导师艾伦、仓库管理员铁栓、修理匠老葛。"],
    )

    assert review["pass"] is False
    assert any("命名NPC" in issue for issue in review["issues"])


def test_web_game_review_rejects_single_trade_omniscient_tracking():
    body = (
        "夜烬把低级狼皮匿名上架交易行。"
        "白袍公会只看了一笔交易，就立刻锁定他的坐标、现实身份和刷怪点。"
        "公会频道宣布已经知道混沌之种就在夜烬身上。"
    ) * 35

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"world_reactions": ["公会外围开始注意。"]},
        world_facts=["低级材料交易只能形成价格、数量、时间戳等弱线索。"],
    )

    assert review["pass"] is False
    assert any("单次" in issue and "锁定" in issue for issue in review["issues"])


def test_web_game_review_allows_explicit_weak_signal_tracking():
    body = (
        "夜烬把低级狼皮匿名上架交易行，界面提示默认隐藏卖家ID与坐标。"
        "药剂师洛婶在药剂铺按任务需求回收毒腺，提醒解毒剂材料正在降价。"
        "白袍公会只记录价格波动、数量批次和时间戳，不查坐标，也不知道现实身份。"
        "执事要求等模式重复三次，再通过论坛风向、资源点目击和NPC任务异常多源汇总。"
    ) * 35

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"world_reactions": ["公会外围开始记录弱线索。"]},
        world_facts=["低级材料交易只能形成价格、数量、时间戳等弱线索。"],
    )

    assert review["pass"] is True, review


def test_web_game_review_allows_first_trade_notice_without_identity_tracking():
    body = (
        "夜烬把灰鼠毒腺拆成多笔匿名挂进灰烬村交易行。"
        "不到十秒，第一笔交易提示亮起，系统只显示价格、数量批次和时间戳。"
        "药剂师洛婶在药剂铺报价回收毒腺，提醒低级材料不要一次砸盘。"
        "世界频道里白袍公会在资源点清场，但交易行没有坐标，没有ID，也不知道现实身份。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"world_reactions": ["商人脚本记录弱线索。"], "npc_beats": ["洛婶报价。"]},
        world_facts=["低级材料交易只能形成价格、数量、时间戳等弱线索。"],
    )

    assert review["pass"] is True, review


def test_web_game_review_rejects_boundary_chapter_drifting_to_money_exchange():
    body = (
        "《天启之门》开服后，夜烬选择元素法师学徒，在灰狼坡确认异常掉落。"
        "他回村后立刻打开交易行寄售灰狼毒腺，成交提示跳出，到账扣了手续费。"
        "药剂师洛婶只按任务数量说话，普通玩家不知道他的现实身份。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"chapter_intent": "第一章确认边界，不是赚钱。"},
        world_facts=["第一章目标：确认边界，不换钱，不写交易行操作。"],
    )

    assert review["pass"] is False
    assert any("边界章目标漂移" in issue for issue in review["issues"])


def test_web_game_review_rejects_first_chapter_missing_core_anchors():
    body = (
        "《天启之门》开服，苏叶用夜烬建号，职业选择元素法师学徒。"
        "角色面板显示等级Lv.1，经验0/100，货币：15铜，技能是元素弹。"
        "他去灰狼坡刷怪，只看到掉落异常和不正常的材料数量。"
        "回村后，他看见柜台排队，准备下一章再处理材料。"
    ) * 30

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"chapter_intent": "第一章只试清楚游戏里的路，不换钱。"},
        world_facts=["长期核心：混沌之种、底层协议校验通过、千倍爆率、基础火球术、初始0铜、进度领先钩子。"],
    )

    assert review["pass"] is False
    issues = "\n".join(review["issues"])
    assert "千倍爆率" in issues
    assert "混沌之种" in issues
    assert "底层协议校验通过" in issues
    assert "基础火球术" in issues
    assert "铜币账本漂移" in issues
    assert "进度领先钩子" in issues


def test_web_game_review_allows_first_chapter_trade_board_without_trade_completion():
    body = (
        "《天启之门》开服，银行卡余额只剩27.60，苏叶戴上旧头盔。"
        "底层协议校验通过后，他用夜烬建号，确认初始身份为见习冒险者（未转职），选择新手法杖和基础火球术。"
        "角色面板显示：身份见习冒险者（未转职），Lv.1，经验0/100，生命100/100，法力60/60，钱袋为空，新手法杖，基础火球术。"
        "灰狼倒下时，提示闪过：混沌之种：未解析。掉落判定×1000，千倍爆率。"
        "任务面板轻轻一跳，清道夫委托的任务前置比旁人少跑了好几趟，下一步可以提前去问基础火球术强化。"
        "仓库窗口后，仓库管理员铁栓敲了敲柜台，说这里只办理仓库寄存服务，规矩是先交押金，没铜币就不能办。"
        "他回村只看见交易行门口的价牌和批次，不寄售，不成交，也没有到账。"
    ) * 30

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"chapter_intent": "第一章只试清楚游戏里的路，不换钱。"},
        world_facts=["长期核心：混沌之种、底层协议校验通过、千倍爆率、基础火球术、初始0铜、进度领先钩子。"],
    )

    assert review["pass"] is True, review


def test_web_game_review_accepts_commission_progress_as_progression_payoff():
    body = (
        "《神域》开服，夜烬以见习冒险者身份选择新手法杖和基础火球术，钱袋为空。"
        "灰狼倒下后，底层协议校验通过，混沌之种和千倍爆率同时出现。"
        "清道夫委托进度已经到了8/16，别人还在等第一份毒腺。"
    )

    review = review_web_game_chapter(chapter_number=1, body=body, event_plan={}, world_facts=[])

    assert not any("进度领先钩子" in issue for issue in review["issues"])


def test_web_game_review_does_not_force_first_chapter_full_npc_service():
    body = (
        "《天启之门》开服，银行卡余额只剩27.60，苏叶戴上旧头盔。"
        "底层协议校验通过后，他用夜烬建号，职业选择元素法师学徒。"
        "角色面板显示：游戏ID夜烬，职业元素法师学徒，等级Lv.1，经验0/100，生命100/100，法力60/60，货币0铜，新手法杖，基础火球术。"
        "灰狼倒下时，提示闪过：混沌之种：未解析。掉落判定×1000，千倍爆率。"
        "背包里多出的毒腺把格子挤满，他没卖，只看见交易行门口的价牌和排队窗口，准备下一章再处理。"
    ) * 15

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"chapter_intent": "第一章只做登录和小验证。"},
        world_facts=["第一章不强制完整NPC柜台，交易行只留弱钩子。"],
    )

    assert review["pass"] is True, review


def test_web_game_review_allows_negated_tracking_language():
    body = (
        "夜烬把灰狼皮拆成多笔匿名挂进灰烬村交易行。"
        "交易行公告写明：卖家坐标、身份标识和现实关联数据已做脱敏处理。"
        "药剂师洛婶在药剂铺报价回收狼牙，提醒低级材料不要一次砸盘。"
        "论坛商会脚本只记录价格、数量批次和时间戳，没有锁定坐标，也不会暴露现实身份。"
        "白袍公会外围只能把这次流水标成弱线索，缺乏坐标锚点与身份关联。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"world_reactions": ["商人脚本记录弱线索。"], "npc_beats": ["洛婶报价。"]},
        world_facts=["低级材料交易只能形成价格、数量、时间戳等弱线索。"],
    )

    assert review["pass"] is True, review


def test_web_game_review_allows_bounded_realtime_visibility_language():
    body = (
        "夜烬把灰狼皮拆成多笔匿名挂进灰烬村交易行。"
        "交易行规则写明：卖家身份、坐标、实时位置对买家不可见，买家只看价格和数量批次。"
        "药剂师洛婶在药剂铺报价回收狼牙，提醒低级材料不要一次砸盘。"
        "白袍公会外围只能记录时间戳，没有锁定坐标，也没有锁定身份。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"world_reactions": ["商人脚本记录弱线索。"], "npc_beats": ["洛婶报价。"]},
        world_facts=["信息可见规则：交易行只能暴露价格、数量、批次和时间戳。"],
    )

    assert review["pass"] is True, review


def test_web_game_review_rejects_unset_real_money_exchange_rate():
    forbidden_currency_name = "\u4eba\u6c11\u5e01"
    body = (
        "夜烬卖出狼皮后看着到账提示。"
        f"他立刻按1金币=100{forbidden_currency_name}计算收益，确认今天已经能付房租。"
        "交易行里其他玩家还在用铜币和银币询价。"
    ) * 35

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={},
        world_facts=[f"没有明确设定前，不得把金币直接换算成{forbidden_currency_name}。"],
    )

    assert review["pass"] is False
    assert any("汇率" in issue for issue in review["issues"])


def test_web_game_review_rejects_over_precise_market_prediction():
    body = (
        "夜烬打开灰烬村交易行，把灰鼠毒腺放进匿名寄售栏。"
        "界面提示：低于均价33%，预计成交速度：快。"
        "药剂师洛婶在药剂铺报价回收毒腺，提醒他低级材料只看品质和批次。"
        "交易行只显示价格、数量和时间戳，不显示卖家坐标。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=2,
        body=body,
        event_plan={"world_reactions": ["交易行弱线索。"], "npc_beats": ["洛婶报价。"]},
        world_facts=["交易行只能给出模糊行情，不给上帝视角成交预测。"],
    )

    assert review["pass"] is False
    assert any("交易行提示过于精确" in issue for issue in review["issues"])


def test_web_game_review_rules_are_prompt_ready():
    rules = web_game_review_rules()

    assert any("游戏ID" in rule for rule in rules)
    assert any("交易行" in rule for rule in rules)
    assert any("NPC" in rule for rule in rules)
    assert any("背景预算" in rule for rule in rules)
    assert any("信息可见" in rule for rule in rules)


def test_web_game_review_rejects_transaction_visibility_overreach():
    body = (
        "《天启之门》开服后，夜烬在灰烬村交易行匿名寄售低级狼皮。"
        "药剂师洛婶在药剂铺回收毒腺，提醒解毒剂任务材料正在涨价。"
        "交易行界面却直接显示卖家坐标、实时位置和真人身份，白袍公会立刻照着坐标追过去。"
    ) * 35

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"world_reactions": ["交易行商人记录价格和时间戳。"]},
        world_facts=["信息可见规则：交易行只能暴露价格、数量、批次和时间戳。"],
    )

    assert review["pass"] is False
    assert any("信息可见" in issue for issue in review["issues"])


def test_web_game_review_rejects_unnormalized_currency_display():
    body = (
        "《天启之门》开服后，夜烬在灰烬村交易行匿名寄售低级毒腺。"
        "药剂师洛婶在药剂铺回收毒腺，提醒他手续费和价格都要算清。"
        "第二批、第三批寄售已经成交，账户余额跳动：0金币3银币2100铜币。"
        "交易行商人只记录价格、数量批次和时间戳，不知道他的现实身份。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=2,
        body=body,
        event_plan={"world_reactions": ["交易行商人记录价格和时间戳。"]},
        world_facts=["网游币制默认使用 1金币=100银币=10000铜币。"],
    )

    assert review["pass"] is False
    assert any("货币显示" in issue for issue in review["issues"])


def test_web_game_review_rejects_mage_written_as_sword_primary():
    body = (
        "《天启之门》开服后，夜烬确认初始身份是见习冒险者（未转职），主武器是新手法杖，任务目标是元素回廊。"
        "他没有使用法杖和基础火球术，而是抽出短剑冲进狼群，用短剑刺穿灰狼弱点。"
        "修理匠老葛在铁匠铺修剑报价，交易行商人只记录价格和时间戳。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=2,
        body=body,
        event_plan={"npc_beats": ["修理匠老葛提供装备修理服务。"]},
        world_facts=["初始身份：夜烬是见习冒险者（未转职），主武器是新手法杖，基础技能是基础火球术。"],
    )

    assert review["pass"] is False
    assert any("武器与战斗方式" in issue for issue in review["issues"])


def test_web_game_review_rejects_mixed_first_chapter_monsters():
    body = (
        "《天启之门》开服后，夜烬在灰烬村外看到几只灰鼠在晨雾里晃动。"
        "他选择元素法师学徒，面板写着基础火苗。"
        "真正动手时，杖尖却对准狼的侧颈，狼爪擦过他的袖口，狼尸倒在地上。"
        "系统提示：【击杀灰鼠。经验+15。】药剂师洛婶提醒灰鼠坡是低级怪物点。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"location_beats": ["灰鼠坡首次验证。"]},
        world_facts=["第一章验证目标：灰鼠。"],
    )

    assert review["pass"] is False
    assert any("怪物对象" in issue for issue in review["issues"])


def test_web_game_review_rejects_gray_mouse_when_plan_locks_gray_wolf():
    body = (
        "《天启之门》开服后，夜烬选择元素法师学徒。"
        "他沿着灰鼠坡往前走，第一只灰鼠从草根下窜出来。"
        "系统提示：【获得：灰鼠毒腺×2，粗糙鼠皮×1】。"
        "仓库管理员铁栓说背包格快满了。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"location_beats": ["灰狼坡首次验证。"]},
        world_facts=["第一章验证目标：灰狼；材料：灰狼毒腺、粗糙狼皮。"],
    )

    assert review["pass"] is False
    assert any("推演事实漂移" in issue for issue in review["issues"])


def test_web_game_review_rejects_unplanned_real_background_expansion():
    body = (
        "房租催款短信还亮着，苏叶戴上旧头盔。"
        "他前世做外包经济模型测试时养成的习惯又冒出来，靶向药费和网贷利息压在心口。"
        "《天启之门》里，夜烬选择元素法师学徒，准备去灰狼坡验证掉落边界。"
        "仓库管理员铁栓提醒他背包格有限。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"location_beats": ["灰狼坡首次验证。"]},
        world_facts=["现实压力：房租、宽带、信用卡最低还款。"],
    )

    assert review["pass"] is False
    assert any("现实背景擅自扩写" in issue for issue in review["issues"])


def test_web_game_review_rejects_panel_value_drift_inside_chapter():
    body = (
        "《天启之门》角色创建完成。角色面板显示：游戏ID：夜烬，身份：见习冒险者（未转职），主武器：新手法杖，基础技能：基础火球术，"
        "生命：120/120，法力：280/280，智力：14，敏捷：8，体质：9。"
        "药剂师洛婶在药剂铺报价回收毒腺，提醒他别乱卖。"
        "章末夜烬再次打开角色面板：生命：92/100，法力：61/80，智力：9，敏捷：4，体质：5。"
    ) * 20

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"npc_beats": ["药剂师洛婶报价。"]},
        world_facts=["角色面板必须前后一致，变化需要正文解释。"],
    )

    assert review["pass"] is False
    assert any("角色面板数值" in issue for issue in review["issues"])


def test_web_game_review_allows_explained_hp_mp_drift():
    body = (
        "《天启之门》角色创建完成。角色面板显示：游戏ID：夜烬，身份：见习冒险者（未转职），"
        "等级：Lv.1，经验：0/100，主武器：新手法杖，基础技能：基础火球术，生命：100/100，法力：80/80，钱袋为空，基础属性：力量3，敏捷4，智力9，体质5。"
        "灰鼠扑上来时抓破他的左臂，夜烬施放基础火苗，法力被抽走一截。"
        "药剂师洛婶在药剂铺报价回收毒腺，提醒他别乱卖。"
        "章末夜烬再次打开角色面板：生命：92/100，法力：61/80，基础属性：力量3，敏捷4，智力9，体质5。"
    ) * 20

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"npc_beats": ["药剂师洛婶报价。"]},
        world_facts=["角色面板必须前后一致，生命法力变化需要正文解释。"],
    )

    assert review["pass"] is True, review


def test_web_game_review_allows_hp_drift_from_visible_wolf_hit():
    body = (
        "夜烬靠着墙打开面板：生命：42/100，法力：12/60。"
        "灰狼扑过来，前爪拍在他胸口，视野边缘跳出红色数字：-4，生命条掉了一截。"
        "他退回村口，再看面板：生命：38/100，法力：0/60。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=2,
        body=body,
        event_plan={"location_beats": ["灰狼坡补齐毒腺。"]},
        world_facts=["本章允许战斗后生命从42/100降到38/100。"],
    )

    assert review["pass"] is True, review


def test_web_game_review_rejects_mage_staff_melee_without_spell_reason():
    body = (
        "《天启之门》开服后，夜烬确认初始身份是见习冒险者（未转职），背着新手法杖进入灰鼠坡。"
        "灰鼠扑上来时，他全程没有施法，只用杖尖砸肋骨、杖尾压鼻梁、杖头磕咽喉。"
        "药剂师洛婶在药剂铺按七铜币回收毒腺，提醒他材料价格只看品质，不问来路。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"npc_beats": ["药剂师洛婶报价。"]},
        world_facts=["战斗需要体现基础火球术、法力消耗或解释技能未解锁。"],
    )

    assert review["pass"] is False
    assert any("法杖战斗方式" in issue for issue in review["issues"])


def test_web_game_review_rejects_named_npc_without_setting_boundary():
    body = (
        "《天启之门》开服后，夜烬进入灰烬村。"
        "药剂师洛婶说任务奖励150铜币，夜烬接了任务就离开。"
        "交易行商人只记录价格、数量批次和时间戳，不知道他的现实身份。"
    ) * 35

    review = review_web_game_chapter(
        chapter_number=2,
        body=body,
        event_plan={"npc_beats": ["药剂师洛婶通过任务门槛影响选择。"]},
        world_facts=["NPC设定：命名NPC需要地点、服务、利益诉求和信息边界。"],
    )

    assert review["pass"] is False
    assert any("命名NPC出场缺少完整设定" in issue for issue in review["issues"])


def test_web_game_review_rejects_first_chapter_npc_budget_overload():
    body = (
        "《天启之门》开服当晚，夜烬进入灰烬村。"
        "药剂师洛婶在药剂铺发布解毒剂支线任务，讲清毒腺回收价格和库存压力。"
        "职业导师艾伦又在职业大厅登记元素回廊试炼，说明法师技能学习和转职门槛。"
        "仓库管理员铁栓随后开放仓库格扩展和寄售流水查询，提醒匿名寄售记录会进入系统风控。"
        "交易行商人只记录价格、数量批次和时间戳，并不知道他的现实身份。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"npc_beats": ["第一章最多一个命名NPC服务节点完整出场。"]},
        world_facts=["背景预算：第一章最多一个命名NPC完整出场，其他NPC只能一笔带过。"],
    )

    assert review["pass"] is False
    assert any("背景预算" in issue for issue in review["issues"])


def test_web_game_review_allows_one_npc_scene_with_other_nodes_as_signposts():
    body = (
        "《天启之门》开服当晚，夜烬进入灰烬村。"
        "药剂师洛婶在药剂铺柜台后抬头，说破损毒腺只能按七铜币回收，"
        "还提醒他解毒剂任务材料缺口大，想卖货就别一次砸盘。"
        "夜烬记下价格，没有继续追问。职业大厅布告栏、仓库排队窗口和修理铺叮当声"
        "只从视线边缘匆匆掠过，没有其他NPC上前办理服务。"
        "交易行商人只记录价格、数量批次和时间戳，不知道他的现实身份。"
    ) * 20

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"npc_beats": ["第一章只完整展开药剂师洛婶。"]},
        world_facts=["背景预算：第一章最多一个命名NPC完整出场，其他NPC只能一笔带过。"],
    )

    assert review["pass"] is True, review


def test_web_game_review_does_not_count_task_panel_npc_as_full_service_scene():
    body = (
        "《天启之门》开服当晚，夜烬进入灰烬村。"
        "任务面板系统自动推送：职业导师艾伦发布前置任务，目标是收集灰狼毒腺。"
        "药剂师洛婶在药剂铺柜台后抬头，说破损毒腺只能按七铜币回收，"
        "还提醒他解毒剂任务材料缺口大，想卖货就别一次砸盘。"
        "交易行商人只记录价格、数量批次和时间戳，不知道他的现实身份。"
    ) * 20

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"npc_beats": ["第一章只完整展开药剂师洛婶。"]},
        world_facts=["背景预算：第一章最多一个命名NPC完整出场，其他NPC只能一笔带过。"],
    )

    assert review["pass"] is True, review


def test_web_game_review_does_not_count_light_npc_mentions_as_full_service_scene():
    body = (
        "《天启之门》开服当晚，夜烬进入灰烬村。"
        "药剂师洛婶在柜台后隐约可见，职业导师艾伦的名字只出现在任务奖励列表里。"
        "他没有上前插队，只扫过药剂铺、职业大厅、仓库窗口和修理铺的队伍。"
        "交易行商人只记录价格、数量批次和时间戳，不知道他的现实身份。"
    ) * 25

    review = review_web_game_chapter(
        chapter_number=2,
        body=body,
        event_plan={"npc_beats": ["第二章需要一个命名NPC服务节点。"]},
        world_facts=["NPC硬规则：命名NPC必须以服务、任务或价格影响选择。"],
    )

    assert review["pass"] is False
    assert any("命名NPC" in issue for issue in review["issues"])


def test_quality_report_fails_when_writing_review_fails():
    quality = {"ok": True, "issues": [], "metrics": {"body_chars": 5200}}
    writing_review = {
        "pass": False,
        "issues": ["第一章节奏过载。"],
        "scores": {"genre_rules": 5, "web_game_market_logic": 5},
        "revision_plan": ["拆分节奏。"],
    }

    merged = _merge_writing_review_quality(quality, writing_review)

    assert merged["ok"] is False
    assert "writing_review" in merged["issues"]
    assert merged["writing_review"] == writing_review


def test_opening_writer_rules_keep_first_chapter_narrow():
    rules = "\n".join(_opening_writer_rules(1))

    assert "NPC、柜台、价牌和队伍只作为环境入口" in rules
    assert "赵胖子" in rules
    assert "白袍据点" in rules
