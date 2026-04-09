from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterState(BaseModel):
    """Mutable character state used by the story engine.

    This is intentionally minimal for now; later tasks will expand it to support
    richer autonomy and consistency checks.
    """

    name: str
    role: str
    traits: dict[str, float] = Field(default_factory=dict)
    goals: list[str] = Field(default_factory=list)
    memory: list[str] = Field(default_factory=list)


class StoryState(BaseModel):
    """Global story state that evolves chapter by chapter."""

    story_id: str
    outline: str
    genre: str
    style: str
    current_chapter: int = 0
    characters: list[CharacterState] = Field(default_factory=list)
