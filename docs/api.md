# API Reference

The backend is a FastAPI application mounted from `apps.api.main:app`.

## Health

- `GET /health`: returns `{ "ok": true }`.

## Stories

- `POST /stories`: create a story branch from an outline, genre, style, optional agent settings, and optional characters.
- `GET /stories`: list story summaries.
- `GET /stories/{story_id}`: read story state and generated chapter history.
- `POST /stories/{story_id}/generate`: generate the next chapter synchronously.
- `POST /stories/{story_id}/generate-async`: start chapter generation in the background.
- `GET /stories/{story_id}/generation-status`: poll background generation progress.
- `POST /stories/{story_id}/rollback`: remove the latest chapter and restore story state.
- `POST /stories/{story_id}/rename`: rename a story id.
- `DELETE /stories/{story_id}`: delete a non-root story branch.
- `POST /stories/{story_id}/branch`: create a branch from a previous chapter.

## Projects And Worldbuilding

- `POST /projects`: create a novel project.
- `GET /projects`: list projects.
- `GET /projects/{project_id}`: read project metadata and attached story branches.
- `PATCH /projects/{project_id}`: update project metadata, world summary, constraints, status, or active story.
- `POST /projects/{project_id}/activate-story`: switch the active story branch.
- `POST /projects/{project_id}/enrich-world`: ask the worldbuilding agent to expand world systems and facts.
- `POST /projects/{project_id}/enrich-rulebook`: ask the rulebook agent to expand genre/plugin rules.

## Characters

- `POST /stories/{story_id}/characters/{character_name}/freeze`: freeze an active character so the simulation does not advance them.

## Runtime Settings

- `GET /runtime-settings`: read global and per-agent OpenAI-compatible endpoint settings.
- `PUT /runtime-settings`: save global/per-agent endpoint settings and optional strategy settings.
- `POST /runtime-settings/test`: test the configured endpoint/model.
- `GET /runtime-strategy`: read model strategy defaults.
- `PUT /runtime-strategy`: save model strategy defaults.

## Longform Planning

- `POST /stories/{story_id}/outline/generate`: generate a longform novel outline.
- `GET /stories/{story_id}/outline`: read saved outline.
- `PUT /stories/{story_id}/outline`: save outline.
- `GET /stories/{story_id}/world-bible`: read saved world bible.
- `PUT /stories/{story_id}/world-bible`: save world bible.
- `GET /stories/{story_id}/status`: read longform status.

See `apps/api/routes/stories.py` for exact request and response schemas.
