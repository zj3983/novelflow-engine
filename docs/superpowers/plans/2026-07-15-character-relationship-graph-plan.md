# Character Relationship Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace duplicated character relationship data with one project-level graph that supports protagonist-centered browsing, editing, chapter-scoped prompt context, and chapter-to-chapter updates.

**Architecture:** `relationship_graph` is the canonical source. A focused backend module normalizes legacy edges and character-card notes, selects the subgraph for a cast, and merges dynamic relationship changes after a chapter. The workbench renders the graph from project data and edits the same edge list; character cards only derive their relationship display from it.

**Tech Stack:** Python 3.11, Pydantic, pytest, Next.js 14, React 18, TypeScript, Playwright, CSS/SVG without a new graph dependency.

---

### Task 1: Canonical Relationship Graph Model

**Files:**
- Create: `packages/story_core/relationship_graph.py`
- Create: `tests/story_core/test_relationship_graph.py`

- [ ] Write failing tests for stable edge IDs, legacy edge normalization, character-note migration, duplicate-pair merging, and cast subgraph selection.
- [ ] Run `python -m pytest tests/story_core/test_relationship_graph.py -q` and verify collection fails because the module is missing.
- [ ] Implement `RelationshipEdge`, `RelationshipChange`, `normalize_relationship_graph()`, `graph_from_character_cards()`, `merge_relationship_graph()`, and `select_relationship_subgraph()`.
- [ ] Preserve directional source/target knowledge, clamp trust/tension to 0-100, and keep old `bond` values.
- [ ] Run the focused tests and commit.

### Task 2: Make The Graph The Runtime Source

**Files:**
- Modify: `packages/story_core/file_project_store.py`
- Modify: `tests/story_core/test_file_project_store.py`

- [ ] Write failing tests proving generated cards populate the project graph, project updates normalize graph data, chapter character-state changes append a graph change, and writing packets include only relationships among the selected cast.
- [ ] Run the focused tests and verify the missing behavior.
- [ ] Normalize `relationship_graph` during project updates and outline-plan saves.
- [ ] Merge `CharacterState.relationships` into the graph in `_sync_project_after_chapter()` with `last_changed_chapter` and a compact change record.
- [ ] Add `relationship_context` to writing packets and remove the full graph from `packet_project`.
- [ ] Run store and writing-packet tests and commit.

### Task 3: Add The Relationship Graph Workbench

**Files:**
- Modify: `apps/web/lib/api.ts`
- Modify: `apps/web/components/ws/WorkspaceShell.tsx`
- Create: `apps/web/app/projects/[id]/relationships/page.tsx`
- Modify: `apps/web/app/globals.css`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] Write a failing Playwright test for protagonist-centered default view, person/chapter/global modes, adding an edge, editing trust/tension, and saving through `updateProject()`.
- [ ] Run `npm --prefix apps/web run test:e2e -- --grep "relationship graph"` and verify the route or controls are missing.
- [ ] Extend `ImportedRelationshipEdge` with canonical optional fields while retaining legacy compatibility.
- [ ] Add a `关系图` workspace navigation item and implement a responsive graph plus an editable relationship list.
- [ ] Use the protagonist as the default visual center, any selected person as an alternate center, the next chapter cast for chapter mode, and all nodes for global mode.
- [ ] Run the focused Playwright test and production build, then commit.

### Task 4: Derive Character Card Relationships From The Graph

**Files:**
- Modify: `apps/web/app/projects/[id]/characters/page.tsx`
- Modify: `apps/web/tests/story-workbench.spec.ts`

- [ ] Extend the character-card test so relationship text comes from `project.relationship_graph` even when `relationship_notes` is empty.
- [ ] Verify the test fails with the current character-card implementation.
- [ ] Replace the relationship-note display with graph edges touching the current character and stop sending `relationship_notes` from the character editor.
- [ ] Run the character and relationship Playwright tests and commit.

### Task 5: Regression And Existing Project Verification

**Files:**
- Modify only if verification exposes a compatibility defect.

- [ ] Run `python -m pytest -q`.
- [ ] Run the two focused Playwright flows and `npm --prefix apps/web run build`.
- [ ] Read `p-gou-webgame-restored` and `p-xianxia-incense-test-2` through `FileProjectStore`, normalize their relationship data without writing, and verify writing packets contain only local relationship context.
- [ ] Review the delta, fix any important findings with failing tests first, merge the feature branch, rerun verification on the merged branch, and clean up the worktree.
