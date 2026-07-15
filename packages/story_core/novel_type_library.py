from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, fields
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from packages.story_core.genre_types import (
    GAME_WEBNOVEL,
    GENERIC_WEBNOVEL,
    ROMANCE,
    RULEBOOK_FIELDS,
    RULES_MYSTERY,
    SUSPENSE,
    URBAN,
    XIANXIA,
    XUANHUAN,
    GenrePlugin,
)
from packages.story_core.novel_type_catalog import NOVEL_TYPE_CATALOG


_BUILTIN_PLUGINS = (
    GENERIC_WEBNOVEL,
    GAME_WEBNOVEL,
    XUANHUAN,
    XIANXIA,
    URBAN,
    ROMANCE,
    SUSPENSE,
    RULES_MYSTERY,
)
_EDITABLE_FIELDS = tuple(
    item.name for item in fields(GenrePlugin) if item.name not in {"plugin_id"}
)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values = (value,)
    else:
        values = value
    return tuple(str(item) for item in values if str(item).strip())


def _normalized_rulebook(value: Any) -> dict[str, tuple[str, ...]]:
    source = value if isinstance(value, Mapping) else {}
    return {field_name: _string_tuple(source.get(field_name)) for field_name in RULEBOOK_FIELDS}


def _trope_templates(value: Any) -> tuple[dict[str, object], ...]:
    if not value:
        return ()
    if isinstance(value, Mapping):
        value = (value,)
    return tuple(deepcopy(dict(item)) for item in value if isinstance(item, Mapping))


@dataclass(frozen=True)
class NovelTypeRecord:
    id: str
    name: str
    description: str = ""
    keywords: tuple[str, ...] = ()
    core_promises: tuple[str, ...] = ()
    ledger_fields: tuple[str, ...] = ()
    rulebook: dict[str, tuple[str, ...]] = field(default_factory=dict)
    quality_checks: tuple[str, ...] = ()
    trope_templates: tuple[dict[str, object], ...] = ()
    builtin: bool = False

    def __post_init__(self) -> None:
        type_id = str(self.id or "").strip()
        name = str(self.name or "").strip()
        if not type_id:
            raise ValueError("Novel type ID cannot be blank")
        if not name:
            raise ValueError("Novel type name cannot be blank")
        object.__setattr__(self, "id", type_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "description", str(self.description or "").strip())
        for field_name in ("keywords", "core_promises", "ledger_fields", "quality_checks"):
            object.__setattr__(self, field_name, _string_tuple(getattr(self, field_name)))
        object.__setattr__(self, "rulebook", _normalized_rulebook(self.rulebook))
        object.__setattr__(self, "trope_templates", _trope_templates(self.trope_templates))
        object.__setattr__(self, "builtin", bool(self.builtin))

    @classmethod
    def from_payload(cls, payload: NovelTypeRecord | Mapping[str, Any]) -> NovelTypeRecord:
        if isinstance(payload, cls):
            return payload
        if not isinstance(payload, Mapping):
            raise TypeError("Novel type payload must be a mapping or NovelTypeRecord")
        return cls(**{item.name: payload[item.name] for item in fields(cls) if item.name in payload})

    def to_dict(self, *, include_builtin: bool = True) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "keywords": list(self.keywords),
            "core_promises": list(self.core_promises),
            "ledger_fields": list(self.ledger_fields),
            "rulebook": {name: list(rules) for name, rules in self.rulebook.items()},
            "quality_checks": list(self.quality_checks),
            "trope_templates": deepcopy(list(self.trope_templates)),
        }
        if include_builtin:
            payload["builtin"] = self.builtin
        return payload


def _record_from_plugin(plugin: GenrePlugin) -> NovelTypeRecord:
    catalog_entry = NOVEL_TYPE_CATALOG.get(plugin.plugin_id)
    return NovelTypeRecord(
        id=plugin.plugin_id,
        name=plugin.name,
        description=catalog_entry.description if catalog_entry else "",
        keywords=plugin.keywords,
        core_promises=plugin.core_promises,
        ledger_fields=plugin.ledger_fields,
        rulebook=plugin.rulebook,
        quality_checks=plugin.quality_checks,
        trope_templates=plugin.trope_templates,
        builtin=True,
    )


_BUILTINS = {plugin.plugin_id: _record_from_plugin(plugin) for plugin in _BUILTIN_PLUGINS}


def _default_storage_path() -> Path:
    configured = os.environ.get("NOVEL_AUTOGROWTH_NOVEL_TYPES_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".novel-autogrowth-engine" / "novel_types.json"


class NovelTypeLibrary:
    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path).expanduser() if path is not None else _default_storage_path()

    def _stored_data(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {"overrides": {}, "custom": {}}
        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, Mapping):
            raise ValueError("Novel type library JSON must contain an object")
        overrides = payload.get("overrides", {})
        custom = payload.get("custom", {})
        if not isinstance(overrides, Mapping) or not isinstance(custom, Mapping):
            raise ValueError("Novel type library overrides and custom values must be objects")
        return {"overrides": dict(overrides), "custom": dict(custom)}

    def _records(self) -> dict[str, NovelTypeRecord]:
        stored = self._stored_data()
        records: dict[str, NovelTypeRecord] = {}
        for type_id, builtin in _BUILTINS.items():
            override = stored["overrides"].get(type_id, {})
            merged = builtin.to_dict()
            if isinstance(override, Mapping):
                merged.update(override)
            merged.update({"id": type_id, "builtin": True})
            records[type_id] = NovelTypeRecord.from_payload(merged)
        for type_id, payload in stored["custom"].items():
            if type_id in records or not isinstance(payload, Mapping):
                continue
            merged = dict(payload)
            merged.update({"id": type_id, "builtin": False})
            records[type_id] = NovelTypeRecord.from_payload(merged)
        return records

    def list(self) -> list[NovelTypeRecord]:
        return list(self._records().values())

    def get(self, type_id: str) -> NovelTypeRecord | None:
        return self._records().get(str(type_id or "").strip())

    def create(self, payload: NovelTypeRecord | Mapping[str, Any]) -> NovelTypeRecord:
        record = NovelTypeRecord.from_payload(payload)
        if record.id in self._records():
            raise ValueError(f"Novel type ID {record.id!r} already exists")
        record = NovelTypeRecord.from_payload({**record.to_dict(), "builtin": False})
        stored = self._stored_data()
        stored["custom"][record.id] = record.to_dict(include_builtin=False)
        self._write(stored)
        return record

    def update(self, type_id: str, payload: NovelTypeRecord | Mapping[str, Any]) -> NovelTypeRecord:
        normalized_id = str(type_id or "").strip()
        current = self.get(normalized_id)
        if current is None:
            raise KeyError(f"Unknown novel type ID: {normalized_id}")
        changes = payload.to_dict() if isinstance(payload, NovelTypeRecord) else dict(payload)
        merged = current.to_dict()
        merged.update(changes)
        merged.update({"id": current.id, "builtin": current.builtin})
        updated = NovelTypeRecord.from_payload(merged)
        updated_payload = updated.to_dict()
        stored = self._stored_data()
        if current.builtin:
            baseline = _BUILTINS[current.id].to_dict()
            override = {
                name: deepcopy(updated_payload[name])
                for name in _EDITABLE_FIELDS
                if updated_payload[name] != baseline[name]
            }
            if updated.description != baseline["description"]:
                override["description"] = updated.description
            if override:
                stored["overrides"][current.id] = override
            else:
                stored["overrides"].pop(current.id, None)
        else:
            stored["custom"][current.id] = updated.to_dict(include_builtin=False)
        self._write(stored)
        return updated

    def delete(self, type_id: str) -> None:
        normalized_id = str(type_id or "").strip()
        current = self.get(normalized_id)
        if current is None:
            raise KeyError(f"Unknown novel type ID: {normalized_id}")
        if current.builtin:
            raise ValueError("A built-in novel type cannot be deleted")
        stored = self._stored_data()
        stored["custom"].pop(normalized_id, None)
        self._write(stored)

    def _write(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, prefix=f".{self.path.name}.", delete=False
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def list_novel_types() -> list[NovelTypeRecord]:
    return NovelTypeLibrary().list()


def get_novel_type(type_id: str) -> NovelTypeRecord | None:
    return NovelTypeLibrary().get(type_id)


def create_novel_type(payload: NovelTypeRecord | Mapping[str, Any]) -> NovelTypeRecord:
    return NovelTypeLibrary().create(payload)


def update_novel_type(type_id: str, payload: NovelTypeRecord | Mapping[str, Any]) -> NovelTypeRecord:
    return NovelTypeLibrary().update(type_id, payload)


def delete_novel_type(type_id: str) -> None:
    NovelTypeLibrary().delete(type_id)


def resolve_genre_plugin(type_id: str) -> GenrePlugin | None:
    record = get_novel_type(type_id)
    if record is None:
        return None
    return GenrePlugin(
        plugin_id=record.id,
        name=record.name,
        keywords=record.keywords,
        core_promises=record.core_promises,
        ledger_fields=record.ledger_fields,
        rulebook=deepcopy(record.rulebook),
        quality_checks=record.quality_checks,
        trope_templates=deepcopy(record.trope_templates),
    )
