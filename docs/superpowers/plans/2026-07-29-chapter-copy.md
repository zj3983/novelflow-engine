# Chapter Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a chapter toolbar action that copies the current chapter number, title, and complete body with clear success or failure feedback.

**Architecture:** Keep the feature client-side in the existing write page. A small pure formatter builds the copied text, while an async handler uses the Clipboard API with a legacy textarea fallback; the existing Playwright workbench fixture verifies the browser-visible behavior.

**Tech Stack:** Next.js 14, React 18, TypeScript, Playwright

---

### Task 1: Specify chapter copy behavior

**Files:**
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Write the failing browser test**

Add a test that opens chapter 1, stubs `navigator.clipboard.writeText`, clicks `复制章节`, and asserts that the captured value is exactly `第 1 章 <title>\n\n<body>` and the button changes to `已复制`.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `npm run test:e2e -- story-workbench.spec.ts --grep "copies the current chapter"`

Expected: FAIL because the `复制章节` button does not exist.

### Task 2: Implement copy action

**Files:**
- Modify: `apps/web/app/projects/[id]/write/page.tsx`

- [ ] **Step 1: Add the text formatter**

Add `chapterCopyText(chapterNumber, chapterTitle, body)` that returns a trimmed heading and body separated by one blank line.

- [ ] **Step 2: Add Clipboard API and compatibility fallback**

Add a helper that first calls `navigator.clipboard.writeText(text)`. If unavailable or rejected, copy through a temporary off-screen textarea and `document.execCommand("copy")`; throw when both methods fail.

- [ ] **Step 3: Add UI state and toolbar action**

Track `idle`, `copied`, and `failed` state. Add a `复制章节` toolbar button with a copy icon; show `已复制` briefly after success and an inline error after failure. Clear stale feedback when the selected chapter changes.

- [ ] **Step 4: Run the focused test**

Run: `npm run test:e2e -- story-workbench.spec.ts --grep "copies the current chapter"`

Expected: PASS.

### Task 3: Verify integration and layout

**Files:**
- Verify: `apps/web/app/projects/[id]/write/page.tsx`
- Verify: `apps/web/tests/story-workbench.spec.ts`

- [ ] **Step 1: Run TypeScript/production build verification**

Run: `npm run build`

Expected: Next.js build completes without TypeScript errors.

- [ ] **Step 2: Run related chapter-page tests**

Run: `npm run test:e2e -- story-workbench.spec.ts --grep "chapter|copies the current chapter"`

Expected: All selected tests pass.

- [ ] **Step 3: Verify the live chapter page**

Reload chapter 142 at desktop and narrow width, confirm the toolbar wraps cleanly, click `复制章节`, and confirm the visible success state.

- [ ] **Step 4: Review the diff**

Run: `git diff --check -- apps/web/app/projects/[id]/write/page.tsx apps/web/tests/story-workbench.spec.ts`

Expected: No whitespace errors.
