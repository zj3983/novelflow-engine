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
  enrichProjectRulebook,
  enrichProjectWorld,
  createStory,
  fetchProjectAgentReview,
  fetchProjectAutomationJob,
  fetchProject,
  fetchProjectWritingPacket,
  fetchStory,
  listProjects,
  reviseProjectChapter,
  rollbackStory,
  startProjectAutomationJob,
  submitProjectManualDraft,
  submitProjectManualSegmentDraft,
  updateProject as updateProjectRecord,
  type AgentReviewResponse,
  type AgentRevisionResponse,
  type BookImportBootstrapResponse,
  type BookLibraryCatalogResponse,
  type BookLibraryItem,
  type ChapterBundle,
  type CodexWritingPacket,
  type ProjectAutomationJobResponse,
  type ProjectResponse,
  type ProjectPipelineStage,
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

function createDraftFromProject(project: ProjectResponse): StoryDraft {
  const projectCharacters = (project.character_profiles ?? [])
    .map((profile) => {
      const extendedProfile = profile as typeof profile & { frozen?: boolean };
      return {
      name: String(profile.name ?? "").trim(),
      gameId: String(profile.game_id ?? "").trim() || undefined,
      goal: String(
        profile.goals?.[0] ??
          profile.motivation ??
          profile.current_state ??
          profile.role ??
          project.current_focus ??
          "推进当前主线",
      ).trim(),
      frozen: Boolean(extendedProfile.frozen),
      relationshipTarget: "",
      relationshipBond: "",
      trust: "0.0",
      tension: "0.0",
      };
    })
    .filter((character) => character.name && character.goal);

  return {
    outline: project.seed_outline.trim() || project.world_summary.trim() || project.current_focus.trim(),
    directorBrief: [project.world_summary.trim(), project.current_focus.trim()].filter(Boolean).join("\n"),
    characters: projectCharacters.length ? projectCharacters : defaultStoryDraft().characters,
  };
}

function buildCharacters(sourceDraft: StoryDraft): StoryCharacter[] {
  return sourceDraft.characters
    .filter((character) => character.name.trim() && character.goal.trim())
    .map((character, index) => ({
      name: character.name.trim(),
      role: index === 0 ? "protagonist" : "supporting",
      game_id: character.gameId?.trim() || undefined,
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
    world_facts: updatedStory?.world_facts ?? baseStory.world_facts ?? [],
    parent_story_id: updatedStory?.parent_story_id ?? baseStory.parent_story_id ?? null,
    branched_from_chapter:
      updatedStory?.branched_from_chapter ?? baseStory.branched_from_chapter ?? null,
    characters: updatedStory?.characters ?? baseStory.characters,
    history: [...baseStory.history, nextBundle],
  };
}

function applyRevisionToStory(baseStory: StoryResponse, revision: AgentRevisionResponse): StoryResponse {
  const chapterNumber = revision.chapter.chapter_number;
  const nextHistory = baseStory.history.map((bundle) => {
    if (bundle.chapter_number !== chapterNumber) {
      return bundle;
    }
    return {
      ...bundle,
      ...(revision.chapter.body !== undefined ? { body: revision.chapter.body } : {}),
      ...(revision.chapter.chapter_title !== undefined ? { chapter_title: revision.chapter.chapter_title } : {}),
      ...(revision.chapter.quality_report !== undefined ? { quality_report: revision.chapter.quality_report } : {}),
    };
  });
  return {
    ...baseStory,
    current_chapter: revision.story.current_chapter ?? baseStory.current_chapter,
    history: nextHistory,
  };
}

function applyReviewToStory(baseStory: StoryResponse, review: AgentReviewResponse): StoryResponse {
  const chapterNumber = review.chapter.chapter_number;
  const nextHistory = baseStory.history.map((bundle) => {
    if (bundle.chapter_number !== chapterNumber) {
      return bundle;
    }
    return {
      ...bundle,
      ...(review.chapter.quality_report !== undefined ? { quality_report: review.chapter.quality_report } : {}),
      ...(review.chapter.chapter_title !== undefined ? { chapter_title: review.chapter.chapter_title } : {}),
      ...(review.chapter.chapter_summary !== undefined ? { chapter_summary: review.chapter.chapter_summary } : {}),
    };
  });
  return {
    ...baseStory,
    history: nextHistory,
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

type GenerationPhase = "idle" | "environment" | "planning" | "writing";

const GENERATION_JOB_POLL_INTERVAL_MS = 1000;
const GENERATION_JOB_TIMEOUT_MS = 30 * 60 * 1000;

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function generationActionLabel(
  phase: GenerationPhase,
  statusText: string | null,
  idleLabel: string,
): string {
  if (statusText) {
    return statusText;
  }
  if (phase === "environment") {
    return "环境搭建中...";
  }
  if (phase === "planning") {
    return "剧情模拟中...";
  }
  if (phase === "writing") {
    return "正文生成中...";
  }
  return idleLabel;
}

function generationPhaseFromAutomationPhase(phase: ProjectAutomationJobResponse["phase"]): GenerationPhase {
  if (phase === "generating" || phase === "reviewing" || phase === "revising") {
    return "writing";
  }
  if (phase === "environment" || phase === "queued") {
    return "environment";
  }
  return "idle";
}

function automationProgressLabel(job: ProjectAutomationJobResponse): string {
  if (job.phase === "queued") {
    return "自动流程排队中...";
  }
  if (job.phase === "environment") {
    return "正在准备故事环境...";
  }
  if (job.phase === "generating") {
    return "正在生成章节正文...";
  }
  if (job.phase === "reviewing") {
    return `正在审稿${job.revision_attempts ? `（第 ${job.revision_attempts + 1} 轮）` : ""}...`;
  }
  if (job.phase === "revising") {
    return `正在按审稿意见改稿（已改 ${job.revision_attempts} 轮）...`;
  }
  if (job.phase === "completed") {
    return "自动流程完成，章节已通过。";
  }
  if (job.phase === "paused") {
    return job.progress || "自动流程暂停，等待人工确认。";
  }
  if (job.phase === "failed") {
    return job.error || "自动流程失败。";
  }
  return job.progress || "自动流程运行中...";
}

const PIPELINE_STEPS: Array<{
  stage: ProjectPipelineStage;
  title: string;
  detail: string;
}> = [
  {
    stage: "imported",
    title: "01 图谱构建",
    detail: "现实种子提取、角色/势力/关系与写作约束入库。",
  },
  {
    stage: "world_ready",
    title: "02 世界档案",
    detail: "大模型补全世界规则、人设动机、关系张力与剧情约束。",
  },
  {
    stage: "environment_ready",
    title: "03 环境搭建",
    detail: "把世界档案注入角色、导演、记忆与写作 Agent。",
  },
  {
    stage: "chapter_planning",
    title: "04 剧情模拟",
    detail: "先推演下一章事件链、冲突、伏笔和下一步焦点。",
  },
  {
    stage: "simulating",
    title: "05 正文生成",
    detail: "基于模拟结果写出章节，并回写时序记忆。",
  },
];

function projectPipelineStage(
  project: ProjectResponse | null,
  story: StoryResponse | null,
  generationPhase: GenerationPhase,
): ProjectPipelineStage {
  if (story?.history?.length) {
    return "simulating";
  }
  if (generationPhase === "writing") {
    return "writing";
  }
  if (generationPhase === "planning") {
    return "chapter_planning";
  }
  if (generationPhase === "environment" || story || project?.active_story_id) {
    return "environment_ready";
  }
  return project?.pipeline_stage ?? "imported";
}

function pipelineStepState(
  step: ProjectPipelineStage,
  currentStage: ProjectPipelineStage,
): "done" | "active" | "pending" {
  const order: ProjectPipelineStage[] = ["imported", "world_ready", "environment_ready", "chapter_planning", "writing", "simulating"];
  const normalizedCurrent = currentStage === "writing" ? "simulating" : currentStage;
  const currentIndex = order.indexOf(normalizedCurrent);
  const stepIndex = order.indexOf(step);
  if (currentStage === "completed") {
    return "done";
  }
  if (currentIndex < 0 || stepIndex < 0) {
    return "pending";
  }
  if (stepIndex < currentIndex) {
    return "done";
  }
  if (stepIndex === currentIndex) {
    return "active";
  }
  return "pending";
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
  const [isRevisingChapter, setIsRevisingChapter] = useState(false);
  const [isReviewingChapter, setIsReviewingChapter] = useState(false);
  const [writingPacket, setWritingPacket] = useState<CodexWritingPacket | null>(null);
  const [manualDraftBody, setManualDraftBody] = useState("");
  const [manualSegmentIndex, setManualSegmentIndex] = useState<number | null>(null);
  const [manualSegmentBody, setManualSegmentBody] = useState("");
  const [isPreparingManualDraft, setIsPreparingManualDraft] = useState(false);
  const [isSubmittingManualDraft, setIsSubmittingManualDraft] = useState(false);
  const [isSubmittingManualSegmentDraft, setIsSubmittingManualSegmentDraft] = useState(false);
  const [isEnrichingWorld, setIsEnrichingWorld] = useState(false);
  const [generationPhase, setGenerationPhase] = useState<GenerationPhase>("idle");
  const [generationStatusText, setGenerationStatusText] = useState<string | null>(null);
  const [reviewStatusText, setReviewStatusText] = useState<string | null>(null);
  const [revisionStatusText, setRevisionStatusText] = useState<string | null>(null);
  const [manualDraftStatusText, setManualDraftStatusText] = useState<string | null>(null);
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

    // Only save project, don't generate yet — let user prepare first
    setError(null);
    setIsGenerating(true);
    try {
      const payload = {
        title: startProjectDraft.title.trim(),
        source_path: "",
        seed_outline: nextDraft.outline.trim(),
        world_summary: startProjectDraft.premise.trim(),
        current_focus: startProjectDraft.mainGoal.trim(),
        author_constraints: [],
        world_blueprint: {},
        character_profiles: nextDraft.characters
          .filter((c) => c.name.trim() && c.goal.trim())
          .map((c) => ({
            name: c.name.trim(),
            role: "supporting",
            goals: [c.goal.trim()],
            frozen: false,
            lifecycle_state: "active",
            relationships: {},
          })),
        relationship_graph: [],
        status: "draft" as const,
        pipeline_stage: "imported" as const,
        active_story_id: "",
      };

      const savedProject = await createProject({
        project_id: projectIdRef.current,
        ...payload,
      });
      updateProject(savedProject);
      // Don't create story yet — user prepares first, then generates
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "创建项目失败");
    } finally {
      setIsGenerating(false);
    }
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
        pipeline_stage: "imported" as const,
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
        const cachedSummary = summaries.find((entry) => entry.project_id === projectIdRef.current);
        const preferredProjectId =
          (cachedSummary?.active_story_id ? cachedSummary.project_id : undefined) ??
          summaries.find((entry) => entry.active_story_id)?.project_id ??
          cachedSummary?.project_id ??
          summaries[0]?.project_id;
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
    const currentProjectForStory = projectRef.current ?? project;
    if (
      currentStory &&
      (!currentProjectForStory ||
        (currentProjectForStory.active_story_id && currentProjectForStory.active_story_id === currentStory.story_id))
    ) {
      try {
        const verifiedStory = await fetchStory(currentStory.story_id);
        updateStory(verifiedStory);
        return verifiedStory;
      } catch {
        updateStory(null);
      }
    }
    if (currentStory && currentProjectForStory) {
      updateStory(null);
    }

    const projectDraft = projectRef.current ? createDraftFromProject(projectRef.current) : null;
    const nextDraft =
      explicitDraft ??
      (sourceDraft ? applyBootstrappedDraft(draftRef.current, sourceDraft) : null) ??
      (canStartFirstChapter(draftRef.current) ? draftRef.current : null) ??
      projectDraft ??
      draftRef.current;
    if (projectDraft && !canStartFirstChapter(draftRef.current)) {
      updateDraft(projectDraft);
    }
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
          pipeline_stage: "environment_ready",
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
    setGenerationPhase("environment");
    setGenerationStatusText("正在准备故事环境...");
    try {
      const readyStory = await ensureStoryReady(sourceDraft, explicitDraft, projectSeed);
      setGenerationPhase("planning");
      setGenerationStatusText("正在整理剧情计划...");
      if (projectRef.current) {
        const planningProject = await updateProjectRecord(projectRef.current.project_id, {
          pipeline_stage: "chapter_planning",
        });
        updateProject({ ...projectRef.current, ...planningProject });
      }
      setGenerationPhase("writing");
      setGenerationStatusText("正在提交生成任务...");
      if (projectRef.current) {
        const writingProject = await updateProjectRecord(projectRef.current.project_id, {
          pipeline_stage: "writing",
        });
        updateProject({ ...projectRef.current, ...writingProject });
      }
      const activeProject = projectRef.current;
      if (!activeProject) {
        throw new Error("项目还没有准备好，无法启动自动流程。");
      }
      let currentJob = await startProjectAutomationJob(activeProject.project_id, {
        max_revisions: 2,
        review_provider: "local",
        include_body: true,
      });
      setGenerationPhase(generationPhaseFromAutomationPhase(currentJob.phase));
      setGenerationStatusText(automationProgressLabel(currentJob));
      const expiresAt = Date.now() + GENERATION_JOB_TIMEOUT_MS;
      while (currentJob.status !== "completed" && currentJob.status !== "failed") {
        if (currentJob.status === "paused") {
          break;
        }
        if (Date.now() > expiresAt) {
          throw new Error("自动流程仍在后台运行，请稍后刷新故事查看结果。");
        }
        await wait(GENERATION_JOB_POLL_INTERVAL_MS);
        currentJob = await fetchProjectAutomationJob(activeProject.project_id, currentJob.job_id);
        if (!isMountedRef.current) {
          return;
        }
        setGenerationPhase(generationPhaseFromAutomationPhase(currentJob.phase));
        setGenerationStatusText(automationProgressLabel(currentJob));
      }
      if (currentJob.status === "failed") {
        throw new Error(currentJob.error || "自动流程失败");
      }
      if (currentJob.status === "paused") {
        setError(currentJob.progress || "自动流程暂停，等待人工确认。");
      }
      setGenerationStatusText("自动流程已写入结果，正在刷新故事...");
      const nextStory = await fetchStory(readyStory.story_id);
      updateStory(nextStory);
      setSelectedChapter(currentJob.chapter_number ?? nextStory.history.at(-1)?.chapter_number ?? nextStory.current_chapter);
      if (projectRef.current) {
        const nextProject = await updateProjectRecord(projectRef.current.project_id, {
          status: "simulating",
          pipeline_stage: "simulating",
          active_story_id: nextStory.story_id,
        });
        updateProject(nextProject);
      }
      await refreshProjectSummaries();
    } catch (generationError) {
      setError(generationError instanceof Error ? generationError.message : "生成失败");
      if (projectRef.current && !storyRef.current?.history?.length) {
        try {
          const resetProject = await updateProjectRecord(projectRef.current.project_id, {
            pipeline_stage: projectRef.current.active_story_id ? "environment_ready" : "world_ready",
          });
          updateProject({ ...projectRef.current, ...resetProject });
        } catch {
          // Keep the original generation error visible.
        }
      }
    } finally {
      if (isMountedRef.current) {
        setIsGenerating(false);
        setGenerationPhase("idle");
        setGenerationStatusText(null);
      }
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

  async function onReviseCurrentChapter() {
    const currentProject = projectRef.current;
    const currentStory = storyRef.current;
    const currentBundle = selectedBundleOrLatest(currentStory, selectedChapter);
    if (!currentProject || !currentStory || !currentBundle) {
      setError("请先打开项目并生成章节，再执行自动改稿。");
      return;
    }
    if (currentBundle.chapter_number !== currentStory.current_chapter) {
      setError("为了保护连续性，当前只支持自动改稿最新章节。");
      return;
    }

    const writingReview = currentBundle.quality_report?.writing_review;
    const instructions = Array.from(
      new Set(
        [
          ...(writingReview?.revision_plan ?? []),
          ...(writingReview?.issues ?? []),
          "按章节审稿 Agent 的质量报告自动改稿，保留核心剧情事实，补足场景、对话、网游规则和章末压力。",
        ].filter((item) => item.trim()),
      ),
    );

    setError(null);
    setIsRevisingChapter(true);
    setRevisionStatusText("正在提交自动改稿...");
    try {
      const revision = await reviseProjectChapter(currentProject.project_id, {
        chapter_number: currentBundle.chapter_number,
        instructions,
        include_body: true,
      });
      setRevisionStatusText("改稿完成，正在刷新章节...");
      const nextStory = applyRevisionToStory(currentStory, revision);
      updateStory(nextStory);
      setSelectedChapter(revision.chapter.chapter_number);
      await refreshProjectSummaries();
    } catch (revisionError) {
      setError(revisionError instanceof Error ? revisionError.message : "自动改稿失败");
    } finally {
      if (isMountedRef.current) {
        setIsRevisingChapter(false);
        setRevisionStatusText(null);
      }
    }
  }

  async function onPrepareManualDraft() {
    const currentProject = projectRef.current;
    const currentStory = storyRef.current;
    const currentBundle = selectedBundleOrLatest(currentStory, selectedChapter);
    if (!currentProject || !currentStory || !currentBundle) {
      setError("请先打开项目并生成章节，再生成 Codex 写作包。");
      return;
    }

    setError(null);
    setIsPreparingManualDraft(true);
    setManualDraftStatusText(`正在整理第 ${currentBundle.chapter_number} 章写作包...`);
    try {
      const packet = await fetchProjectWritingPacket(currentProject.project_id, currentBundle.chapter_number);
      setWritingPacket(packet);
      setManualDraftBody(currentBundle.body ?? "");
      setManualSegmentIndex(null);
      setManualSegmentBody("");
      setManualDraftStatusText("写作包已生成：可以让 Codex 按硬性约束重写，再把正文提交回来。");
    } catch (packetError) {
      setError(packetError instanceof Error ? packetError.message : "生成 Codex 写作包失败");
      setManualDraftStatusText(null);
    } finally {
      if (isMountedRef.current) {
        setIsPreparingManualDraft(false);
      }
    }
  }

  async function onSubmitManualDraft(body: string) {
    const currentProject = projectRef.current;
    const currentStory = storyRef.current;
    const currentBundle = selectedBundleOrLatest(currentStory, selectedChapter);
    const trimmedBody = body.trim();
    if (!currentProject || !currentStory || !currentBundle) {
      setError("请先打开项目并生成章节，再提交手写正文。");
      return;
    }
    if (currentBundle.chapter_number !== currentStory.current_chapter) {
      setError("为了保护连续性，手写正文只能替换当前最新章节。");
      return;
    }
    if (!trimmedBody) {
      setError("手写正文不能为空。");
      return;
    }

    setError(null);
    setIsSubmittingManualDraft(true);
    setManualDraftStatusText(`正在提交第 ${currentBundle.chapter_number} 章手写正文并重新审稿...`);
    try {
      const revision = await submitProjectManualDraft(currentProject.project_id, {
        chapter_number: currentBundle.chapter_number,
        body: trimmedBody,
        instructions: [
          "Codex/manual writing channel",
          "保留推演事实、角色面板和世界账本，只替换小说正文并刷新章节审稿。",
        ],
        include_body: true,
      });
      const nextStory = applyRevisionToStory(currentStory, revision);
      updateStory(nextStory);
      setSelectedChapter(revision.chapter.chapter_number);
      setManualDraftBody(String(revision.chapter.body ?? trimmedBody));
      setManualSegmentIndex(null);
      setManualSegmentBody("");
      setManualDraftStatusText("手写正文已接入：章节正文、审稿报告和角色状态已刷新。");
      await refreshProjectSummaries();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "提交手写正文失败");
      setManualDraftStatusText(null);
    } finally {
      if (isMountedRef.current) {
        setIsSubmittingManualDraft(false);
      }
    }
  }

  function onSelectManualSegment(index: number, body: string) {
    setManualSegmentIndex(index);
    setManualSegmentBody(body);
    setManualDraftStatusText(`已载入第 ${index + 1} 段，可以只改这一段后提交。`);
  }

  async function onSubmitManualSegmentDraft(index: number, body: string) {
    const currentProject = projectRef.current;
    const currentStory = storyRef.current;
    const currentBundle = selectedBundleOrLatest(currentStory, selectedChapter);
    const trimmedBody = body.trim();
    if (!currentProject || !currentStory || !currentBundle) {
      setError("请先打开项目并生成章节，再提交局部改稿。");
      return;
    }
    if (currentBundle.chapter_number !== currentStory.current_chapter) {
      setError("为了保护连续性，局部改稿只能替换当前最新章节。");
      return;
    }
    if (index < 0 || !trimmedBody) {
      setError("请选择段落并填写局部改稿正文。");
      return;
    }

    setError(null);
    setIsSubmittingManualSegmentDraft(true);
    setManualDraftStatusText(`正在替换第 ${index + 1} 段并重新审稿...`);
    try {
      const revision = await submitProjectManualSegmentDraft(currentProject.project_id, {
        chapter_number: currentBundle.chapter_number,
        segment_index: index,
        body: trimmedBody,
        instructions: [
          "Codex/manual segment rewrite channel",
          `只替换第 ${index + 1} 段，保留其他段落、推演事实、角色面板和世界账本。`,
        ],
        include_body: true,
      });
      const nextStory = applyRevisionToStory(currentStory, revision);
      updateStory(nextStory);
      setSelectedChapter(revision.chapter.chapter_number);
      setManualDraftBody(String(revision.chapter.body ?? ""));
      setManualSegmentIndex(null);
      setManualSegmentBody("");
      setManualDraftStatusText("局部段落已接入：章节正文和审稿报告已刷新。");
      await refreshProjectSummaries();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "提交局部改稿失败");
      setManualDraftStatusText(null);
    } finally {
      if (isMountedRef.current) {
        setIsSubmittingManualSegmentDraft(false);
      }
    }
  }

  async function onReviewCurrentChapter() {
    const currentProject = projectRef.current;
    const currentStory = storyRef.current;
    const currentBundle = selectedBundleOrLatest(currentStory, selectedChapter);
    if (!currentProject || !currentStory || !currentBundle) {
      setError("请先打开项目并生成章节，再单独审核。");
      return;
    }

    setError(null);
    setIsReviewingChapter(true);
    setReviewStatusText(`正在审核第 ${currentBundle.chapter_number} 章...`);
    try {
      const review = await fetchProjectAgentReview(currentProject.project_id, currentBundle.chapter_number, true);
      const nextStory = applyReviewToStory(currentStory, review);
      updateStory(nextStory);
      setSelectedChapter(review.chapter.chapter_number);
      const action = review.recommendation?.action === "continue" ? "通过" : "需要修改";
      setReviewStatusText(`第 ${review.chapter.chapter_number} 章审核完成：${action}`);
      window.setTimeout(() => {
        if (isMountedRef.current) {
          setReviewStatusText(null);
        }
      }, 2400);
    } catch (reviewError) {
      setError(reviewError instanceof Error ? reviewError.message : "单章审核失败");
      setReviewStatusText(null);
    } finally {
      if (isMountedRef.current) {
        setIsReviewingChapter(false);
      }
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
        ...(payload.pipeline_stage !== undefined ? { pipeline_stage: payload.pipeline_stage } : {}),
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

  async function onEnrichWorld() {
    if (!projectRef.current) {
      setError("请先创建项目，再增强世界档案。");
      return;
    }
    setError(null);
    setIsEnrichingWorld(true);
    try {
      const enrichedProject = projectRef.current.active_story_id
        ? await enrichProjectRulebook(projectRef.current.project_id)
        : await enrichProjectWorld(projectRef.current.project_id);
      updateProject({
        ...projectRef.current,
        ...enrichedProject,
      });
      await refreshProjectSummaries();
    } catch (enrichError) {
      setError(enrichError instanceof Error ? enrichError.message : "AI 增强世界档案失败");
    } finally {
      setIsEnrichingWorld(false);
    }
  }

  const selectedBundle = selectedBundleOrLatest(story, selectedChapter);
  const activeChapter = selectedBundle?.chapter_number ?? story?.current_chapter ?? 0;
  const canStartGeneration = story ? true : canStartFirstChapter(draft);
  const canReviseSelectedChapter = Boolean(
    project && story && selectedBundle && selectedBundle.chapter_number === story.current_chapter,
  );
  const hasNoChaptersYet = !story?.history?.length;
  const shouldShowStartScreen = !project && !story;
  const shouldShowPrepScreen = project && hasNoChaptersYet && !story;
  const currentPipelineStage = projectPipelineStage(project, story, generationPhase);

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
      ) : shouldShowPrepScreen ? (
        <section className="prep-screen">
          <div className="prep-screen__hero">
            <p className="prep-screen__eyebrow">项目已创建</p>
            <h1 className="prep-screen__title">准备好就开始第一章</h1>
            <p className="prep-screen__lead">
              项目「<strong>{project.title}</strong>」已经建立。确认下方信息无误后，点击按钮直接生成第一章。
            </p>
          </div>

          <section className="pipeline-card" aria-label="小说生成流程">
            <div className="pipeline-card__header">
              <p className="prep-screen__eyebrow">Pipeline</p>
              <h2>从导入到章节生成的正确顺序</h2>
              <p>
                章节正文放在第 5 步：先构建图谱和世界档案，再搭建仿真环境，最后把模拟结果写成小说。
              </p>
            </div>
            <ol className="pipeline-steps">
              {PIPELINE_STEPS.map((step) => {
                const state = pipelineStepState(step.stage, currentPipelineStage);
                return (
                  <li className={`pipeline-step pipeline-step--${state}`} key={step.stage}>
                    <span className="pipeline-step__dot" aria-hidden="true" />
                    <div>
                      <strong>{step.title}</strong>
                      <p>{step.detail}</p>
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>

          <div className="prep-screen__cards">
            <article className="prep-card">
              <header className="prep-card__header">
                <h2>世界设定</h2>
              </header>
              <div className="prep-card__body">
                {project.world_summary ? (
                  <p>{project.world_summary}</p>
                ) : project.seed_outline ? (
                  <p>{project.seed_outline.split('\n').slice(0, 3).join('\n')}</p>
                ) : (
                  <p className="hint">尚未填写世界设定</p>
                )}
              </div>
            </article>

            <article className="prep-card">
              <header className="prep-card__header">
                <h2>主线目标</h2>
              </header>
              <div className="prep-card__body">
                {project.current_focus ? (
                  <p>{project.current_focus}</p>
                ) : (
                  <p className="hint">尚未设置主线目标</p>
                )}
              </div>
            </article>

            <article className="prep-card">
              <header className="prep-card__header">
                <h2>核心角色</h2>
              </header>
              <div className="prep-card__body">
                {project.character_profiles?.length ? (
                  <ul className="prep-characters">
                    {project.character_profiles.map((c: any, i: number) => (
                      <li key={i}>
                        <strong>{c.name || '未命名'}</strong>
                        {c.game_id && <span>（游戏ID：{c.game_id}）</span>}
                        {c.goals?.[0] && <span> — {c.goals[0]}</span>}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="hint">尚未添加角色，生成时会自动补充</p>
                )}
              </div>
            </article>
          </div>

          <div className="prep-screen__actions">
            {error && <p className="form-error">{error}</p>}
            <button
              className="btn btn--secondary"
              disabled={isGenerating || isEnrichingWorld}
              onClick={() => void onEnrichWorld()}
            >
              {isEnrichingWorld
                ? "AI 增强中..."
                : project?.active_story_id
                  ? "AI 补强规则层"
                  : "AI 增强世界档案"}
            </button>
            <button
              className="btn btn--primary"
              disabled={isGenerating || isEnrichingWorld}
              onClick={() => void onGenerateNextChapter(bootstrappedDraft ?? undefined, undefined, {
                title: project?.title,
                worldSummary: project?.world_summary,
                sourcePath: project?.source_path,
                authorConstraints: project?.author_constraints,
                currentFocus: project?.current_focus,
              })}
            >
              {generationActionLabel(generationPhase, generationStatusText, "开始生成第一章 ->")}
            </button>
            <p className="hint">建议先增强世界档案，再生成第一章；生成后会进入完整工作台，可以随时回滚或调整。</p>
          </div>
        </section>
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
            generationStatus={generationStatusText}
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
            {generationStatusText && (
              <div className="panel automation-flow-panel">
                <div className="panel__body automation-flow-panel__body">
                  <p className="panel__eyebrow">自动化流程</p>
                  <h3>{generationStatusText}</h3>
                  <p className="hint">
                    当前阶段：{generationPhase === "environment" ? "环境准备" : generationPhase === "planning" ? "剧情规划" : generationPhase === "writing" ? "生成/审核/改稿" : "待命"}
                  </p>
                </div>
              </div>
            )}
            {error && <p className="form-error">{error}</p>}
            {project?.active_story_id ? (
              <div className="panel quick-actions-panel">
                <div>
                  <p className="panel__eyebrow">世界规则</p>
                  <h3>补强后续章节规则层</h3>
                  <p className="hint">用于已有章节后的规则修订：补足升级、经济、任务、公会、面板和章法约束。</p>
                </div>
                <button
                  className="btn btn--secondary"
                  disabled={isGenerating || isEnrichingWorld}
                  onClick={() => void onEnrichWorld()}
                >
                  {isEnrichingWorld ? "AI 补强中..." : "AI 补强规则层"}
                </button>
              </div>
            ) : null}
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
            isReviewing={isReviewingChapter}
            isRevising={isRevisingChapter}
            isPreparingManualDraft={isPreparingManualDraft}
            isSubmittingManualDraft={isSubmittingManualDraft}
            isSubmittingManualSegmentDraft={isSubmittingManualSegmentDraft}
            generationStatus={generationStatusText}
            reviewStatus={reviewStatusText}
            revisionStatus={revisionStatusText}
            manualDraftStatus={manualDraftStatusText}
            error={error}
            canReviseChapter={canReviseSelectedChapter}
            writingPacket={writingPacket}
            manualDraftBody={manualDraftBody}
            manualSegmentIndex={manualSegmentIndex}
            manualSegmentBody={manualSegmentBody}
            onStartGeneration={onGenerateNextChapter}
            onRollbackChapter={onRollbackChapter}
            onReviewChapter={onReviewCurrentChapter}
            onReviseChapter={onReviseCurrentChapter}
            onPrepareManualDraft={onPrepareManualDraft}
            onManualDraftBodyChange={setManualDraftBody}
            onSubmitManualDraft={onSubmitManualDraft}
            onSelectManualSegment={onSelectManualSegment}
            onManualSegmentBodyChange={setManualSegmentBody}
            onSubmitManualSegmentDraft={onSubmitManualSegmentDraft}
          />
        }
        side={
          <div className="workbench-right-rail">
            <WorldSimulationBoard project={project} story={story} bundle={selectedBundle} />
            <WorkbenchSidePanel
              project={project}
              story={story}
              bundle={selectedBundle}
              projectSummaries={projectSummaries}
              error={error}
              onOpenProject={onOpenProject}
              isGenerating={isGenerating}
            />
          </div>
        }
      />
      )}
    </AppShell>
  );
}
