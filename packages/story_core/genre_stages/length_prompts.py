from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from packages.story_core.prompt_templates import get_effective_prompt_template, render_prompt_template


@dataclass(frozen=True)
class LengthPromptContext:
    story: Any
    chapter_number: int
    source_body: str
    event_plan: dict[str, Any]
    world_facts: list[str]
    target_chars: str
    max_chapter_chars: int
    outline_anchor: dict[str, Any]
    feedback: str = ""
    compression_target_chars: str | None = None


def expansion_ending_anchor(source_body: str) -> str:
    """Return the closing paragraph an expansion must preserve verbatim."""

    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", str(source_body or ""))
        if paragraph.strip()
    ]
    if not paragraphs:
        return ""
    anchor = paragraphs[-1]
    if len(anchor) <= 120:
        return anchor
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[。！？…!?.])", anchor)
        if sentence.strip()
    ]
    return sentences[-1] if sentences else anchor[-120:]


def _expansion_focus_text(context: LengthPromptContext) -> str:
    focus = (
        "扩写已有场景中的行动、对话、阻力和结果，不新增独立的补丁段。"
        "同一事实、判断和旁人误解只写一次；新增内容必须改变行动、关系或资源。"
        "不得新增原文或章节计划之外的设定、能力、人物关系、事件结算。"
        "逐层补足行动链路和场面阻力，不是逐句增肥。"
        "新增内容默认分到3处关键场面，优先补冲突升级的行动拍；"
        "禁止扩写环境介绍、氛围铺垫和总结性旁白。"
        "不输出扩写规划，只输出扩写后的正文。"
    )
    anchor = expansion_ending_anchor(context.source_body)
    if anchor:
        focus += f"原文结尾「{anchor}」必须原样保留为全文最后一段。"
    return focus


def render_generic_expansion_prompt(*, context: LengthPromptContext) -> str:
    return render_prompt_template(
        get_effective_prompt_template("expansion"),
        {
            "target_chars": context.target_chars,
            "expansion_focus": _expansion_focus_text(context),
            "source_body": context.source_body,
        },
    )


def render_generic_polish_prompt(*, context: LengthPromptContext) -> str:
    return render_prompt_template(
        get_effective_prompt_template("polish"),
        {
            "target_chars": context.target_chars,
            "polish_focus": (
                "只润色表达，不改动剧情走向：收紧冗余句式、统一称谓和时态、"
                "让对话和动作衔接更自然。"
                "不得新增、删除或改写剧情事实、人物选择、世界规则、金额数字和结尾钩子。"
            ),
            "source_body": context.source_body,
        },
    )


def render_generic_compression_prompt(*, context: LengthPromptContext) -> str:
    compression_method = "压缩方法：删重复解释、删绕圈心理、合并相似动作；保留核心冲突、人物反应、关键线索、代价、转折和下一步钩子。"
    if context.feedback.strip():
        compression_method = f"压缩反馈：{context.feedback.strip()}\n{compression_method}"
    return render_prompt_template(
        get_effective_prompt_template("compression"),
        {
            "opening_line": "下面这章正文超过目标篇幅，请在不改变剧情事实、人物选择、世界规则、结尾钩子的前提下压缩。",
            "target_chars": context.compression_target_chars
            or f"保留完整网文章节感，调整到5000到5400字，绝对不要超过{context.max_chapter_chars}字",
            "compression_method": compression_method,
            "chapter_scope": "不得新增原文或章节计划之外的设定、能力、人物关系、事件结算。",
            "source_body": context.source_body,
        },
    )


def empty_director_plan_review(*, context: Any) -> list[str]:
    return []


def identity_scene_cards(*, context: Any) -> list[dict[str, Any]]:
    return context.scene_cards
