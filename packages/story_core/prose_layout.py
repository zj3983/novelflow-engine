"""Shared prose layout guidance for every novel genre."""

from __future__ import annotations

import re
from statistics import median


UNIVERSAL_MOBILE_LAYOUT_RULES = (
    "普通叙述段通常写一至两句完整的话；紧接着的动作和结果、观察和反应可以放在同一段，不要机械地每写一句就换段；场景、对象或话题变化时再换段。",
    "对话独立成段，换说话人就换段；同一人的完整发言不机械拆碎。",
    "单句短段只用于真正的转折、揭晓、打断或冲击；换行不能代替完整语法和自然语气。",
)

UNIVERSAL_MOBILE_LAYOUT_EXAMPLE = (
    "他把门推开，屋里的人同时看了过来。桌边的人放下茶杯，问他怎么现在才到。\n\n"
    "“路上出了点事，我先把东西交给你。”\n\n"
    "门后忽然传来第二个人的脚步声，正朝这边走来。桌边那人没有回头，脸色却变了。\n\n"
    "不对。"
)


def universal_mobile_layout_prompt_lines() -> list[str]:
    return [
        *UNIVERSAL_MOBILE_LAYOUT_RULES,
        "排版示例（只说明段落关系，不得照搬人物、场景或台词）：",
        UNIVERSAL_MOBILE_LAYOUT_EXAMPLE,
    ]


def mechanical_sentence_per_paragraph_layout(text: str) -> bool:
    """Detect chapter-wide mechanical one-sentence paragraph splitting."""

    paragraphs = [
        item.strip()
        for item in re.split(r"\n\s*\n", str(text or "").replace("\r", "\n"))
        if item.strip()
    ]
    narrative = [
        item
        for item in paragraphs
        if not item.lstrip().startswith(("“", '"', "‘", "「", "『", "【", "**【"))
    ]
    if len(narrative) < 20:
        return False

    sentence_counts = [
        len([part for part in re.split(r"[。！？!?]", item) if part.strip()])
        for item in narrative
    ]
    compact_lengths = [len(re.sub(r"\s+", "", item)) for item in narrative]
    single_sentence_ratio = sum(count == 1 for count in sentence_counts) / len(narrative)
    return single_sentence_ratio >= 0.9 and median(compact_lengths) <= 45
