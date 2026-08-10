"""Pydantic contracts for the modular agent inputs and outputs.

The director, writer, consistency, and fact-extractor agents
share these shapes. The orchestrator and the workbench treat
them as the boundary protocol; any agent-specific implementation
detail (prompt strings, runtime choices, etc.) stays behind the
boundary.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from packages.story_core.chapter_length_policy import (
    acceptance_chars as default_acceptance_chars,
    target_chars as default_target_chars,
)


# --- Director ----------------------------------------------------------------


class SceneBeat(BaseModel):
    """One ordered scene beat inside a director artifact.

    ``result`` is required because every beat must change the
    world state, not merely observe it. The consistency agent uses
    this to verify that the writer's draft produced the promised
    result, and the fact extractor uses it to anchor proposed
    deltas.
    """

    order: int
    location: str
    action: str
    result: str


class EntityRequirement(BaseModel):
    """A canonical entity the director says must exist before writing.

    ``kind`` is one of the canonical entity kinds (character, item,
    equipment, technique, location, organization, quest, monster,
    rule). ``importance`` is the director's read of how much weight
    the entity carries in this chapter; ``inline_minor`` marks
    disposable unnamed roles that don't need a card.
    """

    kind: Literal[
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
    name: str
    importance: int = Field(default=5, ge=0, le=10)
    inline_minor: bool = False
    notes: str = ""


class DirectorArtifact(BaseModel):
    """The director's structured chapter plan.

    The director decides *what* happens. The writer decides *how*
    it is rendered. ``DirectorArtifact`` is the only contract
    between them; the writer never sees the raw prompt that
    produced it.
    """

    schema_version: Literal["director-artifact/v1"] = "director-artifact/v1"
    chapter_number: int
    # A dedicated title field is separate from ``chapter_goal`` so
    # the workbench can render a short headline and the writer
    # prompt can quote the goal as the dramatic intent without
    # collapsing the two. The plan rule in the prompt explicitly
    # forbids treating the outline summary as a title; the
    # runtime model has to invent one.
    chapter_title: str = ""
    chapter_goal: str
    opening_state: str
    scene_beats: list[SceneBeat]
    ending_state: str
    hook: str = ""
    entity_requirements: list[EntityRequirement] = Field(default_factory=list)


# --- Writer ------------------------------------------------------------------


class WriterRequest(BaseModel):
    """Everything the writer agent needs to render one chapter.

    The orchestrator hands the writer a fully approved director
    artifact plus a context view; the writer has no need to read
    anything else. ``director_artifact`` is the only thing the
    writer treats as ground truth for *what* should happen.

    The slice fields are typed as ``list[Any]`` because the
    role-specific context builders emit heterogeneous payloads
    (plain strings for short rules, dicts for full cards). The
    writer prompt builder accepts either shape and renders
    what it gets.
    """

    chapter_number: int
    director_artifact: DirectorArtifact
    # Project-level metadata is generic — it travels through every
    # genre, world blueprint, and craft module. The writer prompt
    # uses ``project_title`` and ``genre`` to anchor voice and the
    # length ranges to keep prose on the hard production target.
    project_title: str = ""
    genre: str = ""
    rewrite_guidance: str = ""
    target_chars: dict[str, int] = Field(
        default_factory=default_target_chars
    )
    acceptance_chars: dict[str, int] = Field(
        default_factory=default_acceptance_chars
    )
    repair_length: bool = False
    previous_tail: str = ""
    continuity_facts: list[Any] = Field(default_factory=list)
    character_cards: list[dict] = Field(default_factory=list)
    entity_cards: list[dict] = Field(default_factory=list)
    world_rules: list[Any] = Field(default_factory=list)
    craft_modules: list[dict] = Field(default_factory=list)


class WriterResult(BaseModel):
    """The writer's output for one chapter.

    The writer may only *propose* facts; confirmed canon is the
    orchestrator's job once the user accepts the candidate. The
    absence of a ``confirmed_facts`` field is itself a contract:
    the model can suggest, the orchestrator commits.
    """

    body: str
    proposed_facts: list[dict] = Field(default_factory=list)
    word_count: int = 0
    notes: str = ""


__all__ = [
    "DirectorArtifact",
    "EntityRequirement",
    "SceneBeat",
    "WriterRequest",
    "WriterResult",
]
