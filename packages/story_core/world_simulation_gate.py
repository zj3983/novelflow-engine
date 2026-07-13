"""Decide whether a chapter needs external-world simulation."""

from __future__ import annotations

from typing import Any

from packages.story_core.genre_plugins import is_game_genre
from packages.story_core.models import StoryState


_EFFECT_FIELDS = ("ledger_updates", "state_change", "visible_state_changes")
_ACTOR_FIELDS = ("quest_beats", "npc_beats", "world_reactions", "economy_expectations")
_TRIGGER_WORDS = (
    "任务",
    "击杀",
    "掉落",
    "经验",
    "等级",
    "装备",
    "耐久",
    "背包",
    "货币",
    "交易",
    "修理",
    "购买",
    "npc",
    "公会",
    "玩家反应",
    "势力",
)
_CONCRETE_EFFECT_WORDS = ("接取", "完成", "提交", "交", "奖励", "进度", "失败", "掉落", "经验", "等级", "耐久", "货币", "交易", "修理", "购买", "改变", "反应")


def world_simulation_decision(
    story: StoryState,
    chapter_number: int,
    *,
    event_plan: dict[str, Any] | None = None,
    chapter_seed: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the decision and the exact chapter-local reasons behind it."""
    event_plan = event_plan if isinstance(event_plan, dict) else {}
    chapter_seed = chapter_seed if isinstance(chapter_seed, dict) else {}
    # The opening of a game novel needs the initial game state and first drops
    # to become visible facts. Later chapters only pay this cost when a trigger
    # is present in the chapter plan or continuity seed.
    is_game = is_game_genre(" ".join([story.genre, story.style, story.outline]))
    if is_game and chapter_number == 1:
        return {"run": True, "reason": "game_opening", "triggers": ["开篇需要建立游戏状态和首次反馈"]}

    triggers: list[str] = []
    if any(event_plan.get(field) for field in _EFFECT_FIELDS):
        triggers.extend(field for field in _EFFECT_FIELDS if event_plan.get(field))
    actor_text = " ".join(str(event_plan.get(field) or "") for field in _ACTOR_FIELDS).lower()
    if event_plan.get("external_effect") is True or any(word in actor_text for word in _CONCRETE_EFFECT_WORDS):
        triggers.extend(field for field in _ACTOR_FIELDS if event_plan.get(field))

    # The seed contains long-term rules and forbidden examples. Only inspect
    # chapter-local direction data; do not let a persistent word like "任务"
    # turn every dialogue chapter into a world simulation.
    direction = chapter_seed.get("selected_chapter_direction")
    if isinstance(direction, dict):
        direction_text = " ".join(str(direction.get(key) or "") for key in ("chapter_goal", "main_scenes", "state_delta", "ending_hook"))
        if any(word in direction_text.lower() for word in _TRIGGER_WORDS):
            triggers.append("selected_chapter_direction")

    active_text = " ".join(str(event_plan.get(field) or "") for field in (*_EFFECT_FIELDS, "external_effect")).lower()
    matched_words = [word for word in _TRIGGER_WORDS if word in active_text]
    triggers.extend(f"本章事件词:{word}" for word in matched_words[:4])
    if triggers:
        return {"run": True, "reason": "chapter_external_effect", "triggers": list(dict.fromkeys(triggers))}
    return {"run": False, "reason": "no_visible_external_effect", "triggers": []}


def needs_world_simulation(
    story: StoryState,
    chapter_number: int,
    *,
    event_plan: dict[str, Any] | None = None,
    chapter_seed: dict[str, Any] | None = None,
) -> bool:
    return bool(
        world_simulation_decision(
            story,
            chapter_number,
            event_plan=event_plan,
            chapter_seed=chapter_seed,
        ).get("run")
    )
