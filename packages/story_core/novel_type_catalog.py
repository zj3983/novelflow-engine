from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


DEFAULT_NOVEL_TYPE_ID = "generic_webnovel"
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


@dataclass(frozen=True)
class NovelType:
    plugin_id: str
    label: str
    description: str
    keywords: tuple[str, ...]


NOVEL_TYPE_CATALOG: dict[str, NovelType] = {
    "generic_webnovel": NovelType(
        plugin_id="generic_webnovel",
        label="通用网文",
        description="不绑定具体题材规则，只保留章节推进、钩子、人物动机和连续性要求。",
        keywords=("网文", "网络小说", "爽文", "连载"),
    ),
    "game_webnovel": NovelType(
        plugin_id="game_webnovel",
        label="网游升级",
        description="加载等级、面板、背包、任务、货币、掉落、玩家生态和NPC服务规则。",
        keywords=("网游", "游戏", "系统", "等级", "副本", "爆率"),
    ),
    "urban": NovelType(
        plugin_id="urban",
        label="都市现代",
        description="加载职场、商业、舆论、人际关系、现实利益和身份反差规则。",
        keywords=("都市", "职场", "商业", "公司", "现代"),
    ),
    "xuanhuan": NovelType(
        plugin_id="xuanhuan",
        label="东方玄幻",
        description="聚焦自创力量、异物机缘、资源成长和世界秘密，允许项目自行定义力量来源与成长终点。",
        keywords=("玄幻", "血脉", "体质", "武魂", "异火", "遗物", "古族"),
    ),
    "xianxia": NovelType(
        plugin_id="xianxia",
        label="修仙仙侠",
        description="聚焦灵根修炼、道法因果、渡劫飞升和长生求道，加载修真境界、传承与修炼资源规则。",
        keywords=("修仙", "仙侠", "灵根", "修真", "宗门", "境界", "道法"),
    ),
    "suspense": NovelType(
        plugin_id="suspense",
        label="悬疑推理",
        description="加载线索、证据链、嫌疑人、调查推进和公平反转规则。",
        keywords=("悬疑", "推理", "案件", "线索", "调查"),
    ),
    "romance": NovelType(
        plugin_id="romance",
        label="言情关系",
        description="加载关系拉扯、情绪递进、误会、靠近和外部阻碍规则。",
        keywords=("言情", "甜宠", "婚恋", "古言", "女频"),
    ),
    "rules_mystery": NovelType(
        plugin_id="rules_mystery",
        label="规则怪谈",
        description="加载规则验证、禁忌代价、污染递进和异常逻辑规则。",
        keywords=("规则怪谈", "怪谈", "禁忌", "污染", "异常"),
    ),
}


def has_explicit_non_game_type(text: Any) -> bool:
    haystack = str(text or "")
    stripped = haystack.strip()
    if not stripped:
        return False
    if stripped.lower() in EXPLICIT_NON_GAME_TYPE_IDS:
        return True

    type_ids = "|".join(re.escape(plugin_id) for plugin_id in EXPLICIT_NON_GAME_TYPE_IDS)
    type_aliases = "|".join(
        re.escape(alias) for alias in sorted(EXPLICIT_NON_GAME_TYPE_ALIASES, key=len, reverse=True)
    )
    metadata_patterns = (
        rf"(?<![A-Za-z0-9_])[\"']?(?:小说类型|xiaoshuoleixing|novel_type|novelType|genre|type)[\"']?\s*[:=：]\s*[\"']?(?:{type_ids}|{type_aliases})(?![A-Za-z0-9_])",
        rf"(?<![A-Za-z0-9_])[\"']?genre_plugin_ids[\"']?\s*[:=]\s*\[[^\]]*[\"'](?:{type_ids})[\"']",
    )
    return any(re.search(pattern, haystack, flags=re.IGNORECASE) for pattern in metadata_patterns)


def normalize_novel_type_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = [value]
    elif isinstance(value, list):
        raw = [str(item) for item in value if str(item).strip()]
    else:
        raw = []
    result: list[str] = []
    for value in raw:
        plugin_id = normalize_novel_type_id(value)
        if plugin_id and plugin_id not in result:
            result.append(plugin_id)
    return result


def normalize_novel_type_id(value: Any) -> str:
    plugin_id = canonical_novel_type_id(value)
    return plugin_id if plugin_id in NOVEL_TYPE_CATALOG else ""


def canonical_novel_type_id(value: Any) -> str:
    plugin_id = str(value or "").strip().lower()
    return NOVEL_TYPE_ID_ALIASES.get(plugin_id, plugin_id)


def runtime_novel_type(value: Any) -> Any:
    plugin_id = canonical_novel_type_id(value)
    if not plugin_id:
        return None

    # Lazy import keeps the static catalog available as the library bootstrap.
    from packages.story_core.novel_type_library import get_novel_type

    return get_novel_type(plugin_id)


def resolve_novel_type_id(value: Any) -> str:
    record = runtime_novel_type(value)
    return record.id if record is not None else ""


def novel_type_options() -> list[dict[str, Any]]:
    from packages.story_core.novel_type_library import list_novel_types

    return [
        {
            "id": item.id,
            "label": item.name,
            "description": item.description,
            "keywords": list(item.keywords),
        }
        for item in list_novel_types()
    ]
