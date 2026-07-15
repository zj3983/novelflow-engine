from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
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


class _RuntimeNovelTypeCatalog(Mapping[str, NovelType]):
    def __getitem__(self, key: str) -> NovelType:
        record = runtime_novel_type(key)
        if record is None:
            raise KeyError(key)
        return _catalog_item(record)

    def __iter__(self) -> Iterator[str]:
        from packages.story_core.novel_type_library import list_novel_types

        return iter(record.id for record in list_novel_types())

    def __len__(self) -> int:
        from packages.story_core.novel_type_library import list_novel_types

        return len(list_novel_types())


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
