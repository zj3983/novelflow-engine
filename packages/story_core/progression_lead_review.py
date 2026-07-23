from __future__ import annotations

from typing import Any

from packages.story_core.chapter_scope import first_chapter_trade_authorized


CORE_SIGNAL_TERMS = (
    "千倍爆率",
    "掉落判定×1000",
    "掉落判定x1000",
    "混沌之种",
)

PROGRESSION_PAYOFF_TERMS = (
    "领先",
    "快一步",
    "先一步",
    "少跑",
    "前置任务",
    "前置",
    "路线",
    "入口",
    "职业试炼",
    "元素回廊",
    "技能书",
    "地图",
    "任务进度",
    "普通玩家还在",
    "别人还在",
)

MATERIAL_LEDGER_TERMS = (
    "毒腺",
    "狼皮",
    "狼牙",
    "铜",
    "铜币",
    "材料",
    "清道夫委托",
    "奖励",
    "修理",
    "修理铺",
    "药水",
    "药剂铺",
    "背包",
)

FIRST_CHAPTER_SERVICE_CLOSURE_TERMS = (
    "交清道夫委托",
    "任务完成",
    "获得：30铜",
    "获得:30铜",
    "领取三十铜",
    "领取30铜",
    "奖励：30铜",
    "奖励三十枚铜到账",
    "扣除：30铜",
    "扣除:30铜",
    "当前货币：0铜",
    "修满",
    "修完耐久",
    "修好法杖",
    "把法杖修好",
    "买两瓶",
    "两瓶药水",
    "买了药水",
    "买下药水",
    "初级法力药水×",
)

FIRST_CHAPTER_TRADE_CLOSURE_TERMS = (
    "寄售",
    "上架",
    "成交",
    "到账铜币",
    "到账：",
    "钱袋里多了",
    "手续费",
    "提现",
    "换算人民币",
)

CONCRETE_PAYOFF_TERMS = (
    "获得",
    "奖励",
    "三十铜",
    "30铜",
    "修好",
    "修理",
    "买了",
    "入包",
    "任务完成",
    "兑换",
    "拿到",
    "耐久回到",
)

OUTSIDER_MISREAD_TERMS = (
    "只当",
    "以为",
    "没人知道",
    "没人看见",
    "只看见",
    "看不见",
    "没人多问",
    "听过就忘",
    "普通玩家",
    "运气好",
)

NEXT_ACTION_HOOK_TERMS = (
    "下一轮",
    "下一步",
    "再打",
    "入口",
    "后坡",
    "凑够",
    "试一次",
    "等蓝",
)

REPORT_STYLE_TERMS = (
    "风控",
    "收益曲线",
    "路线规划",
    "控制变量",
    "计算力",
    "成本曲线",
    "模型",
)


def _count_terms(body: str, terms: tuple[str, ...]) -> int:
    return sum(body.count(term) for term in terms)


def _count_positive_terms(body: str, terms: tuple[str, ...]) -> int:
    total = 0
    negators = ("不", "未", "没", "没有", "别")
    for term in terms:
        start = 0
        while True:
            index = body.find(term, start)
            if index < 0:
                break
            window = body[max(0, index - 4) : index]
            if not any(negator in window for negator in negators):
                total += 1
            start = index + len(term)
    return total


def _count_trade_closure_terms(body: str) -> int:
    total = 0
    informational_markers = (
        "公告",
        "公示",
        "说法",
        "规则",
        "提示",
        "价牌",
        "入口",
        "尚未开放",
        "将在",
        "只保留",
        "没有",
        "不",
    )
    for term in FIRST_CHAPTER_TRADE_CLOSURE_TERMS:
        start = 0
        while True:
            index = body.find(term, start)
            if index < 0:
                break
            window = body[max(0, index - 12) : index + len(term) + 12]
            if not any(marker in window for marker in informational_markers):
                total += 1
            start = index + len(term)
    return total


def _has_any(body: str, terms: tuple[str, ...]) -> bool:
    return any(term in body for term in terms)


def review_progression_lead(
    *,
    chapter_number: int,
    body: str,
    event_plan: dict[str, Any] | None = None,
    world_facts: list[str] | None = None,
) -> dict[str, Any]:
    """Review whether a game opening turns drops into progression lead.

    The web-game premise should not read as bookkeeping over a few low-tier
    materials. A good opening uses the first abnormal drop as proof that the
    protagonist can reach a task, equipment, skill, or route threshold before
    ordinary players.
    """

    event_plan = event_plan if isinstance(event_plan, dict) else {}
    world_facts = [str(item) for item in (world_facts or [])]
    chapter_one_trade_payoff = first_chapter_trade_authorized(event_plan, world_facts)
    context = "\n".join([body, str(event_plan), "\n".join(world_facts)])
    is_game = _has_any(context, ("网游", "游戏", "VRMMO", "天启之门", "爆率", "混沌之种", "交易行", "职业"))
    issues: list[str] = []
    revision_plan: list[str] = []
    scores = {
        "core_signal": 8,
        "progression_payoff": 8,
        "material_focus": 8,
        "opening_scope": 8,
    }

    if not is_game:
        return {
            "reviewer": "progression_lead/v1",
            "pass": True,
            "scores": scores,
            "issues": [],
            "revision_plan": [],
            "metrics": {"game_context": False},
        }

    core_signal_count = _count_terms(body, CORE_SIGNAL_TERMS)
    payoff_count = _count_terms(body, PROGRESSION_PAYOFF_TERMS)
    material_count = _count_terms(body, MATERIAL_LEDGER_TERMS)
    service_closure_count = _count_positive_terms(body, FIRST_CHAPTER_SERVICE_CLOSURE_TERMS)
    trade_closure_count = _count_trade_closure_terms(body)
    concrete_payoff_count = _count_terms(body, CONCRETE_PAYOFF_TERMS)
    outsider_misread_count = _count_terms(body, OUTSIDER_MISREAD_TERMS)
    next_action_hook_count = _count_terms(body, NEXT_ACTION_HOOK_TERMS)
    report_style_count = _count_terms(body, REPORT_STYLE_TERMS)

    if chapter_number == 1 and core_signal_count == 0:
        scores["core_signal"] = 5
        issues.append("第一章缺少千倍爆率/混沌之种的明确可读信号。")
        revision_plan.append("在首次击杀或掉落提示中保留“混沌之种”“掉落判定×1000”或“千倍爆率”，让读者知道核心爽点是什么。")

    if chapter_number == 1 and payoff_count < 2:
        scores["progression_payoff"] = 5
        issues.append("第一章没有把千倍爆率转成明确领先感，只停留在掉落异常。")
        revision_plan.append("把掉落结果改写成任务进度、装备前置条件、技能书、职业试炼或地图入口上的提前一步；章末要让读者知道下一章抢什么。")

    if chapter_number <= 3 and concrete_payoff_count < 2:
        scores["progression_payoff"] = 5
        issues.append("网游爽点没有落成可见收益：读者看不到主角具体拿到、修好、买入、兑换或推进了什么。")
        revision_plan.append("补一个明确收益动作：递材料、收铜、修法杖、买药、技能入包、任务完成或入口试通，并写出变化后的状态。")

    if chapter_number <= 3 and outsider_misread_count == 0:
        scores["opening_scope"] = 5
        issues.append("缺少外人误判：主角虽然低调，但没有写出别人只看见普通动作这一层信息差。")
        revision_plan.append("加一处旁人/NPC的表层反应：只当他运气好、路线熟、普通排队办事，不能看见背包余量和隐藏机制。")

    if chapter_number <= 3 and next_action_hook_count == 0:
        scores["progression_payoff"] = 5
        issues.append("章尾缺少下一步动作钩子：结尾没有给出下章马上能执行的目标。")
        revision_plan.append("章尾落到具体下一步：再刷一轮、凑够铜、买技能书、等蓝、试后坡入口或处理一个明确前置任务。")

    if report_style_count:
        scores["material_focus"] = 5
        issues.append("正文有策略报告味：风控、模型、收益曲线或路线规划压过了玩家动作。")
        revision_plan.append("删掉报告词，把判断改成可见动作：排队、数铜、递材料、摸耐久、退回安全线、把多余材料压进背包。")

    if chapter_number == 1 and material_count >= 14 and payoff_count < 5:
        scores["material_focus"] = 5
        issues.append("第一章材料账本过重，爽点被毒腺、狼皮、铜币、修理或药水这些小账拖走。")
        revision_plan.append("压缩材料数量和铜币账，只保留材料作为证据；把篇幅转给普通玩家对比、前置任务提前满足和下一步路线。")

    if chapter_number == 1 and service_closure_count >= 4:
        scores["opening_scope"] = 5
        issues.append("第一章服务闭环太满：任务、铜币、修理、药水一起铺开，焦点从幕后领先滑回小账本。")
        revision_plan.append("第一章服务是否办成必须跟随项目账本；未允许时删掉任务提交、修理和补给，只保留价牌、队伍、前置条件和下一步目标。")

    if chapter_number == 1 and trade_closure_count and not chapter_one_trade_payoff:
        scores["opening_scope"] = 5
        issues.append("第一章提前展开交易闭环：出现寄售、上架、成交、到账、手续费或提现。")
        revision_plan.append("删除第一章实际交易，只保留交易行/价牌作为下一章可选目标或路牌。")

    return {
        "reviewer": "progression_lead/v1",
        "pass": not issues,
        "scores": scores,
        "issues": issues,
        "revision_plan": revision_plan,
        "metrics": {
            "game_context": True,
            "core_signal_count": core_signal_count,
            "progression_payoff_count": payoff_count,
            "material_ledger_count": material_count,
            "service_closure_count": service_closure_count,
            "trade_closure_count": trade_closure_count,
            "concrete_payoff_count": concrete_payoff_count,
            "outsider_misread_count": outsider_misread_count,
            "next_action_hook_count": next_action_hook_count,
            "report_style_count": report_style_count,
        },
    }
