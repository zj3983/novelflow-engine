# Story Core Layout

## Chapter workflow

```text
model gateway
  -> context package
  -> outline-first planning
  -> optional world simulation
  -> primary writing and bounded expansion
  -> consolidated review and at most one revision
  -> candidate draft
  -> author confirmation
  -> chapter, review, state, and memory persistence
```

Generation never writes a confirmed chapter directly. It creates a candidate under
`.story-system/candidates/`; confirmation is the only operation that advances the
persisted chapter state.

## Package responsibilities

| Package | Responsibility |
| --- | --- |
| `model_gateway/` | Common request and response contract for CLI and HTTP providers. |
| `context/` | Deterministic chapter-specific context selection and snapshot ids. |
| `pipeline/` | Stage order and the context, planning, simulation, writing, and quality decisions. |
| `review/` | Parallel deterministic reviewers and one consolidated frontend-compatible report. |
| `persistence/` | Raw candidate, chapter artifact, atomic JSON, transaction, and rollback storage. |
| `genre_stages/` | Genre-specific planning, writing, revision, postprocessing, and review behavior. |

`StoryOrchestrator` and `FileProjectStore` remain compatibility facades. They assemble
dependencies and domain state, but new stage logic and raw filesystem behavior should
go into the packages above.

## File-project storage

The persisted paths remain backward-compatible:

```text
<project>/
  chapters/0001-标题.md
  .story-system/
    candidates/cd-*.json
    chapters/0001.json
    reviews/0001.json
    commits/*.json
  .webnovel/
    project.json
    state.json
    outline.json
```

- `CandidateStore` owns candidate draft files.
- `ChapterStore` owns chapter/review/markdown paths and raw chapter enumeration.
- `SnapshotStore` owns JSON writes, multi-file transactions, and rollback snapshots.
- `FileProjectStore` keeps the public API and delegates raw persistence through these stores.

## API boundary

`apps/api/routes/file_projects.py` validates requests and maps service errors to HTTP
responses. File lifecycle moves are implemented in
`apps/api/services/file_project_lifecycle.py`; chapter generation and persistence remain
behind `FileProjectStore`.

## Utility scripts

Root script names remain as compatibility entry points. Implementations are grouped in:

- `scripts/maintenance/`
- `scripts/import/`
- `scripts/export/`

Do not add new one-off implementation scripts at repository root.
