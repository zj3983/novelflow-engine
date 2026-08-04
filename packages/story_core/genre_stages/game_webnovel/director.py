from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from collections.abc import Mapping
from typing import Any

from packages.story_core.attribute_allocation import (
    attribute_allocation_context,
    attribute_allocation_rule_from_story,
    director_attribute_allocation_contract,
)
from packages.story_core.genre_stages.base import review_placeholder_actor_names
from packages.story_core.prompt_templates import (
    get_effective_prompt_template,
    render_prompt_template,
)
from packages.story_core.web_game_economy import normalize_legacy_economy_prompt_value
from packages.story_core.web_game_economy import first_chapter_market_exchange_authorized


DIRECTOR_TEMPLATE_KEY = "director"
_MAX_COMPACT_DEPTH = 5
_MAX_COMPACT_MAPPING_ITEMS = 12
_MAX_COMPACT_LIST_ITEMS = 8
_MAX_COMPACT_STRING_CHARS = 180
_MAX_COMPACT_NODES = 256


def game_chapter_phase(chapter_number: int) -> str:
    if chapter_number == 1:
        return "黄金三章第1章：立世界、立主角、立核心能力、完成第一次有效验证"
    if chapter_number == 2:
        return "黄金三章第2章：把本书核心优势转成任务、装备、关系或路线上的具体领先"
    if chapter_number == 3:
        return "黄金三章第3章：第一个小高潮、明确敌对压力、确立长期成长路线"
    return "常规连载章节：目标、行动、收益、压力、钩子循环"


def review_game_director_plan(*, context: Any) -> list[str]:
    story = context.story
    issues: list[str] = review_placeholder_actor_names(context.moves)
    lead = next(
        (character for character in story.characters if character.role in {"主角", "protagonist"}),
        None,
    )
    if lead and lead.game_id:
        for move in context.moves:
            name = str(move.get("name") or "").strip()
            action_text = " ".join(str(move.get(key) or "") for key in ("goal", "action"))
            if name != lead.name and lead.name not in action_text:
                continue
            if not any(
                marker in action_text
                for marker in (
                    "现实",
                    "下线",
                    "退出游戏",
                    "登录",
                    "头盔",
                    "接驳",
                    "创建角色",
                    "手机",
                    "银行卡",
                    "房租",
                    "官方兑换",
                    "提现",
                )
            ):
                issues.append(f"游戏内行动使用了现实姓名“{lead.name}”，应使用游戏ID“{lead.game_id}”。")
                break

    for move in context.moves:
        name = str(move.get("name") or "").strip()
        if name.endswith(("玩家甲", "商人玩家")):
            issues.append(f"角色“{name}”是岗位或占位称呼；删除该角色，或先使用已有具名角色卡。")
            break

    plan = context.plan if isinstance(context.plan, dict) else {}
    known_text = "\n".join(
        [
            story.outline,
            *story.world_facts,
            *story.author_constraints,
            *(story.chapter_summaries[-1].facts if story.chapter_summaries else []),
            json.dumps(story.progression_ledger, ensure_ascii=False),
            json.dumps(story.outline_context, ensure_ascii=False),
        ]
    )
    plan_text = json.dumps(plan, ensure_ascii=False)
    material_pattern = re.compile(r"[\u4e00-\u9fff]{1,8}(?:毒腺|狼皮|鼠皮|兽皮|矿石|草药)")

    def material_keys(value: object) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            for key, item in value.items():
                if material_pattern.fullmatch(str(key)):
                    found.add(str(key))
                found.update(material_keys(item))
        elif isinstance(value, list):
            for item in value:
                found.update(material_keys(item))
        return found

    known_materials = material_keys(story.progression_ledger)
    if not known_materials:
        known_materials = set(material_pattern.findall(known_text))
    for known in sorted(known_materials):
        suffix = next(
            (item for item in ("毒腺", "狼皮", "鼠皮", "兽皮", "矿石", "草药") if known.endswith(item)),
            "",
        )
        known_prefix = known[: -len(suffix)] if suffix else ""
        if not known_prefix:
            continue
        candidate_pattern = re.compile(rf"[\u4e00-\u9fff]{{{len(known_prefix)}}}{re.escape(suffix)}")
        for candidate in sorted(set(candidate_pattern.findall(plan_text))):
            candidate_prefix = candidate[: -len(suffix)]
            if candidate != known and candidate_prefix[:1] == known_prefix[:1]:
                issues.append(f"材料“{candidate}”与既有材料冲突；既有名称是“{known}”。")

    economy = story.progression_ledger.get("economy") if isinstance(story.progression_ledger, dict) else {}
    inventory = economy.get("inventory") if isinstance(economy, dict) and isinstance(economy.get("inventory"), dict) else {}
    collection_markers = ("补足", "补齐", "继续收集", "继续刷", "再刷", "刷取")
    negated_markers = ("不用收集", "无需收集", "不再收集", "不用再刷", "无需再刷")
    move_texts = [" ".join(str(move.get(key) or "") for key in ("goal", "action")) for move in context.moves]
    for material, raw_count in inventory.items():
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            continue
        name = str(material).strip()
        if not name:
            continue
        requirement_matches: list[int] = []
        for pattern in (
            rf"(?:需要|要求|提交|收集)[^。；\n]{{0,16}}{re.escape(name)}\s*[×xX*]?\s*(\d+)",
            rf"{re.escape(name)}\s*[×xX*]\s*(\d+)",
        ):
            requirement_matches.extend(int(value) for value in re.findall(pattern, known_text))
        if not requirement_matches:
            continue
        required = min(requirement_matches)
        if count < required:
            continue
        suffix = next(
            (item for item in ("毒腺", "狼皮", "鼠皮", "兽皮", "矿石", "草药") if name.endswith(item)),
            name,
        )
        for action_text in move_texts:
            if any(marker in action_text for marker in negated_markers):
                continue
            if (name in action_text or suffix in action_text) and any(marker in action_text for marker in collection_markers):
                issues.append(
                    f"背包已有{count}份{name}，已满足已知需求{required}份，不应重复收集；应先处理接取、提交或其他明确前置。"
                )
                break
    return list(dict.fromkeys(issues))


def prepare_game_scene_cards(*, context: Any) -> list[dict[str, Any]]:
    trade_authorized = first_chapter_market_exchange_authorized(
        world_facts=context.world_facts
    )
    return _compact_first_chapter_scene_cards(
        context.scene_cards,
        chapter_number=context.chapter_number,
        trade_authorized=trade_authorized,
    )


def _compact_first_chapter_scene_cards(
    scene_cards: list[dict[str, Any]],
    *,
    chapter_number: int,
    trade_authorized: bool,
) -> list[dict[str, Any]]:
    if chapter_number != 1:
        return scene_cards

    cards = deepcopy(scene_cards)
    for card in cards:
        must_show = card.get("must_show")
        if isinstance(must_show, list):
            card["must_show"] = [item for item in must_show if "变体boundary-" not in str(item)]
        if "变体boundary-" in str(card.get("ending_pressure") or ""):
            card.pop("ending_pressure", None)
        state_delta = card.get("state_delta")
        if isinstance(state_delta, dict):
            simulation = state_delta.get("simulation")
            if isinstance(simulation, dict) and str(simulation.get("variant") or "").startswith("boundary-"):
                state_delta.pop("simulation", None)

    if not trade_authorized:
        return [card for card in cards if card.get("scene_id") != "s0-plot-simulation"]

    core_ids = {
        "s2-c1-reality-entry",
        "s3-c1-character-create",
        "s4-c1-small-verify",
        "s6-c1-next-step-hook",
    }
    return [card for card in cards if card.get("scene_id") in core_ids]
_MAX_GAME_ADDITIONS_CHARS = 12000
_BUDGET_EXHAUSTED = object()


def _active_character_names(story: Any) -> list[str]:
    characters = story.get("characters", []) if isinstance(story, Mapping) else getattr(story, "characters", [])
    names: list[str] = []
    for character in characters or []:
        if isinstance(character, Mapping):
            name = str(character.get("name") or "").strip()
            lifecycle_state = str(character.get("lifecycle_state") or "active")
            frozen = bool(character.get("frozen"))
        else:
            name = str(getattr(character, "name", "") or "").strip()
            lifecycle_state = str(getattr(character, "lifecycle_state", "active") or "active")
            frozen = bool(getattr(character, "frozen", False))
        if name and lifecycle_state == "active" and not frozen:
            names.append(name)
    return names


def _compact_game_node(value: Any, *, depth: int, remaining_nodes: list[int]) -> Any:
    if remaining_nodes[0] <= 0:
        return _BUDGET_EXHAUSTED
    remaining_nodes[0] -= 1
    if isinstance(value, str):
        return value[:_MAX_COMPACT_STRING_CHARS]
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if depth >= _MAX_COMPACT_DEPTH:
        if isinstance(value, Mapping):
            return {}
        if isinstance(value, (list, tuple)):
            return []
        return None
    if isinstance(value, list):
        compacted_list: list[Any] = []
        for item in value[:_MAX_COMPACT_LIST_ITEMS]:
            compacted = _compact_game_node(
                item,
                depth=depth + 1,
                remaining_nodes=remaining_nodes,
            )
            if compacted is _BUDGET_EXHAUSTED:
                break
            compacted_list.append(compacted)
        return compacted_list
    if isinstance(value, tuple):
        compacted_tuple: list[Any] = []
        for item in value[:_MAX_COMPACT_LIST_ITEMS]:
            compacted = _compact_game_node(
                item,
                depth=depth + 1,
                remaining_nodes=remaining_nodes,
            )
            if compacted is _BUDGET_EXHAUSTED:
                break
            compacted_tuple.append(compacted)
        return compacted_tuple
    if isinstance(value, Mapping):
        compacted: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_COMPACT_MAPPING_ITEMS:
                break
            if not isinstance(key, (str, int, float, bool)) and key is not None:
                continue
            compacted_item = _compact_game_node(
                item,
                depth=depth + 1,
                remaining_nodes=remaining_nodes,
            )
            if compacted_item is _BUDGET_EXHAUSTED:
                break
            compacted[str(key)] = compacted_item
        return compacted
    return None


def _compact_game_value(value: Any, *, depth: int = 0) -> Any:
    compacted = _compact_game_node(
        value,
        depth=depth,
        remaining_nodes=[_MAX_COMPACT_NODES],
    )
    return None if compacted is _BUDGET_EXHAUSTED else compacted


def _bounded_game_additions(value: Any) -> dict[str, Any]:
    for node_limit in range(_MAX_COMPACT_NODES, 0, -1):
        compacted = _compact_game_node(
            value,
            depth=0,
            remaining_nodes=[node_limit],
        )
        if not isinstance(compacted, dict):
            continue
        serialized = json.dumps(compacted, ensure_ascii=False, separators=(",", ":"))
        if len(serialized) <= _MAX_GAME_ADDITIONS_CHARS:
            return compacted
    return {}


def _game_ledger(raw_snapshot: Any) -> dict[str, Any]:
    raw_snapshot = raw_snapshot if isinstance(raw_snapshot, Mapping) else {}
    source = raw_snapshot.get("progression_ledger")
    if not isinstance(source, Mapping):
        source = raw_snapshot.get("ledger") if isinstance(raw_snapshot.get("ledger"), Mapping) else {}
    protagonist = source.get("protagonist") if isinstance(source.get("protagonist"), Mapping) else {}
    economy = source.get("economy") if isinstance(source.get("economy"), Mapping) else {}
    quests = source.get("quests") if isinstance(source.get("quests"), Mapping) else {}
    compacted = {
        "protagonist": {
            key: _compact_game_value(protagonist.get(key))
            for key in (
                "game_id",
                "level",
                "class_path",
                "exp",
                "hp",
                "mp",
                "weapon_durability",
                "attributes",
                "unallocated_attribute_points",
            )
            if protagonist.get(key) not in (None, "", [], {})
        },
        "economy": {
            key: _compact_game_value(economy.get(key))
            for key in ("game_currency", "inventory", "backpack", "real_balance")
            if economy.get(key) not in (None, "", [], {})
        },
        "quests": {
            str(key): _compact_game_value(value)
            for key, value in list(quests.items())[:6]
            if value not in (None, "", [], {})
        },
    }
    return {key: value for key, value in compacted.items() if value}


def _game_characters(raw_snapshot: Any) -> list[dict[str, Any]]:
    raw_snapshot = raw_snapshot if isinstance(raw_snapshot, Mapping) else {}
    characters = raw_snapshot.get("characters") if isinstance(raw_snapshot.get("characters"), list) else []
    compacted: list[dict[str, Any]] = []
    for character in characters[:4]:
        if not isinstance(character, Mapping):
            continue
        item = {
            key: _compact_game_value(character.get(key))
            for key in ("name", "game_id", "game_panel")
            if character.get(key) not in (None, "", [], {})
        }
        if item:
            compacted.append(item)
    return compacted


def _game_outline_context(raw_outline_context: Any) -> dict[str, Any]:
    raw_outline_context = raw_outline_context if isinstance(raw_outline_context, Mapping) else {}
    raw_arc = raw_outline_context.get("active_arc")
    if not isinstance(raw_arc, Mapping):
        return {}
    game_payoffs = {
        key: _compact_game_value(raw_arc.get(key))
        for key in ("game_line_payoff", "reality_line_payoff")
        if raw_arc.get(key) not in (None, "", [], {})
    }
    if not game_payoffs:
        return {}
    return {"active_arc": game_payoffs}


def _game_project_snapshot(
    snapshot_json: str,
    additions: Any,
) -> str:
    try:
        snapshot = json.loads(snapshot_json)
    except (TypeError, json.JSONDecodeError):
        return snapshot_json
    if not isinstance(snapshot, dict):
        return snapshot_json
    additions = additions if isinstance(additions, Mapping) else {}
    for key in ("ledger", "game_characters", "attribute_allocation"):
        if additions.get(key) not in (None, "", [], {}):
            snapshot[key] = additions[key]
    outline_additions = additions.get("outline_context")
    if isinstance(outline_additions, Mapping):
        outline_context = snapshot.get("outline_context")
        if not isinstance(outline_context, dict):
            outline_context = {}
            snapshot["outline_context"] = outline_context
        active_arc_additions = outline_additions.get("active_arc")
        if isinstance(active_arc_additions, Mapping):
            active_arc = outline_context.get("active_arc")
            if not isinstance(active_arc, dict):
                active_arc = {}
                outline_context["active_arc"] = active_arc
            active_arc.update(active_arc_additions)
    return json.dumps(snapshot, ensure_ascii=False)


def _game_character_card_ids(raw_character_cards: Any) -> dict[str, Any]:
    raw_context = raw_character_cards if isinstance(raw_character_cards, Mapping) else {}
    raw_cards = raw_context.get("cards") if isinstance(raw_context.get("cards"), list) else []
    result: dict[str, Any] = {}
    for raw_card in raw_cards[:4]:
        if not isinstance(raw_card, Mapping):
            continue
        identity = raw_card.get("identity") if isinstance(raw_card.get("identity"), Mapping) else {}
        name = str(identity.get("name") or "").strip()
        game_id = identity.get("game_id")
        if name and game_id not in (None, ""):
            result[name] = _compact_game_value(game_id)
    return result


def _game_character_cards(character_cards_json: str, game_ids: Any) -> str:
    try:
        character_cards = json.loads(character_cards_json)
    except (TypeError, json.JSONDecodeError):
        return character_cards_json
    if not isinstance(character_cards, dict):
        return character_cards_json
    compact_cards = character_cards.get("cards") if isinstance(character_cards.get("cards"), list) else []
    game_ids = game_ids if isinstance(game_ids, Mapping) else {}
    for card in compact_cards:
        if not isinstance(card, dict):
            continue
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        game_id = game_ids.get(str(identity.get("name") or "").strip())
        if game_id not in (None, ""):
            identity["game_id"] = game_id
    return json.dumps(character_cards, ensure_ascii=False)


def render_game_director_prompt(
    *,
    story: Any,
    chapter_number: int = 0,
    plan: Any = None,
    values: Mapping[str, Any] | None = None,
) -> str:
    raw_project_snapshot = values.get("raw_project_snapshot")
    allocation = attribute_allocation_context(story)
    game_additions = _bounded_game_additions(
        {
            "project_snapshot": {
                "ledger": _game_ledger(raw_project_snapshot),
                "game_characters": _game_characters(raw_project_snapshot),
                "outline_context": _game_outline_context(values.get("raw_outline_context")),
                "attribute_allocation": allocation,
            },
            "character_cards": {
                "game_ids": _game_character_card_ids(values.get("raw_character_cards")),
            },
        }
    )
    project_additions = game_additions.get("project_snapshot")
    character_card_additions = game_additions.get("character_cards")
    game_ids = (
        character_card_additions.get("game_ids")
        if isinstance(character_card_additions, Mapping)
        else {}
    )
    prompt_values = {
        "chapter_number": str(chapter_number),
        "chapter_phase": game_chapter_phase(chapter_number),
        "project_snapshot": _game_project_snapshot(
            values["project_snapshot"],
            project_additions,
        ),
        "chapter_seed": values["chapter_seed"],
        "character_cards": _game_character_cards(
            values["character_cards"],
            game_ids,
        ),
        "active_characters": ", ".join(_active_character_names(story)),
    }
    rendered = render_prompt_template(
        get_effective_prompt_template(DIRECTOR_TEMPLATE_KEY),
        prompt_values,
    )
    if attribute_allocation_rule_from_story(story):
        rendered += "\n" + director_attribute_allocation_contract()
    return normalize_legacy_economy_prompt_value(
        rendered,
        game_context=True,
        chapter_number=chapter_number,
    )
