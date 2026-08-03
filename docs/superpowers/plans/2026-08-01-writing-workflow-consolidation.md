# Writing Workflow Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate CLI/API model calls, chapter context assembly, planning, writing, review, and author-confirmed submission into one traceable workflow without breaking existing project APIs.

**Architecture:** Keep the existing public routes and `StoryOrchestrator` entry points as compatibility facades. Introduce small internal contracts for model calls, context packages, candidate drafts, and submit snapshots. Migrate the current implementation behind those contracts in phases, so old projects and existing tests continue to work.

**Tech Stack:** Python, Pydantic models already used by `packages/story_core`, FastAPI routes, pytest, existing file-project persistence.

---

## Scope and boundaries

- The model provider is an adapter concern. CLI and HTTP API implement the same gateway protocol.
- “Agent” becomes a logical task label for planning, writing, or review; it does not own separate memory or mutate project state directly.
- The writer receives a compact, chapter-specific context package rather than the whole project.
- World simulation runs only when the chapter plan declares an external state consequence.
- Review is one aggregated quality gate with at most one targeted revision round.
- Generation creates a candidate draft. Only explicit confirmation persists the chapter and derived memory/state updates.
- Existing prompt templates, routes, and stored projects remain readable during migration.

### Task 1: Add model-gateway contract

**Files:**
- Create: `packages/story_core/model_gateway/contracts.py`
- Modify: `packages/story_core/agent_base.py`
- Test: `tests/story_core/test_model_gateway_contract.py`

- [x] Write tests for a normalized success result and a normalized provider error.
- [x] Run `pytest tests/story_core/test_model_gateway_contract.py -q` and verify the new contract tests fail because the module is absent.
- [x] Add `ModelRequest` and `ModelResponse` dataclasses with provider, model, text, request id, usage, and error fields.
- [x] Add a small `ModelGateway` protocol whose only operation accepts a request and returns `ModelResponse`.
- [x] Run the focused test and then the existing provider tests.

### Task 2: Add context-package contract and selective retrieval

**Files:**
- Create: `packages/story_core/context/context_package.py`
- Create: `packages/story_core/context/context_builder.py`
- Test: `tests/story_core/test_context_builder.py`

- [x] Write tests proving a chapter package contains only selected outline, adjacent-chapter, character, relationship, foreshadowing, world, genre, and author-request sections.
- [x] Run the focused tests and verify they fail before implementation.
- [x] Implement deterministic filtering, section limits, source labels, and a stable snapshot id; do not call a model from this module.
- [x] Add an explicit `excluded_sections` list so the workbench can show what was not read.
- [x] Run focused tests and the existing writing-packet tests.

### Task 3: Add candidate-draft lifecycle

**Files:**
- Create: `packages/story_core/candidate_draft.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `apps/api/routes/file_projects.py`
- Test: `tests/story_core/test_candidate_draft.py`
- Test: `tests/api/test_file_project_candidate_routes.py`

- [x] Write tests proving generation can save a candidate without advancing `current_chapter`, and confirmation advances it exactly once.
- [x] Run focused tests and verify failure before implementation.
- [x] Store candidate JSON, body, quality report, context snapshot, and revision history under `.story-system/candidates/`.
- [x] Add candidate read, discard, and confirm operations behind the existing file-project route style.
- [x] Ensure confirm is idempotent and rejects confirmation of a superseded candidate.
- [x] Run focused API and store tests.

### Task 4: Move the chapter pipeline behind explicit stages

**Files:**
- Create: `packages/story_core/pipeline/chapter_pipeline.py`
- Create: `packages/story_core/pipeline/workflow_steps.py`
- Modify: `packages/story_core/orchestrator.py`
- Test: `tests/story_core/test_chapter_pipeline.py`

- [x] Write tests for the stage order: context, plan, optional simulation, writing, quality gate, candidate output.
- [x] Run focused tests and verify failure before implementation.
- [x] Extract stage calls from `StoryOrchestrator.generate_next_chapter` without changing existing prompt text or stored chapter schema.
- [x] Make `orchestrator.generate_next_chapter` delegate to the new pipeline and keep the old return type.
- [x] Emit structured parent-stage metadata while preserving detailed workflow steps; candidate output is now explicit.
- [x] Run chapter-generation, prompt-preview, and generation-progress tests.

Current checkpoint: the public entry delegates through a compatibility pipeline and records the effective stage order. Context assembly lives in `pipeline/context_stage.py`; outline-first planning and its bounded retry live in `pipeline/planning_stage.py`; optional world simulation, scene cards, and style guidance live in `pipeline/simulation_stage.py`; primary body generation, one empty retry, postprocessing, and optional expansion live in `pipeline/writing_stage.py`; review, one bounded revision, compression retry, and final review live in `pipeline/quality_stage.py`.

### Task 5: Consolidate review and revision

**Files:**
- Create: `packages/story_core/review/quality_gate.py`
- Modify: `packages/story_core/orchestrator.py`
- Modify: `packages/story_core/simplified_review.py`
- Test: `tests/story_core/test_quality_gate.py`

- [x] Write tests proving the quality stage preserves one consolidated review and revision runs at most once.
- [x] Run focused tests and verify failure before implementation.
- [x] Move orchestration of prose, dialogue, continuity, genre, and forbidden-meta-language checks into the quality gate.
- [x] Keep rule-based checks deterministic; use the model only for a bounded revision request.
- [x] Preserve the existing simplified review shape for the frontend.
- [x] Run all review and generation-quality tests.

Current checkpoint: `pipeline/quality_stage.py` owns the review/revision/compression decision flow, while `review/quality_gate.py` owns deterministic reviewer aggregation and the compatible consolidated report. `orchestrator.py` retains only a thin dependency-injection wrapper so existing callers and test replacements keep working. Task 5 is complete.

### Task 6: Split persistence and route responsibilities

**Files:**
- Create: `packages/story_core/persistence/chapter_store.py`
- Create: `packages/story_core/persistence/candidate_store.py`
- Create: `packages/story_core/persistence/snapshot_store.py`
- Modify: `packages/story_core/file_project_store.py`
- Modify: `apps/api/routes/file_projects.py`
- Test: existing file-project store and route suites

- [x] Move only persistence helpers first; leave `FileProjectStore` as a facade.
- [x] Keep paths and JSON schemas backward-compatible.
- [x] Reduce route functions to request validation, job dispatch, and response mapping.
- [x] Run the full Python test suite after each move.

### Task 7: Organize remaining files without broad deletion

**Files:**
- Move only after import coverage is green: root maintenance scripts into `scripts/maintenance`, `scripts/import`, and `scripts/export`.
- Add `__init__.py` compatibility exports for moved modules.
- Add a short `docs/architecture/story-core-layout.md`.

- [x] Build an import inventory before every move.
- [x] Move one group at a time and retain compatibility entry points.
- [x] Do not delete old modules until no import or stored-project path depends on them.

## Verification gates

- After Tasks 1–3: focused tests plus existing file-project API tests.
- After Task 4: generation progress, prompt preview, and chapter generation tests.
- After Task 5: all review and writing-quality tests.
- After Tasks 6–7: full `pytest -q` and frontend type/test checks.
- Before completion: update the code graph, inspect affected flows `generate_next`, `regenerate_chapter`, `revise_project_chapter`, and `submit_project_manual_draft`, then run the full suite.
