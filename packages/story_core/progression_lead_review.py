from __future__ import annotations

from typing import Any


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
    "门槛",
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
    "奖励三十铜",
    "奖励30铜",
    "扣除：30铜",
    "扣除:30铜",
    "当前货币：0铜",
    "修满",
    "修完耐久",
    "买两瓶",
    "两瓶药水",
    "初级法力药水，什么价",
)

FIRST_CHAPTER_TRADE_CLOSURE_TERMS = (
    "寄售",
    "上架",
    "成交",
    "到账",
    "手续费",
    "提现",
    "换算人民币",
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
    trade_closure_count = _count_positive_terms(body, FIRST_CHAPTER_TRADE_CLOSURE_TERMS)

    if chapter_number == 1 and core_signal_count == 0:
        scores["core_signal"] = 5
        issues.append("第一章缺少千倍爆率/混沌之种的明确可读信号。")
        revision_plan.append("在首次击杀或掉落提示中保留“混沌之种”“掉落判定×1000”或“千倍爆率”，让读者知道核心爽点是什么。")

    if chapter_number == 1 and payoff_count < 2:
        scores["progression_payoff"] = 5
        issues.append("第一章没有把千倍爆率转成明确领先感，只停留在掉落异常。")
        revision_plan.append("把掉落结果改写成任务进度、装备门槛、技能书、职业试炼或地图入口上的提前一步；章末要让读者知道下一章抢什么。")

    if chapter_number == 1 and material_count >= 14 and payoff_count < 5:
        scores["material_focus"] = 5
        issues.append("第一章材料账本过重，爽点被毒腺、狼皮、铜币、修理或药水这些小账拖走。")
        revision_plan.append("压缩材料数量和铜币账，只保留材料作为证据；把篇幅转给普通玩家对比、门槛提前满足和下一步路线。")

    if chapter_number == 1 and service_closure_count:
        scores["opening_scope"] = 5
        issues.append("第一章提前办完服务闭环：出现交任务、领30铜、修满装备或买药水，焦点从领先验证滑回小账本。")
        revision_plan.append("第一章只允许看见任务/修理/补给门槛，不提交清道夫委托、不领奖励、不扣费修理、不买药水；把这些放到第二章。")

    if chapter_number == 1 and trade_closure_count:
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
        },
    }
