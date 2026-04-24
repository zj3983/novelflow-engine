# Remove Rule-Based Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the rule-based agent mode everywhere and leave only LLM-assisted configuration and runtime behavior.

**Architecture:** Treat LLM-assisted as the only supported mode in shared types, backend defaults, frontend controls, mock fallbacks, and tests. Preserve existing data shape where needed for compatibility, but eliminate any user-facing or new-code path that can select rule-based behavior.

**Tech Stack:** TypeScript/React, FastAPI, Pydantic, Pytest, Playwright.

---

### Task 1: Remove rule-based mode from shared types and defaults

**Files:**
- Modify: `packages/story_core/models.py`
- Modify: `apps/web/lib/api.ts`

- [ ] **Step 1: Update the shared model types**

```python
AgentMode = Literal["LLM-assisted"]

class AgentSettings(BaseModel):
    mode: AgentMode = "LLM-assisted"

class AgentRuntimeEntry(BaseModel):
    mode: AgentMode = "LLM-assisted"
```

- [ ] **Step 2: Remove rule-based defaults and fallbacks from the web API layer**

```ts
type CreateStoryRequest = {
  agent_settings?: {
    mode: "LLM-assisted";
    global_model: string;
    character_model: string;
    director_model: string;
    writer_model: string;
    memory_model: string;
    temperature: string | number;
    new_character_policy: "Director review" | "Auto-approve named candidates" | "Manual review";
  };
};
```

- [ ] **Step 3: Run the relevant unit tests**

Run: `pytest tests/api/test_story_routes.py tests/story_core -q`
Expected: pass after all updated mode assertions use only `LLM-assisted`

### Task 2: Remove the mode selector from the configuration UI

**Files:**
- Modify: `apps/web/components/config/RuntimeStrategyCard.tsx`
- Modify: `apps/web/components/config/ConfigPageClient.tsx`
- Modify: `apps/web/tests/config-page.spec.ts`

- [ ] **Step 1: Remove the `<select>` for agent mode**

```tsx
<p className="hint">当前仅支持 LLM 协助模式。</p>
```

- [ ] **Step 2: Keep the rest of the runtime strategy editor intact**

```tsx
<input value={value.global_model} onChange={...} />
```

- [ ] **Step 3: Update configuration page tests to stop looking for the removed control**

```ts
await expect(page.getByText("LLM 协助模式")).toBeVisible();
```

### Task 3: Update tests and verify the full flow

**Files:**
- Modify: `tests/api/test_story_routes.py`
- Modify: `tests/story_core/*` as needed
- Modify: `apps/web/tests/*` and `tests/e2e/*` as needed

- [ ] **Step 1: Replace any remaining `Rule-based` expectations**

```python
assert response.json()["mode"] == "LLM-assisted"
```

- [ ] **Step 2: Run frontend build and Playwright**

Run:
`npm --prefix apps/web run build`
`npx --prefix apps/web playwright test -c apps/web/playwright.config.ts apps/web/tests/story-workbench.spec.ts apps/web/tests/config-page.spec.ts tests/e2e/book-import-entry.spec.ts tests/e2e/story-generation.spec.ts --workers=1`

Expected: both commands pass.
