from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from packages.story_core.character_profiles import (
    BackgroundProfile,
    CurrentLifeProfile,
    IdentityProfile,
    RelationshipNote,
    StoryDriveProfile,
)

from packages.story_core.env import load_environment_files


load_environment_files()


def default_model_name() -> str:
    return os.getenv("NOVEL_AUTOGROWTH_DEFAULT_MODEL") or os.getenv("OPENAI_MODEL") or "qwen3.6-plus"


def default_fast_model_name() -> str:
    return os.getenv("NOVEL_AUTOGROWTH_FAST_MODEL") or default_model_name()


def _contains_import_noise(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ("snapshots/", "author_intent", "story_bible", "book_rules", "current_focus"))


def _sanitize_outline_text(text: str) -> str:
    if not text:
        return text
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _contains_import_noise(line):
            continue
        lines.append(line)
        if len(lines) >= 24:
            break
    cleaned = "\n".join(lines).strip()
    return cleaned or text[:1200]


def _sanitize_character_goal(goal: str, role: str) -> str:
    compact = " ".join(goal.split()).strip()
    if not compact:
        return ""
    if len(compact) > 180 or _contains_import_noise(compact):
        return "推进当前主线" if role == "protagonist" else "围绕当前主线行动"
    return compact


ForeshadowingStatus = Literal["open", "reinforced", "resolved", "expired"]
Cadence = Literal["urgent", "measured", "breathing"]
CharacterLifecycleState = Literal["proposed", "active", "rejected", "frozen"]
AgentMode = Literal["LLM-assisted"]
AgentRuntimeSource = Literal["idle", "llm", "fallback"]
NewCharacterPolicy = Literal["Director review", "Auto-approve named candidates", "Manual review"]


class AgentSettings(BaseModel):
    mode: AgentMode = "LLM-assisted"
    global_model: str = Field(default_factory=default_model_name)
    character_model: str = Field(default_factory=default_fast_model_name)
    director_model: str = Field(default_factory=default_model_name)
    writer_model: str = Field(default_factory=default_model_name)
    memory_model: str = Field(default_factory=default_model_name)
    temperature: float = 0.7
    new_character_policy: NewCharacterPolicy = "Director review"

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_mode(cls, value):
        if isinstance(value, dict) and value.get("mode") in {"Rule-based", "provider-configured"}:
            next_value = dict(value)
            next_value["mode"] = "LLM-assisted"
            return next_value
        return value


class StageRuntimeEntry(BaseModel):
    source: AgentRuntimeSource = "idle"
    provider: str = ""
    model: str = ""
    fallback_reason: str = ""
    last_run_chapter: int = 0

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_runtime(cls, value):
        if isinstance(value, dict):
            next_value = dict(value)
            if next_value.get("source") == "rule-based":
                next_value["source"] = "fallback"
            return next_value
        return value


AgentRuntimeEntry = StageRuntimeEntry


class AgentRuntimeState(BaseModel):
    planner: StageRuntimeEntry = Field(default_factory=StageRuntimeEntry)
    writer: StageRuntimeEntry = Field(default_factory=StageRuntimeEntry)
    memory: StageRuntimeEntry = Field(default_factory=StageRuntimeEntry)
    recent_events: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_agent_runtime(cls, value):
        if not isinstance(value, dict):
            return value
        migrated = dict(value)
        for stage, legacy_key in (
            ("planner", "director_agent"),
            ("writer", "writer_agent"),
            ("memory", "memory_agent"),
        ):
            if stage not in migrated and legacy_key in migrated:
                migrated[stage] = migrated[legacy_key]
        for legacy_key in (
            "character_agent",
            "director_agent",
            "writer_agent",
            "memory_agent",
            "outline_agent",
        ):
            migrated.pop(legacy_key, None)
        return migrated


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


class MemoryIndexEntry(BaseModel):
    chapter_number: int
    chapter_title: str = ""
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    factions: list[str] = Field(default_factory=list)
    quests: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    unresolved_threads: list[str] = Field(default_factory=list)


class ArcRecap(BaseModel):
    start_chapter: int
    end_chapter: int
    recap: str = ""
    key_threads: list[str] = Field(default_factory=list)
    resolved_threads: list[str] = Field(default_factory=list)
    open_threads: list[str] = Field(default_factory=list)
    character_changes: list[str] = Field(default_factory=list)
    ledger_snapshot: dict = Field(default_factory=dict)


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


class GamePanel(BaseModel):
    """Legacy web-game panel kept as a compatibility mirror for game_state."""

    game_id: str = ""
    level: int | str | None = None
    class_path: str = ""
    exp: str = ""
    hp: str = ""
    mp: str = ""
    attributes: dict = Field(default_factory=dict)
    unallocated_attribute_points: int | None = Field(default=None, exclude_if=lambda value: value is None)
    attribute_point_awards: list[dict] | None = Field(default=None, exclude_if=lambda value: value is None)
    attribute_allocations: list[dict] | None = Field(default=None, exclude_if=lambda value: value is None)
    skills: list[str] = Field(default_factory=list)
    equipment: dict = Field(default_factory=dict)
    inventory: dict = Field(default_factory=dict)
    currency: str = ""
    quests: dict = Field(default_factory=dict)
    risk: dict = Field(default_factory=dict)
    updated_chapter: int = 0


class VoiceSignature(BaseModel):
    """On-page language fingerprint for a character."""

    signature_phrases: list[str] = Field(default_factory=list)
    lexicon: list[str] = Field(default_factory=list)
    taboo: list[str] = Field(default_factory=list)
    sentence_rhythm: str = ""
    self_reference: str = ""
    subtext_habit: str = ""


class CharacterPerformanceProfile(BaseModel):
    """How a character should behave on page, not just who they are."""

    speech_style: str = ""
    action_style: str = ""
    risk_posture: str = ""
    emotional_triggers: list[str] = Field(default_factory=list)
    decision_rules: list[str] = Field(default_factory=list)
    reveal_limits: list[str] = Field(default_factory=list)
    voice: VoiceSignature = Field(default_factory=VoiceSignature)


class NPCBehaviorProfile(BaseModel):
    """Lightweight NPC boundaries for simulation and review."""

    service_role: str = ""
    authority_scope: list[str] = Field(default_factory=list)
    information_limits: list[str] = Field(default_factory=list)
    incentives: list[str] = Field(default_factory=list)
    interaction_rules: list[str] = Field(default_factory=list)


class TemperamentPortrait(BaseModel):
    outward_impression: str = ""
    core_traits: list[str] = Field(default_factory=list)
    inner_contradiction: str = ""
    values: list[str] = Field(default_factory=list)
    bottom_line: str = ""


class PsychologyPortrait(BaseModel):
    desire: str = ""
    fear: str = ""
    blind_spot: str = ""
    defense: str = ""
    shame_point: str = ""


class BehaviorPortrait(BaseModel):
    normal_mode: str = ""
    pressure_mode: str = ""
    conflict_response: str = ""
    failure_response: str = ""
    decision_tendency: str = ""


class EmotionPortrait(BaseModel):
    triggers: list[str] = Field(default_factory=list)
    restraint_style: str = ""
    loss_of_control: str = ""
    mannerisms: list[str] = Field(default_factory=list)


class SocialPortrait(BaseModel):
    strangers: str = ""
    friends: str = ""
    authority: str = ""
    enemies: str = ""


class CharacterVoicePortrait(BaseModel):
    common_words: list[str] = Field(default_factory=list)
    sentence_habit: str = ""
    avoided_topics: list[str] = Field(default_factory=list)
    lying_style: str = ""
    anger_style: str = ""
    relaxed_style: str = ""


class GrowthPortrait(BaseModel):
    initial_flaw: str = ""
    invariants: list[str] = Field(default_factory=list)
    change_conditions: list[str] = Field(default_factory=list)
    stage_direction: str = ""


class PersonalityPortrait(BaseModel):
    temperament: TemperamentPortrait = Field(default_factory=TemperamentPortrait)
    psychology: PsychologyPortrait = Field(default_factory=PsychologyPortrait)
    behavior: BehaviorPortrait = Field(default_factory=BehaviorPortrait)
    emotion: EmotionPortrait = Field(default_factory=EmotionPortrait)
    social: SocialPortrait = Field(default_factory=SocialPortrait)
    voice: CharacterVoicePortrait = Field(default_factory=CharacterVoicePortrait)
    growth: GrowthPortrait = Field(default_factory=GrowthPortrait)
    writing_limits: list[str] = Field(default_factory=list)


class CharacterState(BaseModel):
    """Mutable character state used by the story engine."""

    name: str
    role: str
    character_tier: str = ""
    first_appearance: int = Field(default=0, ge=0)
    identity_profile: IdentityProfile = Field(default_factory=IdentityProfile)
    background_profile: BackgroundProfile = Field(default_factory=BackgroundProfile)
    current_life_profile: CurrentLifeProfile = Field(default_factory=CurrentLifeProfile)
    story_drive: StoryDriveProfile = Field(default_factory=StoryDriveProfile)
    dialogue_examples: list[str] = Field(default_factory=list)
    relationship_notes: list[RelationshipNote] = Field(default_factory=list)
    real_state: dict = Field(default_factory=dict)
    game_state: dict = Field(default_factory=dict)
    game_id: str = ""
    game_panel: GamePanel = Field(default_factory=GamePanel)
    performance_profile: CharacterPerformanceProfile = Field(default_factory=CharacterPerformanceProfile)
    npc_profile: NPCBehaviorProfile = Field(default_factory=NPCBehaviorProfile)
    personality_portrait: PersonalityPortrait = Field(default_factory=PersonalityPortrait)
    character_type: str = ""
    core_motivation: str = ""
    behavior_logic: str = ""
    interaction_mode: str = ""
    poison_points: list[str] = Field(default_factory=list)
    social_profile: dict = Field(default_factory=dict)
    psychological_profile: dict = Field(default_factory=dict)
    moral_profile: dict = Field(default_factory=dict)
    story_function: str = ""
    chapter_role: str = ""
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
        self.goals = [_sanitize_character_goal(goal, self.role) for goal in self.goals if goal.strip()]
        if self.lifecycle_state == "frozen" or self.frozen:
            self.frozen = True
            self.lifecycle_state = "frozen"
        return self


class ChapterSimulationPlan(BaseModel):
    """Unified scene simulation plan used by writer and reviewers."""

    chapter_number: int
    chapter_goal: str = ""
    world_context: dict = Field(default_factory=dict)
    event_plan: dict = Field(default_factory=dict)
    plot_simulation: dict = Field(default_factory=dict)
    longform_plot_contract: dict = Field(default_factory=dict)
    protagonist_strategy: dict = Field(default_factory=dict)
    character_performance: list[dict] = Field(default_factory=list)
    npc_boundaries: list[dict] = Field(default_factory=list)
    information_visibility: list[str] = Field(default_factory=list)
    economy_expectations: list[str] = Field(default_factory=list)
    simulation_variant: dict = Field(default_factory=dict)
    web_game_author_craft: dict = Field(default_factory=dict)
    web_game_director_card: dict = Field(default_factory=dict)
    panel_expectations: list[str] = Field(default_factory=list)
    longform_constraints: list[str] = Field(default_factory=list)
    required_beats: list[str] = Field(default_factory=list)
    forbidden_moves: list[str] = Field(default_factory=list)
    review_focus: list[str] = Field(default_factory=list)


class WorldEvent(BaseModel):
    """A simulated world-side event before it is rendered as prose."""

    event_id: str
    template_id: str = ""
    actor: str
    action: str
    target: str = ""
    location: str = ""
    cause: str = ""
    visible_to: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    state_delta: dict = Field(default_factory=dict)
    prose_priority: int = 0


class SceneCard(BaseModel):
    """A writeable scene extracted from simulated world events."""

    scene_id: str
    template_id: str = ""
    location: str
    pov: str
    purpose: str
    conflict: str
    source_events: list[str] = Field(default_factory=list)
    must_show: list[str] = Field(default_factory=list)
    must_not_explain: list[str] = Field(default_factory=list)
    state_delta: dict = Field(default_factory=dict)
    scene_contract: dict = Field(default_factory=dict)
    ending_pressure: str = ""


class ChapterOutline(BaseModel):
    """A single chapter outline entry."""
    chapter_number: int
    chapter_title: str
    summary: str
    key_characters: list[str] = Field(default_factory=list)
    primary_conflict: str = ""
    cadence: Cadence = "measured"
    word_count_estimate: int = 3000
    arc_phase: str = ""


class NovelOutline(BaseModel):
    """Full novel outline with per-chapter breakdowns."""
    story_id: str
    genre: str
    style: str
    total_chapters: int
    chapters: list[ChapterOutline] = Field(default_factory=list)
    overall_arc: str = ""
    act_breaks: list[dict] = Field(default_factory=list)  # [{"act": 1, "start": 1, "end": 15, "theme": "..."}]
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""


# ── World Bible ──────────────────────────────────────────────

class PowerSystem(BaseModel):
    """Magic/cultivation power system rules."""
    name: str = ""
    description: str = ""
    levels: list[str] = Field(default_factory=list)  # e.g. ["练气", "筑基", "金丹"]
    rules: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class WorldLocation(BaseModel):
    """A place in the story world."""
    name: str
    description: str = ""
    type: str = ""  # e.g. "city", "mountain", "realm"
    importance: int = 1  # 1-5
    connections: list[str] = Field(default_factory=list)  # connected locations


class Faction(BaseModel):
    """A group/organization in the story."""
    name: str
    description: str = ""
    type: str = ""  # e.g. "sect", "kingdom", "guild"
    goals: list[str] = Field(default_factory=list)
    allies: list[str] = Field(default_factory=list)
    enemies: list[str] = Field(default_factory=list)
    notable_members: list[str] = Field(default_factory=list)


class WorldBible(BaseModel):
    """The comprehensive world background shared across all chapters and characters."""
    story_id: str
    world_name: str = ""
    overview: str = ""
    power_system: PowerSystem = Field(default_factory=PowerSystem)
    locations: list[WorldLocation] = Field(default_factory=list)
    factions: list[Faction] = Field(default_factory=list)
    world_facts: list[str] = Field(default_factory=list)  # fundamental truths about the world
    timeline_events: list[dict] = Field(default_factory=list)  # [{"chapter": 1, "event": "..."}]
    cultural_notes: list[str] = Field(default_factory=list)
    glossary: dict[str, str] = Field(default_factory=dict)  # term → explanation
    updated_at: str = ""


# ── Novel Status ─────────────────────────────────────────────

NovelStatusType = Literal["draft", "outlining", "writing", "reviewing", "completed", "paused"]
ProjectStatusType = Literal["draft", "simulating", "paused", "completed"]
ProjectPipelineStage = Literal[
    "draft",
    "idea_pending",
    "direction_ready",
    "outlining",
    "imported",
    "world_ready",
    "environment_ready",
    "chapter_planning",
    "writing",
    "simulating",
    "paused",
    "completed",
]


class NovelStatus(BaseModel):
    """Overall status of the novel."""
    story_id: str
    status: NovelStatusType = "draft"
    total_chapters_planned: int = 0
    total_chapters_written: int = 0
    total_word_count: int = 0
    last_written_chapter: int = 0
    last_written_at: str = ""
    created_at: str = ""
    updated_at: str = ""


class StoryState(BaseModel):
    """Global story state that evolves chapter by chapter."""

    story_id: str
    outline: str
    genre: str
    genre_plugin_ids: list[str] = Field(default_factory=list)
    style: str
    current_chapter: int = 0
    agent_settings: AgentSettings = Field(default_factory=AgentSettings)
    agent_runtime: AgentRuntimeState = Field(default_factory=AgentRuntimeState)
    author_constraints: list[str] = Field(default_factory=list)
    writing_lessons: list[str] = Field(default_factory=list)
    characters: list[CharacterState] = Field(default_factory=list)
    monster_profiles: list[dict] = Field(default_factory=list)
    world_facts: list[str] = Field(default_factory=list)
    progression_ledger: dict = Field(default_factory=dict)
    world_context: dict = Field(default_factory=dict, exclude=True)
    outline_context: dict = Field(default_factory=dict, exclude=True)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    foreshadowing: list[ForeshadowingState] = Field(default_factory=list)
    chapter_summaries: list[ChapterSummary] = Field(default_factory=list)
    memory_index: list[MemoryIndexEntry] = Field(default_factory=list)
    arc_recaps: list[ArcRecap] = Field(default_factory=list)
    enabled_skill_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sanitize_imported_state(self) -> "StoryState":
        if len(self.outline) > 3000 or _contains_import_noise(self.outline):
            self.outline = _sanitize_outline_text(self.outline)
        return self


class NovelProject(BaseModel):
    """Top-level novel project that owns one or more story branches."""

    project_id: str
    title: str
    source_path: str = ""
    seed_outline: str = ""
    world_summary: str = ""
    current_focus: str = ""
    author_constraints: list[str] = Field(default_factory=list)
    world_blueprint: dict = Field(default_factory=dict)
    character_profiles: list[dict] = Field(default_factory=list)
    relationship_graph: list[dict] = Field(default_factory=list)
    enabled_skill_ids: list[str] = Field(default_factory=list)
    status: ProjectStatusType = "draft"
    pipeline_stage: ProjectPipelineStage = "imported"
    active_story_id: str = ""
    created_at: str = ""
    updated_at: str = ""


class NovelProjectSummary(BaseModel):
    """Compact project view for workbench listings."""

    project_id: str
    title: str
    status: ProjectStatusType = "draft"
    pipeline_stage: ProjectPipelineStage = "imported"
    active_story_id: str = ""
    current_chapter: int = 0
    source_path: str = ""
