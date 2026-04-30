from __future__ import annotations

from typing import Any

from packages.story_core.agent_base import compact_list, compact_text
from packages.story_core.genre_plugins import merge_plugin_rulebooks, plugin_simulation_blueprint, select_genre_plugins
from packages.story_core.models import NovelProject, StoryState


LONGFORM_FACT_PREFIXES = (
    "百万字",
    "长期卷阶梯",
    "长期成长阶梯",
    "长期势力阶梯",
    "长期经济阶梯",
    "现实线阶梯",
    "真相揭露阶梯",
    "地图解锁阶梯",
    "NPC演化阶梯",
    "长期推演规则",
)


def _proxy_project(story: StoryState) -> NovelProject:
    latest = story.chapter_summaries[-1] if story.chapter_summaries else None
    return NovelProject(
        project_id=story.story_id,
        title=story.outline[:80] or story.story_id,
        seed_outline=story.outline,
        world_summary="\n".join(story.world_facts[:24]),
        current_focus=(latest.next_focus if latest else ""),
        author_constraints=list(story.author_constraints),
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]} if _is_game_story(story) else {},
    )


def _is_game_story(story: StoryState) -> bool:
    text = "\n".join(
        [
            story.genre,
            story.style,
            story.outline,
            "\n".join(story.world_facts[:24]),
            "\n".join(story.author_constraints[:12]),
        ]
    )
    return any(token in text for token in ("网游", "游戏", "VRMMO", "交易行", "公会", "爆率", "职业"))


def _phase(chapter_number: int) -> str:
    if chapter_number == 1:
        return "黄金三章第1章：立主角、立游戏入口、立金手指风险，完成小额首次验证。"
    if chapter_number == 2:
        return "黄金三章第2章：扩大收益验证，补足NPC/任务/交易规则，让外围压力逼近。"
    if chapter_number == 3:
        return "黄金三章第3章：形成第一个小高潮，确立职业试炼和长期路线。"
    return "常规连载章节：目标、行动、收益、代价、外部反应和章末钩子。"


def _latest_continuity(story: StoryState) -> dict[str, Any]:
    latest = story.chapter_summaries[-1] if story.chapter_summaries else None
    return {
        "latest_summary": compact_text(latest.summary if latest else "", 220),
        "must_keep_facts": compact_list(latest.facts if latest else [], max_items=10, item_chars=150),
        "unresolved_threads": compact_list(latest.unresolved_threads if latest else [], max_items=6, item_chars=120),
        "next_focus": compact_text(latest.next_focus if latest else "", 160),
    }


def _longform_constraints(story: StoryState) -> list[str]:
    return compact_list(
        [fact for fact in story.world_facts if fact.startswith(LONGFORM_FACT_PREFIXES)],
        max_items=16,
        item_chars=220,
    )


def _contract_for_game(chapter_number: int) -> dict[str, list[str]]:
    if chapter_number == 1:
        return {
            "required_beats": [
                "现实压力和主角现实职业/技能来源必须自然出现。",
                "登录或建号阶段必须写出游戏ID/网名。",
                "必须写出职业选择，并让职业进入角色面板。",
                "必须出现短角色面板：ID、等级、职业、经验、生命/法力、基础属性、主武器或基础技能、货币/背包关键项。",
                "金手指必须先有触发伏笔，再完成小额首次验证。",
                "只能完整展开一个命名NPC服务节点，优先选择职业导师、村长或新手引导员，用来完成职业/任务/规则入口。",
                "第一章只聚焦一个核心事件：登录建号后首次验证隐藏优势；交易、追债、公会追查和商人压价全部后移。",
                "交易行最多作为章末看见的地点、下一步目标或路牌出现，不得实际寄售、成交、到账或触发商人追踪。",
                "本章结尾必须给出闭合账本：经验、毒腺/狼皮库存、铜币余额、装备耐久、任务状态；不得出现已卖出材料。",
            ],
            "forbidden_moves": [
                "禁止单次低级材料交易暴露坐标、现实身份、隐藏天赋或精确刷怪点。",
                "禁止写死金币兑人民币汇率，除非世界档案已有明确官方兑换或黑市行情。",
                "禁止第一章出现赵胖子追债、商人脚本盯盘、公会会长、白袍据点、论坛围观或任何公会追查戏。",
                "禁止第一章实际交易：不得上架、寄售、成交、到账、提现、换算人民币或描写手续费扣款。",
                "禁止第一章完整展开多个命名NPC、多个服务点或多地图跑腿。",
                "禁止把规则写成百科说明，必须通过界面、交易、对话和行动展示。",
                "禁止在正文出现作者术语或创作术语，例如爽点、钩子、节奏、读者、网文规则、生成、审稿。",
                "禁止出现卖出16份毒腺后仍剩余8份这类库存矛盾；禁止未提交材料却写成任务已提交。",
            ],
            "world_reaction_targets": [
                "主角只得到个人层面的首次收益反馈和背包变化。",
                "命名NPC只能基于岗位服务或任务入口给出一句边界清楚的反应。",
                "章末只留下下一章交易/补给/任务门槛目标，不让外部势力正式介入。",
            ],
        }
    if chapter_number == 2:
        return {
            "required_beats": [
                "继承第一章等级、经验、职业、货币、库存和装备耐久。",
                "通过刷怪路线、补给成本、NPC服务门槛或交易批次推进收益。",
                "至少一个命名NPC以服务、价格、任务或信息边界影响选择。",
                "外部压力只能从弱线索升级到外围试探。",
            ],
            "forbidden_moves": [
                "禁止不记账地改变材料价格、货币余额、装备或经验。",
                "禁止不直接完成元素回廊前置或直接升级，除非正文完整写出材料、经验和消耗账本。",
                "禁止公会精准锁定坐标、现实身份或隐藏天赋。",
            ],
            "world_reaction_targets": [
                "交易批次或价格曲线被商人注意。",
                "NPC库存、任务回收或服务门槛反馈异常。",
                "公会外围只做资源点或论坛层面的试探。",
            ],
        }
    return {
        "required_beats": [
            "每章必须有目标、行动、收益反馈、新压力。",
            "继承并更新等级、经验、货币、装备、任务和外部压力账本。",
            "世界反应必须来自可见痕迹和利益链条。",
        ],
        "forbidden_moves": [
            "禁止势力全知全能。",
            "禁止规则直接硬讲成长段说明。",
            "禁止跳过成本获得高阶收益。",
        ],
        "world_reaction_targets": [
            "市场、NPC、公会、普通玩家或论坛至少一方做出具体反应。",
        ],
    }


def _generic_contract() -> dict[str, list[str]]:
    return {
        "required_beats": [
            "本章必须明确目标、阻力、行动选择、阶段收益和章末新压力。",
            "设定必须通过场景、对话、行动和后果展示。",
        ],
        "forbidden_moves": [
            "禁止摘要化正文。",
            "禁止角色为推动剧情突然降智。",
            "禁止忘记上一章事实和未解钩子。",
        ],
        "world_reaction_targets": ["至少一个角色、势力或环境系统对主角行动做出反馈。"],
    }


def _simulation_axes(story: StoryState, plugin_ids: list[str]) -> dict[str, list[str]]:
    if "game_webnovel" in plugin_ids:
        return {
            "protagonist": ["现实身份", "游戏ID", "职业路线", "等级经验", "技能装备", "风险偏好"],
            "economy": ["币制", "材料单价", "挂单批次", "手续费", "库存", "现实兑换边界"],
            "npc": ["地点", "服务", "价格/门槛", "利益诉求", "口吻", "信息边界"],
            "factions": ["公会外围", "商人玩家", "散人玩家", "生活职业需求", "论坛传闻"],
            "visibility": ["交易行时间戳", "价格曲线", "资源点目击", "NPC服务数据", "多源交叉延迟"],
        }
    return {
        "protagonist": ["目标", "代价", "关系变化", "当前能力"],
        "world": ["资源流动", "势力反应", "信息传播", "地点功能"],
    }


def build_chapter_seed(story: StoryState, chapter_number: int) -> dict[str, Any]:
    """Build the compact pre-writing contract that connects world simulation to prose."""
    plugins = select_genre_plugins(_proxy_project(story))
    plugin_ids = [plugin.plugin_id for plugin in plugins]
    rulebook = merge_plugin_rulebooks(plugins)
    is_game = "game_webnovel" in plugin_ids
    contract = _contract_for_game(chapter_number) if is_game else _generic_contract()
    return {
        "schema_version": "chapter-seed/v1",
        "chapter_number": chapter_number,
        "phase": _phase(chapter_number),
        "genre_plugins": plugin_ids,
        "core_promises": compact_list(
            [promise for plugin in plugins for promise in plugin.core_promises],
            max_items=6,
            item_chars=150,
        ),
        "rulebook": {
            key: compact_list(value, max_items=5, item_chars=170)
            for key, value in rulebook.items()
        },
        "current_state": story.progression_ledger or {},
        "continuity": _latest_continuity(story),
        "chapter_contract": contract,
        "simulation_axes": _simulation_axes(story, plugin_ids),
        "simulation_blueprint": plugin_simulation_blueprint(plugins),
        "longform_constraints": _longform_constraints(story),
        "world_facts": compact_list(story.world_facts, max_items=18, item_chars=180),
        "author_constraints": compact_list(story.author_constraints, max_items=12, item_chars=180),
    }
