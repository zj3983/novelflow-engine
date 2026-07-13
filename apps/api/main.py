from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes.book_import import init_book_import_routes
from apps.api.routes.file_projects import init_file_project_routes
from apps.api.routes.outlines import init_outline_routes
from apps.api.routes.skill_packs import init_skill_pack_routes
from apps.api.routes.stories import init_story_routes
from packages.story_core.env import load_environment_files


load_environment_files()


def _cors_origins() -> list[str]:
    configured = os.getenv("NOVEL_AUTOGROWTH_CORS_ORIGINS") or os.getenv("CORS_ALLOW_ORIGINS")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
        "http://127.0.0.1:3003",
        "http://127.0.0.1:3004",
        "http://127.0.0.1:3005",
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "http://localhost:3004",
        "http://localhost:3005",
    ]


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(init_story_routes())
app.include_router(init_file_project_routes())
app.include_router(init_book_import_routes())
app.include_router(init_outline_routes())
app.include_router(init_skill_pack_routes())


@app.get("/health")
def health() -> dict:
    return {"ok": True}
