# Evidence-backed Continuity Delta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce evidence-backed location and timeline deltas from confirmed chapter prose while passing structured director context through every production extraction path.

**Architecture:** Keep `FactExtractor` deterministic by default. Add narrow timeline extraction and director-context propagation, preserve the optional model boundary for ambiguous facts, then dry-run and transactionally backfill existing confirmed chapters without touching prose.

**Tech Stack:** Python 3, Pydantic v2 models, pytest, existing Canon and candidate confirmation stores.

---

### Task 1: Reproduce missing deterministic facts

**Files:**
- Modify: `tests/story_core/test_fact_extractor.py`
- Test: `tests/story_core/test_fact_extractor.py`

- [ ] Add a test whose body explicitly moves known characters to `社区诊所` and advances from `凌晨` to `天亮`, asserting `location_movements` and `timeline_advances` retain their source sentences.
- [ ] Run `uv run pytest tests/story_core/test_fact_extractor.py -q` and verify the new timeline assertion fails because the extractor never appends `TimelineAdvance`.

### Task 2: Add narrow evidence-backed timeline extraction

**Files:**
- Modify: `packages/story_core/agents/fact_extractor/agent.py`
- Test: `tests/story_core/test_fact_extractor.py`

- [ ] Import `TimelineAdvance` and add an allowlisted temporal-cue extractor operating sentence by sentence.
- [ ] Append deterministic results in `FactExtractor.extract`, with the exact source sentence and confidence `1.0`.
- [ ] Add a negative test proving ordinary clock-related prose without a progression cue does not create a timeline fact.
- [ ] Run `uv run pytest tests/story_core/test_fact_extractor.py -q` and verify all extractor tests pass.

### Task 3: Preserve director and continuity context

**Files:**
- Modify: `packages/story_core/agents/pipeline.py`
- Modify: `packages/story_core/file_project_store.py`
- Test: `tests/story_core/test_fact_extractor.py`
- Test: `tests/story_core/test_file_project_store.py`

- [ ] Add a capturing extractor test around the modular pipeline and assert `FactExtractorContext.director_artifact` is the exact director result.
- [ ] Verify it fails because `run_modular_writer_pipeline` currently omits that argument.
- [ ] Pass `director_artifact` and available continuity facts into the extraction context without changing the default model behavior.
- [ ] Extend the file-project candidate extraction seam to accept and pass these optional inputs when available.
- [ ] Run the focused pipeline and store tests.

### Task 4: Guard all proposed model facts

**Files:**
- Modify: `packages/story_core/agents/fact_extractor/agent.py`
- Test: `tests/story_core/test_fact_extractor.py`

- [ ] Add failing tests for a model relationship whose entity ID is unknown and whose source text is absent from the chapter.
- [ ] Filter model proposals unless both IDs exist in Canon and normalized evidence text occurs in the body.
- [ ] Keep model failures non-fatal and deterministic facts intact.
- [ ] Run the full fact extractor test module.

### Task 5: Dry-run and backfill the isolated test book

**Files:**
- Read: `data/exported-projects/p-1d9e4ea7285b453e8f2de47abc656b6b/chapters/0001-*.md`
- Read: `data/exported-projects/p-1d9e4ea7285b453e8f2de47abc656b6b/chapters/0002-诊所续药与证据留存.md`
- Modify only through the existing Canon/candidate transaction files under that project.

- [ ] Hash both chapter bodies before backfill.
- [ ] Run the corrected extractor in dry-run mode and inspect every proposed fact and source sentence.
- [ ] Reject unmatched or inferred facts; apply only approved deterministic deltas through the existing transaction boundary.
- [ ] Hash the chapter bodies again and verify they are byte-for-byte unchanged.

### Task 6: Verification

**Files:**
- Test: `tests/story_core/test_fact_extractor.py`
- Test: `tests/story_core/test_candidate_confirmation_transaction.py`
- Test: `tests/story_core/test_file_project_store.py`
- Test: `tests/story_core/test_modular_bundle_adapter.py`

- [ ] Run the four focused test modules with `uv run pytest ... -q`.
- [ ] Run `uv run python -m py_compile` on every modified Python file.
- [ ] Inspect `git diff --check` and the exact scoped diff.
- [ ] Report extracted facts, persisted facts, unchanged chapter hashes, and anything intentionally left empty.
