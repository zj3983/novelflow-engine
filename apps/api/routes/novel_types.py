from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from apps.api.routes import file_projects, stories
from packages.story_core.novel_type_library import NovelTypeLibrary, NovelTypeRecord


router = APIRouter()
NOVEL_TYPE_ID_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"


class NovelTypeRulebookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    progression_rules: list[str] = Field(default_factory=list)
    economy_rules: list[str] = Field(default_factory=list)
    quest_rules: list[str] = Field(default_factory=list)
    faction_rules: list[str] = Field(default_factory=list)
    panel_rules: list[str] = Field(default_factory=list)
    chapter_formula: list[str] = Field(default_factory=list)
    forbidden_breaks: list[str] = Field(default_factory=list)

    @field_validator("*", mode="before")
    @classmethod
    def trim_rule_lists(cls, value: Any) -> Any:
        return _trim_string_list(value)


class NovelTypeWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=NOVEL_TYPE_ID_PATTERN)
    name: str = Field(min_length=1)
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    core_promises: list[str] = Field(default_factory=list)
    ledger_fields: list[str] = Field(default_factory=list)
    rulebook: NovelTypeRulebookRequest = Field(default_factory=NovelTypeRulebookRequest)
    quality_checks: list[str] = Field(default_factory=list)
    trope_templates: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("name", "description", mode="before")
    @classmethod
    def trim_strings(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "keywords", "core_promises", "ledger_fields", "quality_checks", mode="before"
    )
    @classmethod
    def trim_string_lists(cls, value: Any) -> Any:
        return _trim_string_list(value)


def _trim_string_list(value: Any) -> Any:
    if not isinstance(value, list):
        return value
    trimmed = [item.strip() if isinstance(item, str) else item for item in value]
    if any(not isinstance(item, str) or not item for item in trimmed):
        raise ValueError("List values must be non-blank strings")
    return trimmed


def _serialize(record: NovelTypeRecord) -> dict[str, Any]:
    return record.to_dict()


def _payload_dict(payload: NovelTypeWriteRequest) -> dict[str, Any]:
    return payload.model_dump()


def _project_uses_type(world_blueprint: Any, type_id: str) -> bool:
    if not isinstance(world_blueprint, dict):
        return False
    selected = world_blueprint.get("genre_plugin_ids")
    if isinstance(selected, str):
        selected = [selected]
    if not isinstance(selected, list):
        return False
    canonical_type_id = type_id.strip().casefold()
    return canonical_type_id in {str(item).strip().casefold() for item in selected}


def _referencing_project_ids(type_id: str) -> list[str]:
    project_ids: set[str] = set()
    for project in stories.store.list_projects():
        if _project_uses_type(project.world_blueprint, type_id):
            project_ids.add(project.project_id)
    for store in file_projects._stores():
        project = store.project()
        state = store.state()
        project_uses_type = _project_uses_type(project.get("world_blueprint"), type_id)
        state_uses_type = _project_uses_type(state.get("world_blueprint"), type_id)
        if project_uses_type or state_uses_type:
            project_ids.add(str(project.get("project_id") or store.root.name))
    return sorted(project_ids)


def init_novel_type_routes() -> APIRouter:
    @router.get("/novel-types")
    def list_registered_novel_types() -> list[dict[str, Any]]:
        return [_serialize(record) for record in NovelTypeLibrary().list()]

    @router.post("/novel-types", status_code=status.HTTP_201_CREATED)
    def create_registered_novel_type(payload: NovelTypeWriteRequest) -> dict[str, Any]:
        try:
            return _serialize(NovelTypeLibrary().create(_payload_dict(payload)))
        except ValueError as exc:
            detail = str(exc)
            status_code = (
                status.HTTP_409_CONFLICT
                if "already exists" in detail or "collides" in detail
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            )
            raise HTTPException(status_code=status_code, detail=detail) from exc

    @router.put("/novel-types/{type_id}")
    def update_registered_novel_type(
        payload: NovelTypeWriteRequest,
        type_id: str = Path(pattern=NOVEL_TYPE_ID_PATTERN),
    ) -> dict[str, Any]:
        if payload.id != type_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Payload novel type ID must match the path ID",
            )
        try:
            return _serialize(NovelTypeLibrary().update(type_id, _payload_dict(payload)))
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="novel_type_not_found",
            ) from exc
        except ValueError as exc:
            detail = str(exc)
            status_code = (
                status.HTTP_409_CONFLICT
                if "already exists" in detail or "collides" in detail
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            )
            raise HTTPException(status_code=status_code, detail=detail) from exc

    @router.delete("/novel-types/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_registered_novel_type(
        type_id: str = Path(pattern=NOVEL_TYPE_ID_PATTERN),
    ) -> Response:
        library = NovelTypeLibrary()
        record = library.get(type_id)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="novel_type_not_found",
            )
        if record.builtin:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A built-in novel type cannot be deleted",
            )
        project_ids = _referencing_project_ids(record.id)
        if project_ids:
            references = ", ".join(project_ids)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Novel type {record.id!r} is used by project(s): {references}",
            )
        try:
            library.delete(record.id)
        except KeyError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="novel_type_not_found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
