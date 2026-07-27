from __future__ import annotations

import json
import re
import threading
from collections.abc import ItemsView, Iterator, KeysView, Mapping, ValuesView
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from packages.story_core.novel_type_ids import (
    DEFAULT_NOVEL_TYPE_ID,
    EXPLICIT_NON_GAME_TYPE_ALIASES,
    EXPLICIT_NON_GAME_TYPE_IDS,
    NOVEL_TYPE_ID_ALIASES,
    canonical_novel_type_id,
    is_legacy_game_type_alias,
)
from packages.story_core.power_system_templates import compact_power_system_template
from packages.story_core.trope_runtime import (
    compact_trope_candidates,
    merge_trope_templates,
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


_SNAPSHOT_LOCK = threading.Lock()
_SNAPSHOT_TOKEN: tuple[Any, ...] | None = None
_RECORD_SNAPSHOT: dict[str, Any] = {}
_CATALOG_SNAPSHOT: dict[str, NovelType] = {}
_CONVERSION_KEYS = threading.local()


def _current_snapshot_token() -> tuple[Any, ...]:
    from packages.story_core.novel_type_library import (
        list_novel_types,
        novel_type_library_snapshot_token,
    )

    return (*novel_type_library_snapshot_token(), id(list_novel_types))


def _refresh_snapshot() -> tuple[
    dict[str, Any],
    dict[str, NovelType],
    tuple[Any, ...] | None,
]:
    from packages.story_core.novel_type_library import list_novel_types

    global _SNAPSHOT_TOKEN, _RECORD_SNAPSHOT, _CATALOG_SNAPSHOT
    with _SNAPSHOT_LOCK:
        for _ in range(3):
            token = _current_snapshot_token()
            if token == _SNAPSHOT_TOKEN:
                return _RECORD_SNAPSHOT, _CATALOG_SNAPSHOT, token
            records = list_novel_types()
            final_token = _current_snapshot_token()
            if final_token == token:
                _RECORD_SNAPSHOT = {record.id: record for record in records}
                _CATALOG_SNAPSHOT = {
                    record.id: _catalog_item(record) for record in records
                }
                _SNAPSHOT_TOKEN = token
                return _RECORD_SNAPSHOT, _CATALOG_SNAPSHOT, token

        record_snapshot = {record.id: record for record in records}
        catalog_snapshot = {
            record.id: _catalog_item(record) for record in records
        }
        return record_snapshot, catalog_snapshot, None


def _record_snapshot() -> dict[str, Any]:
    return _refresh_snapshot()[0]


def _catalog_snapshot() -> dict[str, NovelType]:
    return _refresh_snapshot()[1]


def _catalog_snapshot_with_token() -> tuple[
    dict[str, NovelType],
    tuple[Any, ...] | None,
]:
    _, snapshot, token = _refresh_snapshot()
    return snapshot, token


def _fresh_key(key: str) -> str:
    return bytes(key, "utf-8").decode("utf-8")


@dataclass
class _ConversionPin:
    snapshot: dict[str, NovelType]
    token: tuple[Any, ...]
    keys: dict[int, str]
    expected_key_ids: list[int]
    remaining_key_count: int
    next_key_index: int


def _replace_conversion_context() -> int:
    generation = getattr(_CONVERSION_KEYS, "generation", 0) + 1
    _CONVERSION_KEYS.generation = generation
    _CONVERSION_KEYS.pin = None
    return generation


def _writer_revision(token: tuple[Any, ...], thread_id: int) -> int:
    return dict(token[2]).get(thread_id, 0)


def _pin_allows_current_token(
    pin: _ConversionPin,
    current_token: tuple[Any, ...],
) -> bool:
    if current_token == pin.token:
        return True
    if current_token[-1] != pin.token[-1]:
        return False
    current_thread_id = threading.get_ident()
    if _writer_revision(current_token, current_thread_id) != _writer_revision(
        pin.token, current_thread_id
    ):
        return False
    return current_token[0] > pin.token[0]


def _conversion_snapshot_for_key(key: str) -> dict[str, NovelType] | None:
    pin = getattr(_CONVERSION_KEYS, "pin", None)
    if pin is None:
        return None
    entry = pin.keys.get(id(key))
    if entry is None or entry is not key:
        _CONVERSION_KEYS.pin = None
        return None
    if (
        pin.next_key_index >= len(pin.expected_key_ids)
        or pin.expected_key_ids[pin.next_key_index] != id(key)
    ):
        _CONVERSION_KEYS.pin = None
        return None
    if not _pin_allows_current_token(pin, _current_snapshot_token()):
        _CONVERSION_KEYS.pin = None
        return None

    pin.next_key_index += 1
    pin.remaining_key_count -= 1
    snapshot = pin.snapshot
    if pin.remaining_key_count == 0:
        _CONVERSION_KEYS.pin = None
    return snapshot


class _CatalogKeysView(KeysView[str]):
    def __init__(
        self,
        mapping: Mapping[str, NovelType],
        snapshot: dict[str, NovelType],
        token: tuple[Any, ...] | None,
        generation: int,
    ) -> None:
        super().__init__(mapping)
        self._snapshot = snapshot
        self._token = token
        self._generation = generation

    def __iter__(self) -> Iterator[str]:
        conversion_keys = [_fresh_key(key) for key in self._snapshot]
        if (
            self._token is not None
            and getattr(_CONVERSION_KEYS, "generation", 0) == self._generation
        ):
            _CONVERSION_KEYS.pin = _ConversionPin(
                snapshot=self._snapshot,
                token=self._token,
                keys={id(key): key for key in conversion_keys},
                expected_key_ids=[id(key) for key in conversion_keys],
                remaining_key_count=len(conversion_keys),
                next_key_index=0,
            )
        yield from conversion_keys



class _RuntimeNovelTypeCatalog(Mapping[str, NovelType]):
    def __getitem__(self, key: str) -> NovelType:
        snapshot = _conversion_snapshot_for_key(key) or _catalog_snapshot()
        item = snapshot.get(str(key))
        if item is None:
            _CONVERSION_KEYS.pin = None
            raise KeyError(key)
        return item

    def __iter__(self) -> Iterator[str]:
        _replace_conversion_context()
        return iter(_catalog_snapshot())

    def __len__(self) -> int:
        return len(_catalog_snapshot())

    def items(self) -> ItemsView[str, NovelType]:
        _replace_conversion_context()
        return _catalog_snapshot().items()

    def values(self) -> ValuesView[NovelType]:
        _replace_conversion_context()
        return _catalog_snapshot().values()

    def keys(self) -> KeysView[str]:
        generation = _replace_conversion_context()
        snapshot, token = _catalog_snapshot_with_token()
        return _CatalogKeysView(snapshot, snapshot, token, generation)

    def copy(self) -> dict[str, NovelType]:
        _replace_conversion_context()
        return dict(_catalog_snapshot())


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
    plugin_id = resolve_novel_type_id(value)
    if plugin_id:
        return plugin_id
    if is_legacy_game_type_alias(value):
        return "game_webnovel"
    genre = str(value or "").strip()
    if genre.endswith("文"):
        return resolve_novel_type_id(genre[:-1])
    return ""


def is_game_story_type(story: Any) -> bool:
    if isinstance(story, Mapping):
        genre_plugin_ids = story.get("genre_plugin_ids")
        genre = story.get("genre")
    else:
        genre_plugin_ids = getattr(story, "genre_plugin_ids", [])
        genre = getattr(story, "genre", "")
    explicit_ids = normalize_novel_type_ids(genre_plugin_ids)
    if explicit_ids:
        return "game_webnovel" in explicit_ids
    return normalize_novel_type_id(genre) == "game_webnovel"


def runtime_novel_type(value: Any) -> Any:
    plugin_id = canonical_novel_type_id(value)
    if not plugin_id:
        return None

    records = _record_snapshot()
    record = records.get(plugin_id)
    if record is not None:
        return deepcopy(record)

    requested_name = str(value or "").strip().casefold()
    matches = [
        item for item in records.values() if item.name.strip().casefold() == requested_name
    ]
    return deepcopy(matches[0]) if len(matches) == 1 else None


def resolve_novel_type_id(value: Any) -> str:
    record = runtime_novel_type(value)
    return record.id if record is not None else ""


def novel_type_id_from_metadata_fact(value: Any) -> str:
    text = str(value or "").lstrip()
    match = re.match(r"^小说类型[：:](.*)$", text)
    if match is None:
        return ""
    return resolve_novel_type_id(match.group(1).strip())


def _printable_text(value: Any, limit: int) -> str:
    return "".join(
        character for character in str(value or "") if character.isprintable()
    )[:limit]


def _emergency_compact_prompt_context(context: dict[str, Any]) -> None:
    power_template = compact_power_system_template(
        context["genre_power_system_template"]
    )
    required_sections = power_template.get("required_sections", [])
    fixed_milestones = power_template.get("fixed_milestones", [])
    minimum_path_count = power_template.get("minimum_path_count")

    context["genre_label"] = _printable_text(context.get("genre_label"), 80)
    context["genre_description"] = _printable_text(
        context.get("genre_description"), 240
    )
    context["genre_core_promises"] = []
    context["genre_rulebook"] = {
        _printable_text(field, 40): []
        for field in list(context.get("genre_rulebook", {}))[:12]
    }
    context["genre_quality_checks"] = []
    context["genre_trope_templates"] = []
    context["genre_power_system_template"] = {
        "system_form": _printable_text(power_template.get("system_form"), 80),
        "required_sections": [
            _printable_text(item, 48) for item in list(required_sections)[:8]
        ],
        "minimum_path_count": (
            minimum_path_count
            if minimum_path_count is None
            or isinstance(minimum_path_count, (bool, int, float))
            else _printable_text(minimum_path_count, 32)
        ),
        "fixed_milestones": [
            item
            if item is None or isinstance(item, (bool, int, float))
            else _printable_text(item, 24)
            for item in list(fixed_milestones)[:8]
        ],
    }


def _minimal_prompt_context() -> dict[str, Any]:
    return {
        "genre_label": "",
        "genre_description": "",
        "genre_core_promises": [],
        "genre_rulebook": {},
        "genre_quality_checks": [],
        "genre_trope_templates": [],
        "genre_power_system_template": {
            "system_form": "",
            "required_sections": [],
            "minimum_path_count": 2,
            "fixed_milestones": [],
        },
    }


def _prompt_context_exceeds_cap(context: Mapping[str, Any]) -> bool:
    try:
        serialized = json.dumps(context, ensure_ascii=False, allow_nan=False)
    except (OverflowError, TypeError, ValueError):
        return True
    return len(serialized) > 6000


def novel_type_prompt_context(record: Any) -> dict[str, Any]:
    from packages.story_core.agent_base import compact_list, compact_text

    specific_trope_templates = list(getattr(record, "trope_templates", ()) or ())
    generic_record = None
    if str(getattr(record, "id", "") or "").strip() != DEFAULT_NOVEL_TYPE_ID:
        generic_record = runtime_novel_type(DEFAULT_NOVEL_TYPE_ID)
    generic_trope_templates = (
        list(getattr(generic_record, "trope_templates", ()) or [])
        if generic_record is not None
        else []
    )
    merged_trope_templates = compact_trope_candidates(
        merge_trope_templates([specific_trope_templates, generic_trope_templates])
    )
    specific_candidate_count = len(compact_trope_candidates(specific_trope_templates))
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
        "genre_trope_templates": deepcopy(merged_trope_templates),
        "genre_power_system_template": compact_power_system_template(
            getattr(record, "power_system_template", {}) or {}
        ),
    }
    power_template = context["genre_power_system_template"]
    lists = [
        items
        for items in (
            context["genre_core_promises"],
            *context["genre_rulebook"].values(),
            context["genre_quality_checks"],
            power_template.get("quality_checks", []),
        )
        if isinstance(items, list)
    ]
    while _prompt_context_exceeds_cap(context):
        trope_candidates = context["genre_trope_templates"]
        if len(trope_candidates) > specific_candidate_count:
            trope_candidates.pop()
            continue
        base_lists = [items for items in lists if isinstance(items, list) and items]
        if base_lists:
            max(base_lists, key=lambda items: len(items[-1])).pop()
            continue
        if trope_candidates:
            trope_candidates.pop()
            specific_candidate_count = min(specific_candidate_count, len(trope_candidates))
            continue
        optional_power_fields = [
            field
            for field in power_template
            if field
            not in {
                "system_form",
                "required_sections",
                "minimum_path_count",
                "fixed_milestones",
            }
        ]
        if optional_power_fields:
            power_template.pop(optional_power_fields[-1])
            continue
        _emergency_compact_prompt_context(context)
        break
    if _prompt_context_exceeds_cap(context):
        context.clear()
        context.update(_minimal_prompt_context())
    return deepcopy(context)


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
