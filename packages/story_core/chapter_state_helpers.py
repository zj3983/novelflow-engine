from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


GAME_STATE_FIELDS = (
    "game_id",
    "level",
    "class_path",
    "exp",
    "hp",
    "mp",
    "attributes",
    "skills",
    "equipment",
    "inventory",
    "currency",
    "quests",
    "risk",
    "backpack",
)


def sync_game_panel_from_state(card: dict[str, Any]) -> dict[str, Any]:
    """Mirror structured game state into the legacy panel."""

    panel = dict(card.get("game_panel") or {})
    state = dict(card.get("game_state") or {})
    current = (
        dict(state.get("current") or {})
        if isinstance(state.get("current"), dict)
        else {}
    )
    for field in GAME_STATE_FIELDS:
        value = current.get(field)
        if value not in (None, "", [], {}):
            panel[field] = deepcopy(value)
    card["game_panel"] = panel
    return card


def without_monster_stat_surfaces(text: str) -> str:
    text = re.sub(
        r"(?:系统(?:弹出)?(?:怪物)?信息|怪物信息)\s*[：:][^。！？\n]*[。！？]?",
        "",
        text,
        flags=re.IGNORECASE,
    )
    monster_panel = re.compile(
        r"【[^】]+】(?:\s*【(?:等级|生命|攻击方式|技能|特性)[^】]*】){2,}",
        flags=re.IGNORECASE,
    )
    text = monster_panel.sub(
        lambda match: "" if "攻击方式" in match.group(0) else match.group(0),
        text,
    )
    compact_monster_panel = re.compile(
        r"【(?=[^】]*(?:等级|Lv\.?))(?=[^】]*生命)(?=[^】]*攻击方式)[^】]+】",
        flags=re.IGNORECASE,
    )
    return compact_monster_panel.sub("", text)
