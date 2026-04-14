from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


ForeshadowingStatus = Literal["open", "reinforced", "resolved", "expired"]
Cadence = Literal["urgent", "measured", "breathing"]
CharacterLifecycleState = Literal["proposed", "active", "rejected", "frozen"]
AgentMode = Literal["Rule-based", "LLM-assisted"]
AgentRuntimeSource = Literal["idle", "rule-based", "llm", "fallback"]
NewCharacterPolicy = Literal["Director review", "Auto-approve named candidates", "Manual review"]


class AgentSettings(BaseModel):
    mode: AgentMode = "Rule-based"
    global_model: str = "gpt-5.4"
    character_model: str = "gpt-5.4-mini"
    director_model: str = "gpt-5.4"
    writer_model: str = "gpt-5.4"
    memory_model: str = "gpt-5.4"
    temperature: float = 0.7
    new_character_policy: NewCharacterPolicy = "Director review"


class AgentRuntimeEntry(BaseModel):
    mode: AgentMode = "Rule-based"
    source: AgentRuntimeSource = "idle"
    fallback_reason: str = ""
    last_run_chapter: int = 0


class AgentRuntimeState(BaseModel):
    character_agent: AgentRuntimeEntry = Field(default_factory=AgentRuntimeEntry)
    director_agent: AgentRuntimeEntry = Field(default_factory=AgentRuntimeEntry)
    writer_agent: AgentRuntimeEntry = Field(default_factory=AgentRuntimeEntry)
    memory_agent: AgentRuntimeEntry = Field(default_factory=AgentRuntimeEntry)
    recent_events: list[str] = Field(default_factory=list)


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


class CharacterProposal(BaseModel):
    name: str
    goal: str
    emotion: str = "neutral"
    action: str = ""
    priority: int = 0
    new_character_candidates: list[str] = Field(default_factory=list)


class DirectorDecision(BaseModel):
    primary_conflict: dict = Field(default_factory=dict)
    secondary_conflict: dict = Field(default_factory=dict)
    event_beat: dict = Field(default_factory=dict)
    cadence: Cadence = "measured"
    chapter_title: str = ""
    approved_new_characters: list[str] = Field(default_factory=list)
    deferred_characters: list[str] = Field(default_factory=list)
    rejected_characters: list[str] = Field(default_factory=list)
    next_focus: str = ""


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
    lifecycle_state: CharacterLifecycleState = "active"
    last_proposed_chapter: int = 0
    last_approved_chapter: int = 0
    introduced_by: str = ""

    @model_validator(mode="after")
    def _sync_frozen_lifecycle(self) -> "CharacterState":
        if self.lifecycle_state == "frozen" or self.frozen:
            self.frozen = True
            self.lifecycle_state = "frozen"
        return self


class StoryState(BaseModel):
    """Global story state that evolves chapter by chapter."""

    story_id: str
    outline: str
    genre: str
    style: str
    current_chapter: int = 0
    agent_settings: AgentSettings = Field(default_factory=AgentSettings)
    agent_runtime: AgentRuntimeState = Field(default_factory=AgentRuntimeState)
    characters: list[CharacterState] = Field(default_factory=list)
    world_facts: list[str] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    foreshadowing: list[ForeshadowingState] = Field(default_factory=list)
    chapter_summaries: list[ChapterSummary] = Field(default_factory=list)
