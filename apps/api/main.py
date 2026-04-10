from __future__ import annotations

from fastapi import FastAPI

from apps.api.routes.book_import import init_book_import_routes
from apps.api.routes.stories import init_story_routes


app = FastAPI()
app.include_router(init_story_routes())
app.include_router(init_book_import_routes())


@app.get("/health")
def health() -> dict:
    return {"ok": True}
