"""In-memory canonical entity registry.

The registry is the in-process source of truth for the project's
named entities. It is intentionally not a database: the
migration script and the file project store are responsible for
durability; the registry answers resolution and lifecycle
questions while a chapter is being planned.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Iterable, Optional

from .contracts import (
    ALLOWED_KINDS,
    LIFECYCLE_TRANSITIONS,
    CanonEntity,
    EntityKind,
    Lifecycle,
)


_KIND_PREFIX: dict[str, str] = {
    "character": "char",
    "item": "item",
    "equipment": "equip",
    "technique": "tech",
    "location": "loc",
    "organization": "org",
    "quest": "quest",
    "monster": "mon",
    "rule": "rule",
}


_INVALID_ALIAS_CHARS = re.compile(r"[/\x00-\x1f\x7f]+")


def _validate_alias(name: str) -> None:
    if not name or not name.strip():
        raise ValueError("alias_empty")
    if _INVALID_ALIAS_CHARS.search(name):
        raise ValueError(f"alias_invalid: {name!r}")


def _make_entity_id(kind: EntityKind) -> str:
    prefix = _KIND_PREFIX.get(kind, "ent")
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class CanonRegistry:
    """Mutable in-memory canonical entity registry.

    The registry keeps three internal maps:

    * ``_by_id`` — id -> ``CanonEntity``
    * ``_by_name`` — (kind, lowercased primary name) -> entity_id
    * ``_by_alias`` — (kind, lowercased alias) -> entity_id

    Alias uniqueness is enforced at write time. Once an entity
    is added, its ID is permanent; renaming detaches the old
    name from the entity so a fresh entity may use it later.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, CanonEntity] = {}
        self._by_name: dict[tuple[str, str], str] = {}
        self._by_alias: dict[tuple[str, str], str] = {}

    @classmethod
    def empty(cls) -> "CanonRegistry":
        return cls()

    # --- Queries -------------------------------------------------------------

    def resolve(self, name: str, kind: EntityKind | str) -> Optional[CanonEntity]:
        key_kind = str(kind)
        if key_kind not in ALLOWED_KINDS:
            return None
        lowered = name.strip().lower()
        entity_id = self._by_alias.get((key_kind, lowered))
        if entity_id is None:
            entity_id = self._by_name.get((key_kind, lowered))
        if entity_id is None:
            return None
        return self._by_id.get(entity_id)

    def get(self, entity_id: str) -> Optional[CanonEntity]:
        return self._by_id.get(entity_id)

    def list_active(self, kind: EntityKind | str) -> list[CanonEntity]:
        key_kind = str(kind)
        return [
            entity
            for entity in self._by_id.values()
            if entity.kind == key_kind and entity.lifecycle == "active"
        ]

    def list_all(self, kind: EntityKind | str | None = None) -> list[CanonEntity]:
        if kind is None:
            return list(self._by_id.values())
        key_kind = str(kind)
        return [entity for entity in self._by_id.values() if entity.kind == key_kind]

    # --- Mutations -----------------------------------------------------------

    def add(
        self,
        *,
        kind: EntityKind,
        name: str,
        aliases: Iterable[str] = (),
        entity_id: str | None = None,
        lifecycle: Lifecycle = "proposed",
        extensions: dict | None = None,
    ) -> CanonEntity:
        if kind not in ALLOWED_KINDS:
            raise ValueError(f"entity_kind_invalid: {kind!r}")
        _validate_alias(name)
        lowered_name = name.strip().lower()
        if (kind, lowered_name) in self._by_name:
            raise ValueError(f"alias_conflict: {kind}:{name}")
        alias_list: list[str] = []
        alias_keys: set[tuple[str, str]] = set()
        for raw_alias in aliases:
            alias = str(raw_alias).strip()
            if not alias:
                continue
            _validate_alias(alias)
            if alias.lower() == lowered_name:
                # Alias equals the primary name — already registered.
                continue
            key = (kind, alias.lower())
            if key in self._by_alias or (kind, alias.lower()) in self._by_name:
                raise ValueError(f"alias_conflict: {kind}:{alias}")
            alias_list.append(alias)
            alias_keys.add(key)
        new_id = entity_id or _make_entity_id(kind)
        if new_id in self._by_id:
            raise ValueError(f"entity_id_conflict: {new_id}")
        entity = CanonEntity(
            entity_id=new_id,
            kind=kind,  # type: ignore[arg-type]
            display_name=name,
            aliases=tuple(alias_list),
            lifecycle=lifecycle,
            extensions=dict(extensions or {}),
        )
        self._by_id[new_id] = entity
        self._by_name[(kind, lowered_name)] = new_id
        for key in alias_keys:
            self._by_alias[key] = new_id
        return entity

    # Convenience adders per kind. Each one delegates to
    # ``add(kind=...)`` so the alias uniqueness rules apply
    # uniformly across all entity kinds.
    def add_character(
        self,
        *,
        name: str,
        aliases: Iterable[str] = (),
        **kwargs: Any,
    ) -> CanonEntity:
        return self.add(kind="character", name=name, aliases=aliases, **kwargs)

    def add_item(
        self,
        *,
        name: str,
        aliases: Iterable[str] = (),
        **kwargs: Any,
    ) -> CanonEntity:
        return self.add(kind="item", name=name, aliases=aliases, **kwargs)

    def add_equipment(
        self,
        *,
        name: str,
        aliases: Iterable[str] = (),
        **kwargs: Any,
    ) -> CanonEntity:
        return self.add(kind="equipment", name=name, aliases=aliases, **kwargs)

    def add_technique(
        self,
        *,
        name: str,
        aliases: Iterable[str] = (),
        **kwargs: Any,
    ) -> CanonEntity:
        return self.add(kind="technique", name=name, aliases=aliases, **kwargs)

    def add_location(
        self,
        *,
        name: str,
        aliases: Iterable[str] = (),
        **kwargs: Any,
    ) -> CanonEntity:
        return self.add(kind="location", name=name, aliases=aliases, **kwargs)

    def add_organization(
        self,
        *,
        name: str,
        aliases: Iterable[str] = (),
        **kwargs: Any,
    ) -> CanonEntity:
        return self.add(kind="organization", name=name, aliases=aliases, **kwargs)

    def add_quest(
        self,
        *,
        name: str,
        aliases: Iterable[str] = (),
        **kwargs: Any,
    ) -> CanonEntity:
        return self.add(kind="quest", name=name, aliases=aliases, **kwargs)

    def add_monster(
        self,
        *,
        name: str,
        aliases: Iterable[str] = (),
        **kwargs: Any,
    ) -> CanonEntity:
        return self.add(kind="monster", name=name, aliases=aliases, **kwargs)

    def add_rule(
        self,
        *,
        name: str,
        aliases: Iterable[str] = (),
        **kwargs: Any,
    ) -> CanonEntity:
        return self.add(kind="rule", name=name, aliases=aliases, **kwargs)

    def rename(self, entity_id: str, *, display_name: str) -> CanonEntity:
        entity = self._require(entity_id)
        new_name = display_name.strip()
        _validate_alias(new_name)
        lowered_new = new_name.lower()
        # Detach the old primary name and any aliases.
        self._by_name.pop((entity.kind, entity.display_name.lower()), None)
        for alias in entity.aliases:
            self._by_alias.pop((entity.kind, alias.lower()), None)
        # Reject if the new name collides.
        existing = self._by_name.get((entity.kind, lowered_new))
        if existing is not None and existing != entity_id:
            raise ValueError(f"alias_conflict: {entity.kind}:{new_name}")
        # Rebuild the entity with the new display name.
        new_entity = entity.model_copy(update={"display_name": new_name})
        self._by_id[entity_id] = new_entity
        self._by_name[(entity.kind, lowered_new)] = entity_id
        for alias in new_entity.aliases:
            self._by_alias[(entity.kind, alias.lower())] = entity_id
        return new_entity

    # --- Lifecycle -----------------------------------------------------------

    def _transition(self, entity_id: str, target: Lifecycle) -> CanonEntity:
        entity = self._require(entity_id)
        allowed = LIFECYCLE_TRANSITIONS.get(entity.lifecycle, frozenset())
        if target not in allowed:
            raise ValueError(
                f"lifecycle_transition_invalid: {entity.lifecycle} -> {target}"
            )
        new_entity = entity.model_copy(update={"lifecycle": target})
        self._by_id[entity_id] = new_entity
        return new_entity

    def approve(self, entity_id: str) -> CanonEntity:
        return self._transition(entity_id, "approved")

    def activate(self, entity_id: str) -> CanonEntity:
        return self._transition(entity_id, "active")

    def retire(self, entity_id: str) -> CanonEntity:
        return self._transition(entity_id, "retired")

    # --- Internals ----------------------------------------------------------

    def _require(self, entity_id: str) -> CanonEntity:
        entity = self._by_id.get(entity_id)
        if entity is None:
            raise ValueError(f"entity_not_found: {entity_id}")
        return entity


__all__ = ["CanonRegistry"]
