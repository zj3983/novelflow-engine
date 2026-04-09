from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.api.storage import InMemoryStoryStore
from packages.story_core.engine import StoryEngine
from packages.story_core.models import CharacterState, StoryState


router = APIRouter()
store = InMemoryStoryStore()
engine = StoryEngine()


class CreateStoryRequest(BaseModel):
    story_id: str
    outline: str
    genre: str
    style: str
    characters: list[CharacterState] = Field(default_factory=list)


class StoryResponse(BaseModel):
    story_id: str
    outline: str
    genre: str
    style: str
    current_chapter: int
    characters: list[dict] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)


class BranchStoryRequest(BaseModel):
    new_story_id: str
    from_chapter: int = Field(ge=0)


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
        characters=[character.model_dump() for character in record.story.characters],
        history=[b.model_dump() for b in record.history],
    )


@router.post("/stories")
def create_story(payload: CreateStoryRequest) -> StoryResponse:
    story = StoryState(
        story_id=payload.story_id,
        outline=payload.outline,
        genre=payload.genre,
        style=payload.style,
        current_chapter=0,
        characters=payload.characters,
    )
    store.create(story)
    return _serialize_story(payload.story_id)


@router.get("/stories/{story_id}")
def get_story(story_id: str) -> StoryResponse:
    return _serialize_story(story_id)


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


@router.post("/stories/{story_id}/branch")
def branch_story(story_id: str, payload: BranchStoryRequest) -> StoryResponse:
    if store.get(story_id) is None:
        raise HTTPException(status_code=404, detail="story_not_found")
    try:
        store.branch_from(story_id, payload.new_story_id, payload.from_chapter)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="story_exists") from exc
    except IndexError as exc:
        raise HTTPException(status_code=404, detail="chapter_not_found") from exc
    return _serialize_story(payload.new_story_id)


@router.post("/stories/{story_id}/characters/{character_name}/freeze")
def freeze_character(story_id: str, character_name: str) -> StoryResponse:
    if store.get(story_id) is None:
        raise HTTPException(status_code=404, detail="story_not_found")
    try:
        store.freeze_character(story_id, character_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="character_not_found") from exc
    return _serialize_story(story_id)


def init_story_routes() -> APIRouter:
    return router
