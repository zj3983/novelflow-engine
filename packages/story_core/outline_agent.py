"""OutlineAgent — generate a full novel outline from a high-level concept.

Supports LLM-assisted mode.
"""

from __future__ import annotations

import json
import math
import urllib.error
from typing import Protocol

from packages.story_core.agent_base import BaseOpenAIProvider
from packages.story_core.models import (
    ChapterOutline,
    NovelOutline,
    StoryState,
)
from packages.story_core.runtime_config import resolve_stage_runtime


# ── act / phase definitions ──────────────────────────────────

_ARC_PHASES = [
    ("intro", "开端：引入人物与世界观"),
    ("rising", "上升：矛盾逐步加剧"),
    ("midpoint", "转折：中途大反转"),
    ("crisis", "危机：人物面临最大考验"),
    ("climax", "高潮：最终对决"),
    ("resolution", "结局：收束与余韵"),
]


def _phase_for_chapter(chapter: int, total: int) -> str:
    """Map chapter number → arc phase based on position."""
    if total <= 1:
        return "intro"
    ratio = (chapter - 1) / max(total - 1, 1)
    if ratio < 0.15:
        return "intro"
    if ratio < 0.40:
        return "rising"
    if ratio < 0.50:
        return "midpoint"
    if ratio < 0.70:
        return "crisis"
    if ratio < 0.90:
        return "climax"
    return "resolution"


def _phase_label(phase: str) -> str:
    for key, label in _ARC_PHASES:
        if key == phase:
            return label
    return phase


# ── chapter title heuristics ─────────────────────────────────

_TITLE_TEMPLATES = {
    "intro": ["{topic}初现", "{topic}暗涌", "{topic}迷局", "{topic}启幕"],
    "rising": ["{topic}交锋", "{topic}裂痕", "{topic}逼近", "{topic}暗战"],
    "midpoint": ["{topic}反转", "{topic}惊变", "{topic}破局", "{topic}迷雾"],
    "crisis": ["{topic}深渊", "{topic}抉择", "{topic}崩塌", "{topic}绝境"],
    "climax": ["{topic}对决", "{topic}决战", "{topic}终局", "{topic}风暴"],
    "resolution": ["{topic}余韵", "{topic}归途", "{topic}真相", "{topic}落幕"],
}

_TOPIC_KEYWORDS = {
    "witness": ["证人", "目击者", "见证"],
    "ledger": ["账本", "秘账", "账册"],
    "forgery": ["伪证", "伪造", "假诏"],
    "truth": ["真相", "隐秘", "谜底"],
    "secret": ["秘辛", "暗线", "隐情"],
    "archive": ["档案", "秘档", "卷宗"],
    "power": ["权力", "权势", "王权"],
    "treasure": ["法宝", "神器", "秘宝"],
    "cultivation": ["修行", "修炼", "道途"],
}


def _extract_topic(text: str) -> str:
    text_lower = text.lower()
    for keyword, synonyms in _TOPIC_KEYWORDS.items():
        if keyword in text_lower or any(s in text for s in synonyms):
            return synonyms[0]
    # Fallback: try to extract from outline
    words = text.split()
    for w in words:
        if len(w) >= 2 and w.isascii() is False:
            return w
    return "迷局"


def _rule_title(topic: str, phase: str, index: int) -> str:
    templates = _TITLE_TEMPLATES.get(phase, _TITLE_TEMPLATES["rising"])
    return templates[index % len(templates)].replace("{topic}", topic)


# ── cadence heuristics ───────────────────────────────────────

def _rule_cadence(phase: str, chapter: int, total: int) -> str:
    if phase in ("intro", "resolution"):
        return "breathing"
    if phase in ("midpoint", "climax"):
        return "urgent"
    if phase == "crisis":
        return "urgent" if chapter % 2 == 0 else "measured"
    # rising: alternate
    return "measured" if chapter % 2 == 0 else "urgent"


# ── conflict heuristics ──────────────────────────────────────

_CONFLICT_TEMPLATES = {
    "intro": [
        "{lead}初探{topic}，尚未察觉暗流。",
        "平静之下，{topic}的阴影已经开始蔓延。",
    ],
    "rising": [
        "{lead}与{rival}因{topic}产生正面碰撞。",
        "围绕{topic}的控制权，各方势力开始角力。",
    ],
    "midpoint": [
        "{topic}背后隐藏的真相令人震惊。",
        "一切看似明朗，实则另有隐情。",
    ],
    "crisis": [
        "{lead}面临前所未有的困境，{topic}成了解脱的关键。",
        "信任崩塌，{topic}成了最后的救命稻草。",
    ],
    "climax": [
        "{lead}与{rival}围绕{topic}展开最终对决。",
        "所有线索汇聚，{topic}的真相大白于天下。",
    ],
    "resolution": [
        "{topic}尘埃落定，但余波未平。",
        "风暴过后，{lead}重新审视一切。",
    ],
}


def _rule_conflict(lead: str, rival: str, topic: str, phase: str, index: int) -> str:
    templates = _CONFLICT_TEMPLATES.get(phase, _CONFLICT_TEMPLATES["rising"])
    t = templates[index % len(templates)]
    return t.replace("{lead}", lead).replace("{rival}", rival).replace("{topic}", topic)


# ── protocol & providers ─────────────────────────────────────

class OutlineGenerator(Protocol):
    def generate(
        self,
        story: StoryState,
        target_chapters: int = 30,
    ) -> NovelOutline:
        pass


class RuleBasedOutlineGenerator:
    def generate(
        self,
        story: StoryState,
        target_chapters: int = 30,
    ) -> NovelOutline:
        topic = _extract_topic(story.outline)
        lead = story.characters[0].name if story.characters else "主角"
        rival = story.characters[1].name if len(story.characters) > 1 else "对手"

        chapters: list[ChapterOutline] = []
        for i in range(1, target_chapters + 1):
            phase = _phase_for_chapter(i, target_chapters)
            chapters.append(
                ChapterOutline(
                    chapter_number=i,
                    chapter_title=_rule_title(topic, phase, i - 1),
                    summary=_rule_conflict(lead, rival, topic, phase, i - 1),
                    key_characters=[lead] if i <= 5 else [lead, rival],
                    primary_conflict=_rule_conflict(lead, rival, topic, phase, i - 1),
                    cadence=_rule_cadence(phase, i, target_chapters),
                    arc_phase=_phase_label(phase),
                )
            )

        # Act breaks
        act_size = max(math.ceil(target_chapters / 3), 1)
        act_breaks = [
            {"act": 1, "start": 1, "end": act_size, "theme": _phase_label("intro") + " → " + _phase_label("rising")},
            {"act": 2, "start": act_size + 1, "end": act_size * 2, "theme": _phase_label("midpoint") + " → " + _phase_label("crisis")},
            {"act": 3, "start": act_size * 2 + 1, "end": target_chapters, "theme": _phase_label("climax") + " → " + _phase_label("resolution")},
        ]

        return NovelOutline(
            story_id=story.story_id,
            genre=story.genre,
            style=story.style,
            total_chapters=target_chapters,
            chapters=chapters,
            overall_arc=story.outline,
            act_breaks=act_breaks,
        )


class OpenAIOutlineGenerator(BaseOpenAIProvider):
    runtime_key = "planner"

    def _runtime_settings(self):
        return resolve_stage_runtime("planner")

    def generate(
        self,
        story: StoryState,
        target_chapters: int = 30,
    ) -> NovelOutline | None:
        settings = self._runtime_settings()
        if settings.provider != "codexcli" and not settings.api_key:
            return None

        prompt = self._build_prompt(story, target_chapters)
        payload = {
            "model": settings.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a novel outline generator. "
                        "Return JSON only with a 'chapters' array and optional 'overall_arc' and 'act_breaks'. "
                        "Each chapter must have: chapter_number, chapter_title, summary, key_characters, "
                        "primary_conflict, cadence (urgent/measured/breathing), arc_phase."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": float(settings.temperature),
        }

        try:
            response = self._post_json("/chat/completions", payload, settings)
            content = response["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError, urllib.error.URLError, TimeoutError, ValueError):
            return None

        if not isinstance(parsed, dict):
            return None

        raw_chapters = parsed.get("chapters", [])
        if not isinstance(raw_chapters, list):
            return None

        chapters: list[ChapterOutline] = []
        for raw in raw_chapters:
            if not isinstance(raw, dict):
                continue
            chapters.append(
                ChapterOutline(
                    chapter_number=int(raw.get("chapter_number", len(chapters) + 1)),
                    chapter_title=str(raw.get("chapter_title", "")).strip(),
                    summary=str(raw.get("summary", "")).strip(),
                    key_characters=raw.get("key_characters", []) if isinstance(raw.get("key_characters"), list) else [],
                    primary_conflict=str(raw.get("primary_conflict", "")).strip(),
                    cadence=str(raw.get("cadence", "measured")).strip(),
                    word_count_estimate=int(raw.get("word_count_estimate", 3000)),
                    arc_phase=str(raw.get("arc_phase", "")).strip(),
                )
            )

        # Pad or trim to target_chapters if needed
        while len(chapters) < target_chapters:
            chapters.append(
                ChapterOutline(
                    chapter_number=len(chapters) + 1,
                    chapter_title=f"第{len(chapters)+1}章",
                    summary="待生成",
                    cadence="measured",
                )
            )

        return NovelOutline(
            story_id=story.story_id,
            genre=story.genre,
            style=story.style,
            total_chapters=target_chapters,
            chapters=chapters[:target_chapters],
            overall_arc=str(parsed.get("overall_arc", story.outline)).strip(),
            act_breaks=parsed.get("act_breaks", []) if isinstance(parsed.get("act_breaks"), list) else [],
        )

    def _build_prompt(self, story: StoryState, target_chapters: int) -> str:
        char_lines = []
        for c in story.characters:
            char_lines.append(
                f"- {c.name} ({c.role}): goals={c.goals}"
            )
        return "\n".join(
            [
                f"小说大纲：{story.outline}",
                f"题材：{story.genre}",
                f"风格：{story.style}",
                f"目标章节数：{target_chapters}",
                f"主要角色：",
                *char_lines,
                "",
                "请生成完整的章节大纲。要求：",
                "1. 每章有明确的冲突和转折。",
                "2. 遵循三幕结构（开端→上升→转折→危机→高潮→结局）。",
                "3. 角色要有成长和变化。",
                "4. 章节之间要有连贯性。",
                "",
                "返回 JSON 格式：",
                '{',
                '  "overall_arc": "总体故事弧线描述",',
                '  "act_breaks": [{"act": 1, "start": 1, "end": 10, "theme": "开端"}],',
                '  "chapters": [',
                '    {',
                '      "chapter_number": 1,',
                '      "chapter_title": "章节标题",',
                '      "summary": "一句话章节摘要",',
                '      "key_characters": ["角色1", "角色2"],',
                '      "primary_conflict": "本章主要冲突",',
                '      "cadence": "urgent/measured/breathing",',
                '      "word_count_estimate": 3000,',
                '      "arc_phase": "intro/rising/midpoint/crisis/climax/resolution"',
                '    }',
                '  ]',
                '}',
            ]
        )


# ── main agent ───────────────────────────────────────────────

class OutlineAgent:
    def __init__(
        self,
        llm_generator: OpenAIOutlineGenerator | None = None,
        rule_generator: RuleBasedOutlineGenerator | None = None,
    ) -> None:
        self.rule_generator = rule_generator or RuleBasedOutlineGenerator()
        self.llm_generator = llm_generator or OpenAIOutlineGenerator()

    def generate(
        self,
        story: StoryState,
        target_chapters: int = 30,
    ) -> NovelOutline:
        if story.agent_settings.mode == "LLM-assisted":
            llm_result = self.llm_generator.generate(story, target_chapters)
            if llm_result is not None:
                return llm_result
        return self.rule_generator.generate(story, target_chapters)
