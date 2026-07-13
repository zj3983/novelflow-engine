from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from packages.story_core.skill_packs import (
    get_skill_pack,
    import_skill_pack_from_path,
    import_skill_pack_from_zip,
    list_skill_packs,
    normalize_skill_id,
)


router = APIRouter()


class ImportSkillPackRequest(BaseModel):
    source_path: str


def _pack_detail(pack) -> dict[str, Any]:
    data = pack.summary()
    data["root_skill"] = pack.root_content
    data["modules"] = [
        {
            "module_id": module.module_id,
            "title": module.title,
            "description": module.description,
            "summary": module.summary,
            "purposes": module.purposes,
            "relative_path": module.relative_path,
            "content": module.content,
        }
        for module in pack.modules
    ]
    return data


def init_skill_pack_routes() -> APIRouter:
    @router.get("/skill-packs")
    def list_registered_skill_packs() -> list[dict[str, Any]]:
        return [pack.summary() for pack in list_skill_packs()]

    @router.get("/skill-packs/{skill_id}")
    def get_registered_skill_pack(skill_id: str) -> dict[str, Any]:
        pack = get_skill_pack(skill_id)
        if pack is None:
            raise HTTPException(status_code=404, detail="skill_pack_not_found")
        return _pack_detail(pack)

    @router.post("/skill-packs/import")
    def import_registered_skill_pack(payload: ImportSkillPackRequest) -> dict[str, Any]:
        try:
            pack = import_skill_pack_from_path(payload.source_path)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _pack_detail(pack)

    @router.post("/skill-packs/upload")
    async def upload_registered_skill_pack(body: bytes = Body(..., media_type="application/zip")) -> dict[str, Any]:
        try:
            pack = import_skill_pack_from_zip(body)
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _pack_detail(pack)

    @router.get("/skill-packs/{skill_id}/exists")
    def skill_pack_exists(skill_id: str) -> dict[str, Any]:
        normalized = normalize_skill_id(skill_id)
        return {"skill_id": normalized, "exists": get_skill_pack(normalized) is not None}

    return router
