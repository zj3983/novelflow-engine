from __future__ import annotations

from typing import Any


BOOK_STYLE_OPTIONS = ("幽默", "轻松", "热血", "冷峻", "细腻")

_BOOK_STYLE_PROMPTS = {
    "幽默": "幽默：让笑点来自人物反应、处境反差和顺口接话，不刻意抖包袱。",
    "轻松": "轻松：语气放松，冲突不拖沓，人物交流保留日常感。",
    "热血": "热血：行动和对抗要有冲劲，关键结果写得有力，但不喊口号。",
    "冷峻": "冷峻：叙述克制直接，少渲染，让压力从行动和后果中显出来。",
    "细腻": "细腻：留意人物关系和细小反应，情绪变化要具体而不过度解释。",
}


def normalize_book_style(value: Any) -> str:
    style = str(value or "").strip()
    return style if style in BOOK_STYLE_OPTIONS else ""


def book_style_prompt(value: Any) -> str:
    return _BOOK_STYLE_PROMPTS.get(normalize_book_style(value), "")
