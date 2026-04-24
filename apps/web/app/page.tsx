"use client";

import { useEffect, useRef, useState } from "react";

import { AppShell } from "../components/AppShell";
import { BookImportPanel } from "../components/BookImportPanel";
import { BookLibraryBrowser } from "../components/BookLibraryBrowser";
import { type StoryDraft } from "../components/StorySidebar";
import { ChapterBundleView } from "../components/ChapterBundleView";
import { WorkbenchDraftEditor } from "../components/workbench/WorkbenchDraftEditor";
import { ChapterHistoryFeed } from "../components/workbench/ChapterHistoryFeed";
import { StoryOverviewGrid } from "../components/workbench/StoryOverviewGrid";
import { ProjectStartScreen, type StartProjectDraft } from "../components/workbench/ProjectStartScreen";
import { WorkbenchImportRail } from "../components/workbench/WorkbenchImportRail";
import { WorkbenchShell } from "../components/workbench/WorkbenchShell";
import { WorkbenchSidePanel } from "../components/workbench/WorkbenchSidePanel";
import { WorkbenchTopBar } from "../components/workbench/WorkbenchTopBar";
import { WorldSimulationBoard } from "../components/workbench/WorldSimulationBoard";
import {
  activateProjectStory,
  createProject,
  createStory,
  fetchProject,
  fetchStory,
  generateNextChapter,
  listProjects,
  rollbackStory,
  updateProject as updateProjectRecord,
  type BookImportBootstrapResponse,
  type BookLibraryCatalogResponse,
  type BookLibraryItem,
  type ChapterBundle,
  type ProjectResponse,
  type ProjectSummary,
  type StoryResponse,
  type StoryCharacter,
  type UpdateProjectRequest,
} from "../lib/api";

const DEFAULT_STORY = {
  genre: "fantasy",
  style: "noir",
} as const;

const STORY_ID_STORAGE_KEY = "novel-autogrowth-engine.story-id";
const PROJECT_ID_STORAGE_KEY = "novel-autogrowth-engine.project-id";
const PROJECT_SNAPSHOT_STORAGE_KEY = "novel-autogrowth-engine.project-snapshot";
const STORY_SNAPSHOT_STORAGE_KEY = "novel-autogrowth-engine.story-snapshot";

function persistSnapshot<T>(storageKey: string, value: T | null) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    if (value) {
      window.localStorage.setItem(storageKey, JSON.stringify(value));
    } else {
      window.localStorage.removeItem(storageKey);
    }
  } catch {
    // Ignore localStorage write failures and keep the in-memory state.
  }
}

function restoreSnapshot<T>(storageKey: string): T | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(storageKey);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

function resolveDefaultStoryId(): string {
  if (typeof window === "undefined") {
    return "s-001";
  }

  try {
    const existing = window.sessionStorage.getItem(STORY_ID_STORAGE_KEY);
    if (existing) {
      return existing;
    }

    const nextId = `s-${crypto.randomUUID().slice(0, 8)}`;
    window.sessionStorage.setItem(STORY_ID_STORAGE_KEY, nextId);
    return nextId;
  } catch {
    return `s-${Math.random().toString(36).slice(2, 10)}`;
  }
}

function resolveDefaultProjectId(): string {
  if (typeof window === "undefined") {
    return "p-001";
  }

  try {
    const existing = window.sessionStorage.getItem(PROJECT_ID_STORAGE_KEY);
    if (existing) {
      return existing;
    }

    const nextId = `p-${crypto.randomUUID().slice(0, 8)}`;
    window.sessionStorage.setItem(PROJECT_ID_STORAGE_KEY, nextId);
    return nextId;
  } catch {
    return `p-${Math.random().toString(36).slice(2, 10)}`;
  }
}

function deriveProjectTitle(sourceDraft: BookImportBootstrapResponse["draft"] | null, draft: StoryDraft): string {
  const importedTitle = sourceDraft?.title?.trim();
  if (importedTitle) {
    return importedTitle;
  }
  const sourcePath = sourceDraft?.source_path?.trim();
  if (sourcePath) {
    const normalized = sourcePath.replace(/\\/g, "/").replace(/\/+$/, "");
    const segments = normalized.split("/").filter(Boolean);
    const last = segments.at(-1) ?? "";
    const parent = segments.at(-2) ?? "";
    const candidate = last.toLowerCase() === "story" ? parent : last;
    if (candidate) {
      return candidate;
    }
  }

  const outline = (sourceDraft?.outline || draft.outline).trim();
  const firstLine = outline.split(/\r?\n/).find((line) => line.trim());
  if (firstLine) {
    return firstLine.replace(/^#+\s*/, "").slice(0, 24);
  }
  return "未命名小说项目";
}

function defaultStoryDraft(): StoryDraft {
  return {
    outline: "",
    directorBrief: "",
    characters: [
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
  };
}

function defaultStartProjectDraft(): StartProjectDraft {
  return {
    title: "",
    premise: "",
    mainGoal: "",
    charactersText: "",
  };
}

function composeOutlineForStory(draft: StoryDraft): string {
  const outline = draft.outline.trim();
  const directorBrief = draft.directorBrief.trim();
  if (!directorBrief) {
    return outline;
  }
  return `${outline}\n\n【导演补充】\n${directorBrief}`;
}

function applyBootstrappedDraft(
  currentDraft: StoryDraft,
  bootstrapDraft: BookImportBootstrapResponse["draft"],
): StoryDraft {
  const defaultImportedGoal =
    bootstrapDraft.summary?.trim() ||
    bootstrapDraft.outline?.trim() ||
    "推进故事主线";
  const importedCharacters = (bootstrapDraft.characters ?? []).length
    ? bootstrapDraft.characters
    : (bootstrapDraft.character_profiles ?? []).map((profile) => ({
        name: profile.name,
        goal: profile.current_state || profile.motivation || profile.goals?.[0] || profile.role || "",
      }));
  const nextCharacters = importedCharacters.length
    ? importedCharacters.map((character) => ({
        name: character.name,
        goal: character.goal?.trim() || defaultImportedGoal,
        frozen: false,
        relationshipTarget: "",
        relationshipBond: "",
        trust: "0.0",
        tension: "0.0",
      }))
    : currentDraft.characters;

  return {
    ...currentDraft,
    outline: bootstrapDraft.outline ?? currentDraft.outline,
    directorBrief: bootstrapDraft.world_summary ?? bootstrapDraft.summary ?? currentDraft.directorBrief,
    characters: nextCharacters.length ? nextCharacters : currentDraft.characters,
  };
}

function createDraftFromStartProject(startDraft: StartProjectDraft): StoryDraft {
  const parsedCharacters = startDraft.charactersText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [namePart, goalPart] = line.split("|").map((part) => part.trim());
      return {
        name: namePart ?? "",
        goal: goalPart ?? startDraft.mainGoal.trim(),
        frozen: false,
        relationshipTarget: "",
        relationshipBond: "",
        trust: "0.0",
        tension: "0.0",
      };
    })
    .filter((character) => character.name);

  return {
    outline: `${startDraft.title.trim()}\n\n世界设定：${startDraft.premise.trim()}\n主线目标：${startDraft.mainGoal.trim()}`,
    directorBrief: `${startDraft.premise.trim()}\n当前任务：${startDraft.mainGoal.trim()}`,
    characters: parsedCharacters.length
      ? parsedCharacters
      : [
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
  };
}

function buildCharacters(sourceDraft: StoryDraft): StoryCharacter[] {
  return sourceDraft.characters
    .filter((character) => character.name.trim() && character.goal.trim())
    .map((character, index) => ({
      name: character.name.trim(),
      role: index === 0 ? "protagonist" : "supporting",
      goals: [character.goal.trim()],
      frozen: character.frozen,
      lifecycle_state: character.frozen ? "frozen" : "active",
      last_proposed_chapter: 0,
      last_approved_chapter: 0,
      introduced_by: "",
      relationships: character.relationshipTarget.trim()
        ? {
            [character.relationshipTarget.trim()]: {
              target: character.relationshipTarget.trim(),
              trust: Number(character.trust || "0"),
              tension: Number(character.tension || "0"),
              bond: character.relationshipBond.trim(),
            },
          }
        : {},
    }));
}

function hasValidCharacter(sourceDraft: StoryDraft): boolean {
  return sourceDraft.characters.some((character) => character.name.trim() && character.goal.trim());
}

function canStartFirstChapter(sourceDraft: StoryDraft): boolean {
  return Boolean(sourceDraft.outline.trim()) && hasValidCharacter(sourceDraft);
}

function buildStoryFromBundle(baseStory: StoryResponse, nextBundle: ChapterBundle, storyId: string): StoryResponse {
  const updatedStory = nextBundle.updated_story as StoryResponse | undefined;
  return {
    story_id: storyId,
    outline: updatedStory?.outline ?? baseStory.outline,
    genre: updatedStory?.genre ?? baseStory.genre,
    style: updatedStory?.style ?? baseStory.style,
    current_chapter: updatedStory?.current_chapter ?? nextBundle.chapter_number,
    agent_settings: updatedStory?.agent_settings ?? baseStory.agent_settings,
    agent_runtime: updatedStory?.agent_runtime ?? baseStory.agent_runtime,
    author_constraints: updatedStory?.author_constraints ?? baseStory.author_constraints ?? [],
    parent_story_id: updatedStory?.parent_story_id ?? baseStory.parent_story_id ?? null,
    branched_from_chapter:
      updatedStory?.branched_from_chapter ?? baseStory.branched_from_chapter ?? null,
    characters: updatedStory?.characters ?? baseStory.characters,
    history: [...baseStory.history, nextBundle],
  };
}

function selectedBundleOrLatest(
  story: StoryResponse | null,
  selectedChapter: number | null,
): ChapterBundle | null {
  if (!story) {
    return null;
  }
  if (selectedChapter == null) {
    return story.history.at(-1) ?? null;
  }
  return story.history.find((entry) => entry.chapter_number === selectedChapter) ?? story.history.at(-1) ?? null;
}

function lastUpdatedLabel(story: StoryResponse | null): string {
  if (!story?.history.length) {
    return "尚未生成";
  }
  return `第 ${story.history.at(-1)?.chapter_number ?? story.current_chapter} 章后`;
}

function topStatusSummary(
  story: StoryResponse | null,
  project: ProjectResponse | null,
  importedDraft: BookImportBootstrapResponse["draft"] | null,
): string {
  if (story?.history.length) {
    return story.history.at(-1)?.chapter_summary?.summary || "故事已进入连续演化阶段。";
  }
  if (project?.world_summary?.trim()) {
    return project.world_summary.trim();
  }
  if (project?.current_focus?.trim()) {
    return project.current_focus.trim();
  }
  if (importedDraft?.summary?.trim()) {
    return importedDraft.summary.trim();
  }
  return "先看故事状态与历史，再决定继续生成、导入素材或调整配置。";
}

function overviewCards(
  project: ProjectResponse | null,
  story: StoryResponse | null,
  bundle: ChapterBundle | null,
  importedDraft: BookImportBootstrapResponse["draft"] | null,
) {
  const chapterLabel = story ? `第 ${story.current_chapter} 章` : "尚未开始";
  const focus =
    project?.current_focus ||
    bundle?.chapter_intent?.next_focus ||
    bundle?.event_plan?.next_focus ||
    importedDraft?.current_focus ||
    bundle?.next_outline ||
    importedDraft?.summary ||
    "等待进入第一章";
  const primaryConflict =
    (bundle?.chapter_intent?.primary_conflict?.collision as string | undefined) ||
    bundle?.chapter_summary?.unresolved_threads[0] ||
    "当前还没有主冲突摘要，生成后会自动提炼。";
  const facts =
    bundle?.memory_constraints?.must_keep_facts?.[0] ||
    bundle?.chapter_summary?.facts[0] ||
    "暂无关键事实。";
  const memory = story?.agent_runtime?.recent_events.at(-1) || "最近还没有运行记录。";
  const foreshadowing =
    bundle?.memory_constraints?.protected_foreshadowing?.[0]?.text ||
    ((bundle?.foreshadowing?.[0] as { text?: string } | undefined)?.text) ||
    "暂无关键伏笔。";
  const worldSituation =
    bundle?.event_plan?.pivot ||
    bundle?.chapter_summary?.summary ||
    project?.world_summary ||
    "当前世界局势还未进入明确推演。";

  return [
    { title: "当前推进", value: chapterLabel, detail: `当前项目：${project?.title ?? "未命名小说项目"}` },
    { title: "世界局势", value: worldSituation, detail: "这一轮演化真正把哪股力量推上了台面。" },
    { title: "当前焦点", value: focus, detail: "下一步应该把哪条线继续往前推。" },
    { title: "主冲突", value: primaryConflict, detail: "导演层当前锁定的核心张力。" },
    { title: "关键事实", value: facts, detail: "记忆层要求保留的最新事实。" },
    { title: "关键伏笔", value: foreshadowing, detail: "后续章节需要回收或强化的信号。" },
    { title: "记忆摘要", value: memory, detail: "最近一次运行留下的上下文。" },
  ];
}

function WorkbenchNavRail({
  catalog,
  selectedSourceItemId,
  onSelectSourceItem,
  draft,
  onDraftChange,
  onBootstrapDraft,
  onCatalogLoaded,
  onLoadWorld,
}: {
  catalog: BookLibraryCatalogResponse | null;
  selectedSourceItemId: string | null;
  onSelectSourceItem: (item: BookLibraryItem) => void;
  draft: StoryDraft;
  onDraftChange: (next: StoryDraft | ((current: StoryDraft) => StoryDraft)) => void;
  onBootstrapDraft: (draft: BookImportBootstrapResponse["draft"]) => void;
  onCatalogLoaded: (catalog: BookLibraryCatalogResponse | null) => void;
  onLoadWorld: (draft?: BookImportBootstrapResponse["draft"]) => Promise<void>;
}) {
  return (
    <div className="workbench-navrail">
      <section className="panel">
        <header className="panel__header">工作台导航</header>
        <div className="panel__body workbench-navrail__quicklinks">
          <span className="workbench-navrail__quicklink">故事总览</span>
          <span className="workbench-navrail__quicklink">章节历史</span>
          <span className="workbench-navrail__quicklink">书籍导入</span>
          <span className="workbench-navrail__quicklink">配置中心</span>
        </div>
      </section>

      <section className="panel">
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

      <section className="panel">
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

export default function Page() {
  const [draft, setDraft] = useState<StoryDraft>(defaultStoryDraft());
  const [startProjectDraft, setStartProjectDraft] = useState<StartProjectDraft>(defaultStartProjectDraft());
  const [bootstrappedDraft, setBootstrappedDraft] = useState<BookImportBootstrapResponse["draft"] | null>(null);
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [story, setStory] = useState<StoryResponse | null>(null);
  const projectIdRef = useRef(resolveDefaultProjectId());
  const storyIdRef = useRef(resolveDefaultStoryId());
  const projectRef = useRef<ProjectResponse | null>(null);
  const storyRef = useRef<StoryResponse | null>(null);
  const draftRef = useRef(draft);
  const [bookCatalog, setBookCatalog] = useState<BookLibraryCatalogResponse | null>(null);
  const [selectedSourceItemId, setSelectedSourceItemId] = useState<string | null>(null);
  const [projectSummaries, setProjectSummaries] = useState<ProjectSummary[]>([]);
  const [selectedChapter, setSelectedChapter] = useState<number | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isSavingProject, setIsSavingProject] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isMountedRef = useRef(true);

  function updateDraft(next: StoryDraft | ((current: StoryDraft) => StoryDraft)) {
    const resolved = typeof next === "function" ? next(draftRef.current) : next;
    draftRef.current = resolved;
    setDraft(resolved);
  }

  function updateProject(next: ProjectResponse | null) {
    projectRef.current = next;
    if (next) {
      projectIdRef.current = next.project_id;
      try {
        window.sessionStorage.setItem(PROJECT_ID_STORAGE_KEY, next.project_id);
      } catch {
        // ignore sessionStorage failures
      }
    }
    persistSnapshot(PROJECT_SNAPSHOT_STORAGE_KEY, next);
    setProject(next);
  }

  function updateStory(next: StoryResponse | null) {
    storyRef.current = next;
    if (next) {
      storyIdRef.current = next.story_id;
      try {
        window.sessionStorage.setItem(STORY_ID_STORAGE_KEY, next.story_id);
      } catch {
        // ignore sessionStorage failures
      }
    }
    persistSnapshot(STORY_SNAPSHOT_STORAGE_KEY, next);
    setStory(next);
  }

  useEffect(() => {
    draftRef.current = draft;
  }, [draft]);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    void refreshProjectSummaries();
  }, []);

  function handleCatalogLoaded(nextCatalog: BookLibraryCatalogResponse | null) {
    setBookCatalog(nextCatalog);
    if (!nextCatalog) {
      setSelectedSourceItemId(null);
    }
  }

  function handleSourceItemSelect(item: BookLibraryItem) {
    setSelectedSourceItemId(item.item_id);

    if (item.filename === "character_matrix.md" && item.parsed_characters?.length) {
      updateDraft({
        ...draftRef.current,
        characters: item.parsed_characters.map((name) => ({
          name,
          goal: "",
          frozen: false,
          relationshipTarget: "",
          relationshipBond: "",
          trust: "0.0",
          tension: "0.0",
        })),
      });
      return;
    }

    if (
      item.filename === "volume_outline.md" ||
      item.filename === "current_focus.md" ||
      item.filename === "author_intent.md" ||
      item.filename === "book_rules.md" ||
      item.filename === "story_bible.md"
    ) {
      updateDraft({
        ...draftRef.current,
        outline: item.content.trim() || item.preview,
      });
      return;
    }

    if (item.chapter_number != null) {
      setSelectedChapter(item.chapter_number);
    }
  }

  function handleBootstrapDraft(nextDraft: BookImportBootstrapResponse["draft"]) {
    setBootstrappedDraft(nextDraft);
    updateDraft(applyBootstrappedDraft(draftRef.current, nextDraft));
  }

  async function onCreateBlankProject() {
    const nextDraft = createDraftFromStartProject(startProjectDraft);
    updateDraft(nextDraft);
    await onGenerateNextChapter(undefined, nextDraft, {
      title: startProjectDraft.title.trim(),
      worldSummary: startProjectDraft.premise.trim(),
      sourcePath: "",
      authorConstraints: [],
      currentFocus: startProjectDraft.mainGoal.trim(),
    });
  }

  async function onLoadImportedWorld(sourceDraft?: BookImportBootstrapResponse["draft"]) {
    const importedDraft = sourceDraft ?? bootstrappedDraft;
    if (!importedDraft) {
      setError("请先导入书籍目录，再生成世界观。");
      return;
    }

    setError(null);
    setIsGenerating(true);
    try {
      setBootstrappedDraft(importedDraft);
      const nextDraft = applyBootstrappedDraft(draftRef.current, importedDraft);
      updateDraft(nextDraft);

      const payload = {
        title: importedDraft.title?.trim() || deriveProjectTitle(importedDraft, nextDraft),
        source_path: importedDraft.source_path ?? "",
        seed_outline: nextDraft.outline.trim(),
        world_summary: importedDraft.world_summary?.trim() || importedDraft.summary?.trim() || nextDraft.directorBrief.trim(),
        current_focus: importedDraft.current_focus?.trim() || "",
        author_constraints: importedDraft.author_constraints ?? [],
        world_blueprint: importedDraft.world_blueprint ?? {},
        character_profiles: importedDraft.character_profiles ?? [],
        relationship_graph: importedDraft.world_blueprint?.relationship_graph ?? [],
        status: "draft" as const,
        active_story_id: "",
      };

      const savedProject = projectRef.current
        ? await updateProjectRecord(projectRef.current.project_id, payload)
        : await createProject({
            project_id: projectIdRef.current,
            ...payload,
          });
      const mergedProject: ProjectResponse = projectRef.current
        ? {
            ...projectRef.current,
            ...savedProject,
            ...payload,
          }
        : savedProject;

      updateProject(mergedProject);
      updateStory(null);
      setSelectedChapter(null);
      await refreshProjectSummaries();
    } catch (worldError) {
      setError(worldError instanceof Error ? worldError.message : "生成世界观失败");
    } finally {
      setIsGenerating(false);
    }
  }

  async function refreshProjectSummaries() {
    try {
      const summaries = await listProjects();
      if (!isMountedRef.current) {
        return;
      }
      setProjectSummaries(summaries);
      if (!projectRef.current) {
        const preferredProjectId =
          summaries.find((entry) => entry.project_id === projectIdRef.current)?.project_id ?? summaries[0]?.project_id;
        if (!preferredProjectId) {
          const cachedProject = restoreSnapshot<ProjectResponse>(PROJECT_SNAPSHOT_STORAGE_KEY);
          const cachedStory = restoreSnapshot<StoryResponse>(STORY_SNAPSHOT_STORAGE_KEY);
          if (cachedProject) {
            updateProject(cachedProject);
          }
          if (cachedStory) {
            updateStory(cachedStory);
            setSelectedChapter(cachedStory.history.at(-1)?.chapter_number ?? null);
          }
          return;
        }
        const latestProject = await fetchProject(preferredProjectId);
        if (!isMountedRef.current) {
          return;
        }
        projectIdRef.current = latestProject.project_id;
        updateProject(latestProject);
        if (latestProject.active_story_id) {
          const activeStory = await fetchStory(latestProject.active_story_id);
          if (!isMountedRef.current) {
            return;
          }
          storyIdRef.current = activeStory.story_id;
          updateStory(activeStory);
          setSelectedChapter(activeStory.history.at(-1)?.chapter_number ?? null);
        }
      }
    } catch {
      if (isMountedRef.current) {
        setProjectSummaries([]);
      }
    }
  }

  async function ensureStoryReady(
    sourceDraft?: BookImportBootstrapResponse["draft"],
    explicitDraft?: StoryDraft,
    projectSeed?: {
      title?: string;
      worldSummary?: string;
      sourcePath?: string;
      authorConstraints?: string[];
      currentFocus?: string;
    },
  ): Promise<StoryResponse> {
    if (sourceDraft) {
      setBootstrappedDraft(sourceDraft);
      updateDraft(applyBootstrappedDraft(draftRef.current, sourceDraft));
    }

    const currentStory = storyRef.current;
    if (currentStory) {
      return currentStory;
    }

    const nextDraft = explicitDraft ?? (sourceDraft ? applyBootstrappedDraft(draftRef.current, sourceDraft) : draftRef.current);
    if (!canStartFirstChapter(nextDraft)) {
      throw new Error("请先填写大纲，并至少补充 1 个有名称和目标的角色。");
    }

    const createdStory = await createStory({
      ...DEFAULT_STORY,
      story_id: storyIdRef.current,
      outline: composeOutlineForStory(nextDraft),
      agent_settings: undefined,
      characters: buildCharacters(nextDraft),
    });
    const currentProject = projectRef.current
      ? await activateProjectStory(projectRef.current.project_id, createdStory.story_id)
      : await createProject({
          project_id: projectIdRef.current,
          title: projectSeed?.title || deriveProjectTitle(sourceDraft ?? bootstrappedDraft, nextDraft),
          source_path: projectSeed?.sourcePath ?? (sourceDraft ?? bootstrappedDraft)?.source_path ?? "",
          seed_outline: nextDraft.outline.trim(),
          world_summary:
            projectSeed?.worldSummary ||
            (sourceDraft ?? bootstrappedDraft)?.world_summary?.trim() ||
            nextDraft.directorBrief.trim(),
          current_focus:
            projectSeed?.currentFocus ||
            (sourceDraft ?? bootstrappedDraft)?.current_focus?.trim() ||
            "",
          author_constraints: projectSeed?.authorConstraints ?? (sourceDraft ?? bootstrappedDraft)?.author_constraints ?? [],
          world_blueprint: (sourceDraft ?? bootstrappedDraft)?.world_blueprint ?? {},
          character_profiles: (sourceDraft ?? bootstrappedDraft)?.character_profiles ?? [],
          relationship_graph: (sourceDraft ?? bootstrappedDraft)?.world_blueprint?.relationship_graph ?? [],
          active_story_id: createdStory.story_id,
        });
    updateProject(currentProject);
    updateStory(createdStory);
    setSelectedChapter(createdStory.history.at(-1)?.chapter_number ?? null);
    await refreshProjectSummaries();
    return createdStory;
  }

  async function onGenerateNextChapter(
    sourceDraft?: BookImportBootstrapResponse["draft"],
    explicitDraft?: StoryDraft,
    projectSeed?: {
      title?: string;
      worldSummary?: string;
      sourcePath?: string;
      authorConstraints?: string[];
      currentFocus?: string;
    },
  ) {
    setError(null);
    setIsGenerating(true);
    try {
      const readyStory = await ensureStoryReady(sourceDraft, explicitDraft, projectSeed);
      const nextBundle = await generateNextChapter(readyStory.story_id);
      const nextStory = buildStoryFromBundle(readyStory, nextBundle, readyStory.story_id);
      updateStory(nextStory);
      setSelectedChapter(nextBundle.chapter_number);
      if (projectRef.current) {
        const nextProject = await activateProjectStory(projectRef.current.project_id, nextStory.story_id);
        updateProject(nextProject);
      }
      await refreshProjectSummaries();
    } catch (generationError) {
      setError(generationError instanceof Error ? generationError.message : "生成失败");
    } finally {
      setIsGenerating(false);
    }
  }

  async function onRollbackChapter() {
    const currentStory = storyRef.current;
    if (!currentStory) {
      return;
    }

    setError(null);
    setIsGenerating(true);
    try {
      const nextStory = await rollbackStory(currentStory.story_id);
      updateStory(nextStory);
      setSelectedChapter(nextStory.history.at(-1)?.chapter_number ?? null);
      await refreshProjectSummaries();
    } catch (rollbackError) {
      setError(rollbackError instanceof Error ? rollbackError.message : "回滚失败");
    } finally {
      setIsGenerating(false);
    }
  }

  async function onOpenProject(projectId: string) {
    setError(null);
    setIsGenerating(true);
    try {
      const openedProject = await fetchProject(projectId);
      updateProject(openedProject);
      if (openedProject.active_story_id) {
        const openedStory = await fetchStory(openedProject.active_story_id);
        updateStory(openedStory);
        setSelectedChapter(openedStory.history.at(-1)?.chapter_number ?? null);
      } else {
        updateStory(null);
        setSelectedChapter(null);
      }
      await refreshProjectSummaries();
    } catch (openError) {
      setError(openError instanceof Error ? openError.message : "打开项目失败");
    } finally {
      setIsGenerating(false);
    }
  }

  async function onSaveProject(payload: UpdateProjectRequest) {
    if (!projectRef.current) {
      setError("请先创建项目，再保存项目资料。");
      return;
    }

    setError(null);
    setIsSavingProject(true);
    try {
      const savedProject = await updateProjectRecord(projectRef.current.project_id, payload);
      const mergedProject: ProjectResponse = {
        ...projectRef.current,
        ...savedProject,
        ...(payload.title !== undefined ? { title: payload.title } : {}),
        ...(payload.source_path !== undefined ? { source_path: payload.source_path } : {}),
        ...(payload.seed_outline !== undefined ? { seed_outline: payload.seed_outline } : {}),
        ...(payload.world_summary !== undefined ? { world_summary: payload.world_summary } : {}),
        ...(payload.current_focus !== undefined ? { current_focus: payload.current_focus } : {}),
        ...(payload.author_constraints !== undefined ? { author_constraints: payload.author_constraints } : {}),
        ...(payload.world_blueprint !== undefined ? { world_blueprint: payload.world_blueprint } : {}),
        ...(payload.character_profiles !== undefined ? { character_profiles: payload.character_profiles } : {}),
        ...(payload.relationship_graph !== undefined ? { relationship_graph: payload.relationship_graph } : {}),
        ...(payload.status !== undefined ? { status: payload.status } : {}),
        ...(payload.active_story_id !== undefined ? { active_story_id: payload.active_story_id } : {}),
      };
      updateProject(mergedProject);
      if (storyRef.current && payload.author_constraints !== undefined) {
        updateStory({
          ...storyRef.current,
          author_constraints: payload.author_constraints,
        });
      }
      await refreshProjectSummaries();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "保存项目资料失败");
      throw saveError instanceof Error ? saveError : new Error("保存项目资料失败");
    } finally {
      setIsSavingProject(false);
    }
  }

  const selectedBundle = selectedBundleOrLatest(story, selectedChapter);
  const activeChapter = selectedBundle?.chapter_number ?? story?.current_chapter ?? 0;
  const canStartGeneration = story ? true : canStartFirstChapter(draft);
  const shouldShowStartScreen = !project && !story;

  return (
    <AppShell
      title="小说工作台"
      description="先看故事现在写到哪、最近几章怎么演化，再决定继续生成、回看历史还是补充素材。"
    >
      {shouldShowStartScreen ? (
        <ProjectStartScreen
          importDraft={bootstrappedDraft}
          startDraft={startProjectDraft}
          onStartDraftChange={setStartProjectDraft}
          onBootstrapDraft={handleBootstrapDraft}
          onCatalogLoaded={handleCatalogLoaded}
          onLoadImportedWorld={onLoadImportedWorld}
          onCreateBlankProject={onCreateBlankProject}
          isGenerating={isGenerating}
        />
      ) : (
      <WorkbenchShell
        topBar={
          <WorkbenchTopBar
            projectTitle={project?.title ?? deriveProjectTitle(bootstrappedDraft, draft)}
            storyId={story?.story_id ?? null}
            currentChapter={activeChapter}
            lastUpdatedLabel={lastUpdatedLabel(story)}
            statusSummary={topStatusSummary(story, project, bootstrappedDraft)}
            canStartGeneration={story ? true : canStartGeneration}
            isGenerating={isGenerating}
            onGenerateNextChapter={() => void onGenerateNextChapter(bootstrappedDraft ?? undefined)}
          />
        }
        nav={
          <WorkbenchImportRail
            currentProjectId={project?.project_id ?? projectIdRef.current}
            projectTitle={project?.title ?? deriveProjectTitle(bootstrappedDraft, draft)}
            project={project}
            story={story}
            bundle={selectedBundle}
            importedDraft={bootstrappedDraft}
            catalog={bookCatalog}
            selectedSourceItemId={selectedSourceItemId}
            onSelectSourceItem={handleSourceItemSelect}
            draft={draft}
            onDraftChange={updateDraft}
            onBootstrapDraft={handleBootstrapDraft}
            onCatalogLoaded={handleCatalogLoaded}
            onLoadWorld={onLoadImportedWorld}
            onSaveProject={onSaveProject}
            isSavingProject={isSavingProject}
          />
        }
        overview={
          <div className="workbench-overview-stack">
            <WorldSimulationBoard project={project} story={story} bundle={selectedBundle} />
            <StoryOverviewGrid cards={overviewCards(project, story, selectedBundle, bootstrappedDraft)} />
          </div>
        }
        history={
          <ChapterHistoryFeed
            history={story?.history ?? []}
            selectedChapter={selectedChapter}
            onOpenChapter={setSelectedChapter}
            isGenerating={isGenerating}
          />
        }
        detail={
          <ChapterBundleView
            story={story}
            bundle={selectedBundle}
            importedDraft={bootstrappedDraft}
            canStartGeneration={canStartGeneration}
            isGenerating={isGenerating}
            error={error}
            onStartGeneration={onGenerateNextChapter}
            onRollbackChapter={onRollbackChapter}
          />
        }
        side={
          <WorkbenchSidePanel
            project={project}
            story={story}
            bundle={selectedBundle}
            projectSummaries={projectSummaries}
            error={error}
            onOpenProject={onOpenProject}
            isGenerating={isGenerating}
          />
        }
      />
      )}
    </AppShell>
  );
}
