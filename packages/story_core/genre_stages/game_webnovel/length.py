from __future__ import annotations

from packages.story_core.genre_stages.length_prompts import (
    LengthPromptContext,
    expansion_ending_anchor,
    render_generic_polish_prompt,
)
from packages.story_core.prompt_templates import get_effective_prompt_template, render_prompt_template
from packages.story_core.web_game_economy import (
    first_chapter_market_exchange_authorized,
    normalize_legacy_economy_prompt_value,
    opening_market_exchange_flow_lines,
)


def _trade_payoff_authorized(context: LengthPromptContext) -> bool:
    return context.chapter_number == 1 and first_chapter_market_exchange_authorized(
        context.event_plan,
        context.world_facts,
    )


def render_game_expansion_prompt(*, context: LengthPromptContext) -> str:
    expansion_scope = ""
    if context.chapter_number == 1:
        expansion_scope = (
            "第一章按大纲补足以下顺序："
            + " ".join(opening_market_exchange_flow_lines())
            + " 不新增公会追查或论坛扩散。"
            if _trade_payoff_authorized(context)
            else "第一章未获大纲授权时，不新增交易、提交委托、修理或买药水。"
        )
    expansion_focus = (
        "扩写已有场景中的行动、对话、阻力和结果，不新增独立的补丁段。"
        "同一事实、判断和旁人误解只写一次；新增内容必须改变行动、关系或资源。"
        f"{expansion_scope}"
        "逐层补足行动链路和场面阻力，不是逐句增肥。"
        "新增内容默认分到3处关键场面，优先补冲突升级的行动拍；"
        "禁止扩写环境介绍、氛围铺垫和总结性旁白。"
        "不输出扩写规划，只输出扩写后的正文。"
    )
    anchor = expansion_ending_anchor(context.source_body)
    if anchor:
        expansion_focus += f"原文结尾「{anchor}」必须原样保留为全文最后一段。"
    rendered = render_prompt_template(
        get_effective_prompt_template("expansion"),
        {
            "target_chars": context.target_chars,
            "expansion_focus": expansion_focus,
            "source_body": context.source_body,
        },
    )
    return str(
        normalize_legacy_economy_prompt_value(
            rendered,
            game_context=True,
            chapter_number=context.chapter_number,
        )
    )


def render_game_polish_prompt(*, context: LengthPromptContext) -> str:
    rendered = render_generic_polish_prompt(context=context)
    return str(
        normalize_legacy_economy_prompt_value(
            rendered,
            game_context=True,
            chapter_number=context.chapter_number,
        )
    )


def render_game_compression_prompt(*, context: LengthPromptContext) -> str:
    locked_amounts = "、".join(
        str(context.outline_anchor.get(key) or "").strip()
        for key in ("opening_balance", "trade_arrival", "ending_balance")
        if str(context.outline_anchor.get(key) or "").strip()
    )
    compression_method = "压缩方法：删重复解释、删绕圈心理、合并相似动作和面板反馈；保留现实压力、登录建号、首次击杀、异常掉落、背包/血蓝/耐久代价、外人误判和下一步钩子。"
    if context.feedback.strip():
        compression_method = f"压缩反馈：{context.feedback.strip()}\n{compression_method}"
    chapter_scope = (
        "第一章必须原样保留角色面板、怪物面板、千倍爆率、现实职业/技能来源、见习冒险者（未转职），并按以下顺序完成："
        + " ".join(opening_market_exchange_flow_lines())
        + " 不要新增游戏内任务提交、修理或买药。"
        + (f" 以下金额必须原样保留，不得改写、换算或删除：{locked_amounts}。" if locked_amounts else "")
        if _trade_payoff_authorized(context)
        else "第一章不要新增寄售、上架、成交、到账、手续费扣款、提现、任务提交、修理或买药。"
    )
    rendered = render_prompt_template(
        get_effective_prompt_template("compression"),
        {
            "opening_line": "下面这章正文超过目标篇幅，请在不改变剧情事实、人物选择、游戏账本、结尾钩子的前提下压缩。",
            "target_chars": context.compression_target_chars
            or f"保留完整网文章节感，调整到5000到5400字，绝对不要超过{context.max_chapter_chars}字",
            "compression_method": compression_method,
            "chapter_scope": chapter_scope,
            "source_body": context.source_body,
        },
    )
    return str(
        normalize_legacy_economy_prompt_value(
            rendered,
            game_context=True,
            chapter_number=context.chapter_number,
        )
    )
