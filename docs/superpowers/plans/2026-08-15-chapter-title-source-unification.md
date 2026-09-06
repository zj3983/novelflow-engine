# Chapter Title Source Unification Plan

**Goal:** Make chapter detail outlines the sole source of chapter titles. The director copies that title, the writer only writes prose, and persistence rejects or corrects divergent titles.

## Tasks

1. Add regression tests proving writer prompts never receive the planned title and modular bundle adaptation no longer invents fallback titles.
2. Add a file-project title resolver with this precedence: existing formal chapter during rewrite, rolling chapter detail, legacy/base chapter detail. Missing titles for new prose generation fail explicitly.
3. Correct generated bundle titles at persistence time and keep the chapter summary title in sync.
4. After rolling chapter detail generation, synchronize titles into the compatibility outline for chapters without formal prose; never rename published chapters.
5. Run focused title, modular pipeline, rolling-outline, and file-project persistence tests, then run the broader story-core suite if focused tests pass.

## Acceptance

- Writer output cannot choose or rename a chapter title.
- A new chapter cannot be persisted without a chapter-detail title.
- Rolling and compatibility outlines show the same title for ungenerated chapters.
- Rewriting a published chapter preserves its existing formal title.
- Existing formal chapters are not bulk-renamed.
