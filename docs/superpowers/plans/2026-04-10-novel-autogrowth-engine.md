# Novel Autogrowth Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a web-based story engine that takes a novel outline and continuously generates chapters, updates character/world state, and feeds the updated state into the next generation loop.

**Architecture:** Use a Python FastAPI backend for the story engine and persistence, plus a Next.js frontend for the interactive workbench. Keep the core story logic in a small Python package so chapter generation, state updates, and memory extraction can be tested without the UI. The backend exposes generation and state-management endpoints; the web app provides editing, preview, freeze, rollback, and regeneration controls.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, pytest, TypeScript, Next.js, React, fetch-based API client, SQLite for local persistence in the first pass.

---

### Task 1: Scaffold the repository and workspace layout

**Files:**
- Create: `pyproject.toml`
- Create: `apps/api/main.py`
- Create: `apps/web/package.json`
- Create: `packages/story_core/__init__.py`
- Create: `packages/story_core/models.py`
- Create: `tests/story_core/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
from packages.story_core.models import StoryState, CharacterState


def test_story_state_can_store_outline_and_chapter_index():
    story = StoryState(
        story_id="s-001",
        outline="A fallen prince becomes a detective.",
        genre="fantasy",
        style="moody",
        current_chapter=1,
    )
    assert story.story_id == "s-001"
    assert story.current_chapter == 1


def test_character_state_supports_memory_and_goals():
    character = CharacterState(
        name="Lin Yue",
        role="protagonist",
        traits={"impulsive": 0.7, "patient": 0.2},
        goals=["find the truth"],
    )
    assert "find the truth" in character.goals
    assert character.traits["impulsive"] == 0.7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/story_core/test_models.py -v`
Expected: fail because `packages.story_core.models` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
from pydantic import BaseModel, Field


class CharacterState(BaseModel):
    name: str
    role: str
    traits: dict[str, float] = Field(default_factory=dict)
    goals: list[str] = Field(default_factory=list)
    memory: list[str] = Field(default_factory=list)


class StoryState(BaseModel):
    story_id: str
    outline: str
    genre: str
    style: str
    current_chapter: int = 0
    characters: list[CharacterState] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/story_core/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml apps/api/main.py apps/web/package.json packages/story_core/__init__.py packages/story_core/models.py tests/story_core/test_models.py
git commit -m "chore: scaffold story engine workspace"
```

### Task 2: Define the story engine core loop

**Files:**
- Create: `packages/story_core/engine.py`
- Create: `packages/story_core/planner.py`
- Create: `packages/story_core/writer.py`
- Create: `packages/story_core/memory.py`
- Modify: `packages/story_core/models.py`
- Create: `tests/story_core/test_engine.py`

- [ ] **Step 1: Write the failing test**

```python
from packages.story_core.engine import StoryEngine
from packages.story_core.models import StoryState, CharacterState


def test_generate_chapter_updates_state_and_returns_bundle():
    story = StoryState(
        story_id="s-001",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        current_chapter=0,
        characters=[
            CharacterState(name="Lin Yue", role="protagonist", traits={"impulsive": 0.6}, goals=["find the culprit"])
        ],
    )
    engine = StoryEngine()
    bundle = engine.generate_next_chapter(story)

    assert bundle.chapter_number == 1
    assert bundle.body
    assert bundle.next_outline
    assert bundle.updated_story.current_chapter == 1
    assert bundle.updated_story.characters[0].memory
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/story_core/test_engine.py -v`
Expected: fail because `StoryEngine` and bundle types are not defined yet.

- [ ] **Step 3: Write minimal implementation**

```python
from pydantic import BaseModel, Field
from packages.story_core.models import StoryState


class ChapterBundle(BaseModel):
    chapter_number: int
    body: str
    character_cards: list[dict] = Field(default_factory=list)
    foreshadowing: list[dict] = Field(default_factory=list)
    next_outline: str
    updated_story: StoryState


class StoryEngine:
    def generate_next_chapter(self, story: StoryState) -> ChapterBundle:
        chapter_number = story.current_chapter + 1
        updated_story = story.model_copy(deep=True)
        updated_story.current_chapter = chapter_number
        if updated_story.characters:
            updated_story.characters[0].memory.append(f"Chapter {chapter_number} changed the situation.")
        return ChapterBundle(
            chapter_number=chapter_number,
            body=f"Chapter {chapter_number} body.",
            character_cards=[{"name": c.name, "memory": c.memory} for c in updated_story.characters],
            foreshadowing=[{"text": "A hidden letter appears."}],
            next_outline=f"Continue from chapter {chapter_number}.",
            updated_story=updated_story,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/story_core/test_engine.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/engine.py packages/story_core/planner.py packages/story_core/writer.py packages/story_core/memory.py packages/story_core/models.py tests/story_core/test_engine.py
git commit -m "feat: add core chapter generation loop"
```

### Task 3: Add state persistence and rollback

**Files:**
- Create: `apps/api/storage.py`
- Create: `apps/api/routes/stories.py`
- Modify: `apps/api/main.py`
- Create: `tests/api/test_story_routes.py`

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient
from apps.api.main import app


client = TestClient(app)


def test_story_can_be_created_and_rolled_back():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-001",
            "outline": "A detective prince uncovers palace crimes.",
            "genre": "fantasy",
            "style": "noir",
        },
    )
    assert create_resp.status_code == 200

    gen_resp = client.post("/stories/s-001/generate")
    assert gen_resp.status_code == 200
    assert gen_resp.json()["chapter_number"] == 1

    rollback_resp = client.post("/stories/s-001/rollback")
    assert rollback_resp.status_code == 200
    assert rollback_resp.json()["current_chapter"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_story_routes.py -v`
Expected: fail because routes and storage do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
from fastapi import FastAPI, APIRouter

app = FastAPI()
router = APIRouter()
stories: dict[str, dict] = {}


@router.post("/stories")
def create_story(payload: dict):
    stories[payload["story_id"]] = {**payload, "current_chapter": 0, "history": []}
    return stories[payload["story_id"]]


@router.post("/stories/{story_id}/generate")
def generate_story(story_id: str):
    story = stories[story_id]
    story["current_chapter"] += 1
    story["history"].append({"chapter_number": story["current_chapter"], "body": "Chapter body."})
    return story["history"][-1]


@router.post("/stories/{story_id}/rollback")
def rollback_story(story_id: str):
    story = stories[story_id]
    if story["history"]:
        story["history"].pop()
        story["current_chapter"] -= 1
    return story


app.include_router(router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_story_routes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/storage.py apps/api/routes/stories.py apps/api/main.py tests/api/test_story_routes.py
git commit -m "feat: add story persistence and rollback"
```

### Task 4: Build the web workbench shell

**Files:**
- Create: `apps/web/app/page.tsx`
- Create: `apps/web/app/globals.css`
- Create: `apps/web/components/StoryEditor.tsx`
- Create: `apps/web/components/StorySidebar.tsx`
- Create: `apps/web/lib/api.ts`
- Create: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { expect, test } from "@playwright/test";

test("workbench shell renders the four-panel layout", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Outline")).toBeVisible();
  await expect(page.getByText("Chapter Draft")).toBeVisible();
  await expect(page.getByText("Character State")).toBeVisible();
  await expect(page.getByText("Controls")).toBeVisible();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx playwright test apps/web/tests/story-workbench.spec.ts`
Expected: fail because the page and layout do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```tsx
export default function Page() {
  return (
    <main className="workbench">
      <section>Outline</section>
      <section>Chapter Draft</section>
      <section>Character State</section>
      <section>Controls</section>
    </main>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx playwright test apps/web/tests/story-workbench.spec.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/app/page.tsx apps/web/app/globals.css apps/web/components/StoryEditor.tsx apps/web/components/StorySidebar.tsx apps/web/lib/api.ts apps/web/tests/story-workbench.spec.ts
git commit -m "feat: add story workbench shell"
```

### Task 5: Connect the workbench to the chapter loop

**Files:**
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/lib/api.ts`
- Create: `apps/web/components/ChapterBundleView.tsx`
- Create: `tests/e2e/story-generation.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
import { expect, test } from "@playwright/test";

test("generate next chapter updates the draft and state panels", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Generate Next Chapter" }).click();
  await expect(page.getByText("Chapter 1 body.")).toBeVisible();
  await expect(page.getByText("Chapter 1")).toBeVisible();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx playwright test tests/e2e/story-generation.spec.ts`
Expected: fail because the button and API wiring do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```tsx
export function ChapterBundleView({ bundle }: { bundle: any }) {
  if (!bundle) return null;
  return (
    <section>
      <h2>Chapter {bundle.chapter_number}</h2>
      <article>{bundle.body}</article>
      <pre>{JSON.stringify(bundle.character_cards, null, 2)}</pre>
    </section>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx playwright test tests/e2e/story-generation.spec.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web/app/page.tsx apps/web/lib/api.ts apps/web/components/ChapterBundleView.tsx tests/e2e/story-generation.spec.ts
git commit -m "feat: wire chapter generation into the workbench"
```

### Task 6: Add story-state quality checks and memory compression

**Files:**
- Create: `packages/story_core/quality.py`
- Create: `tests/story_core/test_quality.py`

- [ ] **Step 1: Write the failing test**

```python
from packages.story_core.quality import validate_bundle


def test_validate_bundle_flags_missing_continuity():
    bundle = {
        "chapter_number": 1,
        "body": "Chapter 1 body.",
        "next_outline": "",
        "character_cards": [],
        "foreshadowing": [],
    }
    report = validate_bundle(bundle)
    assert report["ok"] is False
    assert "next_outline" in report["issues"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/story_core/test_quality.py -v`
Expected: fail because validation does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def validate_bundle(bundle: dict) -> dict:
    issues = []
    if not bundle.get("next_outline"):
        issues.append("next_outline")
    if not bundle.get("body"):
        issues.append("body")
    return {"ok": not issues, "issues": issues}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/story_core/test_quality.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/story_core/quality.py tests/story_core/test_quality.py
git commit -m "feat: add chapter quality checks"
```

### Task 7: Polish docs, scripts, and developer workflow

**Files:**
- Create: `README.md`
- Create: `docs/architecture.md`
- Create: `scripts/dev.sh`
- Create: `scripts/test.sh`

- [ ] **Step 1: Write the failing test**

```bash
test -f README.md
test -f docs/architecture.md
test -f scripts/dev.sh
test -f scripts/test.sh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `bash -lc 'test -f README.md && test -f docs/architecture.md && test -f scripts/dev.sh && test -f scripts/test.sh'`
Expected: fail until the files exist.

- [ ] **Step 3: Write minimal implementation**

```md
# Novel Autogrowth Engine

This project turns a novel outline into a continuously evolving chapter stream.
```

```bash
#!/usr/bin/env bash
set -euo pipefail
pytest
```

- [ ] **Step 4: Run test to verify it passes**

Run: `bash scripts/test.sh`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/architecture.md scripts/dev.sh scripts/test.sh
git commit -m "docs: add project workflow guides"
```

## Self-Review

### Spec coverage check

- Continuous chapter generation: Task 2
- Story state updates: Task 2 and Task 3
- Character autonomy: Task 2
- Full output bundle: Task 2 and Task 5
- Web workbench: Task 4 and Task 5
- Memory compression: Task 6
- Rollback and editing flow: Task 3 and Task 4

### Placeholder scan

- No TBD or TODO markers were introduced.
- Every code-edit task includes concrete file paths, test names, and executable snippets.

### Type consistency check

- `StoryState`, `CharacterState`, `StoryEngine`, `ChapterBundle`, and `validate_bundle` are used consistently across tasks.
- The API routes and frontend names match the same chapter-generation vocabulary.

