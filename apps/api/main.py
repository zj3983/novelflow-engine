from __future__ import annotations

from fastapi import FastAPI

from apps.api.routes.stories import init_story_routes


app = FastAPI()
app.include_router(init_story_routes())


@app.get("/health")
def health() -> dict:
    return {"ok": True}
