# Manual Chapter Expansion Design

## Goal

Expose the existing chapter-expansion prompt as an explicit user action. Automatic review and generation must never invoke expansion.

## Behavior

- Show `扩写本章` for an existing file-project chapter whose compact character count is below 3800.
- The action reuses the existing expansion prompt, configured writer runtime, chapter body, chapter plan, world facts, and story state.
- Expansion targets the existing 4200-5500 character range.
- The expanded body is saved as a pending `regenerate` candidate. It never overwrites the confirmed chapter automatically.
- The existing candidate panel provides `采用候选稿` and `丢弃` actions.
- Empty, shorter, or above-hard-maximum model output fails without changing the chapter.
- Generation and review continue to preserve the first draft and never trigger this action automatically.

## Components

- `FileProjectStore.expand_chapter`: validates the source, calls the existing expansion prompt once, builds a candidate from the current chapter metadata, and records progress.
- File-project generation jobs: accept an explicit `operation=expand` and run expansion on the existing single-worker queue.
- Web API client and write page: submit the expand job, poll existing job status, then load the existing candidate panel.

## Verification

- Store tests prove one expansion call, candidate-only persistence, and source/output validation.
- Route tests prove `operation=expand` dispatches expansion rather than regeneration.
- Playwright tests prove button visibility, job request payload, and candidate presentation.

