# Novel Autogrowth Engine

This project turns a novel outline into a continuously evolving chapter stream.

The backend keeps story state, memory compression, and chapter continuity checks in Python. The web workbench lets you trigger chapter generation and inspect the evolving story bundle from the browser.

## Local development

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
