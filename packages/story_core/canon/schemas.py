"""Type-specific canonical card schemas.

Each entity kind has its own Pydantic model that captures the
fields the preflight must fill in before the writer runs.
Genre-specific fields live under ``extensions`` so the
canonical shapes stay portable across genres.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CharacterCard(BaseModel):
    """Canonical character card.

    Covers identity, origin, age or age range, occupation or
    social role, present goal, fear or weakness, behavioral
    habits, speech tendency, relationships, knowledge boundary,
    current state, and change arc. Genre-specific fields live
    under ``extensions``.
    """

    model_config = ConfigDict(extra="forbid")

    identity: str = ""
    origin: str = ""
    age_or_age_range: str = ""
    occupation_or_role: str = ""
    present_goal: str = ""
    fear_or_weakness: str = ""
    behavioral_habits: str = ""
    speech_tendency: str = ""
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_boundary: list[str] = Field(default_factory=list)
    current_state: str = ""
    change_arc: str = ""


class EquipmentCard(BaseModel):
    """Canonical equipment / item card.

    Captures effect, limitation, cost, owner, provenance, and
    plot function. ``plot_function`` is what the director and
    writer use to keep the item's role in the story explicit.
    """

    model_config = ConfigDict(extra="forbid")

    effect: str = ""
    limitation: str = ""
    cost: str = ""
    owner: str = ""
    provenance: str = ""
    plot_function: str = ""


class TechniqueCard(BaseModel):
    """Canonical technique / skill card.

    Same shape as equipment: effect / limitation / cost /
    owner / provenance / plot function. Kept as a separate
    type so the registry can treat techniques and equipment
    as different kinds even though their fields line up.
    """

    model_config = ConfigDict(extra="forbid")

    effect: str = ""
    limitation: str = ""
    cost: str = ""
    owner: str = ""
    provenance: str = ""
    plot_function: str = ""


__all__ = ["CharacterCard", "EquipmentCard", "TechniqueCard"]
