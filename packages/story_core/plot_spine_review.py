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
_LATIN_SYMBOL_RUN = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*")
_LATIN_CONTRACTED_NEGATION = re.compile(r"\b\w+n['’]t\b", re.IGNORECASE)
_TROPE_NEGATION_TERMS = ("没有", "没能", "未能", "尚未", "并未", "不曾", "拒绝", "不肯", "不愿", "没接", "未接")
_TROPE_NEGATION_LATIN_TERMS = ("not", "never", "refuse", "refused")
_TROPE_QUESTION_TERMS = ("吗", "呢", "？", "?")
_TROPE_PLAN_ONLY_TERMS = ("打算", "计划", "准备", "想要", "以后", "明天再", "下一章", "心里盘算", "只是在心里")
_TROPE_PLAN_ONLY_LATIN_TERMS = ("plan", "plans", "planned", "intend", "intends")
_TROPE_ACTION_CONFIRM_TERMS = ("当场", "立刻", "马上", "直接", "终于", "已经", "真的", "随后", "于是")
_TROPE_OTHER_ACTOR_TERMS = ("别人", "旁人", "有人", "其他人", "另一边")


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


def _trope_terms(text: str) -> set[str]:
    terms = set(_terms(text))
    for match in _LATIN_SYMBOL_RUN.findall(str(text or "")):
        token = match.lower()
        terms.add(token)
        for piece in re.split(r"[-_]", token):
            if piece:
                terms.add(piece)
    return {term for term in terms if term}


def _latin_symbol_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in _LATIN_SYMBOL_RUN.findall(str(text or "")):
        token = match.lower()
        tokens.add(token)
        tokens.update(piece for piece in re.split(r"[-_]", token) if piece)
    return tokens


def _trope_term_coverage(text: str, terms: set[str]) -> float:
    if not terms:
        return 0.0
    lowered = str(text or "").lower()
    hits = sum(1 for term in terms if term in lowered)
    return hits / len(terms)


def _normalized_trope_phrase(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def _trope_action_anchors(text: str) -> list[str]:
    anchors: list[str] = []
    for run in _CJK_RUN.findall(str(text or "")):
        if len(run) >= 4:
            anchors.append(run)
            anchors.extend(run[index : index + 4] for index in range(len(run) - 3))
    latin_phrase = _normalized_trope_phrase(text)
    if latin_phrase and _LATIN_SYMBOL_RUN.search(latin_phrase):
        anchors.append(latin_phrase)
    return list(dict.fromkeys(anchors))


def _trope_sentence_is_invalid(sentence: str) -> bool:
    latin_tokens = _latin_symbol_tokens(sentence)
    if any(term in sentence for term in _TROPE_QUESTION_TERMS):
        return True
    if _LATIN_CONTRACTED_NEGATION.search(sentence):
        return True
    if any(term in sentence for term in _TROPE_NEGATION_TERMS) or any(
        term in latin_tokens for term in _TROPE_NEGATION_LATIN_TERMS
    ):
        return True
    if any(term in sentence for term in _TROPE_OTHER_ACTOR_TERMS):
        return True
    has_plan_marker = any(term in sentence for term in _TROPE_PLAN_ONLY_TERMS) or any(
        term in latin_tokens for term in _TROPE_PLAN_ONLY_LATIN_TERMS
    )
    if has_plan_marker and not any(
        term in sentence for term in _TROPE_ACTION_CONFIRM_TERMS
    ):
        return True
    return False


def _trope_sentence_has_anchor(sentence: str, anchors: list[str]) -> bool:
    lowered = _normalized_trope_phrase(sentence)
    return any((anchor in sentence) or (anchor in lowered) for anchor in anchors)


def _trope_beat_coverage(body: str, beat: str) -> tuple[bool, float]:
    terms = _trope_terms(beat)
    if not terms:
        return False, 0.0

    anchors = _trope_action_anchors(beat)
    best_ratio = 0.0
    sentences = [part.strip() for part in re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", str(body or "")) if part.strip()]
    for sentence in sentences:
        sentence_ratio = _trope_term_coverage(sentence, terms)
        best_ratio = max(best_ratio, sentence_ratio)
        if sentence_ratio < 0.25:
            continue
        if _trope_sentence_is_invalid(sentence):
            continue
        if not _trope_sentence_has_anchor(sentence, anchors):
            continue
        return True, sentence_ratio

    return False, best_ratio


def _compact_trope_avoid(value: Any) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        items = []
    return [str(item).strip()[:180] for item in items[:8] if str(item).strip()]


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
    trope_contract = simulation_plan.get("trope_contract")
    trope_contract = trope_contract if isinstance(trope_contract, dict) else {}
    trope_avoid = _compact_trope_avoid(trope_contract.get("avoid"))
    if (not isinstance(plot, dict) or not plot) and not contract and not trope_contract:
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

    trope_beat = str(trope_contract.get("current_beat") or "").strip()
    trope_payoff = str(trope_contract.get("payoff") or "").strip()
    trope_beat_coverage = 0.0
    trope_beat_covered: bool | str = "not_scheduled"
    if trope_beat:
        trope_beat_covered, trope_beat_coverage = _trope_beat_coverage(body, trope_beat)
        if not trope_beat_covered:
            scores["trope_beat_missing"] = 5
            issues.append(f"套路节点未兑现：本章未写出当前节点「{trope_beat}」的正文动作或反馈。")
            payoff_clause = f"，并落到回报「{trope_payoff}」" if trope_payoff else ""
            revision_plan.append(f"按套路节点改：本章必须兑现「{trope_beat}」{payoff_clause}；不要只提到节点名，要写成行动、反馈或关系变化。")

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
            "trope_avoid": trope_avoid,
            "trope_beat_covered": trope_beat_covered,
            "trope_beat_coverage": round(trope_beat_coverage, 2),
        },
    }
