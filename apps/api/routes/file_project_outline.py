from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.story_core.file_project_store import FileProjectStore


class OutlinePlanGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["initial", "regenerate", "extend"] = "initial"
    guidance: str = Field(default="", max_length=1000)
    restart_from: Literal[
        "outline_foundation",
        "character_roster",
        "chapter_window",
    ] | None = None

    @field_validator("guidance", mode="before")
    @classmethod
    def trim_guidance(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class VolumeWorkflowGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    guidance: str = Field(default="", max_length=1000)

    @field_validator("guidance", mode="before")
    @classmethod
    def trim_guidance(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


def _raise_volume_workflow_write_error(
    exc: Exception,
    *,
    operation: str,
) -> None:
    if not isinstance(exc, ValueError):
        detail = re.sub(r"\s+", " ", str(exc)).strip()[:500]
        raise HTTPException(
            status_code=502,
            detail=(
                f"{operation}_generation_failed:{type(exc).__name__}:"
                f"{detail or 'no_detail'}"
            ),
        ) from exc
    detail = str(exc)
    if detail in {
        "outline_changed_during_volume_design",
        "project_generation_in_progress",
    }:
        raise HTTPException(status_code=409, detail=detail) from exc
    if "generation_failed" in detail or detail in {
        "runtime_unavailable",
        "invalid_next_volume_json",
    }:
        raise HTTPException(status_code=502, detail=detail) from exc
    raise HTTPException(status_code=422, detail=detail) from exc


def register_file_project_outline_routes(
    router: APIRouter,
    *,
    store_for: Callable[[str], FileProjectStore],
    planning_generator: Callable[[], Any],
) -> None:
    @router.get("/file-projects/{project_id}/outline")
    def get_file_project_outline(project_id: str) -> dict[str, Any]:
        try:
            return store_for(project_id).project_outline()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/file-projects/{project_id}/outline/volume-workflow")
    def get_file_project_volume_workflow(
        project_id: str,
        target_chapter: int,
    ) -> dict[str, Any]:
        try:
            return store_for(project_id).volume_workflow_status(target_chapter)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/file-projects/{project_id}/outline/volumes/next")
    def design_file_project_next_volume(
        project_id: str,
        payload: VolumeWorkflowGenerationRequest | None = None,
    ) -> dict[str, Any]:
        try:
            return store_for(project_id).design_next_volume(
                planning_generator(),
                guidance=payload.guidance if payload else "",
            )
        except Exception as exc:
            _raise_volume_workflow_write_error(exc, operation="next_volume")

    @router.post("/file-projects/{project_id}/outline/volumes/{volume_id}/detail")
    def generate_file_project_volume_detail(
        project_id: str,
        volume_id: str,
        payload: VolumeWorkflowGenerationRequest | None = None,
    ) -> dict[str, Any]:
        try:
            return store_for(project_id).generate_volume_detail(
                planning_generator(),
                volume_id=volume_id,
                guidance=payload.guidance if payload else "",
            )
        except Exception as exc:
            _raise_volume_workflow_write_error(exc, operation="volume_detail")

    @router.get("/file-projects/{project_id}/outline/extension-readiness")
    def get_file_project_outline_extension_readiness(
        project_id: str,
    ) -> dict[str, Any]:
        try:
            return store_for(project_id).outline_extension_readiness()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/file-projects/{project_id}/outline/generate")
    def generate_file_project_outline_plan(
        project_id: str,
        payload: OutlinePlanGenerationRequest,
    ) -> dict[str, Any]:
        store = store_for(project_id)
        try:
            kwargs: dict[str, Any] = {
                "mode": payload.mode,
                "guidance": payload.guidance,
            }
            if payload.restart_from is not None:
                kwargs["restart_from"] = payload.restart_from
            return store.generate_outline_plan(planning_generator(), **kwargs)
        except ValueError as exc:
            detail = str(exc)
            if (
                detail == "outline_planning_generation_failed"
                and exc.__cause__ is not None
            ):
                cause = exc.__cause__
                cause_text = re.sub(r"\s+", " ", str(cause)).strip()[:500]
                detail = (
                    f"{detail}:{type(cause).__name__}:"
                    f"{cause_text or 'no_detail'}"
                )
            status_code = (
                502 if detail.startswith("outline_planning_generation_failed") else 422
            )
            raise HTTPException(status_code=status_code, detail=detail) from exc

    @router.get("/file-projects/{project_id}/outline/generation-checkpoints")
    def get_outline_generation_checkpoints(project_id: str) -> dict[str, Any]:
        return store_for(project_id).outline_generation_checkpoints()

    @router.put("/file-projects/{project_id}/outline")
    def update_file_project_outline(
        project_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return store_for(project_id).update_project_outline(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
