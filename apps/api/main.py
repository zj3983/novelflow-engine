from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
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
_RUNTIME_SECRET_PATHS = {("PUT", "/runtime-settings"), ("POST", "/runtime-settings/test")}
_RUNTIME_BODY_MAX = 1024 * 1024


def _runtime_secret_request(request) -> bool:
    return (request.method, request.url.path) in _RUNTIME_SECRET_PATHS


def _json_depth_exceeds(data: bytes, limit: int = 64) -> bool:
    depth = 0
    in_string = False
    escaped = False
    for byte in data:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                in_string = False
            continue
        if byte == 34:
            in_string = True
        elif byte in (91, 123):
            depth += 1
            if depth > limit:
                return True
        elif byte in (93, 125):
            depth = max(0, depth - 1)
    return False


@app.middleware("http")
async def bound_runtime_secret_bodies(request, call_next):
    if not _runtime_secret_request(request):
        return await call_next(request)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _RUNTIME_BODY_MAX:
                return JSONResponse(status_code=413, content={"detail": "runtime_settings_payload_too_large"})
        except ValueError:
            return JSONResponse(status_code=422, content={"detail": [{"type": "validation_error", "loc": ["body"], "msg": "invalid runtime settings"}]})
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _RUNTIME_BODY_MAX:
            return JSONResponse(status_code=413, content={"detail": "runtime_settings_payload_too_large"})
        chunks.append(chunk)
    body = b"".join(chunks)
    if _json_depth_exceeds(body):
        return JSONResponse(status_code=422, content={"detail": [{"type": "validation_error", "loc": ["body"], "msg": "invalid runtime settings"}]})
    request._body = body
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def redact_runtime_validation_error(request, exc: RequestValidationError):
    if not _runtime_secret_request(request):
        return await request_validation_exception_handler(request, exc)
    details = []
    for error in exc.errors()[:32]:
        raw_loc = error.get("loc")
        loc = ["body"]
        if isinstance(raw_loc, tuple) and raw_loc and raw_loc[0] != "body":
            loc = [str(raw_loc[0])[:32]]
        details.append({"type": str(error.get("type") or "validation_error")[:80], "loc": loc, "msg": "invalid runtime settings"})
    return JSONResponse(status_code=422, content={"detail": details or [{"type": "validation_error", "loc": ["body"], "msg": "invalid runtime settings"}]})
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
