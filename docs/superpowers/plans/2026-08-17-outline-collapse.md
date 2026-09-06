# Chapter Outline Collapse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add compact, controllable folding to pending and completed chapter outlines.

**Architecture:** Keep fold state entirely in the outline page. Render pending chapter summaries with native `details` elements controlled by React state, and wrap completed chapter records in one native `details` section. Existing outline data and save handlers remain unchanged.

**Tech Stack:** Next.js 14, React 18, TypeScript, Playwright.

---

### Task 1: Add folding behavior and tests

**Files:**
- Modify: `apps/web/app/projects/[id]/outline/page.tsx`
- Modify: `apps/web/app/globals.css`
- Test: `apps/web/tests/story-workbench.spec.ts`

- [x] **Step 1: Write the failing browser assertions**

Extend the outline fixture test so chapter 21 opens from `?tab=chapters&chapter=21`, chapter details are visible, “全部折叠” hides them, “全部展开” restores them, and completed chapter records are closed by default but can be opened.

- [x] **Step 2: Run the focused test and verify failure**

Run: `pnpm exec playwright test tests/story-workbench.spec.ts --grep "edits the project outline"`

Expected: FAIL because the folding controls and accessible disclosure labels do not exist.

- [x] **Step 3: Implement page-local fold state**

Add `expandedChapterNumbers: Set<number>` initialized from the URL `chapter` value, handlers for one/all chapters, controlled pending chapter disclosures, and a closed-by-default completed-record disclosure. Use a stable DOM id such as `chapter-outline-21` for URL-target scrolling.

- [x] **Step 4: Add compact disclosure styling**

Style the summary as a full-width clickable row, retain visible goal/status text, use the existing card borders, and keep controls wrapping on mobile.

- [x] **Step 5: Verify behavior and types**

Run:

```powershell
pnpm exec playwright test tests/story-workbench.spec.ts --grep "edits the project outline"
pnpm exec tsc --noEmit
```

Expected: focused test passes and TypeScript exits with code 0.

- [x] **Step 6: Verify in the live workbench**

Open `/projects/file%3Ap-da2c16a6ee9440d6ad52cb402ead88a0/outline?tab=chapters&chapter=191`, confirm chapter 191 is expanded, test both global controls, and confirm completed records remain editable after expansion.
