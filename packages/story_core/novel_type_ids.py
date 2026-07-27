from __future__ import annotations

from typing import Any


DEFAULT_NOVEL_TYPE_ID = "generic_webnovel"
BUILTIN_NOVEL_TYPE_IDS = (
    "generic_webnovel",
    "game_webnovel",
    "urban",
    "xuanhuan",
    "xianxia",
    "suspense",
    "romance",
    "rules_mystery",
)
EXPLICIT_NON_GAME_TYPE_IDS = (
    "generic_webnovel",
    "urban",
    "xuanhuan",
    "xianxia",
    "suspense",
    "romance",
    "rules_mystery",
)
EXPLICIT_NON_GAME_TYPE_ALIASES = (
    "通用网文",
    "都市",
    "都市现代",
    "玄幻",
    "东方玄幻",
    "修仙",
    "仙侠",
    "修仙仙侠",
    "悬疑",
    "悬疑推理",
    "言情",
    "言情关系",
    "规则怪谈",
)
NOVEL_TYPE_ID_ALIASES = {
    "webgame": "game_webnovel",
    "web game": "game_webnovel",
    "game web": "game_webnovel",
    "game webnovel": "game_webnovel",
    "game fantasy": "game_webnovel",
    "通用网文": "generic_webnovel",
    "网游": "game_webnovel",
    "网游升级": "game_webnovel",
    "都市": "urban",
    "都市现代": "urban",
    "玄幻": "xuanhuan",
    "东方玄幻": "xuanhuan",
    "修仙": "xianxia",
    "仙侠": "xianxia",
    "修仙仙侠": "xianxia",
    "悬疑": "suspense",
    "悬疑推理": "suspense",
    "言情": "romance",
    "言情关系": "romance",
    "规则怪谈": "rules_mystery",
}


def canonical_novel_type_id(value: Any) -> str:
    type_id = str(value or "").strip().casefold()
    return NOVEL_TYPE_ID_ALIASES.get(type_id, type_id)
