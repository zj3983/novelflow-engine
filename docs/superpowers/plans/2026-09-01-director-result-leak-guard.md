# Director Result Leakage Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent director-only result summaries from reaching reader prose and repair chapter 300 without regenerating it.

**Architecture:** Add a pure, director-aware prose sub-review and merge it into the modular orchestration quality report after adaptation but before persistence. Keep the adapter pure, rely on the existing file-project hard quality assertion, then repair the confirmed chapter through an integrity-preserving data transaction.

**Tech Stack:** Python 3.12, Pydantic chapter bundles, pytest, JSON file-project persistence, SHA-256 body integrity.

---

## File Map

- Modify `packages/story_core/prose_rule_review.py`: add the contextual director-result leakage reviewer and hard category.
- Modify `packages/story_core/orchestrator.py`: run the contextual reviewer on modular output and merge its findings into quality metadata.
- Modify `tests/story_core/test_prose_rule_review.py`: pin exact, editorial-marker, dialogue, and legitimate-role behavior.
- Modify `tests/story_core/test_modular_main_flow.py`: pin modular orchestration wiring and quality propagation.
- Modify project chapter artifacts under `data/exported-projects/p-da2c16a6ee9440d6ad52cb402ead88a0`: replace only reader-facing prose and synchronize integrity metadata.

### Task 1: Pure Director-Result Leakage Reviewer

**Files:**
- Modify: `tests/story_core/test_prose_rule_review.py`
- Modify: `packages/story_core/prose_rule_review.py`

- [ ] **Step 1: Write the failing reviewer tests**

Add imports and tests for a wished-for API:

```python
from packages.story_core.prose_rule_review import review_director_result_leak


def test_review_flags_verbatim_director_result_in_body():
    result = "完成本卷终局收束，林修主角身份从求生反抗者正式升华为万界灵气网络维修工。"
    review = review_director_result_leak(f"林修踏入通道，{result}", director_results=[result])
    assert review["pass"] is False
    assert review["scores"]["director_result_leak"] == 5


def test_review_flags_editorial_identity_summary_without_exact_match():
    review = review_director_result_leak(
        "至此完成本卷收束，主角身份也正式升华为万界维修工。",
        director_results=["林修离开本界。"],
    )
    assert review["pass"] is False


def test_review_allows_role_language_without_editorial_summary():
    review = review_director_result_leak(
        "林修扣紧工具箱：‘维修工不修好东西，难道留着过年？’",
        director_results=["林修接下跨界维修任务。"],
    )
    assert review["pass"] is True
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/story_core/test_prose_rule_review.py -k director_result -q
```

Expected: collection fails because `review_director_result_leak` does not exist.

- [ ] **Step 3: Implement the minimal pure reviewer**

Add a helper that normalizes whitespace and punctuation, searches meaningful director results, and searches reader narration for narrow editorial markers. Return the standard review envelope:

```python
def review_director_result_leak(
    text: str,
    *,
    director_results: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    issues: list[str] = []
    # exact normalized overlap and narrow editorial-marker checks
    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": ["把导演结果改写成动作、对话和可观察后果。"] if issues else [],
        "scores": {"director_result_leak": 5 if issues else 8},
    }
```

Add `director_result_leak` to `HARD_REVIEWERS`. Avoid a broad blacklist: quoted dialogue and a standalone role word must remain valid.

- [ ] **Step 4: Run the focused reviewer tests and verify GREEN**

Run the same pytest command. Expected: the new tests pass.

### Task 2: Modular Orchestration Hard Gate

**Files:**
- Modify: `tests/story_core/test_modular_main_flow.py`
- Modify: `packages/story_core/orchestrator.py`

- [ ] **Step 1: Write the failing modular-flow test**

Use the existing `_StubDirectorRuntime`, `_StubWriterRuntime`, `_seed_legacy_webnovel`, and `_story_state` helpers. Generate a long body that contains `进入山路` verbatim and assert:

```python
assert bundle.quality_report["ok"] is False
writing = bundle.quality_report["writing_review"]
assert writing["requires_revision"] is True
assert writing["scores"]["director_result_leak"] == 5
```

Also retain an assertion in the existing normal main-flow test that a clean body has no hard director-result finding.

- [ ] **Step 2: Run the modular-flow test and verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/story_core/test_modular_main_flow.py -k director_result -q
```

Expected: quality remains `ok=True` because only consistency findings are currently adapted.

- [ ] **Step 3: Merge the contextual review in the orchestrator**

In `_generate_next_chapter_bundle_via_modular_agents`, keep adaptation pure:

```python
legacy_bundle = adapt_modular_bundle_to_legacy(...)
director_results = [str(beat.result or "") for beat in bundle.director_artifact.scene_beats]
director_review = review_director_result_leak(
    legacy_bundle.body,
    director_results=director_results,
)
writing_review = review_critical_prose_rules(
    legacy_bundle.body,
    extra_subreviews=[director_review],
)
legacy_bundle.quality_report = _merge_writing_review_quality(
    legacy_bundle.quality_report,
    writing_review,
)
return legacy_bundle
```

Preserve pre-existing consistency blocking and warnings when merging. Do not add a model retry.

- [ ] **Step 4: Run modular and adapter tests and verify GREEN**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/story_core/test_modular_main_flow.py tests/story_core/test_modular_bundle_adapter.py -q
```

Expected: all tests pass, including the pre-existing dirty-worktree character-card assertions.

### Task 3: Repair and Verify Chapter 300

**Files:**
- Modify: `data/exported-projects/p-da2c16a6ee9440d6ad52cb402ead88a0/chapters/0300-新的维修单.md`
- Modify through the existing project transaction boundary: confirmed candidate and chapter integrity metadata.

- [ ] **Step 1: Capture the current integrity baseline**

Read the chapter record, confirmed candidate, markdown SHA-256, `body_chars`, and occurrences of the three director-result sentences. Expected baseline: three prose hits and a matching pre-repair hash.

- [ ] **Step 2: Apply the three prose-only rewrites**

Replace the three synopsis sentences with observable action:

- the network turns green and delegates sign the maintenance contract;
- decoded realm-739 coordinates change Lin Xiu and Shen Moli's decision;
- Lin Xiu and Shen Moli exchange one brief line and step into the portal.

Do not change the outline, director artifact, chapter summary, continuity facts, chapter title, or hook.

- [ ] **Step 3: Synchronize persisted body representations atomically**

Use the existing project transaction/store boundary to update the confirmed candidate body and the chapter body's `body_sha256` and `body_chars`. Preserve candidate id, confirmation time, continuity delta, and chapter history.

- [ ] **Step 4: Verify data consistency**

Assert:

```text
director result prose hits = 0
chapter body_sha256 = sha256(markdown UTF-8 bytes)
chapter body_chars = len(markdown text)
confirmed candidate body = markdown text
chapter number/title/hook unchanged
no generation job created
```

- [ ] **Step 5: Run final focused verification**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/story_core/test_prose_rule_review.py tests/story_core/test_modular_main_flow.py tests/story_core/test_modular_bundle_adapter.py tests/story_core/test_file_project_store.py -q
git diff --check
```

Report any unrelated pre-existing failures separately; do not claim the full repository is clean unless the command proves it.
