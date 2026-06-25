"""Review whether the chapter landed the plot-first simulation spine."""

from __future__ import annotations

import re
from typing import Any


_FIELD_LABELS = {
    "chapter_desire": "主角目标",
    "payoff": "爽点兑现",
    "cost": "代价",
    "ending_hook": "章末钩子",
}

_COST_RESOURCE_TERMS = ("蓝量", "蓝条", "法力", "耐久", "铜币", "药水", "补药", "修理")
_COST_ACTION_TERMS = ("付出", "花", "耗", "掉", "剩", "红字", "快裂", "见底", "补", "修理费", "买药", "拆成", "扣")
_PAYOFF_TERMS = (
    "升级",
    "升到",
    "经验",
    "任务完成",
    "完成委托",
    "奖励",
    "铜币",
    "到账",
    "余额",
    "修好",
    "买了",
    "入包",
    "获得",
    "拿到",
    "学会",
    "技能",
    "装备",
    "前置",
    "权限",
    "通行",
    "路线",
    "登记",
)
_FOLLOWUP_TERMS = ("下一步", "下一章", "前置", "入口", "还差", "继续", "明天", "后坡", "任务牌", "登记", "通行")

_STOP_TERMS = {
    "读者",
    "看到",
    "必须",
    "至少",
    "其中",
    "一项",
    "明确",
    "章末",
    "落到",
    "本章",
    "主角",
    "外人",
    "只能",
    "以为",
}

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")


def _terms(text: str) -> set[str]:
    terms: set[str] = set()
    for run in _CJK_RUN.findall(str(text or "")):
        if run in _STOP_TERMS:
            continue
        if 2 <= len(run) <= 6:
            terms.add(run)
        for index in range(len(run) - 1):
            window = run[index : index + 2]
            if window not in _STOP_TERMS:
                terms.add(window)
    return terms


def _coverage(body: str, text: str) -> float:
    terms = _terms(text)
    if not terms:
        return 1.0
    hits = sum(1 for term in terms if term in body)
    return hits / len(terms)


def _field_is_covered(key: str, body: str, text: str, threshold: float) -> tuple[bool, float]:
    ratio = _coverage(body, text)
    if ratio >= threshold:
        return True, ratio
    if key == "cost":
        resource_hits = [term for term in _COST_RESOURCE_TERMS if term in body]
        has_resource = bool(resource_hits)
        has_action = any(term in body for term in _COST_ACTION_TERMS)
        if has_resource and (has_action or len(resource_hits) >= 2):
            return True, max(ratio, threshold)
    return False, ratio


def _contract_payoff_landed(body: str) -> bool:
    return any(term in body for term in _PAYOFF_TERMS)


def _contract_followup_landed(body: str) -> bool:
    return any(term in body for term in _FOLLOWUP_TERMS)


def review_plot_spine_completion(
    body: str,
    simulation_plan: dict[str, Any] | None,
    *,
    covered_threshold: float = 0.32,
) -> dict[str, Any]:
    if not isinstance(simulation_plan, dict):
        return {"pass": True, "issues": [], "revision_plan": [], "scores": {}}
    plot = simulation_plan.get("plot_simulation")
    contract = simulation_plan.get("longform_plot_contract")
    contract = contract if isinstance(contract, dict) else {}
    if (not isinstance(plot, dict) or not plot) and not contract:
        return {"pass": True, "issues": [], "revision_plan": [], "scores": {}}
    plot = plot if isinstance(plot, dict) else {}

    missing: list[str] = []
    covered: list[str] = []
    ratios: dict[str, float] = {}
    for key, label in _FIELD_LABELS.items():
        text = str(plot.get(key) or "").strip()
        if not text:
            continue
        is_covered, ratio = _field_is_covered(key, body, text, covered_threshold)
        ratios[label] = round(ratio, 2)
        if is_covered:
            covered.append(label)
        else:
            missing.append(label)

    if not ratios:
        ratios = {}

    scores: dict[str, int] = {}
    issues: list[str] = []
    revision_plan: list[str] = []
    if len(missing) >= 3:
        scores["plot_spine_critical"] = 4
        issues.append(f"剧情主线落地严重不足：缺少{'、'.join(missing)}。")
        revision_plan.append(
            "按剧情推演补正文：先写主角这章想要什么，再写付出的具体代价，"
            "把爽点兑现成任务/经验/补给/装备/路线变化，章末落到下一项具体前置任务或资源缺口。"
        )
    elif missing:
        scores["plot_spine_partial"] = 6
        issues.append(f"剧情主线部分缺失：缺少{'、'.join(missing)}。")
        revision_plan.append("补齐缺失的剧情主线，不要只写账本或移动过程。")

    contract_missing: list[str] = []
    contract_partial: list[str] = []
    payoff_requirement = str(contract.get("payoff_requirement") or plot.get("payoff_requirement") or "").strip()
    future_use_rule = str(contract.get("future_use_rule") or plot.get("future_use_rule") or "").strip()
    reader_reason = str(contract.get("reader_reason_to_continue") or plot.get("reader_reason_to_continue") or "").strip()
    anti_drag_rule = str(contract.get("anti_drag_rule") or plot.get("anti_drag_rule") or "").strip()

    payoff_landed = _contract_payoff_landed(body) or "爽点兑现" in covered
    followup_landed = _contract_followup_landed(body) or "章末钩子" in covered

    if payoff_requirement and not payoff_landed:
        contract_missing.append("本章兑现")
    if (future_use_rule or reader_reason) and not followup_landed:
        contract_partial.append("后续用途/追读动作")
    if anti_drag_rule and len(body) >= 800 and not payoff_landed:
        contract_missing.append("防拖沓")

    if contract_missing:
        scores["longform_payoff_missing"] = 4
        labels = "、".join(dict.fromkeys(contract_missing))
        issues.append(f"长篇推进没有兑现：缺少{labels}。")
        revision_plan.append(
            "按长篇剧情合同改：本章必须把一项收获写成可见结果，"
            "例如等级/经验、任务完成、技能、装备、铜币、现实余额、路线权限或材料渠道变化。"
        )
    if contract_partial:
        scores["longform_followup_weak"] = 6
        labels = "、".join(dict.fromkeys(contract_partial))
        issues.append(f"长篇后续承接偏弱：缺少{labels}。")
        revision_plan.append("补一处章末可执行动作，让本章新增道具、任务、人物或线索能推动下一章。")

    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": scores,
        "diagnostics": {
            "covered_labels": covered,
            "missing_labels": missing,
            "contract_missing": list(dict.fromkeys(contract_missing)),
            "contract_partial": list(dict.fromkeys(contract_partial)),
            "coverage": ratios,
        },
    }
