# Configuration Provider Visibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide API-only configuration in Codex CLI mode while preserving all saved values and restoring the controls when OpenAI-compatible API is selected.

**Architecture:** Keep provider state authoritative in `ConfigPageClient`. Let `GlobalApiConfigCard` own provider-specific global fields, while the page controls whether the runtime strategy and per-agent override sections exist in the rendered tree. Do not change API payloads or persistence.

**Tech Stack:** Next.js, React, TypeScript, Playwright

---

### Task 1: Lock Provider Visibility in the E2E Test

**Files:**
- Modify: `apps/web/tests/config-page.spec.ts`

- [x] **Step 1: Write the failing CLI-mode assertions**

Update the test so the default `codexcli` response requires the CLI command to be visible and API key, base URL, runtime strategy, and Agent overrides to be hidden.

```ts
await expect(page.getByLabel("Codex CLI 命令")).toBeVisible();
await expect(page.getByLabel("全局 API 密钥")).toBeHidden();
await expect(page.getByLabel("全局接口地址")).toBeHidden();
await expect(page.getByRole("heading", { name: "运行策略" })).toBeHidden();
await expect(page.getByRole("button", { name: "Agent 覆盖（高级）" })).toBeHidden();
```

- [x] **Step 2: Add API-mode restoration assertions**

Select `OpenAI 兼容 API`, then assert that API fields, runtime strategy, and Agent overrides appear. Expand the override section and retain the four existing Agent card assertions.

```ts
await page.getByLabel("模型来源").selectOption("openai");
await expect(page.getByLabel("全局 API 密钥")).toBeVisible();
await expect(page.getByLabel("全局接口地址")).toBeVisible();
await expect(page.getByRole("heading", { name: "运行策略" })).toBeVisible();
await expect(page.getByRole("button", { name: "Agent 覆盖（高级）" })).toBeVisible();
```

- [x] **Step 3: Run the focused test and verify RED**

Run from `apps/web`:

```powershell
node node_modules/@playwright/test/cli.js test tests/config-page.spec.ts
```

Expected: FAIL because CLI mode still renders API fields, runtime strategy, or Agent overrides.

### Task 2: Render Only Provider-Relevant Controls

**Files:**
- Modify: `apps/web/components/config/GlobalApiConfigCard.tsx`
- Modify: `apps/web/components/config/ConfigPageClient.tsx`
- Test: `apps/web/tests/config-page.spec.ts`

- [x] **Step 1: Hide global API fields in CLI mode**

Wrap the API key and base URL fields in an OpenAI-only condition. Keep the Codex command condition unchanged and keep the connection-test footer available for both providers.

```tsx
{value.provider === "openai" ? (
  <>
    {/* API key field */}
    {/* Base URL field */}
  </>
) : null}
```

- [x] **Step 2: Hide strategy and Agent overrides in CLI mode**

Derive an OpenAI-mode boolean in `ConfigPageClient` and use it around both API-only sections.

```tsx
const usesOpenAICompatibleApi = runtimeSettings.global.provider === "openai";

{usesOpenAICompatibleApi ? (
  <RuntimeStrategyCard value={runtimeStrategy} onChange={setRuntimeStrategy} />
) : null}

{usesOpenAICompatibleApi ? <AgentOverrideGrid ... /> : null}
```

Do not mutate hidden state when the provider changes. Keep `saveAll()` unchanged so both settings payloads are persisted.

- [x] **Step 3: Run the focused test and verify GREEN**

Run from `apps/web`:

```powershell
node node_modules/@playwright/test/cli.js test tests/config-page.spec.ts
```

Expected: `1 passed`.

- [x] **Step 4: Run build and whitespace verification**

```powershell
node node_modules/next/dist/bin/next build
git diff --check
```

Expected: both commands exit successfully.

- [x] **Step 5: Verify the local page**

Start or reuse the web development server, open `/config`, and verify both provider states at desktop width. Confirm there is no empty secondary area in CLI mode and that switching back to OpenAI-compatible API restores all controls.
