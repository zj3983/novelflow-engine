from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


RULE_FIELDS = (
    "world_rules",
    "power_system",
    "progression_rules",
    "economy_rules",
    "quest_rules",
    "faction_rules",
    "panel_rules",
    "reality_bridge_rules",
)

_RULE_KEYWORDS = {
    "power_system": (
        "等级",
        "技能",
        "装备",
        "武器",
        "法杖",
        "战斗",
        "怪物",
        "职业",
        "转职",
        "生命",
        "法力",
    ),
    "progression_rules": (
        "升级",
        "进阶",
        "成长",
        "突破",
        "经验",
        "熟练度",
        "属性",
    ),
    "economy_rules": (
        "铜币",
        "材料",
        "掉落",
        "交易",
        "价格",
        "背包",
        "寄售",
        "收购",
        "药水",
        "修理",
        "钱袋",
    ),
    "quest_rules": ("任务", "委托", "登记", "提交", "前置", "奖励"),
    "faction_rules": ("玩家", "公会", "阵营", "势力", "仓库", "守卫"),
    "panel_rules": ("面板", "生命", "法力", "经验", "耐久", "等级", "背包"),
    "reality_bridge_rules": (
        "现实余额",
        "现实到账",
        "人民币",
        "提现",
        "房租",
        "宽带",
        "信用卡",
        "银行卡",
        "银行账户",
        "现实工作",
    ),
}

_CJK_SEQUENCE = re.compile(r"[\u4e00-\u9fff]+")
_GENERIC_QUEST_TERMS = (
    "完成任务后",
    "完成委托后",
    "完成",
    "任务",
    "委托",
    "后续",
    "领取",
    "奖励",
    "提交",
    "登记",
    "前置",
)
_GENERIC_NPC_SHORT_NAMES = {
    "守卫",
    "村长",
    "铁匠",
    "商人",
    "店员",
    "管事",
    "掌柜",
    "导师",
    "队长",
    "老板",
    "伙计",
    "药师",
    "医师",
}


def merge_world_blueprint(current: Any, patch: Any) -> dict[str, Any]:
    merged = deepcopy(current) if isinstance(current, dict) else {}
    if isinstance(patch, dict):
        merged.update(deepcopy(patch))
    return merged


def select_world_context(
    blueprint: Any,
    relevance_text: Any,
    max_rules: int = 8,
) -> dict[str, Any]:
    if isinstance(max_rules, bool) or not isinstance(max_rules, int) or max_rules < 0:
        raise ValueError("max_rules must be a non-negative integer")
    if not isinstance(blueprint, dict):
        return {}

    selected: dict[str, Any] = {}
    premise = blueprint.get("premise")
    if premise not in (None, "", [], {}):
        selected["premise"] = deepcopy(premise)

    rule_budget = max_rules
    world_rules = _rule_values(blueprint, "world_rules")[: min(2, rule_budget)]
    if world_rules:
        selected["world_rules"] = deepcopy(world_rules)
        rule_budget -= len(world_rules)

    relevance = str(relevance_text or "").casefold()
    matched_modules = [
        (field, _rule_values(blueprint, field))
        for field in RULE_FIELDS[1:]
        if _matches_module(field, relevance) and _rule_values(blueprint, field)
    ]
    positions = {field: 0 for field, _ in matched_modules}

    while rule_budget and matched_modules:
        added = False
        for field, values in matched_modules:
            position = positions[field]
            if position >= len(values):
                continue
            selected.setdefault(field, []).append(deepcopy(values[position]))
            positions[field] += 1
            rule_budget -= 1
            added = True
            if not rule_budget:
                break
        if not added:
            break

    matching_chains = _matching_quest_chains(blueprint.get("quest_network"), relevance)
    if matching_chains:
        selected["quest_network"] = {"active_chains": matching_chains}

    return selected


def flatten_selected_rules(selected: Any) -> list[Any]:
    if not isinstance(selected, dict):
        return []

    flattened: list[Any] = []
    for field in RULE_FIELDS:
        values = selected.get(field)
        if isinstance(values, list):
            flattened.extend(deepcopy(values))
    return flattened


def _rule_values(blueprint: dict[str, Any], field: str) -> list[Any]:
    values = blueprint.get(field)
    return values if isinstance(values, list) else []


def _matches_module(field: str, relevance: str) -> bool:
    return any(keyword.casefold() in relevance for keyword in _RULE_KEYWORDS[field])


def _matching_quest_chains(quest_network: Any, relevance: str) -> list[dict[str, Any]]:
    if not isinstance(quest_network, dict):
        return []
    active_chains = quest_network.get("active_chains")
    if not isinstance(active_chains, list):
        return []

    chains = [chain for chain in active_chains if isinstance(chain, dict)]
    exact_name_matches = [
        (chain, name)
        for chain in chains
        if (name := _chain_name(chain)) and name in relevance
    ]
    if exact_name_matches:
        matching_names = {name for _, name in exact_name_matches}
        most_specific_names = {
            name
            for name in matching_names
            if not any(name != other and name in other for other in matching_names)
        }
        return [
            deepcopy(chain)
            for chain, name in exact_name_matches
            if name in most_specific_names
        ]

    return [
        deepcopy(chain)
        for chain in chains
        if _quest_chain_matches(chain, relevance)
    ]


def _quest_chain_matches(chain: dict[str, Any], relevance: str) -> bool:
    if any(identifier in relevance for identifier in _quest_identifiers(chain)):
        return True

    relevance_bigrams = _cjk_bigrams(_remove_generic_quest_terms(relevance))
    chain_text = " ".join(_text_values(chain)).casefold()
    chain_bigrams = _cjk_bigrams(_remove_generic_quest_terms(chain_text))
    return len(relevance_bigrams & chain_bigrams) >= 2


def _quest_identifiers(chain: dict[str, Any]) -> set[str]:
    identifiers: set[str] = set()

    npc_links = chain.get("npc_links")
    if isinstance(npc_links, (list, tuple)):
        for link in npc_links:
            if isinstance(link, str):
                values = [link]
            elif isinstance(link, dict):
                values = _name_like_values(link)
            else:
                continue
            npc_identifiers = _cjk_identifiers(values) - _GENERIC_NPC_SHORT_NAMES
            identifiers.update(npc_identifiers)
            identifiers.update(
                identifier[-2:]
                for identifier in npc_identifiers
                if len(identifier) > 2
                and identifier[-2:] not in _GENERIC_NPC_SHORT_NAMES
            )

    stages = chain.get("stages")
    if isinstance(stages, (list, tuple)):
        for stage in stages:
            if isinstance(stage, dict):
                identifiers.update(_cjk_identifiers(_name_like_values(stage)))

    return identifiers


def _chain_name(chain: dict[str, Any]) -> str:
    name = chain.get("name")
    return name.strip().casefold() if isinstance(name, str) else ""


def _cjk_identifiers(values: list[str]) -> set[str]:
    return {
        sequence
        for value in values
        for sequence in _CJK_SEQUENCE.findall(value)
        if len(sequence) >= 2 and sequence not in _GENERIC_QUEST_TERMS
    }


def _name_like_values(value: dict[Any, Any]) -> list[str]:
    return [
        text
        for key, item in value.items()
        if isinstance(key, str)
        and (key.casefold() == "npc" or key.casefold().endswith("name"))
        for text in _text_values(item)
    ]


def _remove_generic_quest_terms(text: str) -> str:
    cleaned = text
    for term in _GENERIC_QUEST_TERMS:
        cleaned = cleaned.replace(term, " ")
    return cleaned


def _cjk_bigrams(text: str) -> set[str]:
    return {
        sequence[index : index + 2]
        for sequence in _CJK_SEQUENCE.findall(text)
        for index in range(len(sequence) - 1)
    }


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _text_values(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _text_values(item)]
    return []
