"""Normalize inventory item names captured from prose-shaped legacy data."""

from __future__ import annotations

import re
from typing import Any


def normalize_inventory_item_name(value: Any) -> str:
    item = str(value or "").strip()
    item = item.replace("【", "").replace("】", "")
    item = item.strip(" \t:：;；,，、")
    item = re.sub(r"^背包\s*", "", item)
    item = re.sub(r"^(?:里|中)\s*", "", item)
    item = re.sub(
        r"^(?:(?:静静|安静|整齐)(?:地)?\s*)?"
        r"(?:堆叠着|堆放着|放着|装着|还剩|只剩|剩下|有)\s*",
        "",
        item,
    )
    item = re.sub(r"^(?:和|及|以及|与)\s*", "", item)
    return item.strip(" \t:：;；,，、")


def normalize_inventory_mapping(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    normalized: dict[str, Any] = {}
    for raw_name, count in value.items():
        name = normalize_inventory_item_name(raw_name)
        if not name:
            continue
        if (
            name in normalized
            and isinstance(normalized[name], (int, float))
            and isinstance(count, (int, float))
        ):
            normalized[name] += count
        else:
            normalized[name] = count
    return normalized


def normalize_inventory_tree(value: Any) -> Any:
    """Return a normalized copy of every ``inventory`` mapping in a payload."""
    if isinstance(value, list):
        return [normalize_inventory_tree(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized: dict[Any, Any] = {}
    for key, item in value.items():
        if str(key) == "inventory" and isinstance(item, dict):
            normalized[key] = normalize_inventory_mapping(item)
        else:
            normalized[key] = normalize_inventory_tree(item)
    return normalized


__all__ = [
    "normalize_inventory_item_name",
    "normalize_inventory_mapping",
    "normalize_inventory_tree",
]
