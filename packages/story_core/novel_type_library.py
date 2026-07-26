from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, fields
import json
import os
from pathlib import Path
import tempfile
import threading
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
from packages.story_core.novel_type_ids import canonical_novel_type_id
from packages.story_core.power_system_templates import copy_power_system_template


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
_BUILTIN_DESCRIPTIONS = {
    "generic_webnovel": "不绑定具体题材规则，只保留章节推进、钩子、人物动机和连续性要求。",
    "game_webnovel": "加载等级、面板、背包、任务、货币、掉落、玩家生态和NPC服务规则。",
    "urban": "加载职场、商业、舆论、人际关系、现实利益和身份反差规则。",
    "xuanhuan": "聚焦自创力量、异物机缘、资源成长和世界秘密，允许项目自行定义力量来源与成长终点。",
    "xianxia": "聚焦灵根修炼、道法因果、渡劫飞升和长生求道，加载修真境界、传承与修炼资源规则。",
    "suspense": "加载线索、证据链、嫌疑人、调查推进和公平反转规则。",
    "romance": "加载关系拉扯、情绪递进、误会、靠近和外部阻碍规则。",
    "rules_mystery": "加载规则验证、禁忌代价、污染递进和异常逻辑规则。",
}
_EDITABLE_FIELDS = tuple(
    item.name for item in fields(GenrePlugin) if item.name not in {"plugin_id"}
)
_EMPTY_STORAGE: dict[str, dict[str, Any]] = {"overrides": {}, "custom": {}}
_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()
_LIBRARY_REVISION = 0
_LIBRARY_REVISION_LOCK = threading.Lock()
_LIBRARY_REVISION_WRITER_THREAD_ID: int | None = None
_LIBRARY_WRITER_REVISIONS: dict[int, int] = {}


def _bump_library_revision() -> None:
    global _LIBRARY_REVISION, _LIBRARY_REVISION_WRITER_THREAD_ID
    with _LIBRARY_REVISION_LOCK:
        _LIBRARY_REVISION += 1
        writer_thread_id = threading.get_ident()
        _LIBRARY_REVISION_WRITER_THREAD_ID = writer_thread_id
        _LIBRARY_WRITER_REVISIONS[writer_thread_id] = _LIBRARY_REVISION


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


def _power_system_template(value: Any) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return deepcopy(dict(value))


def _custom_power_system_template(value: Any) -> dict[str, object]:
    template = copy_power_system_template("generic_webnovel")
    if isinstance(value, Mapping):
        template.update(deepcopy(dict(value)))
    return template


def _canonical_type_id(value: Any) -> str:
    return canonical_novel_type_id(value)


@dataclass
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
    power_system_template: dict[str, object] = field(default_factory=dict)
    builtin: bool = False

    def __post_init__(self) -> None:
        type_id = str(self.id or "").strip()
        name = str(self.name or "").strip()
        if not type_id:
            raise ValueError("Novel type ID cannot be blank")
        if not name:
            raise ValueError("Novel type name cannot be blank")
        self.id = type_id
        self.name = name
        self.description = str(self.description or "").strip()
        for field_name in ("keywords", "core_promises", "ledger_fields", "quality_checks"):
            setattr(self, field_name, _string_tuple(getattr(self, field_name)))
        self.rulebook = _normalized_rulebook(self.rulebook)
        self.trope_templates = _trope_templates(self.trope_templates)
        self.power_system_template = _power_system_template(self.power_system_template)
        self.builtin = bool(self.builtin)

    @classmethod
    def from_payload(cls, payload: NovelTypeRecord | Mapping[str, Any]) -> NovelTypeRecord:
        if isinstance(payload, cls):
            return deepcopy(payload)
        if not isinstance(payload, Mapping):
            raise TypeError("Novel type payload must be a mapping or NovelTypeRecord")
        field_names = {item.name for item in fields(cls)}
        unknown_fields = set(payload) - field_names
        if unknown_fields:
            names = ", ".join(sorted(str(name) for name in unknown_fields))
            raise ValueError(f"Unknown novel type field(s): {names}")
        return cls(**dict(payload))

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
            "power_system_template": deepcopy(self.power_system_template),
        }
        if include_builtin:
            payload["builtin"] = self.builtin
        return payload


def _record_from_plugin(plugin: GenrePlugin) -> NovelTypeRecord:
    return NovelTypeRecord(
        id=plugin.plugin_id,
        name=plugin.name,
        description=_BUILTIN_DESCRIPTIONS[plugin.plugin_id],
        keywords=plugin.keywords,
        core_promises=plugin.core_promises,
        ledger_fields=plugin.ledger_fields,
        rulebook=plugin.rulebook,
        quality_checks=plugin.quality_checks,
        trope_templates=plugin.trope_templates,
        power_system_template=deepcopy(plugin.power_system_template),
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

    @property
    def backup_path(self) -> Path:
        return self.path.with_name(f"{self.path.name}.bak")

    @property
    def lock_path(self) -> Path:
        return self.path.with_name(f"{self.path.name}.lock")

    def _stored_data(self) -> dict[str, dict[str, Any]]:
        for candidate in (self.path, self.backup_path):
            try:
                return self._read_storage_file(candidate)
            except (OSError, TypeError, ValueError):
                continue
        return deepcopy(_EMPTY_STORAGE)

    def _read_storage_file(self, path: Path) -> dict[str, dict[str, Any]]:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, Mapping):
            raise ValueError("Novel type library JSON must contain an object")
        overrides = payload.get("overrides", {})
        custom = payload.get("custom", {})
        if not isinstance(overrides, Mapping) or not isinstance(custom, Mapping):
            raise ValueError("Novel type library overrides and custom values must be objects")
        stored = {"overrides": dict(overrides), "custom": dict(custom)}
        self._records_from_data(stored)
        return stored

    def _records_from_data(
        self, stored: Mapping[str, Mapping[str, Any]]
    ) -> dict[str, NovelTypeRecord]:
        records: dict[str, NovelTypeRecord] = {}
        canonical_ids: set[str] = set()
        for type_id, builtin in _BUILTINS.items():
            override = stored["overrides"].get(type_id, {})
            merged = builtin.to_dict()
            if not isinstance(override, Mapping):
                raise ValueError(f"Novel type override {type_id!r} must be an object")
            merged.update(override)
            merged.update({"id": type_id, "builtin": True})
            records[type_id] = NovelTypeRecord.from_payload(merged)
            canonical_ids.add(_canonical_type_id(type_id))
        for type_id, payload in stored["custom"].items():
            canonical_id = _canonical_type_id(type_id)
            if canonical_id in canonical_ids:
                raise ValueError(f"Novel type ID {type_id!r} collides with an existing type")
            if not isinstance(payload, Mapping):
                raise ValueError(f"Custom novel type {type_id!r} must be an object")
            merged = dict(payload)
            merged["power_system_template"] = _custom_power_system_template(
                payload.get("power_system_template")
            )
            merged.update({"id": type_id, "builtin": False})
            records[type_id] = NovelTypeRecord.from_payload(merged)
            canonical_ids.add(canonical_id)
        return records

    def _records(self) -> dict[str, NovelTypeRecord]:
        return self._records_from_data(self._stored_data())

    def list(self) -> list[NovelTypeRecord]:
        return deepcopy(list(self._records().values()))

    def get(self, type_id: str) -> NovelTypeRecord | None:
        record = self._records().get(str(type_id or "").strip())
        return deepcopy(record) if record is not None else None

    def create(self, payload: NovelTypeRecord | Mapping[str, Any]) -> NovelTypeRecord:
        record = NovelTypeRecord.from_payload(payload)
        with self._transaction_lock():
            stored = self._stored_data()
            records = self._records_from_data(stored)
            if _canonical_type_id(record.id) in {
                _canonical_type_id(existing_id) for existing_id in records
            }:
                raise ValueError(f"Novel type ID {record.id!r} already exists")
            record = NovelTypeRecord.from_payload(
                {
                    **record.to_dict(),
                    "power_system_template": _custom_power_system_template(
                        record.power_system_template
                    ),
                    "builtin": False,
                }
            )
            stored["custom"][record.id] = record.to_dict(include_builtin=False)
            self._write(stored)
        _bump_library_revision()
        return deepcopy(record)

    def update(self, type_id: str, payload: NovelTypeRecord | Mapping[str, Any]) -> NovelTypeRecord:
        normalized_id = str(type_id or "").strip()
        if isinstance(payload, NovelTypeRecord):
            changes = payload.to_dict()
        elif isinstance(payload, Mapping):
            NovelTypeRecord.from_payload(
                {"id": normalized_id or "validation", "name": "validation", **dict(payload)}
            )
            changes = dict(payload)
        else:
            raise TypeError("Novel type payload must be a mapping or NovelTypeRecord")
        with self._transaction_lock():
            stored = self._stored_data()
            current = self._records_from_data(stored).get(normalized_id)
            if current is None:
                raise KeyError(f"Unknown novel type ID: {normalized_id}")
            merged = current.to_dict()
            merged.update(changes)
            merged.update({"id": current.id, "builtin": current.builtin})
            if not current.builtin:
                merged["power_system_template"] = _custom_power_system_template(
                    merged.get("power_system_template")
                )
            updated = NovelTypeRecord.from_payload(merged)
            updated_payload = updated.to_dict()
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
        _bump_library_revision()
        return deepcopy(updated)

    def delete(self, type_id: str) -> None:
        normalized_id = str(type_id or "").strip()
        with self._transaction_lock():
            stored = self._stored_data()
            current = self._records_from_data(stored).get(normalized_id)
            if current is None:
                raise KeyError(f"Unknown novel type ID: {normalized_id}")
            if current.builtin:
                raise ValueError("A built-in novel type cannot be deleted")
            stored["custom"].pop(normalized_id, None)
            self._write(stored)
        _bump_library_revision()

    @contextmanager
    def _transaction_lock(self):
        key = str(self.lock_path.resolve())
        with _PATH_LOCKS_GUARD:
            process_lock = _PATH_LOCKS.setdefault(key, threading.Lock())
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with process_lock:
            with self.lock_path.open("a+b") as lock_file:
                self._lock_file(lock_file)
                try:
                    yield
                finally:
                    self._unlock_file(lock_file)

    @staticmethod
    def _lock_file(lock_file) -> None:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            return
        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

    @staticmethod
    def _unlock_file(lock_file) -> None:
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _write(self, payload: Mapping[str, Any]) -> None:
        previous_payload = self._stored_data()
        self._atomic_write(self.backup_path, previous_payload)
        self._atomic_write(self.path, payload)

    @staticmethod
    def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
            ) as handle:
                temporary_path = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()


def list_novel_types() -> list[NovelTypeRecord]:
    return NovelTypeLibrary().list()


def novel_type_library_snapshot_token() -> tuple[Any, ...]:
    library = NovelTypeLibrary()
    with _LIBRARY_REVISION_LOCK:
        revision = _LIBRARY_REVISION
        writer_thread_id = _LIBRARY_REVISION_WRITER_THREAD_ID
        writer_revisions = tuple(sorted(_LIBRARY_WRITER_REVISIONS.items()))

    def fingerprint(path: Path) -> tuple[Any, ...]:
        try:
            stat = path.stat()
        except OSError:
            return (str(path.resolve()), None)
        return (
            str(path.resolve()),
            stat.st_mtime_ns,
            stat.st_size,
            getattr(stat, "st_ino", 0),
        )

    return (
        revision,
        writer_thread_id,
        writer_revisions,
        fingerprint(library.path),
        fingerprint(library.backup_path),
    )


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
    return novel_type_record_to_genre_plugin(record)


def novel_type_record_to_genre_plugin(record: NovelTypeRecord) -> GenrePlugin:
    return GenrePlugin(
        plugin_id=record.id,
        name=record.name,
        keywords=record.keywords,
        core_promises=record.core_promises,
        ledger_fields=record.ledger_fields,
        rulebook=deepcopy(record.rulebook),
        quality_checks=record.quality_checks,
        trope_templates=deepcopy(record.trope_templates),
        power_system_template=deepcopy(record.power_system_template),
    )
