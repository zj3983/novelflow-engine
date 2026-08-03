# Per-Genre Outline Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every novel type an independent, editable outline template that AI fills during book creation without leaking rules from other genres.

**Architecture:** Store a compact three-layer template on each novel-type record. The outline generator receives only the selected type's template and writes the filled result into the canonical project outline. The Novel Types page exposes the template in overall, arc, and chapter tabs.

**Tech Stack:** Python, FastAPI, Pydantic, Next.js, TypeScript, Playwright, pytest.

---

## Task 1: Add the canonical outline-template model

- [x] Add failing tests for built-in templates, custom type persistence, validation, and isolation.
- [x] Create `packages/story_core/outline_templates.py` with the versioned three-layer schema and per-genre defaults.
- [x] Add `outline_template` to `NovelTypeRecord`, serialization, custom storage, and API requests.
- [x] Run the focused library and API tests.

## Task 2: Pass only the selected template into outline generation

- [x] Add failing tests proving xuanhuan, webgame, and custom types receive different templates.
- [x] Add the selected template to `novel_type_prompt_context` with compact serialization.
- [x] Update the outline generation prompt so AI fills the supplied structure instead of inventing one.
- [x] Add explicit errors for missing or invalid templates.
- [x] Run the focused prompt and generation tests.

## Task 3: Persist the filled long-form outline

- [x] Add failing tests for long-term lines, arc progression, and chapter-detail fields.
- [x] Extend the canonical project-outline models and normalizers.
- [x] Update generation schemas, markdown synchronization, and frontend API types.
- [x] Ensure opening generation creates only the first ten chapter details.
- [x] Run outline model, planning, store, and sync tests.

## Task 4: Make templates visible and editable

- [x] Add a failing component or Playwright test for the three template tabs.
- [x] Add overall, arc, and chapter template editors to the Novel Types page.
- [x] Validate before save and show clear errors instead of silently falling back.
- [x] Show template source and version on the project outline page.
- [x] Run frontend typecheck/build and Playwright coverage.

## Task 5: Verify the complete book-opening flow

- [x] Create or reuse one webgame project and one non-game project.
- [x] Inspect the actual generation packages and confirm each contains only its own template.
- [x] Run generated-plan fixtures and confirm saved results preserve distinct genre-specific lines and arcs.
- [x] Run the full relevant backend suite and frontend build.
- [x] Record any compatibility migration applied to existing projects and novel types.
