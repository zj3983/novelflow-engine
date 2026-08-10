from __future__ import annotations

import re
from typing import Any


FORMULA_PATTERNS: tuple[str, ...] = (
    r"不是[^。！？\n]{1,28}而是[^。！？\n]{1,36}",
    r"不是[^。！？\n]{1,28}只是[^。！？\n]{1,36}",
    r"不是为了[^。！？\n]{1,24}",
)

ABSTRACT_TERMS: tuple[str, ...] = (
    "边界",
    "验证",
    "逻辑",
    "模型",
    "数据模型",
    "数据建模",
    "模型跑不动",
    "可见性",
    "稳定性",
    "阈值",
    "概率",
    "止损线",
    "资金链",
    "变量",
    "算法",
    "常规掉落池",
    "后台数据异常",
    "闭环",
    "样本",
    "基准",
    "成立",
    "风险很清楚",
    "逻辑也很完整",
    "答案",
)

REPORT_PHRASES: tuple[str, ...] = (
    "这意味着",
    "这代表",
    "这说明",
    "从某种意义上",
    "准确来说",
    "换句话说",
    "本质上",
    "核心问题",
)

AUTHOR_VERDICT_PATTERNS: tuple[str, ...] = (
    r"[^。！？\n]{0,24}可谓[^。！？\n]{1,28}",
    r"这就是[^。！？\n]{1,36}",
    r"(?:建立的)?世界观(?:被|让)[^。！？\n]{0,20}(?:击碎|粉碎|颠覆)",
)

CONCRETE_TOKENS: tuple[str, ...] = (
    "手",
    "指",
    "眼",
    "脚",
    "背包",
    "法杖",
    "木牌",
    "柜台",
    "账本",
    "毒腺",
    "狼皮",
    "铜",
    "耐久",
    "法力",
    "生命",
    "提示",
    "任务",
    "门",
    "窗口",
    "灰狼",
    "火球",
    "跑",
    "退",
    "看",
    "问",
    "说",
    "推",
    "拖",
    "咬",
    "攥",
    "苦笑",
    "发热",
    "发沉",
)


def _sentences(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[。！？!?])\s*", text.replace("\r", "\n"))
        if part.strip()
    ]


def _formula_hits(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in FORMULA_PATTERNS:
        hits.extend(match.group(0) for match in re.finditer(pattern, text))
    return list(dict.fromkeys(hits))


def _author_verdict_hits(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in AUTHOR_VERDICT_PATTERNS:
        hits.extend(match.group(0) for match in re.finditer(pattern, text))
    return list(dict.fromkeys(hits))


def _concrete_density(text: str) -> float:
    sentences = _sentences(text)
    if not sentences:
        return 0.0
    concrete = sum(1 for sentence in sentences if any(token in sentence for token in CONCRETE_TOKENS))
    return round(concrete / len(sentences), 3)


def _cut_for_formula(hit: str) -> dict[str, str]:
    return {
        "type": "formulaic_negation",
        "target_text": hit,
        "reason": "对称总结句容易像模型在给段落下定义。",
        "suggestion": "删掉总结，改成一个动作、一个物件反馈，或一句短对白承接下一步。",
    }


def _cut_for_abstract(term: str) -> dict[str, str]:
    replacements = {
        "边界": "柜台能不能办",
        "验证": "试一把",
        "逻辑": "眼前这一步",
        "模型": "账本上的数",
        "可见性": "别人能不能看见",
        "稳定性": "下一次还算不算数",
        "阈值": "那条线",
    }
    return {
        "type": "abstract_term",
        "target_text": term,
        "reason": "抽象审稿词会把小说拉回报告腔。",
        "suggestion": f"换成更具体的写法，例如：{replacements.get(term, '动作、价格、背包格、NPC回话或面板变化')}。",
    }


def review_ai_flavor(text: str) -> dict[str, Any]:
    """Review whether prose has obvious model voice instead of webnovel texture."""

    formula_hits = _formula_hits(text)
    abstract_hits = [term for term in ABSTRACT_TERMS if term in text]
    report_hits = [term for term in REPORT_PHRASES if term in text]
    author_verdict_hits = _author_verdict_hits(text)
    concrete_density = _concrete_density(text)

    metrics = {
        "formula_count": len(formula_hits),
        "abstract_count": len(abstract_hits),
        "report_phrase_count": len(report_hits),
        "author_verdict_count": len(author_verdict_hits),
        "concrete_density": concrete_density,
    }
    issues: list[str] = []
    revision_plan: list[str] = []
    cuts: list[dict[str, str]] = []
    score = 8

    if len(formula_hits) >= 3:
        score = min(score, 5)
        issues.append(f"AI味/模型腔明显：连续使用“不是X而是Y”式总结句，样例：{'、'.join(hit[:28] for hit in formula_hits[:3])}。")
        revision_plan.append("删掉对称总结句，把判断落到动作、道具、NPC回话、面板变化或一个具体选择上；同章同类句式最多保留1处。")
    elif len(formula_hits) >= 2:
        score = min(score, 6)
        issues.append("AI味偏重：同章多次使用“不是X而是Y/不是为了X”式解释。")
        revision_plan.append("把第二处以后改成角色动作或短对白，避免像模型在给段落下定义。")
    cuts.extend(_cut_for_formula(hit) for hit in formula_hits[:6])

    if len(abstract_hits) >= 4:
        score = min(score, 5)
        issues.append(f"AI味/报告腔明显：抽象审稿词进入正文过多：{'、'.join(abstract_hits[:6])}。")
        revision_plan.append("把边界、验证、逻辑、模型、阈值、可见性、稳定性等词换成通俗动作：问一嘴、试一把、柜台不给办、包快满、法杖快断。")
    elif len(abstract_hits) >= 2 and report_hits:
        score = min(score, 6)
        issues.append(f"AI味偏重：抽象判断词和解释短语连用：{'、'.join([*abstract_hits[:3], *report_hits[:2]])}。")
        revision_plan.append("保留事实，删除解释短语；让读者从价格、队伍、任务牌、背包格和人物反应里自己看懂。")
    cuts.extend(_cut_for_abstract(term) for term in abstract_hits[:8])

    if len(report_hits) >= 3:
        score = min(score, 6)
        issues.append(f"AI味偏重：报告式连接词过多：{'、'.join(report_hits[:4])}。")
        revision_plan.append("删除“这意味着/这说明/换句话说”等连接词，直接进入下一步动作或对话。")

    if len(author_verdict_hits) >= 2:
        score = min(score, 6)
        issues.append(
            "AI味偏重：动作之后又追加作者判词："
            + "、".join(hit[:32] for hit in author_verdict_hits[:3])
            + "。"
        )
        revision_plan.append(
            "删除“可谓、这就是、世界观被击碎”等替读者下结论的句子；"
            "保留前面的动作、对话和物件变化。"
        )

    if text.strip() and concrete_density < 0.2 and len(_sentences(text)) >= 3:
        score = min(score, 6)
        issues.append("AI味偏重：具体动作、物件、对白或界面反馈太少，读起来像判断清单。")
        revision_plan.append("每一小段至少落一个可见东西：手、物件、价格、背包格、NPC台词、面板变化或身体反应。")

    return {
        "reviewer": "ai_flavor/v1",
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": {"ai_flavor": score},
        "metrics": metrics,
        "cuts": cuts,
        "hits": {
            "formula": formula_hits,
            "abstract_terms": abstract_hits,
            "report_phrases": report_hits,
            "author_verdicts": author_verdict_hits,
        },
    }
