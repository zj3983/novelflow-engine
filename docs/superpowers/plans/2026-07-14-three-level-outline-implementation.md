# Three-Level Outline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an editable three-level outline for file projects and make chapter planning consume only the book outline, active arc, and target chapter outline.

**Architecture:** Store the canonical outline in `.webnovel/outline.json`. A focused story-core module owns validation, legacy projection, and target-chapter selection; the file-project API only transports that model, and the workbench only edits it. `FileProjectStore.writing_packet()` receives a compact `outline_context` instead of the complete outline.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, pytest, Next.js 14, React, TypeScript, Playwright.

---

## File Map

- Create `packages/story_core/project_outline.py`: canonical models, legacy compatibility, validation, target chapter selection.
- Create `tests/story_core/test_project_outline.py`: unit tests for the module boundary.
- Modify `packages/story_core/file_project_store.py`: read/write outline file and insert compact context into the writing packet.
- Modify `packages/story_core/models.py`: carry transient target-chapter outline context without persisting it as story history.
- Modify `packages/story_core/orchestrator.py`: expose scoped outline context to the real planning prompt.
- Modify `apps/api/routes/file_projects.py`: GET/PUT file-project outline endpoints.
- Modify `tests/api/test_book_dissection_routes.py`: API persistence and writing-packet integration tests.
- Create `tests/story_core/test_orchestrator_prompt_contracts.py`: prove the director prompt receives scoped outline context.
- Modify `apps/web/lib/api.ts`: outline response types and API functions.
- Replace `apps/web/app/projects/[id]/outline/page.tsx`: three-tab editor.
- Modify `apps/web/tests/story-workbench.spec.ts`: outline page interaction coverage.

### Task 1: Canonical Outline Module

**Files:**
- Create: `packages/story_core/project_outline.py`
- Create: `tests/story_core/test_project_outline.py`

- [ ] **Step 1: Write failing normalization and selection tests**

```python
from packages.story_core.project_outline import (
    normalize_project_outline,
    outline_from_legacy_project,
    select_outline_context,
)


def test_legacy_project_projects_into_three_levels_without_mutation():
    project = {
        "seed_outline": "林照靠断香炉追查宗门旧案。",
        "world_blueprint": {
            "current_arc": "先查清祖祠失火原因。",
            "opening_arc": {
                "chapter_beats": [
                    {"chapter": 2, "title": "夜查祖祠", "required_payoff": "找到灰烬脚印", "ending_hook": "脚印通向内门"}
                ]
            },
        },
    }

    outline = outline_from_legacy_project(project)

    assert outline["overall"]["story"] == "林照靠断香炉追查宗门旧案。"
    assert outline["arcs"][0]["goal"] == "先查清祖祠失火原因。"
    assert outline["chapters"][0]["chapter_number"] == 2
    assert "outline" not in project


def test_selection_returns_only_active_arc_and_target_chapter():
    outline = normalize_project_outline({
        "overall": {"story": "总纲"},
        "arcs": [
            {"id": "opening", "title": "开篇", "start_chapter": 1, "end_chapter": 10, "goal": "站稳外门"},
            {"id": "inner", "title": "内门", "start_chapter": 11, "end_chapter": 30, "goal": "进入内门"},
        ],
        "chapters": [
            {"chapter_number": 2, "goal": "查祖祠"},
            {"chapter_number": 12, "goal": "过内门考核"},
        ],
    })

    context = select_outline_context(outline, 12)

    assert context["overall"]["story"] == "总纲"
    assert context["active_arc"]["id"] == "inner"
    assert context["chapter"]["chapter_number"] == 12
    assert "arcs" not in context
    assert "chapters" not in context
```

- [ ] **Step 2: Run the tests and confirm the module is missing**

Run: `python -m pytest tests/story_core/test_project_outline.py -q`

Expected: FAIL with `ModuleNotFoundError: packages.story_core.project_outline`.

- [ ] **Step 3: Implement the canonical models and pure functions**

```python
from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class OverallOutline(BaseModel):
    story: str = ""
    protagonist_goal: str = ""
    main_conflict: str = ""
    growth_path: str = ""
    ending_direction: str = ""


class ArcOutline(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    title: str = ""
    start_chapter: int = 1
    end_chapter: int = 1
    goal: str = ""
    obstacle: str = ""
    payoff: str = ""
    end_state: str = ""

    @model_validator(mode="after")
    def validate_range(self) -> "ArcOutline":
        if self.start_chapter < 1 or self.end_chapter < self.start_chapter:
            raise ValueError("invalid_arc_chapter_range")
        return self


class ChapterPlan(BaseModel):
    chapter_number: int
    title: str = ""
    goal: str = ""
    obstacle: str = ""
    action: str = ""
    turn: str = ""
    payoff: str = ""
    ending_hook: str = ""

    @model_validator(mode="after")
    def validate_chapter(self) -> "ChapterPlan":
        if self.chapter_number < 1:
            raise ValueError("invalid_chapter_number")
        return self


class ProjectOutline(BaseModel):
    schema_version: str = "project-outline/v1"
    overall: OverallOutline = Field(default_factory=OverallOutline)
    arcs: list[ArcOutline] = Field(default_factory=list)
    chapters: list[ChapterPlan] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_duplicate_chapters(self) -> "ProjectOutline":
        numbers = [item.chapter_number for item in self.chapters]
        if len(numbers) != len(set(numbers)):
            raise ValueError("duplicate_chapter_outline")
        self.arcs.sort(key=lambda item: (item.start_chapter, item.end_chapter))
        self.chapters.sort(key=lambda item: item.chapter_number)
        return self


def normalize_project_outline(payload: Any) -> dict[str, Any]:
    return ProjectOutline.model_validate(payload or {}).model_dump()


def outline_from_legacy_project(project: dict[str, Any]) -> dict[str, Any]:
    blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
    opening = blueprint.get("opening_arc") if isinstance(blueprint.get("opening_arc"), dict) else {}
    beats = opening.get("chapter_beats") if isinstance(opening.get("chapter_beats"), list) else []
    chapters = []
    for beat in beats:
        if not isinstance(beat, dict) or int(beat.get("chapter") or 0) < 1:
            continue
        chapters.append({
            "chapter_number": int(beat["chapter"]),
            "title": str(beat.get("title") or ""),
            "payoff": str(beat.get("required_payoff") or beat.get("payoff") or ""),
            "ending_hook": str(beat.get("ending_hook") or beat.get("hook") or ""),
        })
    current_arc = str(blueprint.get("current_arc") or "").strip()
    return normalize_project_outline({
        "overall": {"story": str(project.get("seed_outline") or "")},
        "arcs": [{"id": "legacy-opening", "title": "当前阶段", "start_chapter": 1, "end_chapter": max([item["chapter_number"] for item in chapters] or [10]), "goal": current_arc}] if current_arc else [],
        "chapters": chapters,
    })


def select_outline_context(outline: dict[str, Any], chapter_number: int) -> dict[str, Any]:
    normalized = normalize_project_outline(outline)
    matching = [item for item in normalized["arcs"] if item["start_chapter"] <= chapter_number <= item["end_chapter"]]
    active_arc = max(matching, key=lambda item: item["start_chapter"], default=None)
    chapter = next((item for item in normalized["chapters"] if item["chapter_number"] == chapter_number), None)
    return {
        "schema_version": "outline-context/v1",
        "overall": normalized["overall"],
        "active_arc": active_arc,
        "chapter": chapter,
    }
```

- [ ] **Step 4: Run the unit tests**

Run: `python -m pytest tests/story_core/test_project_outline.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the module**

```powershell
git add packages/story_core/project_outline.py tests/story_core/test_project_outline.py
git commit -m "feat: add canonical project outline model"
```

### Task 2: File Storage and API

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `apps/api/routes/file_projects.py`
- Modify: `tests/api/test_book_dissection_routes.py`

- [ ] **Step 1: Write failing API tests**

```python
response = client.get("/file-projects/file:outline-fixture/outline")
assert response.status_code == 200
assert response.json()["source"] == "legacy"
assert not (project_root / ".webnovel" / "outline.json").exists()

saved = client.put("/file-projects/file:outline-fixture/outline", json={
    "overall": {"story": "林照追查祖祠旧案。"},
    "arcs": [{"id": "opening", "title": "祖祠", "start_chapter": 1, "end_chapter": 8, "goal": "找出纵火者"}],
    "chapters": [{"chapter_number": 2, "goal": "夜查祖祠"}],
})
assert saved.status_code == 200
assert saved.json()["source"] == "saved"
persisted = json.loads((project_root / ".webnovel" / "outline.json").read_text(encoding="utf-8"))
assert persisted["arcs"][0]["id"] == "opening"

duplicate = client.put("/file-projects/file:outline-fixture/outline", json={
    "overall": {"story": "林照追查祖祠旧案。"},
    "chapters": [
        {"chapter_number": 2, "goal": "夜查祖祠"},
        {"chapter_number": 2, "goal": "再查一次"},
    ],
})
assert duplicate.status_code == 422
assert "duplicate_chapter_outline" in duplicate.json()["detail"]
```

- [ ] **Step 2: Run the focused API tests**

Run: `python -m pytest tests/api/test_book_dissection_routes.py -k "outline" -q`

Expected: FAIL because the new route returns 404.

- [ ] **Step 3: Add store methods and routes**

Add these methods to `FileProjectStore`:

```python
def project_outline(self) -> dict[str, Any]:
    path = self.webnovel_dir / "outline.json"
    if path.exists():
        return {**normalize_project_outline(self._read_json(path, {})), "source": "saved"}
    return {**outline_from_legacy_project(self.project()), "source": "legacy"}

def update_project_outline(self, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_project_outline(payload)
    self._write_json(self.webnovel_dir / "outline.json", normalized)
    return {**normalized, "source": "saved"}
```

Add routes in `init_file_project_routes()`:

```python
@router.get("/file-projects/{project_id}/outline")
def get_file_project_outline(project_id: str) -> dict[str, Any]:
    return _store_for(project_id).project_outline()

@router.put("/file-projects/{project_id}/outline")
def update_file_project_outline(project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return _store_for(project_id).update_project_outline(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Step 4: Run API tests**

Run: `python -m pytest tests/api/test_book_dissection_routes.py -k "outline" -q`

Expected: PASS.

- [ ] **Step 5: Commit storage and API**

```powershell
git add packages/story_core/file_project_store.py apps/api/routes/file_projects.py tests/api/test_book_dissection_routes.py
git commit -m "feat: persist file project outlines"
```

### Task 3: Writing Packet Integration

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `packages/story_core/models.py`
- Modify: `packages/story_core/orchestrator.py`
- Modify: `tests/api/test_book_dissection_routes.py`
- Create: `tests/story_core/test_orchestrator_prompt_contracts.py`

- [ ] **Step 1: Replace the old packet expectation with a focused context test**

```python
packet = client.get("/file-projects/file:packet-fixture/writing-packet?chapter_number=12").json()
context = packet["outline_context"]
assert context["overall"]["story"] == "林照追查祖祠旧案。"
assert context["active_arc"]["id"] == "inner"
assert context["chapter"]["chapter_number"] == 12
assert "arcs" not in context
assert "chapters" not in context
assert "opening_arc" not in packet["outline_constraints"]
```

- [ ] **Step 2: Run the focused writing packet test**

Run: `python -m pytest tests/api/test_book_dissection_routes.py::test_file_project_writing_packet_uses_file_outline_and_character_cards -q`

Expected: FAIL because `outline_context` is absent.

- [ ] **Step 3: Build target context once in `writing_packet()`**

At the start of `writing_packet()`, call:

```python
outline = self.project_outline()
outline_context = select_outline_context(outline, int(target))
target_outline = outline_context.get("chapter") or {}
```

Use `target_outline` for the outline-derived scene card and hard locks. Return `outline_context` as a top-level packet field. Keep world progression and forbidden rules under `outline_constraints`, but remove `opening_arc` and current-arc duplication from that block.

- [ ] **Step 4: Write a failing real-planner prompt test**

```python
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator


def test_director_prompt_receives_transient_outline_context():
    story = StoryState(
        story_id="outline-context",
        outline="全书总纲",
        outline_context={
            "schema_version": "outline-context/v1",
            "overall": {"story": "全书总纲"},
            "active_arc": {"id": "opening", "goal": "查清祖祠失火"},
            "chapter": {"chapter_number": 2, "goal": "夜查祖祠"},
        },
    )

    prompt = StoryOrchestrator()._plan_prompt(story, 2)

    assert '"active_arc"' in prompt
    assert "查清祖祠失火" in prompt
    assert "夜查祖祠" in prompt
```

Run: `python -m pytest tests/story_core/test_orchestrator_prompt_contracts.py -k "outline_context" -q`

Expected: FAIL because `StoryState` and `_story_snapshot()` do not expose the new context.

- [ ] **Step 5: Carry the context into actual generation**

Add a transient field to `StoryState` in `packages/story_core/models.py`:

```python
outline_context: dict = Field(default_factory=dict, exclude=True)
```

Add this entry to `_story_snapshot()` in `packages/story_core/orchestrator.py`:

```python
"outline_context": story.outline_context,
```

Change `_story_state_payload_for_direction()` to accept `chapter_number`, select the context, and return it:

```python
def _story_state_payload_for_direction(
    self,
    state: dict[str, Any],
    project: dict[str, Any],
    chapter_number: int | None = None,
) -> dict[str, Any]:
    target = chapter_number or int(state.get("current_chapter") or 0) + 1
    outline_context = select_outline_context(self.project_outline(), target)
    return {
        # existing fields remain unchanged
        "outline_context": outline_context,
    }
```

Pass the target chapter from `_chapter_direction_options()`, `generate_next_chapter()`, and `regenerate_chapter()` when building `StoryState`. Because the field is excluded from `model_dump()`, target-specific context cannot be written back as permanent story state.

- [ ] **Step 6: Update prompt preview compaction**

Ensure `_compact_prompt_preview_packet()` copies only:

```python
"outline_context": self._slim_prompt_preview_value(packet.get("outline_context", {})),
```

and does not reconstruct the complete outline.

- [ ] **Step 7: Run packet and prompt tests**

Run: `python -m pytest tests/api/test_book_dissection_routes.py -k "outline or writing_packet or prompt_preview" -q; python -m pytest tests/story_core/test_orchestrator_prompt_contracts.py -k "outline_context" -q`

Expected: PASS.

- [ ] **Step 8: Commit integration**

```powershell
git add packages/story_core/file_project_store.py packages/story_core/models.py packages/story_core/orchestrator.py tests/api/test_book_dissection_routes.py tests/story_core/test_orchestrator_prompt_contracts.py
git commit -m "feat: scope outline context to target chapter"
```

### Task 4: Workbench Outline Editor

**Files:**
- Modify: `apps/web/lib/api.ts`
- Replace: `apps/web/app/projects/[id]/outline/page.tsx`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Add API types and functions**

```typescript
export type ProjectOutline = {
  schema_version: "project-outline/v1" | string;
  source: "saved" | "legacy";
  overall: { story: string; protagonist_goal: string; main_conflict: string; growth_path: string; ending_direction: string };
  arcs: Array<{ id: string; title: string; start_chapter: number; end_chapter: number; goal: string; obstacle: string; payoff: string; end_state: string }>;
  chapters: Array<{ chapter_number: number; title: string; goal: string; obstacle: string; action: string; turn: string; payoff: string; ending_hook: string }>;
};

export async function fetchProjectOutline(projectId: string): Promise<ProjectOutline> {
  return tryFetchJson(`${apiBase()}/file-projects/${encodeURIComponent(projectId)}/outline`, { method: "GET" });
}

export async function updateProjectOutline(projectId: string, outline: Omit<ProjectOutline, "source">): Promise<ProjectOutline> {
  return tryFetchJson(`${apiBase()}/file-projects/${encodeURIComponent(projectId)}/outline`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(outline),
  });
}
```

- [ ] **Step 2: Write the failing workbench test**

```typescript
test("file project outline edits three independent levels", async ({ page }) => {
  let savedBody: Record<string, unknown> | null = null;
  const outline = {
    schema_version: "project-outline/v1",
    source: "saved",
    overall: { story: "林照追查祖祠旧案。", protagonist_goal: "", main_conflict: "", growth_path: "", ending_direction: "" },
    arcs: [{ id: "opening", title: "祖祠", start_chapter: 1, end_chapter: 8, goal: "找出纵火者", obstacle: "", payoff: "", end_state: "" }],
    chapters: [{ chapter_number: 1, title: "守炉", goal: "检查断香炉", obstacle: "", action: "", turn: "", payoff: "", ending_hook: "" }],
  };
  await page.route("**/file-projects/file%3Aoutline-fixture/outline", async (route) => {
    if (route.request().method() === "PUT") {
      savedBody = route.request().postDataJSON();
      await route.fulfill({ json: { ...outline, ...savedBody, source: "saved" } });
      return;
    }
    await route.fulfill({ json: outline });
  });

  await page.goto("/projects/file%3Aoutline-fixture/outline");
  await expect(page.getByRole("button", { name: "总纲" })).toBeVisible();
  await expect(page.getByRole("button", { name: "阶段大纲" })).toBeVisible();
  await expect(page.getByRole("button", { name: "章节大纲" })).toBeVisible();
  await page.getByLabel("主角长期目标").fill("洗清父亲旧案");
  await page.getByRole("button", { name: "保存大纲" }).click();

  expect(savedBody).toMatchObject({
    overall: { protagonist_goal: "洗清父亲旧案" },
    arcs: outline.arcs,
    chapters: outline.chapters,
  });
});
```

- [ ] **Step 3: Run the frontend test**

Run: `cd apps/web; npx playwright test tests/story-workbench.spec.ts`

Expected: FAIL because the page still edits `world_blueprint`.

- [ ] **Step 4: Replace the page with the three-tab editor**

Implement a single local `draft: ProjectOutline` state and `activeTab: "overall" | "arcs" | "chapters"`. Load with `fetchProjectOutline(projectId)`, save with `updateProjectOutline()`, and keep add/remove helpers local to the page. The three tabs render only their own fields; use the existing `ws-btn`, `ws-input`, `ws-toolbar`, `ws-rule-list`, and `ws-rule-item` classes.

Required UI behavior:

```typescript
const tabs = [
  { id: "overall", label: "总纲" },
  { id: "arcs", label: "阶段大纲" },
  { id: "chapters", label: "章节大纲" },
] as const;

function addArc() {
  setDraft((current) => ({
    ...current,
    arcs: [...current.arcs, { id: crypto.randomUUID(), title: "", start_chapter: 1, end_chapter: 10, goal: "", obstacle: "", payoff: "", end_state: "" }],
  }));
}

function addChapter() {
  const chapter_number = Math.max(0, ...draft.chapters.map((item) => item.chapter_number)) + 1;
  setDraft((current) => ({
    ...current,
    chapters: [...current.chapters, { chapter_number, title: "", goal: "", obstacle: "", action: "", turn: "", payoff: "", ending_hook: "" }],
  }));
}
```

Show `旧大纲预览，保存后转为新版结构` when `source === "legacy"`. Do not render forbidden rules, world rules, or character cards.

Before rendering the form, compute non-blocking warnings. Show `请先填写总纲中的核心故事` when `draft.overall.story` is empty. Compare every pair of stage ranges and show `阶段章节范围有重叠；生成时会采用起始章节最接近当前章的阶段` when they overlap. These warnings do not prevent saving.

- [ ] **Step 5: Run frontend tests and production build**

Run: `cd apps/web; npx playwright test tests/story-workbench.spec.ts`

Expected: PASS.

Run: `cd apps/web; npm run build`

Expected: build succeeds and `/projects/[id]/outline` is listed.

- [ ] **Step 6: Commit the workbench**

```powershell
git add apps/web/lib/api.ts apps/web/app/projects/[id]/outline/page.tsx apps/web/tests/story-workbench.spec.ts
git commit -m "feat: add three-level outline editor"
```

### Task 5: Regression Verification

**Files:**
- Modify only if a regression test exposes a defect in the files above.

- [ ] **Step 1: Run backend tests**

Run: `python -m pytest tests/story_core/test_project_outline.py tests/api/test_book_dissection_routes.py -q`

Expected: PASS.

- [ ] **Step 2: Run the complete test suite**

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Run frontend verification**

Run: `cd apps/web; npm run build`

Expected: production build succeeds.

- [ ] **Step 4: Test the live project without changing its chapters**

Record the SHA-256 hash of the existing chapter JSON, restart API and web services, open `http://127.0.0.1:3000/projects/p-xianxia-incense-test-2/outline`, and verify:

- all three tabs load;
- legacy data is visible before saving;
- switching tabs does not lose draft edits;
- saving creates `.webnovel/outline.json` only for the selected test project;
- requesting the writing packet for chapter 1 includes only chapter 1 outline context;
- the recorded chapter hash is unchanged.

- [ ] **Step 5: Commit any test-only adjustments**

```powershell
git add tests apps/web/tests
git commit -m "test: verify three-level outline workflow"
```
