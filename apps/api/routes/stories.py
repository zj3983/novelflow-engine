from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.api.storage import InMemoryStoryStore
from packages.story_core.engine import StoryEngine
from packages.story_core.models import AgentSettings, CharacterState, StoryState


router = APIRouter()
store = InMemoryStoryStore()
engine = StoryEngine()


class CreateStoryRequest(BaseModel):
    story_id: str
    outline: str
    genre: str
    style: str
    agent_settings: AgentSettings = Field(default_factory=AgentSettings)
    characters: list[CharacterState] = Field(default_factory=list)


class StoryResponse(BaseModel):
    story_id: str
    outline: str
    genre: str
    style: str
    current_chapter: int
    agent_settings: dict = Field(default_factory=dict)
    characters: list[dict] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)
    parent_story_id: str | None = None
    branched_from_chapter: int | None = None


class BranchStoryRequest(BaseModel):
    new_story_id: str
    from_chapter: int = Field(ge=0)


class StorySummaryResponse(BaseModel):
    story_id: str
    current_chapter: int
    parent_story_id: str | None = None
    branched_from_chapter: int | None = None


class RenameStoryRequest(BaseModel):
    new_story_id: str


class DeleteStoryResponse(BaseModel):
    deleted: bool
    story_id: str


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
        agent_settings=record.story.agent_settings.model_dump(),
        characters=[character.model_dump() for character in record.story.characters],
        history=[b.model_dump() for b in record.history],
        parent_story_id=record.parent_story_id,
        branched_from_chapter=record.branched_from_chapter,
    )


def _serialize_story_summary(record) -> StorySummaryResponse:
    return StorySummaryResponse(
        story_id=record.story.story_id,
        current_chapter=record.story.current_chapter,
        parent_story_id=record.parent_story_id,
        branched_from_chapter=record.branched_from_chapter,
    )


@router.post("/stories")
def create_story(payload: CreateStoryRequest) -> StoryResponse:
    story = StoryState(
        story_id=payload.story_id,
        outline=payload.outline,
        genre=payload.genre,
        style=payload.style,
        current_chapter=0,
        agent_settings=payload.agent_settings,
        characters=payload.characters,
    )
    store.create(story)
    return _serialize_story(payload.story_id)


@router.get("/stories")
def list_stories() -> list[StorySummaryResponse]:
    return [_serialize_story_summary(record) for record in store.list()]


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


@router.post("/stories/{story_id}/rename")
def rename_story(story_id: str, payload: RenameStoryRequest) -> StoryResponse:
    if store.get(story_id) is None:
        raise HTTPException(status_code=404, detail="story_not_found")
    try:
        store.rename(story_id, payload.new_story_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="story_exists") from exc
    return _serialize_story(payload.new_story_id)


@router.delete("/stories/{story_id}")
def delete_story(story_id: str) -> DeleteStoryResponse:
    if store.get(story_id) is None:
        raise HTTPException(status_code=404, detail="story_not_found")
    try:
        deleted = store.delete(story_id)
    except ValueError as exc:
        detail = str(exc)
        if detail == "cannot_delete_root":
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=409, detail="story_has_children") from exc
    return DeleteStoryResponse(deleted=True, story_id=deleted.story.story_id)


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
