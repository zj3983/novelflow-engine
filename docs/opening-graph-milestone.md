# Opening Graph milestone

Extend the existing project Build Graph through an explicit Workbench activation action. Keep the same BuildGraphService, artifact history, run ownership, validators, and orchestration loop.

The graph orders author input, Story Core, character seeds, the existing WorldBuild slice, detailed characters, relationships, longform story engine, book outline, volume plan, event chains, per-chapter outlines, and a deterministic OutlineExecutionContract handoff. The initial chapter window is the first three chapters, as selected by the user; book and volume planning cover the whole book.

Activation is a sanctioned definition migration under the project lock. Preserve immutable artifact/run history and archive the previous manifest. New dependencies invalidate the affected existing tasks. Browsing never initializes or migrates a graph. Existing WorldBuild projects keep their current definition until activation.

All generated tasks use the existing one-call Workbench executor and commit boundary. Validators reuse StoryCoreCard, PlanningCharacterSeed/Card, RelationshipEdge, OverallOutline, ArcOutline, ChapterPlan, validate_generated_opening_plan, and the Director's contract builder. Model input contains only declared committed reads and the full output contract.

Materialization publishes the project, outline, handoff, and revision marker together. It requires a clean graph and unchanged project/outline sources. Opening revisions invalidate readiness; current graph artifacts, not legacy projections, supply the new outputs. Existing prose projects cannot activate this opening-only workflow.

Acceptance: synthetic graph/API regressions for migration, ownership/validation, revision/stale closure, failures and source conflicts, complete deterministic handoff, atomic materialization, reload, and read-only browsing; Workbench UI activation and progress; relevant core/API suites, Web build, and CI. No real provider or real project writes. Deliver one Draft PR for independent milestone review.

This milestone ends at the typed outline handoff. The existing prose workflow still requires complete volume detail before writing; the three-chapter opening window does not bypass that gate. Character Intent / Director / Writer / Canon runtime integration and continuation after prose are the following milestone. The opening-only workflow rejects projects that already have written chapters.
