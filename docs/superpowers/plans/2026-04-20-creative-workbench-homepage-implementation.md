# Creative Workbench Homepage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the web homepage into a story-first creative workbench that foregrounds current story state and chapter history while keeping import and configuration as secondary, easy-to-reach actions.

**Architecture:** Keep the existing two-page app structure and refactor the homepage by composing smaller workbench-specific components on top of the existing `AppShell`. Reuse existing data-fetching and story actions from `apps/web/app/page.tsx`, but move presentation concerns into focused components for the top status bar, overview cards, chapter history feed, and right-side insight panel.

**Tech Stack:** Next.js App Router, React client components, TypeScript, existing web API client in `apps/web/lib/api.ts`, Playwright tests, CSS in `apps/web/app/globals.css`

---

## File Map

- Modify: `apps/web/app/page.tsx`
  Responsibility: orchestrate homepage state, wire story actions into the new workbench layout, pass data into smaller presentation components
- Modify: `apps/web/components/workbench/WorkbenchShell.tsx`
  Responsibility: replace the current three-column hero shell with the new creative-workbench frame and responsive slots
- Create: `apps/web/components/workbench/WorkbenchTopBar.tsx`
  Responsibility: render book title, chapter progress, quick status summary, and primary actions
- Create: `apps/web/components/workbench/StoryOverviewGrid.tsx`
  Responsibility: render the top summary cards for current focus, conflicts, foreshadowing, and memory
- Create: `apps/web/components/workbench/ChapterHistoryFeed.tsx`
  Responsibility: render story history as readable chapter cards with open/branch actions
- Create: `apps/web/components/workbench/WorkbenchSidePanel.tsx`
  Responsibility: render right-side status cards for characters, runtime activity, and writing risks
- Modify: `apps/web/components/BookImportPanel.tsx`
  Responsibility: adapt labels and CTA placement so import feels secondary on the homepage
- Modify: `apps/web/components/ChapterBundleView.tsx`
  Responsibility: align chapter detail presentation with the new workbench center flow and detail handoff from history cards
- Modify: `apps/web/components/StorySidebar.tsx`
  Responsibility: either retire or reduce to reusable subparts so logic is not duplicated
- Modify: `apps/web/app/globals.css`
  Responsibility: define the new workbench visual system, layout, typography, cards, and responsive behavior
- Modify: `apps/web/tests/story-workbench.spec.ts`
  Responsibility: update page-level structure assertions for the new homepage layout
- Modify: `tests/e2e/story-generation.spec.ts`
  Responsibility: verify homepage generation still works with the new primary action placement
- Modify: `tests/e2e/book-import-entry.spec.ts`
  Responsibility: verify import is still accessible but no longer the visual center

### Task 1: Lock Homepage Skeleton With a Failing Test

**Files:**
- Modify: `apps/web/tests/story-workbench.spec.ts`
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/components/workbench/WorkbenchShell.tsx`

- [ ] **Step 1: Write the failing test**

```ts
test("homepage foregrounds story status and history before import", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("banner")).toBeVisible();
  await expect(page.getByRole("region", { name: "故事总览" })).toBeVisible();
  await expect(page.getByRole("region", { name: "章节历史" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "创作侧栏" })).toBeVisible();
  await expect(page.getByRole("button", { name: "继续生成下一章" })).toBeVisible();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx --prefix apps/web playwright test apps/web/tests/story-workbench.spec.ts --workers=1`
Expected: FAIL because the current homepage exposes `创作导入区 / 当前章节 / 故事状态`, not the new story-first structure.

- [ ] **Step 3: Write minimal implementation**

```tsx
// apps/web/components/workbench/WorkbenchShell.tsx
type WorkbenchShellProps = {
  topBar: ReactNode;
  nav: ReactNode;
  overview: ReactNode;
  history: ReactNode;
  detail: ReactNode;
  side: ReactNode;
};

export function WorkbenchShell({ topBar, nav, overview, history, detail, side }: WorkbenchShellProps) {
  return (
    <div className="creative-workbench">
      <header className="creative-workbench__topbar" role="banner">
        {topBar}
      </header>
      <div className="creative-workbench__body">
        <aside className="creative-workbench__nav">{nav}</aside>
        <main className="creative-workbench__main">
          <section aria-label="故事总览">{overview}</section>
          <section aria-label="章节历史">{history}</section>
          <section aria-label="章节详情">{detail}</section>
        </main>
        <aside className="creative-workbench__side" role="complementary" aria-label="创作侧栏">
          {side}
        </aside>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx --prefix apps/web playwright test apps/web/tests/story-workbench.spec.ts --workers=1`
Expected: PASS for the new structural assertions, with any remaining assertions updated in later tasks.

- [ ] **Step 5: Commit**

```bash
git add apps/web/tests/story-workbench.spec.ts apps/web/app/page.tsx apps/web/components/workbench/WorkbenchShell.tsx
git commit -m "feat: reshape homepage into creative workbench shell"
```

### Task 2: Build the Story-First Top Bar and Overview Cards

**Files:**
- Create: `apps/web/components/workbench/WorkbenchTopBar.tsx`
- Create: `apps/web/components/workbench/StoryOverviewGrid.tsx`
- Modify: `apps/web/app/page.tsx`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
test("homepage top bar shows writing progress and core actions", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.getByText("当前推进", { exact: false })).toBeVisible();
  await expect(page.getByText("最近更新", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "继续生成下一章" })).toBeVisible();
  await expect(page.getByRole("link", { name: "查看配置" })).toBeVisible();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx --prefix apps/web playwright test apps/web/tests/story-workbench.spec.ts --grep "top bar" --workers=1`
Expected: FAIL because no top bar summary exists yet.

- [ ] **Step 3: Write minimal implementation**

```tsx
// apps/web/components/workbench/WorkbenchTopBar.tsx
import Link from "next/link";

type WorkbenchTopBarProps = {
  storyId: string | null;
  currentChapter: number;
  lastUpdatedLabel: string;
  isGenerating: boolean;
  onGenerateNextChapter: () => void;
};

export function WorkbenchTopBar(props: WorkbenchTopBarProps) {
  return (
    <div className="workbench-topbar panel">
      <div>
        <p className="workbench-topbar__eyebrow">当前推进</p>
        <h1>{props.storyId ?? "未命名故事"}</h1>
        <p>第 {props.currentChapter} 章 · 最近更新 {props.lastUpdatedLabel}</p>
      </div>
      <div className="workbench-topbar__actions">
        <button type="button" className="btn btn--primary" onClick={props.onGenerateNextChapter} disabled={props.isGenerating}>
          {props.currentChapter > 0 ? "继续生成下一章" : "开始生成第一章"}
        </button>
        <Link className="btn btn--ghost" href="/config">
          查看配置
        </Link>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx --prefix apps/web playwright test apps/web/tests/story-workbench.spec.ts --grep "top bar" --workers=1`
Expected: PASS, and homepage renders the new progress header in Chinese.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/workbench/WorkbenchTopBar.tsx apps/web/components/workbench/StoryOverviewGrid.tsx apps/web/app/page.tsx apps/web/tests/story-workbench.spec.ts
git commit -m "feat: add homepage progress bar and story overview cards"
```

### Task 3: Replace Sidebar History With a Readable Chapter Feed

**Files:**
- Create: `apps/web/components/workbench/ChapterHistoryFeed.tsx`
- Modify: `apps/web/components/ChapterBundleView.tsx`
- Modify: `apps/web/app/page.tsx`
- Modify: `tests/e2e/story-generation.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
test("generated chapters appear in the homepage history feed", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "开始生成第一章" }).click();

  await expect(page.getByRole("region", { name: "章节历史" })).toContainText("第 1 章");
  await expect(page.getByRole("button", { name: "打开章节详情" })).toBeVisible();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx --prefix apps/web playwright test tests/e2e/story-generation.spec.ts --workers=1`
Expected: FAIL because history currently lives in the old right sidebar and has no chapter-card CTA.

- [ ] **Step 3: Write minimal implementation**

```tsx
// apps/web/components/workbench/ChapterHistoryFeed.tsx
type ChapterHistoryFeedProps = {
  history: ChapterBundle[];
  selectedChapter: number | null;
  onOpenChapter: (chapterNumber: number) => void;
  onBranchFromChapter: (chapterNumber: number) => Promise<void>;
  isGenerating: boolean;
};

export function ChapterHistoryFeed(props: ChapterHistoryFeedProps) {
  return (
    <div className="chapter-history-feed">
      {props.history.map((entry) => (
        <article key={entry.chapter_number} className="chapter-history-card">
          <p className="chapter-history-card__eyebrow">第 {entry.chapter_number} 章</p>
          <h3>{entry.chapter_title || `章节 ${entry.chapter_number}`}</h3>
          <p>{entry.summary}</p>
          <div className="chapter-history-card__actions">
            <button type="button" className="btn btn--ghost" onClick={() => props.onOpenChapter(entry.chapter_number)}>
              打开章节详情
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => void props.onBranchFromChapter(entry.chapter_number)} disabled={props.isGenerating}>
              从这里分支
            </button>
          </div>
        </article>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx --prefix apps/web playwright test tests/e2e/story-generation.spec.ts --workers=1`
Expected: PASS, with history cards visible below the overview area after generation.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/workbench/ChapterHistoryFeed.tsx apps/web/components/ChapterBundleView.tsx apps/web/app/page.tsx tests/e2e/story-generation.spec.ts
git commit -m "feat: move chapter history into homepage feed"
```

### Task 4: Build the Right-Side Insight Panel and De-Emphasize Import

**Files:**
- Create: `apps/web/components/workbench/WorkbenchSidePanel.tsx`
- Modify: `apps/web/components/BookImportPanel.tsx`
- Modify: `apps/web/components/StorySidebar.tsx`
- Modify: `apps/web/app/page.tsx`
- Test: `tests/e2e/book-import-entry.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
test("import stays reachable without dominating the homepage", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.getByRole("navigation")).toContainText("书籍导入");
  await expect(page.getByRole("complementary", { name: "创作侧栏" })).toContainText("运行记录");
  await expect(page.getByRole("complementary", { name: "创作侧栏" })).toContainText("风险提醒");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx --prefix apps/web playwright test tests/e2e/book-import-entry.spec.ts --workers=1`
Expected: FAIL because import currently sits as a full left rail and the side panel does not expose the new writing insights.

- [ ] **Step 3: Write minimal implementation**

```tsx
// apps/web/components/workbench/WorkbenchSidePanel.tsx
type WorkbenchSidePanelProps = {
  story: StoryResponse | null;
  error: string | null;
};

export function WorkbenchSidePanel({ story, error }: WorkbenchSidePanelProps) {
  return (
    <div className="workbench-sidepanel">
      <section className="panel">
        <header className="panel__header">角色状态</header>
        <div className="panel__body">{story?.characters.length ? story.characters.map((character) => <p key={character.name}>{character.name}</p>) : <p className="hint">暂无角色状态。</p>}</div>
      </section>
      <section className="panel">
        <header className="panel__header">运行记录</header>
        <div className="panel__body">
          <p className="hint">{story?.agent_runtime?.recent_events.at(-1) ?? "最近还没有运行记录。"}</p>
        </div>
      </section>
      <section className="panel">
        <header className="panel__header">风险提醒</header>
        <div className="panel__body">
          <p className="hint">{error ?? "当前没有明显风险。后续可在这里提醒伏笔和角色偏移。"}</p>
        </div>
      </section>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx --prefix apps/web playwright test tests/e2e/book-import-entry.spec.ts --workers=1`
Expected: PASS, with import accessible from navigation or compact panel instead of owning the page.

- [ ] **Step 5: Commit**

```bash
git add apps/web/components/workbench/WorkbenchSidePanel.tsx apps/web/components/BookImportPanel.tsx apps/web/components/StorySidebar.tsx apps/web/app/page.tsx tests/e2e/book-import-entry.spec.ts
git commit -m "feat: add homepage insight panel and secondary import entry"
```

### Task 5: Apply the New Visual System and Responsive Layout

**Files:**
- Modify: `apps/web/app/globals.css`
- Modify: `apps/web/components/workbench/WorkbenchShell.tsx`
- Modify: `apps/web/app/page.tsx`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
test("homepage uses the creative workbench visual landmarks", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.locator(".creative-workbench")).toBeVisible();
  await expect(page.locator(".story-overview-grid")).toBeVisible();
  await expect(page.locator(".chapter-history-feed")).toBeVisible();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx --prefix apps/web playwright test apps/web/tests/story-workbench.spec.ts --grep "visual landmarks" --workers=1`
Expected: FAIL because the new CSS classes and layout landmarks do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```css
/* apps/web/app/globals.css */
.creative-workbench {
  display: grid;
  gap: 1.5rem;
}

.creative-workbench__body {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr) 320px;
  gap: 1.25rem;
}

.story-overview-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1rem;
}

.chapter-history-feed {
  display: grid;
  gap: 0.9rem;
}

@media (max-width: 1100px) {
  .creative-workbench__body {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx --prefix apps/web playwright test apps/web/tests/story-workbench.spec.ts --workers=1`
Expected: PASS, and the homepage remains usable on both desktop and narrow widths.

- [ ] **Step 5: Commit**

```bash
git add apps/web/app/globals.css apps/web/components/workbench/WorkbenchShell.tsx apps/web/app/page.tsx apps/web/tests/story-workbench.spec.ts
git commit -m "style: apply creative workbench homepage system"
```

### Task 6: Full Regression and Chinese Copy Sweep

**Files:**
- Modify: `apps/web/app/page.tsx`
- Modify: `apps/web/components/BookImportPanel.tsx`
- Modify: `apps/web/components/ChapterBundleView.tsx`
- Modify: `apps/web/tests/story-workbench.spec.ts`
- Modify: `tests/e2e/story-generation.spec.ts`
- Modify: `tests/e2e/book-import-entry.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
test("homepage keeps core copy in Chinese", async ({ page }) => {
  await page.goto("/", { waitUntil: "domcontentloaded" });

  await expect(page.getByText("故事总览", { exact: true })).toBeVisible();
  await expect(page.getByText("章节历史", { exact: true })).toBeVisible();
  await expect(page.getByText("运行记录", { exact: true })).toBeVisible();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx --prefix apps/web playwright test apps/web/tests/story-workbench.spec.ts tests/e2e/story-generation.spec.ts tests/e2e/book-import-entry.spec.ts --workers=1`
Expected: FAIL if any old English or outdated homepage labels remain.

- [ ] **Step 3: Write minimal implementation**

```tsx
// apps/web/app/page.tsx
<StoryOverviewGrid title="故事总览" />
<ChapterHistoryFeed title="章节历史" />
<WorkbenchSidePanel />
```

```tsx
// apps/web/components/BookImportPanel.tsx
<p className="hint">书籍导入仍可随时进入，但首页现在优先展示故事状态与历史章节。</p>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm --prefix apps/web run build`
Expected: PASS

Run: `npx --prefix apps/web playwright test -c apps/web/playwright.config.ts apps/web/tests/story-workbench.spec.ts apps/web/tests/config-page.spec.ts tests/e2e/book-import-entry.spec.ts tests/e2e/story-generation.spec.ts tests/e2e/story-character-controls.spec.ts --workers=1`
Expected: PASS, and homepage copy is uniformly Chinese while config page still works.

- [ ] **Step 5: Commit**

```bash
git add apps/web/app/page.tsx apps/web/components/BookImportPanel.tsx apps/web/components/ChapterBundleView.tsx apps/web/tests/story-workbench.spec.ts tests/e2e/story-generation.spec.ts tests/e2e/book-import-entry.spec.ts
git commit -m "test: verify creative homepage copy and flow"
```

## Self-Review

- Spec coverage: The plan maps to the approved spec sections for top status bar, left navigation, story overview, chapter history, right-side insight panel, responsive layout, and Chinese homepage copy. The plan intentionally does not alter backend story generation or the standalone config page logic.
- Placeholder scan: Removed generic directives and kept each task tied to explicit files, tests, commands, and minimum implementation shapes.
- Type consistency: The plan uses the current homepage data model (`StoryResponse`, `ChapterBundle`, story action callbacks) and keeps the new components presentation-only where possible.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-20-creative-workbench-homepage-implementation.md`.

Assumption for this session: execute inline immediately, since the user explicitly asked to start directly instead of stopping for an execution-mode choice.
