from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterState(BaseModel):
    name: str
    role: str
    traits: dict[str, float] = Field(default_factory=dict)
    goals: list[str] = Field(default_factory=list)
    memory: list[str] = Field(default_factory=list)


class StoryState(BaseModel):
    story_id: str
    outline: str
    genre: str
    style: str
    current_chapter: int = 0
    characters: list[CharacterState] = Field(default_factory=list)

