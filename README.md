# Novel Autogrowth Engine

This project turns a novel outline into a continuously evolving chapter stream.

The backend keeps story state, memory compression, and chapter continuity checks in Python. The web workbench lets you trigger chapter generation and inspect the evolving story bundle from the browser.

## Local development

Create local configuration:

```bash
cp .env.example .env.local
```

API:

```bash
uvicorn apps.api.main:app --reload --port 8000
```

Web:

```bash
cd apps/web
npm install
npm run dev
```

Tests:

```bash
pytest -q
cd apps/web
npx playwright test
```

## Configuration

The API loads `.env` and `.env.local` without overriding real process
environment variables. Runtime settings changed in the UI are persisted under
`~/.novel-autogrowth-engine/runtime_config.json` by default.

State is persisted with SQLite through `SQLiteStoryStore`; the default database
path is `apps/api/data/stories.db`.

See `docs/configuration.md` for model, API key, database, CORS, and storage
roadmap details. See `docs/api.md` for backend endpoints and
`docs/deployment.md` for Docker/Compose deployment.
