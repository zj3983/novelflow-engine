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
_COST_ACTION_TERMS = ("付出", "花", "耗", "掉", "剩", "红字", "快裂", "见底", "补")

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
        has_resource = any(term in body for term in _COST_RESOURCE_TERMS)
        has_action = any(term in body for term in _COST_ACTION_TERMS)
        if has_resource and has_action:
            return True, max(ratio, threshold)
    return False, ratio


def review_plot_spine_completion(
    body: str,
    simulation_plan: dict[str, Any] | None,
    *,
    covered_threshold: float = 0.32,
) -> dict[str, Any]:
    if not isinstance(simulation_plan, dict):
        return {"pass": True, "issues": [], "revision_plan": [], "scores": {}}
    plot = simulation_plan.get("plot_simulation")
    if not isinstance(plot, dict) or not plot:
        return {"pass": True, "issues": [], "revision_plan": [], "scores": {}}

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
        return {"pass": True, "issues": [], "revision_plan": [], "scores": {}}

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

    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": scores,
        "diagnostics": {
            "covered_labels": covered,
            "missing_labels": missing,
            "coverage": ratios,
        },
    }
