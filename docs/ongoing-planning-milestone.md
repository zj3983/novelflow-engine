# Ongoing planning and the first cross-volume release

Base: main `00d8689839552e1d1a8342880517468233c7ae25` after its Python and Web post-merge checks succeeded.

The first volume continues to use the published Opening artifacts. Pending, discarded, and failed prose candidates do not advance `current_chapter`; every chapter still needs explicit confirmation. The next volume is planned only at the confirmed volume boundary.

## Explicit extension

`POST /file-projects/{id}/build-graph/opening/next-volume` accepts the current graph revision. It requires an active execution baseline, a clean graph, unchanged confirmed source fingerprint, and a complete confirmed first volume. It reads the next range from the accepted `volume_plan`, adds only missing `chapter_outline_N` tasks, and makes the deterministic handoff stale. It calls no provider. The prior manifest, materialization marker, published outline, and handoff are archived under `.webnovel/opening_plan_versions/vN/`; existing artifact history and prose receipts remain in place. The extension settings and graph manifest are committed together. An interrupted extension remains pending and blocks prose until a later orchestration completes publication.

`Continue Build` uses the existing Build Graph orchestration and validators. Each future chapter task receives its declared artifact reads plus bounded recent confirmed summaries, continuity state and Canon registry view. Pending candidates never enter that input. Every model result is validated and committed independently; failures or source/revision conflicts stop the job. Consumed tasks are not rerun or editable. The deterministic handoff is recalculated after all new details are accepted.

Confirmed prose can legitimately advance the project's `current_arc`, making the old world materialization domain hash stale. During an active future extension, orchestration therefore uses the exact confirmed-state/source fingerprint captured at extension instead of treating that old domain hash as an author edit. The ordinary WorldBuild materialization conflict check remains in place for other builds.

When the graph is clean, the publication transaction compares all consumed artifact revisions and the previously released chapter detail/contracts, then writes the combined outline and handoff, a new materialization marker, a version record and a new execution source baseline together. The archived prior version remains available as evidence for old receipts. This is the sanctioned version transition; an edit to the old planning baseline or confirmed state cannot be adopted by changing a fingerprint alone.

The prose gate remains whole-volume: until this publication is complete, `capture()` rejects candidates before any Character, Director, Writer or review provider call. New candidates use the committed Opening projection, full handoff contract, confirmed runtime state and the existing Canon Review/explicit confirmation transaction. Receipts include the applicable plan version and retain their graph/artifact authority.

Scope: one bounded successor volume (up to the graph's 200-chapter limit), with synthetic providers only. No automatic prose confirmation, accepted-prose rewrite, whole-book detail generation, or new scheduler. Real provider quality and cross-process filesystem atomicity remain outside this milestone.

The synthetic regression uses a 50-chapter first volume and a legally short 10-chapter final successor volume, so it can verify complete successor detail, publication and the first three successor prose chapters without making CI generate another 50 synthetic tasks. Production uses the accepted volume boundary, not this fixture length.
