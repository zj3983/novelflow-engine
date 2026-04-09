from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.api.storage import InMemoryStoryStore
from packages.story_core.engine import StoryEngine
from packages.story_core.models import StoryState


router = APIRouter()
store = InMemoryStoryStore()
engine = StoryEngine()


class CreateStoryRequest(BaseModel):
    story_id: str
    outline: str
    genre: str
    style: str


class StoryResponse(BaseModel):
    story_id: str
    outline: str
    genre: str
    style: str
    current_chapter: int
    history: list[dict] = Field(default_factory=list)


def _serialize_story(story_id: str) -> StoryResponse:
    record = store.get(story_id)
    if record is None:
        raise HTTPException(status_code=404, detail="story_not_found")
    return StoryResponse(
        story_id=record.story.story_id,
        outline=record.story.outline,
        genre=record.story.genre,
        style=record.story.style,
        current_chapter=record.story.current_chapter,
        history=[b.model_dump() for b in record.history],
    )


@router.post("/stories")
def create_story(payload: CreateStoryRequest) -> StoryResponse:
    # For now, we don't ingest character setup from the API; UI can add later.
    story = StoryState(
        story_id=payload.story_id,
        outline=payload.outline,
        genre=payload.genre,
        style=payload.style,
        current_chapter=0,
        characters=[],
    )
    store.create(story)
    return _serialize_story(payload.story_id)


@router.post("/stories/{story_id}/generate")
def generate_next_chapter(story_id: str) -> dict:
    if store.get(story_id) is None:
        raise HTTPException(status_code=404, detail="story_not_found")
    bundle = store.generate_next(story_id, engine)
    return bundle.model_dump()


@router.post("/stories/{story_id}/rollback")
def rollback(story_id: str) -> StoryResponse:
    if store.get(story_id) is None:
        raise HTTPException(status_code=404, detail="story_not_found")
    store.rollback_last(story_id)
    return _serialize_story(story_id)


def init_story_routes() -> APIRouter:
    return router
