# Publishing safety hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent generated publishing assets from overwriting concurrent human edits, avoid client/server timeout mismatches, bound image HTTP payloads, and provide a Docker-safe Chinese title font.

**Architecture:** Publishing routes will snapshot mutable publishing values before remote generation and give the store those snapshots as compare-and-set preconditions. Publishing remote calls use explicit finite retry budgets that fit their UI deadlines. The shared HTTP utility reads bounded chunks and rejects a known oversized response before allocation; image requests supply its 20 MiB response budget. The API image supplies a compact Noto CJK font and exports its known path.

**Tech Stack:** FastAPI, Python urllib, pytest, TypeScript API client, Docker Compose.

---

### Task 1: CAS generated synopsis and cover prompt

**Files:**
- Modify: `apps/api/routes/file_projects.py`
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/api/test_publishing_asset_routes.py`

- [ ] Write route tests whose generation callback performs a manual update before return, then assert `409 publishing_asset_stale_synopsis` / `409 publishing_asset_stale_cover` and retained manual data.
- [ ] Run: `pytest -q tests/api/test_publishing_asset_routes.py -k stale` and confirm each new assertion fails before implementation.
- [ ] Add store preconditions for the snapshot values and map stale failures to 409 at the generation routes.
- [ ] Re-run the focused route tests and commit the green changes.

### Task 2: Bound publishing generation duration

**Files:**
- Modify: `packages/story_core/publishing_assets.py`
- Modify: `packages/story_core/cover_image_provider.py`
- Modify: `apps/web/lib/api.ts`
- Test: `tests/story_core/test_publishing_assets.py`
- Test: `tests/story_core/test_cover_image_provider.py`

- [ ] Write tests asserting the explicit retry configuration and API client generation deadlines.
- [ ] Run the focused tests and confirm the expected configuration is absent.
- [ ] Use one non-retried 90-second image request and explicit two-attempt 80-second text requests; expose matching 100-second UI deadlines.
- [ ] Re-run the focused tests.

### Task 3: Stream-bound image API JSON

**Files:**
- Modify: `packages/story_core/http_retry.py`
- Modify: `packages/story_core/cover_image_provider.py`
- Test: `tests/story_core/test_http_retry.py`

- [ ] Write tests for early Content-Length rejection and chunked 20 MiB limit rejection without an unbounded read.
- [ ] Run the focused tests and confirm the response reader is currently unbounded.
- [ ] Add a `RetryConfig.max_response_bytes` option and bounded chunk reader; request it for cover generation and map the overflow to `invalid_image_payload`.
- [ ] Re-run the focused tests.

### Task 4: Docker font and docs

**Files:**
- Modify: `Dockerfile.api`
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `docs/configuration.md`
- Test: `tests/test_docker_configuration.py`

- [ ] Write a static configuration test for the installed CJK font and the same configured path in image and compose.
- [ ] Run it and confirm it fails.
- [ ] Install `fonts-noto-cjk` without recommended packages, set the fixed font path, and document that Docker uses it by default.
- [ ] Run focused test suites, `npx tsc --noEmit`, and `git diff --check`, then commit.
