from __future__ import annotations

import re
from typing import Any

from packages.story_core.agent_base import compact_list, compact_text
from packages.story_core.models import StoryState
from packages.story_core.novel_type_catalog import normalize_novel_type_id


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


def _genre_mode(story: StoryState, game_story: bool) -> str:
    genre_id = normalize_novel_type_id(story.genre)
    if genre_id == "game_webnovel":
        return "game_webnovel"
    if genre_id in {"xuanhuan", "xianxia"}:
        return genre_id
    if genre_id:
        return "unknown"
    if game_story:
        return "game_webnovel"
    return "unknown"


def _arc_window(chapter_number: int, *, genre_mode: str) -> dict[str, str]:
    if genre_mode == "xuanhuan":
        if chapter_number <= 3:
            return {
                "name": "开篇立足",
                "purpose": "立住主角身份、力量体系的可见反馈、势力压力，以及机缘对应的代价。",
                "upper_bound": "先兑现眼前处境和小反馈，不擅自命名境界，也不提前送出完整传承。",
            }
        return {
            "name": "阶段成长",
            "purpose": "让身份、力量、资源和势力关系随行动一起变化，机缘必须继续带来代价。",
            "upper_bound": "只推进大纲已经允许的世界层级，不擅造境界名或跳过成长条件。",
        }
    if genre_mode == "xianxia":
        if chapter_number <= 3:
            return {
                "name": "开篇立因",
                "purpose": "从具体差事立住修行处境、因果牵连、宗门或社会秩序和资源代价。",
                "upper_bound": "先给可验证的小反馈，不擅自命名境界，也不直接送出完整传承。",
            }
        return {
            "name": "因果推进",
            "purpose": "让修行选择、资源代价、关系和秩序反应互相推动。",
            "upper_bound": "只推进大纲已明确的修行层级，不擅造境界名或跳过因果代价。",
        }
    if genre_mode == "unknown":
        return {
            "name": "当前剧情阶段",
            "purpose": "推动目标、关系、信息、资源和风险发生可见变化。",
            "upper_bound": "只使用大纲和既有事实，不套用未选择题材的成长体系。",
        }
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


def _pace_contract(chapter_number: int, level: int | None, *, genre_mode: str) -> dict[str, str]:
    if genre_mode == "xuanhuan":
        return {
            "pace": "每章都要有具体推进",
            "must_payoff": "身份、力量体系反馈、势力压力、机缘或代价至少有一项发生可见变化。",
            "must_not_drag": "不能只解释设定；变化必须由人物行动和后果完成。",
        }
    if genre_mode == "xianxia":
        return {
            "pace": "每章都要推进选择与后果",
            "must_payoff": "修行、因果、宗门或社会秩序、资源代价至少有一项发生可见变化。",
            "must_not_drag": "不能只讲规则和背景；选择必须在本章产生结果。",
        }
    if genre_mode == "unknown":
        return {
            "pace": "每章都要改变局面",
            "must_payoff": "目标、关系、信息、资源或风险至少有一项发生可见变化。",
            "must_not_drag": "不能用背景说明替代人物行动和本章结果。",
        }
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


def _snowball_logic(chapter_number: int, *, genre_mode: str) -> list[str]:
    if genre_mode == "xuanhuan":
        return [
            "本章得到的力量反馈、资源或人情必须在后续继续有用。",
            "势力只能依据看得见的行动和利益作出反应，不能无故看穿秘密。",
            "机缘带来的收益要和代价一起进入后续剧情。",
        ]
    if genre_mode == "xianxia":
        return [
            "本章的修行所得、资源消耗和人情因果必须留到后续继续发生作用。",
            "宗门与他人只能依据可见行为、秩序和利益作出反应。",
            "每次选择都要留下可追踪的因果或资源代价。",
        ]
    if genre_mode == "unknown":
        return [
            "本章目标的结果必须改变下一步行动。",
            "关系、信息、资源和风险变化要在后续继续发生作用。",
            "外部反应只能来自人物已经看见或能够查到的事实。",
        ]
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


def _future_use_rule(genre_mode: str) -> str:
    if genre_mode == "unknown":
        return "本章目标、关系、信息、资源和风险的变化都要继续推动后续，不能当章用完就丢。"
    if genre_mode == "xuanhuan":
        return "本章新增的力量反馈、人物、机缘、资源和代价都要继续推动后续，不能只为当章圆场。"
    if genre_mode == "xianxia":
        return "本章新增的修行所得、人物、因果和资源代价都要继续推动后续，不能只为当章圆场。"
    return "本章新增道具、人物、任务和线索都要说明能怎样继续推动后续，不能只为当章圆场。"


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
    genre_mode = _genre_mode(story, game_story)
    arc = _arc_window(chapter_number, genre_mode=genre_mode)
    pace = _pace_contract(chapter_number, level, genre_mode=genre_mode)
    longform_facts = [
        fact
        for fact in getattr(story, "world_facts", [])
        if str(fact).startswith(("百万字", "长卷阶段", "长期成长阶段", "长期经济阶段", "现实线阶段", "真相揭露阶段", "地图解锁阶段"))
    ]
    previous_next_focus = story.chapter_summaries[-1].next_focus if story.chapter_summaries else ""
    visible_goal = chapter_goal or previous_next_focus or story.outline or "推进当前章节目标"
    contract = {
        "schema_version": "longform-plot-contract/v1",
        "mode": "longform-plot-first",
        "genre_mode": genre_mode,
        "arc_window": arc,
        "chapter_goal": compact_text(visible_goal, 180),
        "pace_contract": pace,
        "snowball_logic": _snowball_logic(chapter_number, genre_mode=genre_mode),
        "payoff_requirement": pace["must_payoff"],
        "anti_drag_rule": pace["must_not_drag"],
        "future_use_rule": _future_use_rule(genre_mode),
        "reader_reason_to_continue": "章末必须留下一个下一章立刻能执行的动作，并且这个动作来自本章已经兑现的收获或新压力。",
        "longform_references": compact_list(longform_facts, max_items=8, item_chars=180),
        "story_priority": {
            "outline": compact_text(story.outline, 240),
            "previous_next_focus": compact_text(previous_next_focus, 160),
            "chapter_goal": compact_text(visible_goal, 180),
            "rule": "用户大纲、本章目标和上一章下一步高于章节号默认节奏。",
        },
    }
    if genre_mode == "game_webnovel":
        contract["webgame_satisfaction"] = [
            "爽感落在暗中领先：任务更快、资源更多、现实压力被缓解，外人只看见普通动作。",
            "数值和物品必须能进账本；可堆叠背包、货币、经验、耐久、法力和任务状态都要可追踪。",
            "低等级不能硬开高等级转职线；可以看到前置任务，但不能跳过等级、材料、费用和服务流程。",
        ]
    return contract
