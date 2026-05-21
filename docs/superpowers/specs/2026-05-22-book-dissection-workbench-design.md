# Book Dissection Workbench Design

## Goal

Add a "拆书" workflow to the writing workbench. The first version should help the user learn from reference webnovel chapters and diagnose their own project chapters without copying source prose.

The feature should answer two practical questions:

- 参考书这一章为什么好看，结构怎么起作用？
- 我自己的章节哪里不爽、哪里跑设定、下一版该怎么改？

## Scope

Version 1 supports pasted text and current project chapters. It does not need full-book import, website crawling, automatic copyright scraping, or batch analysis.

The workbench adds one entry point named "拆书". It supports two modes:

- `参考书拆解`: user pastes one chapter or a short multi-chapter excerpt.
- `本书体检`: user selects an existing project chapter.

Both modes return a structured report. The report can be read directly and can also be turned into writing guidance for later generation.

## User Flow

For reference text:

1. User opens the "拆书" page.
2. User chooses "参考书拆解".
3. User pastes chapter text and optionally adds genre notes such as "网游", "苟道", "幕后流".
4. Backend returns a dissection report.
5. User may save selected points into project writing references.

For the current novel:

1. User opens the "拆书" page from a project.
2. User chooses "本书体检".
3. User selects a chapter.
4. Backend reads the chapter body and project state.
5. Backend returns a diagnosis report with concrete revision advice.

## Report Shape

The report uses clear Chinese labels and avoids vague AI-report language.

Reference report:

- `章节作用`: this chapter's job in the larger story.
- `爽点来源`: what gives the reader reward.
- `主角进展`: what changed for the protagonist.
- `冲突推进`: pressure, obstacle, action, result.
- `对话功能`: what each important exchange does.
- `节奏拆解`: scene order and turning points.
- `结尾钩子`: why the reader continues.
- `可学习写法`: reusable craft patterns.
- `不能照抄`: source-specific content that should not be copied.

Current-chapter report:

- `主要问题`: ranked concrete issues.
- `不爽原因`: where reward, pressure, or progress is weak.
- `设定冲突`: state, task, inventory, money, level, timeline.
- `对话问题`: short, stiff, unnatural, or exposition-heavy lines.
- `说明感问题`: places that read like a design note.
- `下一版改法`: actionable rewrite instructions.
- `可写入提示词`: concise guidance usable by the generation pipeline.

## Backend Design

Add a new story-core module, for example `packages/story_core/book_dissection.py`.

Core functions:

- `dissect_reference_text(text, *, genre="", focus="") -> dict`
- `diagnose_project_chapter(project_context, chapter) -> dict`

The module should keep output schema stable and easy to test. The first implementation can use deterministic local heuristics plus existing model infrastructure where available. Heuristics should cover obvious issues such as very short dialogue runs, repeated combat pattern, missing chapter progress, forbidden game-state conflicts, and stale ledger terms.

Add API routes:

- `POST /book-dissection/reference`
- `POST /file-projects/{project_id}/book-dissection/chapter`

The file-project route should use `FileProjectStore` as the source of truth, not screenshots or browser state.

## Frontend Design

Add a project page at:

- `/projects/[id]/dissection`

Add a navigation item named "拆书" near existing write/review/world entries.

Page layout:

- Mode switch: `参考书拆解` / `本书体检`.
- Reference mode: textarea, genre/focus input, run button.
- Project mode: chapter selector, run button.
- Result area: grouped sections with compact headings.
- Optional action: save selected guidance into project references or author constraints. This can be present but disabled until the backend save endpoint exists.

The interface should be utilitarian, not a landing page. It should feel like a workbench panel.

## Data Flow

Reference mode:

`textarea text -> API -> dissection module -> structured report -> UI`

Project mode:

`project id + chapter number -> FileProjectStore -> chapter body + state -> dissection module -> structured report -> UI`

Later integration:

Selected report items can be converted into writing references. They should not automatically become hard author constraints unless the user explicitly saves them.

## Error Handling

- Empty text returns a clear validation message.
- Very long pasted text is rejected with a length message in v1.
- Missing project or chapter returns a normal API error.
- If model-backed analysis fails, return a deterministic fallback report with basic checks instead of a blank panel.

## Testing

Backend tests:

- Reference text returns all required sections.
- Project chapter diagnosis reads from `FileProjectStore`.
- Empty input returns validation error.
- Fallback report still contains concrete issue lists.

Frontend tests:

- Dissection page renders.
- User can switch modes.
- Reference mode submits text and displays report sections.
- Project mode loads chapters and displays diagnosis.

## Non-Goals

- No web scraping.
- No full-book import in v1.
- No copying source prose into prompts.
- No automatic overwrite of author constraints.
- No automatic rewrite triggered by a dissection report.

## Save Policy

The first implementation should store saved dissection guidance only after the user asks for it. Until then, reports are read-only.
