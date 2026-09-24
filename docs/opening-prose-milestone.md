# Opening prose handoff milestone

Base: PR #31 merged main a6b79df493d6a7798b9349d708d945c25aa312d8. Exact-commit Python and Web CI passed on the temporary verification branch.

Scope: explicitly extend the Opening Graph chapter window to the first volume boundary, retain existing accepted task artifacts, complete missing detail through the existing orchestration loop, then generate prose candidates through the existing Character Intent / Director / Writer / Canon Review pipeline. Acceptance covers the first three chapters with synthetic providers. No real project writes or provider calls.

Keep the full-volume prose gate. Generation does not confirm prose or canon. Bind every candidate to a clean, materialized graph revision and a project/state/canon snapshot; recheck after provider work and at confirmation. Conflicts stop without official writes. Confirmation reuses the existing project transaction and records which graph artifacts supplied the chapter. After prose begins, the opening graph remains frozen; subsequent chapter candidates consume the same planning baseline plus confirmed runtime state.

Do not add a second graph scheduler, automatic prose acceptance, cross-volume planning, or a new agent. Deliver a Draft PR for independent review; do not merge.

## User flow

1. Complete and materialize the initial three-chapter Opening Graph.
2. Explicitly select “补齐首卷细纲任务”. This adds missing chapter tasks up to the first volume end, archives the previous manifest, and invalidates readiness. It does not call a model.
3. Select “继续构建”. Existing orchestration generates only missing detail tasks, validates each commit, and publishes the clean graph. The bounded expansion supports at most 200 chapters; larger first volumes fail before mutation.
4. Open the existing writing page. Generate a pending candidate, review Canon/quality findings, then explicitly confirm it. Hard review findings remain blocking even when soft warnings are accepted.
5. Subsequent candidates use the frozen graph plus the last confirmed runtime state. Workbench displays `in_use`; the original materialization marker is retained as revision evidence.

## Review boundaries

- Candidate authority records graph revision, definition fingerprint, all artifact revisions, chapter number, and project/state/Canon/prose fingerprint. Rechecks occur after generation and inside confirmation's existing project lock.
- Provider work remains outside that project lock. A competing source edit causes candidate rejection; a graph edit before confirmation blocks publication.
- Confirmation receipts and the updated execution baseline participate in the existing rollback transaction with prose and Canon writes. This reuses the existing in-process lock and exception rollback guarantees; it does not introduce a cross-process filesystem transaction.
- The legacy direct-persist generation, regeneration, and polishing paths reject Opening projects. This milestone supports new pending candidates and explicit confirmation, not rewriting accepted Opening prose.
- Once prose is confirmed, planning/source drift stops continuation. In-place migration of a consumed plan and cross-volume continuation remain outside this milestone.
- Synthetic acceptance covers a 50-chapter first-volume shape, first-three confirmation flow, and the actual modular Character/Director/Writer/Canon-review integration using injected test runtimes. It does not establish real-provider prose quality.

## Iteration 1: bind consumed planning to Opening artifacts

Opening generation now projects StoryState and Director planning directly from the committed, validated Opening artifacts. Existing canonical/rolling files cannot override the chapter, neighboring detail, volume, or book summary. The projected chapter contract is compared in full with the committed and materialized handoff. Runtime continuity and confirmed story state retain their existing readers.

Immediately before Writer runs, its Director artifact contract and hook must equal the official handoff; mismatches fail before the provider. The source fingerprint additionally includes canonical outline/volume files, so changes during generation or before confirmation fail closed even though their planning overrides are ignored.

Regression fixtures demonstrate the original canonical-first reader choosing an obsolete hook, then verify that each of chapters 1–3 delivers the official complete contract to Character, the persisted Director artifact, and Writer. Both canonical and rolling conflicts are covered, including nonempty must_not_write and payoff_contract. Separate tests cover drift during provider work/before confirmation and rejection of forged Director contracts before Writer calls.
