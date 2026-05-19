from __future__ import annotations

from copy import deepcopy
from typing import Any


WEB_GAME_OPENING_GUIDANCE: dict[str, Any] = {
    "profile_id": "web_game_leveling_opening",
    "genre": "web_game_leveling",
    "voice": "直白、紧凑、生活化，有爽点但不喊爽点",
    "chapter_pattern": "现实压力 -> 游戏入口 -> 异常伏笔 -> 领先验证 -> 下一步升级目标",
    "show_rules": [
        "爆率优势通过任务进度、经验条、装备门槛、技能条件和普通玩家对比表现。",
        "金手指先异常再验证，不直接解释成百科。",
        "大型服务器会吞掉低级材料噪音；早期旁人最多觉得主角运气好或刷怪路线熟。",
        "公会压力只给资源点目击、榜单、稀有物或多源记录，不正面对抗。",
        "NPC服务通过地点、口吻、价格、账本和信息边界影响选择。",
        "交易规则通过界面、价牌、队伍闲聊或柜台反馈露出，不写成说明书。",
    ],
    "avoid_rules": [
        "不要用意味着、很直接、很清楚、风险也是这类报告式判断。",
        "不要连续使用孤立机械短段，让段落像 AI 卡片。",
        "不要让润色新增消费、装备、任务结果或改变账本。",
        "不要把交易行、公会、NPC规则写成说明书。",
    ],
}


CARD_GUIDANCE: dict[str, dict[str, list[str]]] = {
    "reality_entry": {
        "write_as": ["账单物件", "房间细节", "手指停顿", "现实技能带来的判断"],
        "avoid": ["直接总结主角很惨", "大段解释现实背景"],
        "fact_locks": ["现实职业/技能来源不得改", "登录动机不得改"],
    },
    "character_creation": {
        "write_as": ["角色创建界面", "职业列表", "价钱和补给", "角色面板"],
        "avoid": ["只在旁白里说职业", "漏掉基础属性"],
        "fact_locks": ["游戏ID", "职业", "等级", "经验", "生命/法力", "基础属性"],
    },
    "small_verification": {
        "write_as": ["低级怪战斗", "掉落提示音", "背包数字变化", "主角停顿"],
        "avoid": ["直接宣布金手指无敌", "跳过验证过程"],
        "fact_locks": ["掉落数量", "背包变化", "经验变化"],
    },
    "single_npc_service": {
        "write_as": ["NPC地点", "柜台/工具/账本", "岗位口吻", "服务价格或门槛"],
        "avoid": ["NPC只当任务牌子", "NPC全知隐藏天赋"],
        "fact_locks": ["NPC只能看到服务记录", "NPC不能知道隐藏天赋"],
    },
    "market_weak_trace": {
        "write_as": ["界面操作", "界面价牌", "队伍噪音", "材料背景", "普通玩家误读"],
        "avoid": ["解释市场规则", "直接说风险", "暴露坐标", "新增消费"],
        "fact_locks": ["材料数量", "任务门槛", "余额/货币不得漂移", "手续费只作规则提示不完成扣款", "外部只见弱线索", "不能直接暴露身份"],
    },
}


def _is_web_game(genre: str, world_events: list[dict[str, Any]], scene_cards: list[dict[str, Any]]) -> bool:
    text = " ".join(
        [
            genre,
            *[str(event.get("template_id", "")) for event in world_events],
            *[str(card.get("template_id", "")) for card in scene_cards],
        ]
    )
    return any(token in text for token in ("网游", "web_game", "market_weak_trace", "character_creation"))


def build_style_guidance(
    *,
    genre: str,
    chapter_number: int,
    world_events: list[dict[str, Any]] | None = None,
    scene_cards: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    world_events = world_events or []
    scene_cards = scene_cards or []
    if chapter_number <= 3 and _is_web_game(genre, world_events, scene_cards):
        return deepcopy(WEB_GAME_OPENING_GUIDANCE)
    return {
        "profile_id": "generic_plain_prose",
        "genre": "generic",
        "voice": "清楚、自然、少解释，多用动作和场景承载信息",
        "chapter_pattern": "目标 -> 行动 -> 反馈 -> 新压力",
        "show_rules": ["规则和设定优先通过动作、对话、界面或环境反馈表现。"],
        "avoid_rules": ["不要写成说明书，不要连续机械短段。"],
    }


def enrich_performance_cards(
    scene_cards: list[dict[str, Any]] | None,
    style_guidance: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for card in scene_cards or []:
        new_card = deepcopy(card)
        template_id = str(new_card.get("template_id", ""))
        guidance = CARD_GUIDANCE.get(template_id, {})
        for key in ("write_as", "avoid", "fact_locks"):
            existing = (
                [str(item) for item in new_card.get(key, []) if str(item).strip()]
                if isinstance(new_card.get(key), list)
                else []
            )
            additions = guidance.get(key, [])
            merged: list[str] = []
            for item in [*existing, *additions]:
                if item and item not in merged:
                    merged.append(item)
            if merged:
                new_card[key] = merged
        enriched.append(new_card)
    return enriched
