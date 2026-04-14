"""API routes for outline generation and management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.api.routes.stories import store
from apps.api.routes.stories import engine
from packages.story_core.models import NovelOutline
from packages.story_core.outline_agent import OutlineAgent


router = APIRouter()
outline_agent = OutlineAgent()


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


class ChapterOutlineResponse(BaseModel):
    chapter_number: int
    chapter_title: str
    summary: str
    key_characters: list[str]
    primary_conflict: str
    cadence: str
    word_count_estimate: int
    arc_phase: str


@router.post("/stories/{story_id}/outline/generate")
def generate_outline(story_id: str, payload: GenerateOutlineRequest = GenerateOutlineRequest()) -> OutlineResponse:
    record = store.get(story_id)
    if record is None:
        raise HTTPException(status_code=404, detail="story_not_found")

    outline = outline_agent.generate(record.story, target_chapters=payload.target_chapters)

    return OutlineResponse(
        story_id=outline.story_id,
        genre=outline.genre,
        style=outline.style,
        total_chapters=outline.total_chapters,
        chapters=[ch.model_dump() for ch in outline.chapters],
        overall_arc=outline.overall_arc,
        act_breaks=outline.act_breaks,
        notes=outline.notes,
    )


@router.get("/stories/{story_id}/outline")
def get_outline(story_id: str) -> OutlineResponse:
    record = store.get(story_id)
    if record is None:
        raise HTTPException(status_code=404, detail="story_not_found")

    # Currently outlines are generated on-demand, not stored.
    # If we stored outlines, we'd fetch from DB here.
    # For now, generate fresh.
    outline = outline_agent.generate(record.story, target_chapters=30)

    return OutlineResponse(
        story_id=outline.story_id,
        genre=outline.genre,
        style=outline.style,
        total_chapters=outline.total_chapters,
        chapters=[ch.model_dump() for ch in outline.chapters],
        overall_arc=outline.overall_arc,
        act_breaks=outline.act_breaks,
        notes=outline.notes,
    )


def init_outline_routes() -> APIRouter:
    return router
