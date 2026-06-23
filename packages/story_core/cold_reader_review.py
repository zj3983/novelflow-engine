from __future__ import annotations

import re
from typing import Any


HOOK_TERMS = (
    "下一章",
    "下一步",
    "散人",
    "收购",
    "黑市",
    "委托",
    "交易行",
    "公会",
    "倒计时",
    "未鉴定",
    "提示",
    "前置任务",
    "隐藏",
)

CARE_TERMS = (
    "房租",
    "账单",
    "催租",
    "停职",
    "失业",
    "欠",
    "倒计时",
    "余额",
    "现实",
    "必须",
    "只剩",
    "药水",
    "耐久",
)

PAYOFF_TERMS = (
    "稀有",
    "未鉴定",
    "晶核",
    "额外",
    "千倍",
    "异常",
    "隐藏",
    "掉落",
    "协议",
)

OVERLOAD_TERMS = (
    "隐藏优势",
    "底层协议",
    "灰烬王庭",
    "星门议会",
    "灵魂链路",
    "七阶职业",
    "天启拍卖行",
    "白塔公会",
    "神格碎片",
    "深渊税则",
)

REPETITIVE_MARKERS = ("打开面板", "查面板", "刷了", "成本已经先到了")


def _score_presence(body: str, terms: tuple[str, ...], *, base: int = 2, cap: int = 5) -> int:
    hits = sum(1 for term in terms if term in body)
    return max(1, min(cap, base + hits))


def _issue(issue_type: str, reason: str, suggestion: str) -> dict[str, str]:
    return {"type": issue_type, "reason": reason, "suggestion": suggestion}


def _unknown_concept_count(body: str) -> int:
    return sum(1 for term in OVERLOAD_TERMS if term in body)


def _sentence_count(body: str) -> int:
    return len([item for item in re.split(r"[。！？\n]+", body) if item.strip()])


def review_cold_reader_experience(body: str, *, previous_summary: str = "") -> dict[str, Any]:
    """Review a chapter as a cold reader who cannot see outline or world bible."""

    body = str(body or "")
    issues: list[dict[str, str]] = []
    concept_count = _unknown_concept_count(body)

    scores = {
        "page_turn": _score_presence(body, HOOK_TERMS, base=1),
        "cognitive_load": 5 if concept_count <= 3 else 2 if concept_count <= 6 else 1,
        "empathy_connection": _score_presence(body, CARE_TERMS, base=1),
        "pace_feel": 4,
    }

    if not body.strip():
        return {
            "reviewer": "cold_reader/v1",
            "pass": False,
            "scores": {key: 0 for key in scores},
            "issues": [
                _issue("empty_body", "正文为空，冷读者没有可评估内容。", "补齐章节正文后再进行冷读者审查。")
            ],
            "revision_plan": ["补写完整章节正文。"],
            "previous_summary_used": bool(previous_summary.strip()),
        }

    if scores["page_turn"] <= 2:
        issues.append(
            _issue(
                "missing_specific_hook",
                "章末缺少具体下一步诱饵，冷读者不知道下一章要看什么。",
                "把结尾落到可执行目标：交易行、散人渠道、NPC委托、公会门槛、材料异动或现实倒计时。",
            )
        )

    if scores["empathy_connection"] <= 2:
        issues.append(
            _issue(
                "weak_why_care",
                "正文没有把主角收益和现实压力、人物目标或明确代价挂起来。",
                "补一根现实或人物动机线，让读者知道这笔收益为什么重要、失败会损失什么。",
            )
        )

    if concept_count > 3:
        issues.append(
            _issue(
                "cognitive_overload",
                f"冷读者一次看到 {concept_count} 个陌生高概念，认知负担过高。",
                "删减或后移未服务当前冲突的概念；第一章最多保留1个新概念，并先用场景呈现。",
            )
        )

    repetitive_hits = sum(1 for marker in REPETITIVE_MARKERS if marker in body)
    short_sentences = _sentence_count(body)
    if repetitive_hits >= 3 and short_sentences <= 8:
        scores["pace_feel"] = 2
        issues.append(
            _issue(
                "repetitive_loop",
                "场景推进像重复动作清单，缺少质变事件或决策升级。",
                "至少让一段验证出现质变：异常掉落、耐久骤降、怪物反扑、路线变化或NPC门槛。",
            )
        )

    if any(term in body for term in PAYOFF_TERMS):
        scores["page_turn"] = max(scores["page_turn"], 4)

    pass_review = not issues and all(score >= 3 for score in scores.values())
    return {
        "reviewer": "cold_reader/v1",
        "pass": pass_review,
        "scores": scores,
        "issues": issues,
        "revision_plan": [issue["suggestion"] for issue in issues],
        "previous_summary_used": bool(previous_summary.strip()),
    }
