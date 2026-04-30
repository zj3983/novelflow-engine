# Deployment

## Local Development

1. Copy `.env.example` to `.env.local`.
2. Fill either `OPENAI_API_KEY` or `DASHSCOPE_API_KEY`.
3. Install dependencies:

```bash
uv sync --extra dev
cd apps/web
npm ci
```

4. Start the API:

```bash
uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```

5. Start the web app:

```bash
cd apps/web
npm run dev
```

## Docker Compose

Use Docker Compose when you want the API, web app, and SQLite data volume to move together:

```bash
docker compose up --build
```

The API listens on `http://127.0.0.1:8000`.
The web app listens on `http://127.0.0.1:3000`.
Story data is persisted in the `novel-data` volume at `/data/stories.db`.

## Environment Variables

Recommended production variables:

```bash
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=
NOVEL_AUTOGROWTH_DEFAULT_MODEL=qwen3.6-plus
NOVEL_AUTOGROWTH_FAST_MODEL=qwen3.6-plus
NOVEL_AUTOGROWTH_DB_PATH=/data/stories.db
NOVEL_AUTOGROWTH_RUNTIME_CONFIG_PATH=/data/runtime_config.json
NOVEL_AUTOGROWTH_CORS_ORIGINS=https://your-web-domain.example
```

## Production Notes

- Put the API behind HTTPS.
- Restrict `NOVEL_AUTOGROWTH_CORS_ORIGINS` to the real web domain.
- Store secrets in the host/container secret manager, not in Git.
- Back up the SQLite database volume regularly.
- For multi-user production, migrate the `SQLiteStoryStore` interface to PostgreSQL while keeping the route layer unchanged.
