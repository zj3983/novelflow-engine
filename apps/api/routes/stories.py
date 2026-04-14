from __future__ import annotations

import json
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from apps.api.storage import InMemoryStoryStore
from packages.story_core.engine import StoryEngine
from packages.story_core.models import AgentSettings, CharacterState, StoryState
from packages.story_core.runtime_config import (
    OpenAIRuntimeSettings,
    get_all_runtime_settings,
    resolve_openai_runtime_settings,
    set_all_runtime_settings,
)


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
    agent_runtime: dict = Field(default_factory=dict)
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


class RuntimeSettingsResponse(BaseModel):
    global_: OpenAIRuntimeSettings = Field(alias="global")
    agents: dict[str, OpenAIRuntimeSettings] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class RuntimeSettingsRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    global_: OpenAIRuntimeSettings | None = Field(default=None, alias="global")
    agents: dict[str, OpenAIRuntimeSettings] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


class RuntimeSettingsTestRequest(BaseModel):
    agent_name: str
    model_name: str | None = None
    runtime_settings: RuntimeSettingsRequest = Field(default_factory=RuntimeSettingsRequest)


class RuntimeSettingsTestResponse(BaseModel):
    ok: bool
    agent_name: str
    message: str


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
        agent_runtime=record.story.agent_runtime.model_dump(),
        characters=[character.model_dump() for character in record.story.characters],
        history=[bundle.model_dump() for bundle in record.history],
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


def _serialize_runtime_settings() -> dict[str, object]:
    runtime = get_all_runtime_settings()
    return {
        "global": runtime["global"].model_dump(),
        "agents": {
            name: agent.model_dump()
            for name, agent in runtime["agents"].items()
        },
    }


def _runtime_target_label(agent_name: str) -> str:
    return {
        "global": "全局默认",
        "character": "角色代理",
        "director": "导演代理",
        "writer": "写作代理",
        "memory": "记忆代理",
    }.get(agent_name, agent_name)


def _probe_via_chat_completions(base_url: str, api_key: str, model_name: str) -> None:
    payload = json.dumps(
        {
            "model": model_name,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10):
        return None


def _probe_via_models(base_url: str, api_key: str) -> None:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=10):
        return None


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


@router.get("/runtime-settings")
def read_runtime_settings() -> dict[str, object]:
    return _serialize_runtime_settings()


@router.put("/runtime-settings")
def update_runtime_settings(payload: RuntimeSettingsRequest) -> dict[str, object]:
    data = payload.model_dump(by_alias=True)
    if data.get("global") is None and payload.api_key is not None and payload.base_url is not None:
        data["global"] = {
            "api_key": payload.api_key,
            "base_url": payload.base_url,
        }
    elif data.get("global") is None and (payload.api_key is not None or payload.base_url is not None):
        data["global"] = {
            "api_key": payload.api_key or "",
            "base_url": payload.base_url or "https://api.openai.com/v1",
        }
    if "agents" not in data:
        data["agents"] = {}
    set_all_runtime_settings(data)
    return _serialize_runtime_settings()


@router.post("/runtime-settings/test")
def test_runtime_settings(payload: RuntimeSettingsTestRequest) -> RuntimeSettingsTestResponse:
    agent_name = payload.agent_name
    if agent_name not in {"character", "director", "writer", "memory", "global"}:
        raise HTTPException(status_code=400, detail="invalid_agent_name")

    overrides = payload.runtime_settings.model_dump(by_alias=True)
    if agent_name == "global":
        resolved = resolve_openai_runtime_settings(overrides=overrides)
    else:
        resolved = resolve_openai_runtime_settings(agent_name=agent_name, overrides=overrides)

    if not resolved.api_key or not resolved.base_url:
        return RuntimeSettingsTestResponse(
            ok=False,
            agent_name=agent_name,
            message="缺少 API 密钥或接口地址",
        )

    try:
        if payload.model_name:
            try:
                _probe_via_chat_completions(
                    base_url=resolved.base_url,
                    api_key=resolved.api_key,
                    model_name=payload.model_name,
                )
            except urllib.error.HTTPError as exc:
                if exc.code not in {404, 405}:
                    raise
                _probe_via_models(base_url=resolved.base_url, api_key=resolved.api_key)
        else:
            _probe_via_models(base_url=resolved.base_url, api_key=resolved.api_key)
        return RuntimeSettingsTestResponse(
            ok=True,
            agent_name=agent_name,
            message=f"{_runtime_target_label(agent_name)} 连接正常",
        )
    except Exception as exc:  # pragma: no cover - surfaced in UI and tests
        return RuntimeSettingsTestResponse(
            ok=False,
            agent_name=agent_name,
            message=f"{_runtime_target_label(agent_name)} 连接失败：{exc}",
        )


def init_story_routes() -> APIRouter:
    return router
