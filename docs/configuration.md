# Configuration

Novel Autogrowth Engine loads environment values from the real process
environment first, then `.env`, then `.env.local`. Values from the real process
environment are never overwritten by files.

## Required Runtime Settings

Use `.env.example` as the starting point:

```powershell
Copy-Item .env.example .env.local
```

For the current Qwen-compatible setup:

```env
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=your-api-key
NOVEL_AUTOGROWTH_DEFAULT_MODEL=qwen3.6-plus
NOVEL_AUTOGROWTH_FAST_MODEL=qwen3.6-plus
```

`DASHSCOPE_API_KEY` is also accepted as a fallback if `OPENAI_API_KEY` is not
set.

## Persistence

The API uses a SQLite-backed `SQLiteStoryStore` by default. Data is persisted
to:

```text
apps/api/data/stories.db
```

Override it with:

```env
NOVEL_AUTOGROWTH_DB_PATH=D:/novel-autogrowth/stories.db
```

`STORY_DB_PATH` is still supported for backwards compatibility.

## Runtime Config Persistence

Runtime settings changed from the UI are stored outside the repo by default:

```text
~/.novel-autogrowth-engine/runtime_config.json
```

Override with:

```env
NOVEL_AUTOGROWTH_RUNTIME_CONFIG_PATH=D:/novel-autogrowth/runtime_config.json
```

## CORS

Development origins are allowed by default. Production should provide an
explicit comma-separated list:

```env
NOVEL_AUTOGROWTH_CORS_ORIGINS=https://your-domain.example
```

## Storage Roadmap

SQLite is the supported development and single-user store. A future PostgreSQL
store should keep the same `SQLiteStoryStore` public methods behind a storage
protocol, then migrate serialized story/project JSON columns into JSONB with
indexes on project id, story id, and chapter number.
