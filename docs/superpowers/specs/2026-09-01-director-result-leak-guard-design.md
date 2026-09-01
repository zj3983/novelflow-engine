# Director Result Leakage Guard Design

## Problem

Chapter 300 of the file project `p-da2c16a6ee9440d6ad52cb402ead88a0`
contains director-only result language in reader-facing prose. The writer copied or
closely paraphrased all three `scene_beats[].result` values, including the literal
meta sentence “完成本卷终局收束，林修主角身份从求生反抗者正式升华为万界灵气网络维修工”.

The modular generation path currently converts consistency findings into
`quality_report.writing_review` but does not run a director-aware prose leakage
check before persistence. The existing generic planning-meta detector only catches
planning terms treated as physical entities and does not cover editorial result
sentences.

## Constraints

- Do not regenerate chapter 300.
- Preserve its intended plot: the local cultivation world stabilizes, the outside
  signal is decoded, and Lin Xiu leaves for realm 739.
- Repair only reader-facing prose leakage; planning summaries may retain planning
  language.
- Preserve the existing uncommitted character-card work in the modular adapter and
  its tests.
- Keep `modular_bundle_adapter.py` a pure modular-to-legacy conversion boundary.

## Considered Approaches

### 1. Prompt-only prevention

Tell the writer more strongly not to copy director results. This is cheap but cannot
guarantee compliance and would not protect persistence when a model ignores the
instruction.

### 2. Generic phrase blacklist

Reject phrases such as “完成本卷收束” and “身份升华”. This catches the observed
sentence but is brittle, easy to paraphrase around, and risks false positives in
legitimate dialogue or quoted documents.

### 3. Director-aware deterministic hard gate (selected)

Compare the generated body against the actual director scene results, detect exact
or strongly signalled editorial leakage, and merge the finding into the modular
chapter quality report before persistence. This follows the real data flow, remains
deterministic, and can distinguish a legitimate use of “维修工” from copied planning
language.

## Design

Add a pure review helper in the prose-review layer. It accepts the chapter body and
the director result strings and returns the standard review shape: `pass`, `issues`,
`revision_plan`, and a hard score key named `director_result_leak`.

The helper reports a hard violation when either condition is true:

1. A normalized director result of meaningful length occurs verbatim in the body.
2. A sentence contains editorial markers such as “完成本卷/本章收束”, “故事舞台从…扩展”,
   or “主角身份…升华”, outside dialogue and quoted in-world text.

Normal plot vocabulary, including “维修工”, “万界”, “收束阵法”, or a character
describing a job, must not fail by itself.

In `StoryOrchestrator._generate_next_chapter_bundle_via_modular_agents`, adapt the
modular result first, run the director-aware sub-review together with the existing
critical prose review, and merge that review into the legacy bundle quality report.
The adapter stays pure. The existing file-project quality assertion then prevents a
leaking candidate from being persisted or confirmed. This change adds no automatic
model retry.

## Current Chapter Repair

After the guard is green, replace only the three reader-facing summary sentences in
`chapters/0300-新的维修单.md` with dramatized action, dialogue, or observable change.
Keep the outline, director artifact, chapter summary, scene results, continuity
facts, and hook unchanged because their planning language is valid metadata.

Synchronize every persisted reader-body representation and integrity field used by
the confirmed chapter transaction, including the confirmed candidate body,
`body_chars`, and `body_sha256`. Do not edit unrelated historical snapshots.

## Error Handling

The hard gate returns a specific issue explaining that director result text leaked
into prose. Persistence should fail through the existing quality mechanism and keep
the rejected draft in the normal failed-draft path. No silent text deletion occurs.

## Tests and Acceptance

- A body containing an exact director result fails with `director_result_leak`.
- A body containing “完成本卷终局收束” or “主角身份…升华” fails even when paraphrased.
- Legitimate narrative use of “万界维修工” passes.
- The modular orchestration path exposes the hard finding in the legacy quality
  report while preserving existing consistency findings.
- Focused prose-review, modular-adapter, modular-main-flow, and persistence tests
  pass.
- Chapter 300 contains none of the three planning-summary sentences, its markdown
  hash and character count match persisted metadata, and no chapter generation job
  is started.
