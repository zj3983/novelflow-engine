from __future__ import annotations

import re
from typing import Any

from packages.story_core.agent_base import compact_list, compact_text
from packages.story_core.models import StoryState


def _ledger_value(story: StoryState, *path: str) -> Any:
    value: Any = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _level_number(story: StoryState) -> int | None:
    raw = _ledger_value(story, "protagonist", "level")
    if isinstance(raw, int):
        return raw
    if raw not in (None, ""):
        match = re.search(r"\d{1,3}", str(raw))
        if match:
            return int(match.group(0))
    if story.chapter_summaries:
        text = "\n".join(story.chapter_summaries[-1].facts)
        match = re.search(r"(?:Lv\.?|等级)\s*(\d{1,3})", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _arc_window(chapter_number: int) -> dict[str, str]:
    if chapter_number <= 3:
        return {
            "name": "黄金三章",
            "purpose": "用现实压力、千倍爆率验证和第一笔可见领先留住读者。",
            "upper_bound": "只写新手村低级任务和低级资源变现，不提前进入转职试炼或公会正面追查。",
        }
    if chapter_number <= 10:
        return {
            "name": "新手村滚雪球",
            "purpose": "让夜烬把掉落优势换成等级、技能、装备、铜币和前置任务优势。",
            "upper_bound": "可以出现商人、散人玩家和公会外围弱试探，但不能直接揭开千倍爆率。",
        }
    if chapter_number <= 30:
        return {
            "name": "灰烬村外扩",
            "purpose": "把新手村优势扩成稳定资源线，并让外部势力开始用弱线索逼近。",
            "upper_bound": "可以推进10级后的正式职业线，但每次解锁都要有等级、材料、费用和失败代价。",
        }
    return {
        "name": "长线推进",
        "purpose": "承接上一卷资源与敌意，把优势换成更高层级的地图、职业、势力或真相推进。",
        "upper_bound": "只解锁当前卷允许的世界层级，不跳过关键前置。",
    }


def _pace_contract(chapter_number: int, level: int | None) -> dict[str, str]:
    level_text = f"Lv.{level}" if level is not None else "当前等级未明"
    if chapter_number == 1:
        return {
            "pace": "第一章必须快兑现",
            "must_payoff": "现实压力要得到第一步缓解，游戏内要看到千倍爆率确实能变成钱、任务或资源优势。",
            "must_not_drag": "不要只写登录、犹豫和刷几只怪；章末必须有可见结果。",
        }
    if chapter_number <= 3:
        return {
            "pace": "前三章必须连续升级爽感",
            "must_payoff": f"承接{level_text}状态，至少兑现等级/经验大进度、任务完成、技能、装备修复、补给或现实余额变化中的一项。",
            "must_not_drag": "不能连续两章只拿线索、只观察、只解释规则。",
        }
    if chapter_number <= 10:
        return {
            "pace": "新手期推进要密",
            "must_payoff": "每章至少让一项账本向前滚：等级、技能、装备、铜币、任务权限、材料渠道或现实收入。",
            "must_not_drag": "不要把耐久、蓝量、排队写成整章主线；它们只能制造阻力，不能替代收获。",
        }
    return {
        "pace": "长线章节也要有本章兑现",
        "must_payoff": "本章必须完成一个阶段结果，同时留下新的压力。",
        "must_not_drag": "不能用世界观说明替代行动结果。",
    }


def _snowball_logic(chapter_number: int) -> list[str]:
    if chapter_number == 1:
        return [
            "别人看到的是普通玩家卖材料或办服务，读者看到的是夜烬把异常掉落换成第一口喘息。",
            "裂纹狼心这类稀有物必须有买家用途：配方、图鉴、样本、前置任务或公会需求，不能只是没用杂物。",
            "第一章的爽点不是公开炫耀，而是账本真的变好，外人还看不懂来源。",
        ]
    if chapter_number <= 3:
        return [
            "上一章的收获必须在本章变成新动作，不要重新从零验证。",
            "苟不是不拿好处，而是拆开拿、换壳拿、让别人以为只是排队办事或运气好。",
            "本章结尾要让下一章马上有事可做：交前置、买技能、修装备、冲等级、试地图入口或避开盯梢。",
        ]
    if chapter_number <= 10:
        return [
            "苟不是不拿好处，而是暗中把每一笔好处滚进等级、技能、装备、任务权限或现实收入。",
            "上一章兑现的收获必须在本章继续使用，不能变成一次性圆场道具。",
            "外人只能看见普通玩家会做的事：排队、问价、修装备、买药、交任务、换地图入口。",
            "章末要把新收益变成下一章的明确动作，而不是只留下抽象感慨。",
        ]
    return [
        "每章收获都要进入长期账本，后续能继续使用或引来反应。",
        "外部势力只能根据可见痕迹逐步误判和逼近，不能全知锁定夜烬。",
        "资源、任务、人物和地图入口要形成链条，不能当章用完就丢。",
    ]


def build_longform_plot_contract(
    story: StoryState,
    chapter_number: int,
    *,
    chapter_goal: str = "",
    game_story: bool = False,
) -> dict[str, Any]:
    """Build a plot-first contract for long-form serial writing.

    This sits between world simulation and prose. It does not write a chapter;
    it tells the later stages what the chapter must achieve in the book-length
    snowball, so generation does not fall back to one-chapter patching.
    """

    level = _level_number(story)
    arc = _arc_window(chapter_number)
    pace = _pace_contract(chapter_number, level)
    longform_facts = [
        fact
        for fact in getattr(story, "world_facts", [])
        if str(fact).startswith(("百万字", "长卷阶段", "长期成长阶段", "长期经济阶段", "现实线阶段", "真相揭露阶段", "地图解锁阶段"))
    ]
    visible_goal = chapter_goal or (story.chapter_summaries[-1].next_focus if story.chapter_summaries else "") or "推进当前章节目标"
    contract = {
        "schema_version": "longform-plot-contract/v1",
        "mode": "longform-plot-first",
        "arc_window": arc,
        "chapter_goal": compact_text(visible_goal, 180),
        "pace_contract": pace,
        "snowball_logic": _snowball_logic(chapter_number if game_story else 99),
        "payoff_requirement": pace["must_payoff"],
        "anti_drag_rule": pace["must_not_drag"],
        "future_use_rule": "本章新增道具、人物、任务和线索都要说明能怎样继续推动后续，不能只为当章圆场。",
        "reader_reason_to_continue": "章末必须留下一个下一章立刻能执行的动作，并且这个动作来自本章已经兑现的收获或新压力。",
        "longform_references": compact_list(longform_facts, max_items=8, item_chars=180),
    }
    if game_story:
        contract["webgame_satisfaction"] = [
            "爽感落在暗中领先：任务更快、资源更多、现实压力被缓解，外人只看见普通动作。",
            "数值和物品必须能进账本；可堆叠背包、货币、经验、耐久、法力和任务状态都要可追踪。",
            "低等级不能硬开高等级转职线；可以看到前置任务，但不能跳过等级、材料、费用和服务流程。",
        ]
    return contract
