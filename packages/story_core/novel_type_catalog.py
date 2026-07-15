from __future__ import annotations

import json
import re
from collections.abc import ItemsView, Iterator, KeysView, Mapping, ValuesView
from dataclasses import dataclass
from typing import Any

from packages.story_core.novel_type_ids import (
    DEFAULT_NOVEL_TYPE_ID,
    EXPLICIT_NON_GAME_TYPE_ALIASES,
    EXPLICIT_NON_GAME_TYPE_IDS,
    NOVEL_TYPE_ID_ALIASES,
    canonical_novel_type_id,
)


@dataclass(frozen=True)
class NovelType:
    plugin_id: str
    label: str
    description: str
    keywords: tuple[str, ...]


def _catalog_item(record: Any) -> NovelType:
    return NovelType(
        plugin_id=record.id,
        label=record.name,
        description=record.description,
        keywords=tuple(record.keywords),
    )


def _catalog_snapshot() -> dict[str, NovelType]:
    from packages.story_core.novel_type_library import list_novel_types

    return {record.id: _catalog_item(record) for record in list_novel_types()}


class _RuntimeNovelTypeCatalog(Mapping[str, NovelType]):
    def __getitem__(self, key: str) -> NovelType:
        record = runtime_novel_type(key)
        if record is None:
            raise KeyError(key)
        return _catalog_item(record)

    def __iter__(self) -> Iterator[str]:
        return iter(_catalog_snapshot())

    def __len__(self) -> int:
        return len(_catalog_snapshot())

    def items(self) -> ItemsView[str, NovelType]:
        return _catalog_snapshot().items()

    def values(self) -> ValuesView[NovelType]:
        return _catalog_snapshot().values()

    def keys(self) -> KeysView[str]:
        return _catalog_snapshot().keys()

    def copy(self) -> dict[str, NovelType]:
        return _catalog_snapshot()


NOVEL_TYPE_CATALOG: Mapping[str, NovelType] = _RuntimeNovelTypeCatalog()


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
    return resolve_novel_type_id(value)


def runtime_novel_type(value: Any) -> Any:
    plugin_id = canonical_novel_type_id(value)
    if not plugin_id:
        return None

    # Lazy import keeps the static catalog available as the library bootstrap.
    from packages.story_core.novel_type_library import list_novel_types

    records = list_novel_types()
    record = next((item for item in records if item.id == plugin_id), None)
    if record is not None:
        return record

    requested_name = str(value or "").strip().casefold()
    matches = [
        item for item in records if item.name.strip().casefold() == requested_name
    ]
    return matches[0] if len(matches) == 1 else None


def resolve_novel_type_id(value: Any) -> str:
    record = runtime_novel_type(value)
    return record.id if record is not None else ""


def novel_type_id_from_metadata_fact(value: Any) -> str:
    text = str(value or "").lstrip()
    match = re.match(r"^小说类型[：:](.*)$", text)
    if match is None:
        return ""
    return resolve_novel_type_id(match.group(1).strip())


def novel_type_prompt_context(record: Any) -> dict[str, Any]:
    from packages.story_core.agent_base import compact_list, compact_text

    context = {
        "genre_label": compact_text(str(record.name), 100),
        "genre_description": compact_text(str(record.description), 700),
        "genre_core_promises": compact_list(
            list(record.core_promises), max_items=8, item_chars=180
        ),
        "genre_rulebook": {
            field: compact_list(list(rules), max_items=6, item_chars=160)
            for field, rules in record.rulebook.items()
        },
        "genre_quality_checks": compact_list(
            list(record.quality_checks), max_items=10, item_chars=180
        ),
    }
    lists = [
        context["genre_core_promises"],
        *context["genre_rulebook"].values(),
        context["genre_quality_checks"],
    ]
    while len(json.dumps(context, ensure_ascii=False)) > 6000:
        candidates = [items for items in lists if len(items) > 1]
        if not candidates:
            break
        max(candidates, key=lambda items: len(items[-1])).pop()
    return context


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
