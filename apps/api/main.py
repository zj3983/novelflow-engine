from __future__ import annotations

import os
import json
from typing import Any

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from apps.api.routes.book_import import init_book_import_routes
from apps.api.routes.continuation_imports import init_continuation_import_routes
from apps.api.routes.file_projects import init_file_project_routes
from apps.api.routes.novel_types import init_novel_type_routes
from apps.api.routes.outlines import init_outline_routes
from apps.api.routes.prompt_audit import init_prompt_audit_routes
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


def _submitted_api_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).casefold() == "api_key" and isinstance(nested, str) and nested:
                keys.add(nested)
            keys.update(_submitted_api_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.update(_submitted_api_keys(nested))
    return keys


def _redact_validation_value(value: Any, secrets: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: "********" if str(key).casefold() == "api_key" else _redact_validation_value(nested, secrets)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [_redact_validation_value(nested, secrets) for nested in value]
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            redacted = redacted.replace(secret, "********")
        return redacted
    return value


@app.exception_handler(RequestValidationError)
async def redact_request_validation_error(request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI includes invalid input in Pydantic errors; never echo submitted API keys."""
    try:
        submitted = json.loads((await request.body()) or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        submitted = {}
    secrets = _submitted_api_keys(submitted)
    detail = _redact_validation_value(exc.errors(), secrets)
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(detail)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(init_story_routes())
app.include_router(init_file_project_routes())
app.include_router(init_novel_type_routes())
app.include_router(init_book_import_routes())
app.include_router(init_continuation_import_routes())
app.include_router(init_outline_routes())
app.include_router(init_skill_pack_routes())
app.include_router(init_prompt_audit_routes())


@app.get("/", include_in_schema=False)
def workbench() -> RedirectResponse:
    frontend_url = os.getenv("NOVEL_AUTOGROWTH_FRONTEND_URL", "http://localhost:3000").rstrip("/")
    return RedirectResponse(f"{frontend_url}/projects")


@app.get("/health")
def health() -> dict:
    return {"ok": True}
