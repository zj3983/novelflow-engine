from __future__ import annotations

from dataclasses import dataclass
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


def render_generic_expansion_prompt(*, context: LengthPromptContext) -> str:
    return render_prompt_template(
        get_effective_prompt_template("expansion"),
        {
            "target_chars": context.target_chars,
            "expansion_focus": (
                "扩写已有场景中的行动、对话、阻力和结果，不新增独立的补丁段。"
                "同一事实、判断和旁人误解只写一次；新增内容必须改变行动、关系或资源。"
                "不得新增原文或章节计划之外的设定、能力、人物关系、事件结算。"
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
