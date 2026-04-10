from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ForeshadowingStatus = Literal["open", "reinforced", "resolved", "expired"]
Cadence = Literal["urgent", "measured", "breathing"]


class CharacterRelationship(BaseModel):
    target: str
    trust: float = 0.0
    tension: float = 0.0
    bond: str = ""


class TimelineEvent(BaseModel):
    chapter_number: int
    summary: str
    impact: str


class ForeshadowingState(BaseModel):
    text: str
    first_chapter: int
    status: ForeshadowingStatus = "open"


class ChapterSummary(BaseModel):
    chapter_number: int
    chapter_title: str = ""
    cadence: Cadence = "measured"
    summary: str
    facts: list[str] = Field(default_factory=list)
    unresolved_threads: list[str] = Field(default_factory=list)
    next_focus: str = ""
    primary_conflict: dict = Field(default_factory=dict)
    secondary_conflict: dict = Field(default_factory=dict)
    event_beat: dict = Field(default_factory=dict)


class CharacterState(BaseModel):
    """Mutable character state used by the story engine."""

    name: str
    role: str
    traits: dict[str, float] = Field(default_factory=dict)
    goals: list[str] = Field(default_factory=list)
    memory: list[str] = Field(default_factory=list)
    relationships: dict[str, CharacterRelationship] = Field(default_factory=dict)
    current_emotion: str = "neutral"
    location: str = ""
    secrets: list[str] = Field(default_factory=list)
    frozen: bool = False


class StoryState(BaseModel):
    """Global story state that evolves chapter by chapter."""

    story_id: str
    outline: str
    genre: str
    style: str
    current_chapter: int = 0
    characters: list[CharacterState] = Field(default_factory=list)
    world_facts: list[str] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    foreshadowing: list[ForeshadowingState] = Field(default_factory=list)
    chapter_summaries: list[ChapterSummary] = Field(default_factory=list)
