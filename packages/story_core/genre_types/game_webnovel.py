from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from packages.story_core.genre_types.base import GenrePlugin
from packages.story_core.power_system_templates import copy_power_system_template
from packages.story_core.game_level_gap import level_gap_rule_text
from packages.story_core.web_game_economy import (
    appraisal_rules,
    exchange_rules,
    first_chapter_market_exchange_authorized,
    market_rules,
)


@dataclass(frozen=True)
class GameLanguageCard:
    card_id: str
    trigger_terms: tuple[str, ...]
    preferred: tuple[str, ...]
    avoid: tuple[str, ...]
    example: str


GAME_WEBNOVEL_LANGUAGE_CARDS = (
    GameLanguageCard(
        card_id="base",
        trigger_terms=(),
        preferred=("玩家能看见的界面词", "玩家会顺口说的游戏词", "动作后的直接结果"),
        avoid=("服务器实现", "数据字段", "后台流程", "运营报告", "区域分片", "登记资格"),
        example="写“任务进度变成1/16”，不写“系统完成数据同步”。",
    ),
    GameLanguageCard(
        card_id="login_server",
        trigger_terms=("登录", "建号", "创建角色", "服务器", "区服", "开服", "新手村", "分线", "位面"),
        preferred=("服务器", "区服", "分线", "位面", "换线", "排队登录"),
        avoid=("负载分片", "承载节点", "区域分片", "跨区数据同步"),
        example="写“新手村又开了几条分线”，不解释服务器怎样分配玩家。",
    ),
    GameLanguageCard(
        card_id="quest",
        trigger_terms=("任务", "委托", "接取", "接任务", "交任务", "任务进度", "任务物品", "解锁", "前置"),
        preferred=("接任务", "交任务", "任务进度", "任务物品", "完成", "解锁后续任务"),
        avoid=("登记资格", "服务节点", "任务门槛", "流程校验"),
        example="写“交掉前置任务以后，新的区域任务才会解锁”。",
    ),
    GameLanguageCard(
        card_id="combat",
        trigger_terms=("战斗", "击杀", "灰狼", "怪物", "拉怪", "仇恨", "抢怪", "火球", "伤害", "生命", "法力"),
        preferred=("刷新", "拉怪", "仇恨", "抢怪", "归属", "残血", "回蓝", "卡位", "脱战"),
        avoid=("战斗模型", "控制变量", "仇恨算法", "行为树"),
        example="写“石傀儡转头扑向他”，需要时再让熟练玩家说“仇恨转了”。",
    ),
    GameLanguageCard(
        card_id="loot_inventory",
        trigger_terms=("掉落", "战利品", "拾取", "背包", "任务物品", "绑定", "可交易", "材料", "狼心", "毒腺", "狼皮", "狼牙"),
        preferred=("出了", "掉了", "拾取", "战利品", "叠加", "绑定", "可交易", "放进背包"),
        avoid=("配方验证", "样本判定", "数据用途", "掉落数据集"),
        example="写“任务材料叠进原来的格子，进度跳到1/16”。",
    ),
    GameLanguageCard(
        card_id="trade",
        trigger_terms=("交易", "交易行", "拍卖行", "上架", "挂单", "出售", "卖出", "立即出售", "求购", "一口价", "成交", "手续费", "游戏币到账", "寄售"),
        preferred=("交易行", "求购单", "挂单", "立即出售", "一口价", "成交", "手续费", "游戏币到账"),
        avoid=("平台封存", "字段权限", "交易流转"),
        example="写“卖家按一口价挂单，等待买家购买；若接受现有求购单价格，则点立即出售并直接成交，游戏币到账”。",
    ),
    GameLanguageCard(
        card_id="currency_exchange",
        trigger_terms=("官方兑换", "官方兑换渠道", "兑换渠道", "兑换价", "兑换额度", "现实货币", "现实账户", "预计到账"),
        preferred=("兑换价", "额度", "手续费", "预计到账", "现实账户"),
        avoid=("交易行兑现实货币", "游戏物品直达现实账户", "市场与兑换混写"),
        example="写“确认额度和手续费后，界面显示现实账户预计到账金额”。",
    ),
    GameLanguageCard(
        card_id="group_dungeon",
        trigger_terms=("组队", "队伍", "小队", "副本", "地下城", "首领", "团本", "坦克", "治疗", "灭团"),
        preferred=("组队", "进本", "坦克", "治疗", "输出", "开怪", "灭团", "拾取分配"),
        avoid=("协作单元", "战斗岗位矩阵", "实例化空间", "团队资源调度"),
        example="写“坦克先开怪，治疗等他站稳再抬血”。",
    ),
    GameLanguageCard(
        card_id="equipment_progression",
        trigger_terms=("装备", "武器", "法杖", "耐久", "修理", "属性", "技能", "专精", "天赋", "换装"),
        preferred=("装备等级", "品质", "耐久", "修理", "需求等级", "绑定", "换装", "技能冷却"),
        avoid=("属性矩阵", "装备参数模型", "成长数据管线", "技能配置项"),
        example="写“法杖只剩两点耐久，回村后得先修一下”，不用解释耐久系统怎样结算。",
    ),
    GameLanguageCard(
        card_id="guild_social",
        trigger_terms=("公会", "会长", "团长", "招募", "开荒", "公会频道", "团队进度", "固定团"),
        preferred=("公会频道", "招募", "开荒", "团长", "固定团", "团队进度", "活动时间"),
        avoid=("组织节点", "成员资源调度", "协作网络", "社交关系数据"),
        example="写“公会频道正在招人开荒”，不写“组织开始调度成员资源”。",
    ),
)


_IGNORED_LANGUAGE_PLAN_KEYS = (
    "avoid",
    "forbidden",
    "must_not",
    "prohibit",
    "ban",
)

_LANGUAGE_CARD_PRIORITY_MARKERS = {
    "login_server": ("entry_login", "登录建号", "创建角色"),
    "combat": ("small_verification", "低级怪小验证", "怪物面板"),
    "loot_inventory": ("异常掉落", "掉落异常", "战利品"),
    "trade": ("交易行出售", "挂单成交", "游戏币到账"),
    "currency_exchange": ("官方兑换", "兑换渠道", "兑换价", "现实账户"),
    "group_dungeon": ("副本开荒", "进入副本", "团队副本"),
    "guild_social": ("公会招募", "固定团招募", "公会频道"),
}


def _language_plan_text(value: Any) -> str:
    if isinstance(value, dict):
        return "\n".join(
            _language_plan_text(item)
            for key, item in value.items()
            if not any(marker in str(key).lower() for marker in _IGNORED_LANGUAGE_PLAN_KEYS)
        )
    if isinstance(value, (list, tuple, set)):
        return "\n".join(_language_plan_text(item) for item in value)
    return str(value or "")


def select_game_language_cards(
    plan: dict[str, Any] | str | None,
    *,
    max_cards: int = 3,
) -> list[GameLanguageCard]:
    """Select a compact set of player-facing language cards for one chapter."""

    limit = min(3, max(1, int(max_cards)))
    text = _language_plan_text(plan)
    selected = [GAME_WEBNOVEL_LANGUAGE_CARDS[0]]
    scored: list[tuple[int, int, GameLanguageCard]] = []
    for index, card in enumerate(GAME_WEBNOVEL_LANGUAGE_CARDS[1:], start=1):
        score = sum(text.count(term) for term in card.trigger_terms)
        if any(marker in text for marker in _LANGUAGE_CARD_PRIORITY_MARKERS.get(card.card_id, ())):
            score += 1000
        if score:
            scored.append((score, index, card))

    scored_card_ids = {card.card_id for _, _, card in scored}
    market_exchange_pair = {"trade", "currency_exchange"}
    legacy_opening_authorized = first_chapter_market_exchange_authorized(
        plan if isinstance(plan, dict) else {"turn": text},
        [],
    )
    if market_exchange_pair.issubset(scored_card_ids) or legacy_opening_authorized:
        cards_by_id = {card.card_id: card for card in GAME_WEBNOVEL_LANGUAGE_CARDS}
        selected.extend((cards_by_id["trade"], cards_by_id["currency_exchange"]))
        return selected[:limit]

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected.extend(card for _, _, card in scored[: max(0, limit - 1)])
    return selected


GAME_WEBNOVEL = GenrePlugin(
    plugin_id="game_webnovel",
    name="网游升级流",
    keywords=("网游", "游戏", "系统", "等级", "副本", "爆率", "职业", "玩家", "公会", "交易行", "VRMMO"),
    core_promises=(
        "读者期待看到稳定的等级、经验、掉落、装备、任务和地图推进循环。",
        "隐藏优势的主爽点是让主角更快完成任务、凑齐装备/技能前置条件，并持续领先普通玩家半步到一步。",
        "大型服务器里低级材料和小额铜币是普通噪音，旁人最多觉得主角运气好；真正关注必须等到稀有物、榜单、连续高频记录或多源证据叠加后才出现。",
    ),
    ledger_fields=("等级", "经验", "金币", "装备", "技能", "任务", "领先进度", "金手指暴露度", "外部关注度"),
    rulebook={
        "progression_rules": (
            "等级、经验、装备、技能和称号必须前后一致，任何升级都要有可见成本或明确收益来源。",
            level_gap_rule_text(),
            "主角可以有隐藏优势，但优势不能自动解决所有问题，必须受到资源、情报、时间或身份暴露风险限制。",
            "第一章需要按本书章纲写清登录或角色创建阶段的游戏身份、当前状态和第一项行动；不得从题材模板擅自指定职业、武器或技能。",
            "游戏身份和现实身份分别记录；职业、技能与成长路线只能来自本书世界观、角色卡和连续性账本。",
            "每章至少形成一次小收益闭环：目标、行动、收益反馈、新压力。",
        ),
        "economy_rules": (
            *market_rules(),
            *appraisal_rules(),
            *exchange_rules(),
            "网游币制默认使用 1金币=100银币=10000铜币；新手村低级材料优先用铜币或银币计价，金币是大额单位。",
            "金币、材料、装备价格要体现供需关系，交易行、当面交易和公会垄断都会影响价格。",
            "开服初期兑换价尚未稳定，除非世界档案明确给出官方兑换规则，否则不得写死游戏币与现实货币的兑换比例。",
            "稀有掉落不能随意变现，必须考虑买家来源、匿名出售、压价、追踪和信誉风险。",
            "主角短期变强可以靠信息差，但不能无代价暴富到破坏世界经济。",
            "低级材料不是主冲突：它们只作为任务、装备、技能或路线前置条件的证据，不承担引发市场风暴或第一章服务闭环的戏剧职责。",
        ),
        "quest_rules": (
            "任务、隐藏任务、副本和职业试炼都应有触发条件、失败代价、阶段目标和可验证奖励。",
            "前几章要自然铺垫核心职业试炼或体系入口，不要突然跳到高阶内容。",
            "职业导师或职业大厅应承担职业选择、技能学习、试炼前置任务和路线限制，不要让系统旁白替代职业体系运行。",
        ),
        "faction_rules": (
            "公会、商会、NPC势力和普通玩家都有利益诉求，不能只作为背景板。",
            "强势组织会通过拉拢、清场、监视、压价或封锁资源点来制造外部压力。",
            "所有追踪都要遵守信息可见性：交易记录、论坛传闻、资源点目击和NPC反馈只能逐步拼图，不能一步知道真相。",
        ),
        "panel_rules": (
            "系统面板只展示必要信息，使用短提示推进爽点，不要刷屏或替代叙事。",
            "隐藏天赋、爆率倍率、任务奖励等关键信息要分层披露，不能让全世界立刻知道。",
            "角色面板至少能稳定承载：游戏ID、等级、职业/路线、经验、主武器、基础技能、钱袋/背包和关键任务；第一章必须出现一次职业栏。",
        ),
        "chapter_formula": (
            "开场用压力或收益钩子抓人，中段用行动选择推动规则运转，结尾留下更大的资源或身份压力。",
            "每章都要同时推进主角成长、世界规则展示和领先感：普通玩家还在跑重复流程时，主角已经拿到下一项任务、装备、技能或地图入口。",
            "网游第一章只聚焦一个核心事件：现实压力、登录/建号、选择游戏ID、选择职业、角色面板、首次领先验证、章末下一步目标。",
            "第一章是否完成实际交易必须服从项目大纲；公会追踪、商人盯盘和论坛扩散移到有足够公开证据后逐步展开。",
            "第一章是否交低级任务、领取铜币、修理或买药，必须跟随项目账本/章节计划；未允许时只写价牌、队伍、前置条件和下一步目标，不能擅自结算。",
        ),
        "forbidden_breaks": (
            "禁止无解释跳级、无成本获得神装、NPC无理由送资源、反派突然降智。",
            "禁止把设定写成百科说明，规则必须通过场景、交易、战斗、对话或系统反馈体现。",
        ),
    },
    quality_checks=("等级经验一致", "收益代价闭环", "市场反应", "势力压迫", "信息可见性", "系统提示克制"),
    power_system_template=copy_power_system_template("game_webnovel"),
    trope_templates=(
        {
            "id": "login_character_creation",
            "name": "登录建号",
            "trigger": "故事开局或新账号阶段，需要把现实动机和游戏身份连接起来。",
            "beats": ["现实压力", "登录入口", "游戏ID", "初始身份/职业栏", "基础武器或技能选择"],
            "payoff": "读者明确主角为什么进入游戏，以及第一套可追踪面板信息。",
            "avoid": ["不要把现实债务立刻解决", "不要开局独有职业", "不要刷屏式面板"],
        },
        {
            "id": "first_advantage_verification",
            "name": "首次验证隐藏优势",
            "trigger": "主角拥有爆率、经验、路线记忆或职业信息差，需要第一次证明领先。",
            "beats": ["选择低风险目标", "普通玩家参照", "优势产生小收益", "背包/任务进度变化", "确认领先但不惊动全服"],
            "payoff": "隐藏优势变成可见爽点，同时保持信息可见性边界。",
            "avoid": ["不要第一章引发公会全知追踪", "不要直接掉神装", "不要忽略消耗和时间成本"],
        },
        {
            "id": "hidden_quest_trigger",
            "name": "隐藏任务触发",
            "trigger": "主角需要进入职业试炼、稀有地图或特殊路线。",
            "beats": ["普通任务前置", "异常NPC反馈", "主角做出非标准选择", "触发隐藏条件", "给出阶段目标和失败代价"],
            "payoff": "信息差带来路线优势，并自然引出下一章任务。",
            "avoid": ["不要让NPC无理由偏爱主角", "不要一次讲完整奖励", "不要绕过前置成本"],
        },
        {
            "id": "trade_house_probe",
            "name": "交易行试水",
            "trigger": "主角获得可变现材料、装备或情报，需要把收益转化为资源并引出外部关注。",
            "beats": ["估价/手续费", "匿名或分批上架", "成交或压价", "商人玩家注意到模式", "主角调整暴露度"],
            "payoff": "经济系统开始运转，收益和风险同时增加。",
            "avoid": ["不要写死现实汇率", "不要让买家知道现实身份", "不要低级材料引发全服风暴"],
        },
        {
            "id": "guild_pressure",
            "name": "公会压力升级",
            "trigger": "主角连续领先或占用资源点后，需要出现组织化阻力。",
            "beats": ["传闻/榜单/目击证据", "外围试探", "拉拢或压价", "资源点封锁", "主角用路线或时间差脱身"],
            "payoff": "领先感转化为外部压力，推动地图和势力升级。",
            "avoid": ["不要公会全知", "不要一步锁定坐标", "不要让普通玩家全体降智"],
        },
    ),
)


GAME_WEBNOVEL_SIMULATION_BLUEPRINT = {
    "plugin_id": "game_webnovel",
    "opening_scene_templates": [
        {
            "id": "reality_entry",
            "location": "现实出租屋",
            "purpose": "交代现实职业、压力、登录动机和主角的谨慎计算。",
            "conflict": "现实压力迫使主角进入游戏试机会，但不能立刻解决现实债务。",
            "must_show": ["现实职业/技能来源", "为什么登录游戏"],
        },
        {
            "id": "character_creation",
            "location": "角色创建界面",
            "purpose": "按本书设定建立游戏ID、初始身份、当前状态和第一项目标。",
            "conflict": "初始选择会影响第一章的行动方式和成本。",
            "must_show": ["游戏ID", "本书设定的初始身份", "当前状态", "第一项目标"],
        },
        {
            "id": "small_verification",
            "location": "初始活动区域",
            "purpose": "用一项低风险行动展示本书核心优势如何影响正常游戏流程，并让主角获得第一项具体进展。",
            "conflict": "收益让主角确认优势，但规模不足以惊动全服，旁人最多觉得他运气好或路线熟。",
            "must_show": ["低级怪物", "掉落反馈", "背包变化", "进度领先反馈"],
        },
        {
            "id": "single_npc_service",
            "location": "初始据点",
            "purpose": "只轻量露出一个NPC服务入口或任务窗口。",
            "conflict": "NPC只提供岗位范围内的服务、报价、任务或前置条件，不替主角解释全局规则。",
            "must_show": ["NPC地点或窗口", "服务内容", "价格/前置条件"],
        },
        {
            "id": "chapter_1_next_step",
            "location": "初始据点或任务区域",
            "purpose": "只作为章末下一步目标，不展开实际寄售、成交、到账或商人盘点。",
            "conflict": "下一步目标已经出现：主角知道这些掉落能让他更快交任务、换装备或摸到下一条路线，但第一章只收在谨慎决定上。",
            "must_show": ["下一步目标", "领先下一步"],
        },
    ],
    "conflict_ladders": {
        "chapter_1": ["现实压力", "初始身份", "领先验证", "下一步任务/装备前置", "下一步目标"],
        "chapter_2": ["刷怪路线", "补给/耐久", "NPC任务前置", "装备或技能前置", "普通玩家对比"],
        "chapter_3": ["资源点秩序", "职业试炼前置", "路线竞争", "玩家传闻", "小高潮"],
    },
    "forbidden_conflict_modes": {
        "chapter_1": [
            "market_overreaction",
            "guild_omniscience",
            "real_identity_exposure",
            "coordinate_lock",
            "multi_npc_tour",
        ]
    },
    "visibility_matrix": {
        "trade_house": {
            "can_see": ["价格", "数量", "批次", "时间戳", "手续费", "匿名卖家ID"],
            "cannot_see": ["现实身份", "实时坐标", "隐藏天赋", "完整刷怪点", "真实姓名"],
        },
        "guild": {
            "can_see": ["论坛传闻", "资源点目击", "榜单变化", "重复交易模式", "NPC任务异常"],
            "cannot_see": ["隐藏天赋真相", "现实身份", "系统底层倍率", "交易行后台全量数据"],
        },
        "npc": {
            "can_see": ["岗位记录", "任务提交", "公开交易", "眼前行为"],
            "cannot_see": ["现实身份", "隐藏天赋", "玩家完整背包", "未公开意图"],
        },
    },
}
