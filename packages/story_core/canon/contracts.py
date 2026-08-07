"""Pydantic contracts for the canonical entity registry."""

from __future__ import annotations

from typing import Any, Literal

import pydantic
from pydantic import BaseModel, ConfigDict, Field


# The nine canonical entity kinds. The kind set is fixed; the
# value carried inside each kind is open-ended (genre-specific
# fields live under ``extensions``) but the discrimination is
# not.
EntityKind = Literal[
    "character",
    "item",
    "equipment",
    "technique",
    "location",
    "organization",
    "quest",
    "monster",
    "rule",
]
ALLOWED_KINDS: tuple[EntityKind, ...] = (
    "character",
    "item",
    "equipment",
    "technique",
    "location",
    "organization",
    "quest",
    "monster",
    "rule",
)


Lifecycle = Literal["proposed", "approved", "active", "retired"]


# Lifecycle transition graph. Keys are the source state; values
# are the set of states the source may transition to. The graph
# is monotonic: an entity cannot regress to an earlier state.
LIFECYCLE_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"approved"}),
    "approved": frozenset({"active", "retired"}),
    "active": frozenset({"retired"}),
    "retired": frozenset(),
}


class CanonEntity(BaseModel):
    """One canonical entity.

    ``entity_id`` is permanent. The display name and aliases
    are mutable through the registry's ``rename`` and
    ``add_alias`` operations, but the ID is what downstream
    code stores and references.
    """

    model_config = ConfigDict(frozen=True)

    entity_id: str
    kind: EntityKind
    display_name: str
    aliases: tuple[str, ...] = Field(default_factory=tuple)
    lifecycle: Lifecycle = "proposed"
    extensions: dict = Field(default_factory=dict)

    @pydantic.model_validator(mode="before")
    @classmethod
    def _validate_kind(cls, data: Any) -> Any:
        if isinstance(data, dict) and "kind" in data:
            kind = data["kind"]
            if kind not in ALLOWED_KINDS:
                raise ValueError(f"entity_kind_invalid: {kind!r}")
        return data

    def matches(self, name: str) -> bool:
        if name == self.display_name:
            return True
        return name in self.aliases


__all__ = [
    "ALLOWED_KINDS",
    "CanonEntity",
    "EntityKind",
    "LIFECYCLE_TRANSITIONS",
    "Lifecycle",
]
