"""Entity designer protocol.

The designer is the bridge between the director's
``EntityRequirement`` and a concrete ``CanonEntity``. In tests,
a recording double returns a canned card. In production, the
designer would call the canonical model gateway, pass the
requirement plus the relevant director context, and return a
validated card.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..agents.contracts import EntityRequirement
from .registry import CanonEntity, CanonRegistry


class EntityDesigner(Protocol):
    """Anything that turns a director's ``EntityRequirement`` into a card."""

    def design(
        self,
        requirement: EntityRequirement,
        registry: CanonRegistry,
    ) -> CanonEntity: ...


__all__ = ["EntityDesigner"]
