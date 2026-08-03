from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import re
from typing import Any, Iterable, Mapping, Sequence


_MAX_TEXT = 500
_MAX_LORE = 2_000
_MAX_LIST = 48
_ALLOWED_LORE_STATUS = {"confirmed", "rumor", "unknown"}
_MUTABLE_FIELDS = {
    "current_owner",
    "current_location",
    "durability",
    "status",
}
_LIST_FIELDS = {
    "aliases",
    "class_restrictions",
    "special_effects",
    "skills",
    "related_characters",
    "related_factions",
}
_EQUIPMENT_TYPE_MARKERS = (
    "weapon",
    "armor",
    "accessory",
    "equipment",
    "武器",
    "防具",
    "护甲",
    "饰品",
    "装备",
)
_REJECTED_TYPE_MARKERS = (
    "material",
    "currency",
    "consumable",
    "quest item",
    "材料",
    "货币",
    "消耗品",
    "任务物品",
)


@dataclass(frozen=True)
class EquipmentMergeResult:
    cards: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    conflicts: list[dict[str, Any]]


def _text(value: Any, *, limit: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:limit]


def _text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = list(value[:_MAX_LIST])
    else:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        compact = _text(item)
        marker = compact.casefold()
        if compact and marker not in seen:
            seen.add(marker)
            result.append(compact)
    return result


def _chapter(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return min(max(value, 1), 1_000_000)


def _stable_id(name: str) -> str:
    digest = hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:16]
    return f"equipment-{digest}"


def _valid_equipment_type(value: str) -> bool:
    folded = value.casefold()
    if any(marker in folded for marker in _REJECTED_TYPE_MARKERS):
        return False
    return any(marker in folded for marker in _EQUIPMENT_TYPE_MARKERS)


def _attributes(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, raw in list(value.items())[:_MAX_LIST]:
        name = _text(str(key), limit=80)
        content = _text(str(raw))
        if name and content:
            result[name] = content
    return result


def _evidence(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: list[dict[str, Any]] = []
    for raw in list(value)[:_MAX_LIST]:
        if not isinstance(raw, Mapping):
            continue
        item: dict[str, Any] = {}
        chapter = _chapter(raw.get("chapter"))
        quote = _text(raw.get("quote"), limit=800)
        confidence = _text(raw.get("confidence"), limit=24).casefold()
        if chapter is not None:
            item["chapter"] = chapter
        if quote:
            item["quote"] = quote
        if confidence in _ALLOWED_LORE_STATUS:
            item["confidence"] = confidence
        if item:
            result.append(item)
    return result


def normalize_equipment_card(
    value: Any,
    *,
    chapter_number: int | None = None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    name = _text(value.get("name"), limit=120)
    equipment_type = _text(value.get("equipment_type"), limit=80)
    if not name or not equipment_type or not _valid_equipment_type(equipment_type):
        return {}

    result: dict[str, Any] = {
        "id": _text(value.get("id"), limit=120) or _stable_id(name),
        "name": name,
        "equipment_type": equipment_type,
    }
    for field in (
        "slot",
        "rarity",
        "required_level",
        "durability",
        "source",
        "current_owner",
        "current_location",
        "status",
        "description",
        "lore",
        "set_name",
        "set_lore",
    ):
        compact = _text(
            value.get(field),
            limit=_MAX_LORE if field in {"description", "lore", "set_lore"} else _MAX_TEXT,
        )
        if compact:
            result[field] = compact
    for field in _LIST_FIELDS:
        items = _text_list(value.get(field))
        if items:
            result[field] = items
    attributes = _attributes(value.get("base_attributes"))
    if attributes:
        result["base_attributes"] = attributes
    evidence = _evidence(value.get("evidence"))
    if evidence:
        result["evidence"] = evidence

    lore_status = _text(value.get("lore_status"), limit=24).casefold()
    if lore_status not in _ALLOWED_LORE_STATUS:
        lore_status = "unknown"
    result["lore_status"] = lore_status

    supplied_first = _chapter(value.get("first_appearance_chapter"))
    supplied_last = _chapter(value.get("last_update_chapter"))
    fallback_chapter = _chapter(chapter_number)
    first = supplied_first or fallback_chapter
    last = supplied_last or fallback_chapter or first
    if first is not None:
        result["first_appearance_chapter"] = first
    if last is not None:
        result["last_update_chapter"] = last
    return result


def normalize_equipment_cards(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result: list[dict[str, Any]] = []
    for raw in list(value)[:_MAX_LIST]:
        card = normalize_equipment_card(raw)
        if card:
            result.append(card)
    return result


def _aliases(card: Mapping[str, Any]) -> set[str]:
    return {
        item.casefold()
        for item in [str(card.get("name") or ""), *_text_list(card.get("aliases"))]
        if item.strip()
    }


def _has_confirmed_evidence(card: Mapping[str, Any]) -> bool:
    return any(
        isinstance(item, Mapping) and item.get("confidence") == "confirmed"
        for item in card.get("evidence", [])
        if isinstance(card.get("evidence"), list)
    )


def _merge_list(existing: Any, update: Any) -> list[Any]:
    result = deepcopy(existing) if isinstance(existing, list) else []
    for item in update if isinstance(update, list) else []:
        if item not in result:
            result.append(deepcopy(item))
    return result[:_MAX_LIST]


def _merge_card(existing: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(existing)
    for field, value in update.items():
        if value in (None, "", [], {}):
            continue
        if field in _MUTABLE_FIELDS:
            merged[field] = deepcopy(value)
        elif field in _LIST_FIELDS or field == "evidence":
            merged[field] = _merge_list(merged.get(field), value)
        elif field == "base_attributes":
            merged[field] = {**dict(merged.get(field) or {}), **dict(value)}
        elif field == "first_appearance_chapter":
            current = _chapter(merged.get(field))
            merged[field] = min(item for item in (current, value) if item is not None)
        elif field == "last_update_chapter":
            current = _chapter(merged.get(field))
            merged[field] = max(item for item in (current, value) if item is not None)
        elif field not in merged or merged[field] in (None, "", [], {}):
            merged[field] = deepcopy(value)

    if update.get("lore") and not existing.get("lore"):
        desired = str(update.get("lore_status") or "unknown")
        merged["lore_status"] = (
            "confirmed"
            if desired == "confirmed" and _has_confirmed_evidence(update)
            else "rumor" if desired == "confirmed" else desired
        )
    elif existing.get("lore_status") == "confirmed":
        merged["lore_status"] = "confirmed"
    return merged


def merge_equipment_cards(existing: Any, updates: Any) -> EquipmentMergeResult:
    cards = normalize_equipment_cards(existing)
    rejected: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for raw in updates if isinstance(updates, Sequence) and not isinstance(updates, (str, bytes, bytearray)) else []:
        update = normalize_equipment_card(raw)
        if not update:
            rejected.append(deepcopy(dict(raw)) if isinstance(raw, Mapping) else {"value": str(raw)})
            continue
        update_aliases = _aliases(update)
        match_index = next(
            (
                index
                for index, card in enumerate(cards)
                if card.get("id") == update.get("id") or bool(_aliases(card) & update_aliases)
            ),
            None,
        )
        if match_index is None:
            cards.append(update)
            continue
        current = cards[match_index]
        type_conflict = current.get("equipment_type") != update.get("equipment_type")
        slot_conflict = bool(current.get("slot") and update.get("slot") and current.get("slot") != update.get("slot"))
        if type_conflict or slot_conflict:
            candidate = deepcopy(update)
            candidate["id"] = f"{update['id']}-candidate-{len(conflicts) + 2}"
            candidate["status"] = "待确认：同名装备冲突"
            conflicts.append({"existing": deepcopy(current), "candidate": deepcopy(candidate)})
            cards.append(candidate)
            continue
        cards[match_index] = _merge_card(current, update)
    return EquipmentMergeResult(cards=cards, rejected=rejected, conflicts=conflicts)


def equipment_cards_for_context(
    cards: Any,
    *,
    names: Iterable[str] = (),
    owners: Iterable[str] = (),
    limit: int = 12,
) -> list[dict[str, Any]]:
    normalized = normalize_equipment_cards(cards)
    wanted_names = {str(item).strip().casefold() for item in names if str(item).strip()}
    wanted_owners = {str(item).strip().casefold() for item in owners if str(item).strip()}
    ranked = sorted(
        enumerate(normalized),
        key=lambda pair: (
            -int(bool(_aliases(pair[1]) & wanted_names)),
            -int(str(pair[1].get("current_owner") or "").casefold() in wanted_owners),
            pair[0],
        ),
    )
    bounded_limit = min(max(int(limit), 0), _MAX_LIST)
    return [deepcopy(card) for _, card in ranked[:bounded_limit]]
