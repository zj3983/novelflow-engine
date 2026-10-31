from __future__ import annotations

from typing import Any


BOOK_STYLE_OPTIONS = ("幽默", "轻松", "热血", "冷峻", "细腻")
WRITING_GUIDANCE_MAX_CHARS = 2000
WRITING_REFERENCE_MAX_CHARS = 4000
BOOK_WRITING_FIELDS = ("writing_style", "writing_guidance", "writing_reference")

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


def normalize_writing_preferences_patch(blueprint: dict[str, Any]) -> dict[str, Any]:
    """Validate only supplied voice fields; an empty string explicitly clears one."""
    result = dict(blueprint)
    for field, limit in (
        ("writing_guidance", WRITING_GUIDANCE_MAX_CHARS),
        ("writing_reference", WRITING_REFERENCE_MAX_CHARS),
    ):
        if field not in result:
            continue
        value = result[field]
        if value is None:
            value = ""
        if not isinstance(value, str) or len(value) > limit:
            raise ValueError("invalid_writing_preferences")
        result[field] = value.strip()
    return result


def book_writing_preferences(project: Any, state: Any = None) -> dict[str, str]:
    """Read the book's current expression settings, including explicit clears."""
    project = project if isinstance(project, dict) else {}
    state = state if isinstance(state, dict) else {}
    blueprint = project.get("world_blueprint")
    blueprint = blueprint if isinstance(blueprint, dict) else {}
    raw_style = blueprint.get("writing_style", project.get("writing_style", state.get("style")))
    result = {"writing_style": normalize_book_style(raw_style)}
    for field, limit in (
        ("writing_guidance", WRITING_GUIDANCE_MAX_CHARS),
        ("writing_reference", WRITING_REFERENCE_MAX_CHARS),
    ):
        value = blueprint.get(field, project.get(field, ""))
        result[field] = value.strip()[:limit] if isinstance(value, str) else ""
    return result


def render_book_writing_preferences(style: str, guidance: str, reference: str) -> str:
    preset = book_style_prompt(style)
    guidance = guidance.strip()
    reference = reference.strip()
    if not (preset or guidance or reference):
        return ""
    blocks = [
        "## 本书文风与表达要求",
        "以下要求决定怎样表达；本章发生什么仍以导演给出的场景节拍、人物状态和世界规则为准。",
    ]
    if preset:
        blocks.append(preset)
    if guidance:
        blocks.extend(["### 自定义写法", guidance])
    if reference:
        blocks.extend([
            "### 参考片段（仅参考写法）",
            "只参考语气、节奏、人物反应和接话方式，不照抄原句，不机械重复口头禅；"
            "片段不作为本章已发生的事实，也不引入其中的人物、物品或世界设定。",
            reference,
        ])
    return "\n".join(blocks)
