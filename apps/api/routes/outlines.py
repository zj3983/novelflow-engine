"""API routes for outline generation, world bible, and novel status management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.api.routes.stories import store
from apps.api.routes.stories import engine
from packages.story_core.models import NovelOutline, NovelStatus, WorldBible
from packages.story_core.outline_agent import OutlineAgent


router = APIRouter()
outline_agent = OutlineAgent()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Outline routes ───────────────────────────────────────────

class GenerateOutlineRequest(BaseModel):
    target_chapters: int = 30


class OutlineResponse(BaseModel):
    story_id: str
    genre: str
    style: str
    total_chapters: int
    chapters: list[dict]
    overall_arc: str
    act_breaks: list[dict]
    notes: str
    created_at: str = ""
    updated_at: str = ""
    saved: bool = False  # True if persisted to DB


class UpdateOutlineRequest(BaseModel):
    chapters: list[dict]
    overall_arc: str = ""
    act_breaks: list[dict] = Field(default_factory=list)
    notes: str = ""


@router.post("/stories/{story_id}/outline/generate")
def generate_outline(story_id: str, payload: GenerateOutlineRequest = GenerateOutlineRequest()) -> OutlineResponse:
    record = store.get(story_id)
    if record is None:
        raise HTTPException(status_code=404, detail="story_not_found")

    outline = outline_agent.generate(record.story, target_chapters=payload.target_chapters)
    outline.created_at = _now()
    outline.updated_at = _now()

    # Save to DB
    store.save_outline(story_id, outline)

    # Auto-create novel status if not exists
    existing_status = store.get_novel_status(story_id)
    if existing_status is None:
        status = NovelStatus(
            story_id=story_id,
            status="outlining",
            total_chapters_planned=outline.total_chapters,
            created_at=_now(),
            updated_at=_now(),
        )
        store.save_novel_status(story_id, status)
    else:
        existing_status.total_chapters_planned = outline.total_chapters
        existing_status.updated_at = _now()
        store.save_novel_status(story_id, existing_status)

    return OutlineResponse(
        story_id=outline.story_id,
        genre=outline.genre,
        style=outline.style,
        total_chapters=outline.total_chapters,
        chapters=[ch.model_dump() for ch in outline.chapters],
        overall_arc=outline.overall_arc,
        act_breaks=outline.act_breaks,
        notes=outline.notes,
        created_at=outline.created_at,
        updated_at=outline.updated_at,
        saved=True,
    )


@router.get("/stories/{story_id}/outline")
def get_outline(story_id: str) -> OutlineResponse:
    record = store.get(story_id)
    if record is None:
        raise HTTPException(status_code=404, detail="story_not_found")

    # Try to get saved outline first
    outline = store.get_outline(story_id)
    if outline is not None:
        return OutlineResponse(
            story_id=outline.story_id,
            genre=outline.genre,
            style=outline.style,
            total_chapters=outline.total_chapters,
            chapters=[ch.model_dump() for ch in outline.chapters],
            overall_arc=outline.overall_arc,
            act_breaks=outline.act_breaks,
            notes=outline.notes,
            created_at=outline.created_at,
            updated_at=outline.updated_at,
            saved=True,
        )

    # Fallback: generate on demand
    outline = outline_agent.generate(record.story, target_chapters=30)
    outline.created_at = _now()
    outline.updated_at = _now()

    return OutlineResponse(
        story_id=outline.story_id,
        genre=outline.genre,
        style=outline.style,
        total_chapters=outline.total_chapters,
        chapters=[ch.model_dump() for ch in outline.chapters],
        overall_arc=outline.overall_arc,
        act_breaks=outline.act_breaks,
        notes=outline.notes,
        created_at=outline.created_at,
        updated_at=outline.updated_at,
        saved=False,
    )


@router.put("/stories/{story_id}/outline")
def update_outline(story_id: str, payload: UpdateOutlineRequest) -> OutlineResponse:
    record = store.get(story_id)
    if record is None:
        raise HTTPException(status_code=404, detail="story_not_found")

    existing = store.get_outline(story_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="outline_not_found")

    existing.overall_arc = payload.overall_arc
    existing.act_breaks = payload.act_breaks
    existing.notes = payload.notes
    existing.updated_at = _now()

    # Update chapters
    from packages.story_core.models import ChapterOutline
    new_chapters: list[ChapterOutline] = []
    for raw in payload.chapters:
        new_chapters.append(ChapterOutline.model_validate(raw))
    existing.chapters = new_chapters

    store.save_outline(story_id, existing)

    return OutlineResponse(
        story_id=existing.story_id,
        genre=existing.genre,
        style=existing.style,
        total_chapters=existing.total_chapters,
        chapters=[ch.model_dump() for ch in existing.chapters],
        overall_arc=existing.overall_arc,
        act_breaks=existing.act_breaks,
        notes=existing.notes,
        created_at=existing.created_at,
        updated_at=existing.updated_at,
        saved=True,
    )


# ── World Bible routes ───────────────────────────────────────

class WorldBibleResponse(BaseModel):
    story_id: str
    world_name: str
    overview: str
    power_system: dict
    locations: list[dict]
    factions: list[dict]
    world_facts: list[str]
    timeline_events: list[dict]
    cultural_notes: list[str]
    glossary: dict[str, str]
    updated_at: str = ""


class WorldBibleRequest(BaseModel):
    world_name: str = ""
    overview: str = ""
    power_system: dict = Field(default_factory=dict)
    locations: list[dict] = Field(default_factory=list)
    factions: list[dict] = Field(default_factory=list)
    world_facts: list[str] = Field(default_factory=list)
    timeline_events: list[dict] = Field(default_factory=list)
    cultural_notes: list[str] = Field(default_factory=list)
    glossary: dict[str, str] = Field(default_factory=dict)


@router.get("/stories/{story_id}/world-bible")
def get_world_bible(story_id: str) -> WorldBibleResponse:
    record = store.get(story_id)
    if record is None:
        raise HTTPException(status_code=404, detail="story_not_found")

    world_bible = store.get_world_bible(story_id)
    if world_bible is None:
        # Create default world bible
        world_bible = WorldBible(
            story_id=story_id,
            world_name=f"{record.story.genre}世界",
            updated_at=_now(),
        )
        store.save_world_bible(story_id, world_bible)

    return WorldBibleResponse(
        story_id=world_bible.story_id,
        world_name=world_bible.world_name,
        overview=world_bible.overview,
        power_system=world_bible.power_system.model_dump(),
        locations=[loc.model_dump() for loc in world_bible.locations],
        factions=[f.model_dump() for f in world_bible.factions],
        world_facts=world_bible.world_facts,
        timeline_events=world_bible.timeline_events,
        cultural_notes=world_bible.cultural_notes,
        glossary=world_bible.glossary,
        updated_at=world_bible.updated_at,
    )


@router.put("/stories/{story_id}/world-bible")
def update_world_bible(story_id: str, payload: WorldBibleRequest) -> WorldBibleResponse:
    record = store.get(story_id)
    if record is None:
        raise HTTPException(status_code=404, detail="story_not_found")

    existing = store.get_world_bible(story_id)
    if existing is None:
        existing = WorldBible(story_id=story_id)

    existing.world_name = payload.world_name
    existing.overview = payload.overview
    existing.world_facts = payload.world_facts
    existing.timeline_events = payload.timeline_events
    existing.cultural_notes = payload.cultural_notes
    existing.glossary = payload.glossary
    existing.updated_at = _now()

    # Parse complex types
    from packages.story_core.models import PowerSystem, WorldLocation, Faction
    if payload.power_system:
        existing.power_system = PowerSystem.model_validate(payload.power_system)
    if payload.locations:
        existing.locations = [WorldLocation.model_validate(loc) for loc in payload.locations]
    if payload.factions:
        existing.factions = [Faction.model_validate(f) for f in payload.factions]

    store.save_world_bible(story_id, existing)

    return WorldBibleResponse(
        story_id=existing.story_id,
        world_name=existing.world_name,
        overview=existing.overview,
        power_system=existing.power_system.model_dump(),
        locations=[loc.model_dump() for loc in existing.locations],
        factions=[f.model_dump() for f in existing.factions],
        world_facts=existing.world_facts,
        timeline_events=existing.timeline_events,
        cultural_notes=existing.cultural_notes,
        glossary=existing.glossary,
        updated_at=existing.updated_at,
    )


# ── Novel Status routes ──────────────────────────────────────

NovelStatusType = Literal["draft", "outlining", "writing", "reviewing", "completed", "paused"]


class NovelStatusResponse(BaseModel):
    story_id: str
    status: NovelStatusType
    total_chapters_planned: int
    total_chapters_written: int
    total_word_count: int
    last_written_chapter: int
    last_written_at: str = ""
    created_at: str = ""
    updated_at: str = ""


class UpdateNovelStatusRequest(BaseModel):
    status: NovelStatusType | None = None
    total_chapters_planned: int | None = None


@router.get("/stories/{story_id}/status")
def get_novel_status(story_id: str) -> NovelStatusResponse:
    record = store.get(story_id)
    if record is None:
        raise HTTPException(status_code=404, detail="story_not_found")

    status = store.get_novel_status(story_id)
    if status is None:
        status = NovelStatus(
            story_id=story_id,
            total_chapters_planned=0,
            total_chapters_written=record.story.current_chapter,
            last_written_chapter=record.story.current_chapter,
            created_at=_now(),
            updated_at=_now(),
        )
        store.save_novel_status(story_id, status)

    return NovelStatusResponse(
        story_id=status.story_id,
        status=status.status,
        total_chapters_planned=status.total_chapters_planned,
        total_chapters_written=status.total_chapters_written,
        total_word_count=status.total_word_count,
        last_written_chapter=status.last_written_chapter,
        last_written_at=status.last_written_at,
        created_at=status.created_at,
        updated_at=status.updated_at,
    )


@router.put("/stories/{story_id}/status")
def update_novel_status(story_id: str, payload: UpdateNovelStatusRequest) -> NovelStatusResponse:
    record = store.get(story_id)
    if record is None:
        raise HTTPException(status_code=404, detail="story_not_found")

    status = store.get_novel_status(story_id)
    if status is None:
        status = NovelStatus(story_id=story_id, created_at=_now())

    if payload.status is not None:
        status.status = payload.status
    if payload.total_chapters_planned is not None:
        status.total_chapters_planned = payload.total_chapters_planned
    status.updated_at = _now()

    store.save_novel_status(story_id, status)

    return NovelStatusResponse(
        story_id=status.story_id,
        status=status.status,
        total_chapters_planned=status.total_chapters_planned,
        total_chapters_written=status.total_chapters_written,
        total_word_count=status.total_word_count,
        last_written_chapter=status.last_written_chapter,
        last_written_at=status.last_written_at,
        created_at=status.created_at,
        updated_at=status.updated_at,
    )


def init_outline_routes() -> APIRouter:
    return router
