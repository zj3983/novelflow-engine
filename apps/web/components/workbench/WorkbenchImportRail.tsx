"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { BookImportPanel } from "../BookImportPanel";
import { BookLibraryBrowser } from "../BookLibraryBrowser";
import type {
  BookImportBootstrapResponse,
  BookLibraryCatalogResponse,
  BookLibraryItem,
  ChapterBundle,
  ProjectResponse,
  StoryResponse,
  UpdateProjectRequest,
} from "../../lib/api";
import type { StoryDraft } from "../StorySidebar";
import { WorkbenchDraftEditor } from "./WorkbenchDraftEditor";

type WorkbenchImportRailProps = {
  currentProjectId: string;
  projectTitle: string;
  project: ProjectResponse | null;
  story: StoryResponse | null;
  bundle: ChapterBundle | null;
  importedDraft: BookImportBootstrapResponse["draft"] | null;
  catalog: BookLibraryCatalogResponse | null;
  selectedSourceItemId: string | null;
  onSelectSourceItem: (item: BookLibraryItem) => void;
  draft: StoryDraft;
  onDraftChange: (next: StoryDraft | ((current: StoryDraft) => StoryDraft)) => void;
  onBootstrapDraft: (draft: BookImportBootstrapResponse["draft"]) => void;
  onCatalogLoaded: (catalog: BookLibraryCatalogResponse | null) => void;
  onLoadWorld: (draft?: BookImportBootstrapResponse["draft"]) => Promise<void>;
  onSaveProject: (payload: UpdateProjectRequest) => Promise<void>;
  isSavingProject: boolean;
};

type ProjectEditorState = {
  title: string;
  source_path: string;
  seed_outline: string;
  world_summary: string;
  current_focus: string;
  author_constraints: string;
};

const PROJECT_EDITOR_CACHE_PREFIX = "novel-autogrowth-engine.project-editor.";
const CURRENT_PROJECT_EDITOR_CACHE_KEY = "novel-autogrowth-engine.project-editor.current";

function projectStatusLabel(status: ProjectResponse["status"] | null | undefined): string {
  if (status === "simulating") return "演化中";
  if (status === "paused") return "暂停";
  if (status === "completed") return "完结";
  return "准备中";
}

function sourceLabel(project: ProjectResponse | null, importedDraft: BookImportBootstrapResponse["draft"] | null): string {
  return project?.source_path?.trim() || importedDraft?.source_path?.trim() || "";
}

function focusLabel(
  project: ProjectResponse | null,
  bundle: ChapterBundle | null,
  importedDraft: BookImportBootstrapResponse["draft"] | null,
): string {
  return (
    project?.current_focus?.trim() ||
    bundle?.chapter_intent?.next_focus ||
    bundle?.event_plan?.next_focus ||
    importedDraft?.current_focus?.trim() ||
    importedDraft?.summary ||
    "等待导演层确定下一轮推进焦点。"
  );
}

function worldSummaryLabel(
  project: ProjectResponse | null,
  bundle: ChapterBundle | null,
  importedDraft: BookImportBootstrapResponse["draft"] | null,
): string {
  return (
    project?.world_summary?.trim() ||
    importedDraft?.world_summary?.trim() ||
    importedDraft?.summary?.trim() ||
    bundle?.event_plan?.pivot ||
    "世界背景还在沉淀中，随着章节推进会越来越清晰。"
  );
}

function outlinePreview(project: ProjectResponse | null, draft: StoryDraft): string {
  const outline = project?.seed_outline?.trim() || draft.outline.trim();
  if (!outline) {
    return "还没有填写种子大纲。";
  }
  return outline.split(/\r?\n/).slice(0, 3).join(" ");
}

function recentEventLabel(story: StoryResponse | null, bundle: ChapterBundle | null): string {
  return bundle?.event_plan?.pivot || story?.agent_runtime?.recent_events.at(-1) || "最近还没有运行记录。";
}

function createEditorState(
  currentProjectId: string,
  projectTitle: string,
  project: ProjectResponse | null,
  draft: StoryDraft,
  importedDraft: BookImportBootstrapResponse["draft"] | null,
): ProjectEditorState {
  const baseState: ProjectEditorState = {
    title: project?.title || projectTitle,
    source_path: sourceLabel(project, importedDraft),
    seed_outline: project?.seed_outline || draft.outline,
    world_summary: project?.world_summary || importedDraft?.world_summary || importedDraft?.summary || draft.directorBrief,
    current_focus: project?.current_focus || importedDraft?.current_focus || "",
    author_constraints: (project?.author_constraints ?? importedDraft?.author_constraints ?? []).join("\n"),
  };

  if (typeof window === "undefined") {
    return baseState;
  }

  try {
    const scopedKey = `${PROJECT_EDITOR_CACHE_PREFIX}${currentProjectId}`;
    const scopedRaw = currentProjectId ? window.localStorage.getItem(scopedKey) : null;
    if (scopedRaw) {
      return {
        ...baseState,
        ...(JSON.parse(scopedRaw) as Partial<ProjectEditorState>),
      };
    }

    const fallbackRaw = window.localStorage.getItem(CURRENT_PROJECT_EDITOR_CACHE_KEY);
    if (!fallbackRaw) {
      return baseState;
    }

    return {
      ...baseState,
      ...(JSON.parse(fallbackRaw) as Partial<ProjectEditorState>),
    };
  } catch {
    return baseState;
  }
}

function saveEditorCache(projectId: string, editor: ProjectEditorState) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    if (projectId) {
      window.localStorage.setItem(`${PROJECT_EDITOR_CACHE_PREFIX}${projectId}`, JSON.stringify(editor));
    }
    window.localStorage.setItem(CURRENT_PROJECT_EDITOR_CACHE_KEY, JSON.stringify(editor));
  } catch {
    // Ignore storage failures and keep the in-memory editor state.
  }
}

export function WorkbenchImportRail({
  currentProjectId,
  projectTitle,
  project,
  story,
  bundle,
  importedDraft,
  catalog,
  selectedSourceItemId,
  onSelectSourceItem,
  draft,
  onDraftChange,
  onBootstrapDraft,
  onCatalogLoaded,
  onLoadWorld,
  onSaveProject,
  isSavingProject,
}: WorkbenchImportRailProps) {
  const [editor, setEditor] = useState<ProjectEditorState>(() =>
    createEditorState(currentProjectId, projectTitle, project, draft, importedDraft),
  );
  const [saveNotice, setSaveNotice] = useState("");

  useEffect(() => {
    setEditor(createEditorState(currentProjectId, projectTitle, project, draft, importedDraft));
  }, [currentProjectId, projectTitle, project, draft.outline, draft.directorBrief, importedDraft]);

  const constraints = project?.author_constraints?.filter(Boolean) ?? importedDraft?.author_constraints?.filter(Boolean) ?? [];
  const sourcePath = sourceLabel(project, importedDraft);

  async function handleSaveProject() {
    if (!project) {
      setSaveNotice("请先生成第一章或创建项目，再保存项目资料。");
      saveEditorCache(currentProjectId, editor);
      return;
    }

    const payload: UpdateProjectRequest = {
      title: editor.title.trim() || project.title,
      source_path: editor.source_path.trim(),
      seed_outline: editor.seed_outline.trim(),
      world_summary: editor.world_summary.trim(),
      current_focus: editor.current_focus.trim(),
      author_constraints: editor.author_constraints
        .split(/\r?\n/)
        .map((item) => item.trim())
        .filter(Boolean),
    };

    try {
      await onSaveProject(payload);
      saveEditorCache(currentProjectId, editor);
      setSaveNotice("项目资料已保存到后端。");
    } catch {
      saveEditorCache(currentProjectId, editor);
      setSaveNotice("项目资料保存失败，请查看页面上的错误提示。");
    }
  }

  return (
    <div className="workbench-navrail">
      <section className="panel">
        <header className="panel__header">工作台导航</header>
        <div className="panel__body workbench-navrail__quicklinks">
          <span className="workbench-navrail__quicklink">项目资料</span>
          <span className="workbench-navrail__quicklink">世界锚点</span>
          <span className="workbench-navrail__quicklink">书籍导入</span>
          <span className="workbench-navrail__quicklink">配置中心</span>
        </div>
      </section>

      <section className="panel" aria-label="项目资料面板">
        <header className="panel__header">项目资料</header>
        <div className="panel__body workbench-navrail__stack">
          <article className="project-dossier-card project-dossier-card--hero">
            <p className="project-dossier-card__eyebrow">小说项目</p>
            <h3 className="project-dossier-card__title">{projectTitle || "未命名小说项目"}</h3>
            <p className="project-dossier-card__summary">{worldSummaryLabel(project, bundle, importedDraft)}</p>
            <div className="project-dossier-card__meta">
              <span className="project-chip">状态：{projectStatusLabel(project?.status)}</span>
              <span className="project-chip">主线：{project?.active_story_id || story?.story_id || "未创建"}</span>
              <span className="project-chip">推进：第 {story?.current_chapter ?? 0} 章</span>
            </div>
          </article>

          <div className="project-editor">
            <label className="project-editor__field">
              <span className="project-editor__label">项目标题</span>
              <input
                aria-label="项目标题"
                className="project-editor__input"
                value={editor.title}
                onChange={(event) => setEditor((current) => ({ ...current, title: event.target.value }))}
              />
            </label>

            <label className="project-editor__field">
              <span className="project-editor__label">导入来源</span>
              <input
                aria-label="导入来源"
                className="project-editor__input"
                value={editor.source_path}
                onChange={(event) => setEditor((current) => ({ ...current, source_path: event.target.value }))}
              />
            </label>

            <label className="project-editor__field">
              <span className="project-editor__label">种子大纲</span>
              <textarea
                aria-label="种子大纲"
                className="project-editor__textarea project-editor__textarea--medium"
                value={editor.seed_outline}
                onChange={(event) => setEditor((current) => ({ ...current, seed_outline: event.target.value }))}
              />
            </label>

            <label className="project-editor__field">
              <span className="project-editor__label">世界摘要</span>
              <textarea
                aria-label="世界摘要"
                className="project-editor__textarea"
                value={editor.world_summary}
                onChange={(event) => setEditor((current) => ({ ...current, world_summary: event.target.value }))}
              />
            </label>

            <label className="project-editor__field">
              <span className="project-editor__label">当前焦点</span>
              <textarea
                aria-label="当前焦点"
                className="project-editor__textarea project-editor__textarea--compact"
                placeholder="例如：这一轮优先推进哪条线、盯住哪个角色、承接哪一个未收束钩子"
                value={editor.current_focus}
                onChange={(event) => setEditor((current) => ({ ...current, current_focus: event.target.value }))}
              />
            </label>

            <label className="project-editor__field">
              <span className="project-editor__label">作者约束</span>
              <textarea
                aria-label="作者约束"
                className="project-editor__textarea project-editor__textarea--compact"
                placeholder="每行一条，例如：不要跳过调查过程"
                value={editor.author_constraints}
                onChange={(event) => setEditor((current) => ({ ...current, author_constraints: event.target.value }))}
              />
            </label>

            <div className="workbench-navrail__actions">
              <button className="btn btn--primary" type="button" onClick={() => void handleSaveProject()} disabled={isSavingProject}>
                {isSavingProject ? "保存中..." : "保存项目资料"}
              </button>
              <Link className="btn btn--ghost" href="/config">
                打开配置
              </Link>
            </div>
            {saveNotice ? <p className="hint">{saveNotice}</p> : null}
          </div>

          <article className="project-dossier-card">
            <p className="project-dossier-card__label">当前导入来源</p>
            <p className="project-dossier-card__body">{sourcePath || "还没有绑定导入目录。"}</p>
          </article>

          <article className="project-dossier-card">
            <p className="project-dossier-card__label">种子大纲预览</p>
            <p className="project-dossier-card__body">{outlinePreview(project, draft)}</p>
          </article>

          <article className="project-dossier-card">
            <p className="project-dossier-card__label">当前作者约束</p>
            {constraints.length ? (
              <div className="project-chip-row">
                {constraints.map((constraint) => (
                  <span key={constraint} className="project-chip project-chip--soft">
                    {constraint}
                  </span>
                ))}
              </div>
            ) : (
              <p className="project-dossier-card__body project-dossier-card__body--muted">
                还没有整理单独的硬约束，目前按导入大纲与配置页设定推进。
              </p>
            )}
          </article>
        </div>
      </section>

      <section className="panel" aria-label="世界锚点面板">
        <header className="panel__header">世界锚点</header>
        <div className="panel__body workbench-navrail__stack">
          <article className="project-dossier-card project-dossier-card--soft">
            <p className="project-dossier-card__label">当前焦点</p>
            <p className="project-dossier-card__body">{focusLabel(project, bundle, importedDraft)}</p>
          </article>

          <article className="project-dossier-card project-dossier-card--soft">
            <p className="project-dossier-card__label">本轮事件拐点</p>
            <p className="project-dossier-card__body">{bundle?.event_plan?.pivot || "这一轮还没有形成清晰拐点。"}</p>
          </article>

          <article className="project-dossier-card project-dossier-card--soft">
            <p className="project-dossier-card__label">最近世界回声</p>
            <p className="project-dossier-card__body">{recentEventLabel(story, bundle)}</p>
          </article>
        </div>
      </section>

      <section className="panel" aria-label="书籍导入面板">
        <header className="panel__header">书籍导入</header>
        <div className="panel__body">
          <p className="hint workbench-navrail__intro">
            导入入口保留在左侧，方便随时换源或补充素材，但首页主区优先展示故事状态和章节历史。
          </p>
          <BookImportPanel
            onBootstrapDraft={onBootstrapDraft}
            onCatalogLoaded={onCatalogLoaded}
            onLoadWorld={onLoadWorld}
          />
        </div>
      </section>

      <WorkbenchDraftEditor
        draft={draft}
        onChange={onDraftChange}
        onAddCharacter={() =>
          onDraftChange((currentDraft) => ({
            ...currentDraft,
            characters: [
              ...currentDraft.characters,
              {
                name: "",
                goal: "",
                frozen: false,
                relationshipTarget: "",
                relationshipBond: "",
                trust: "0.0",
                tension: "0.0",
              },
            ],
          }))
        }
      />

      <section className="panel" aria-label="导入内容浏览面板">
        <header className="panel__header">导入内容浏览</header>
        <div className="panel__body">
          <BookLibraryBrowser
            catalog={catalog}
            selectedSourceItemId={selectedSourceItemId}
            onSelectSourceItem={onSelectSourceItem}
          />
        </div>
      </section>
    </div>
  );
}
