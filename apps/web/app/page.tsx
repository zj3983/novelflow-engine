"use client";

import { useEffect, useRef, useState } from "react";

import { ChapterBundleView } from "../components/ChapterBundleView";
import {
  StorySidebar,
  type AgentSettings,
  type StoryDraft,
} from "../components/StorySidebar";
import {
  branchStory,
  createStory,
  deleteStory,
  fetchStory,
  generateNextChapter,
  listStories,
  rollbackStory,
  fetchRuntimeSettings,
  saveRuntimeSettings,
  testRuntimeSettingsConnection,

  type AgentSettings as ApiAgentSettings,
  type AgentRuntimeName,
  type BookImportBootstrapResponse,
  type ChapterBundle,
  type RuntimeConnectionTarget,
  type RuntimeSettings,
  type StoryCharacter,
  type StoryResponse,
  type StorySummary,
} from "../lib/api";

const DEFAULT_STORY = {
  story_id: "s-001",
  genre: "fantasy",
  style: "noir",
} as const;

const AGENT_SETTINGS_STORAGE_KEY = "novel-autogrowth-engine.agent-settings";

function defaultAgentSettings(): AgentSettings {
  return {
    mode: "Rule-based",
    globalModel: "gpt-5.4",
    characterModel: "gpt-5.4-mini",
    directorModel: "gpt-5.4",
    writerModel: "gpt-5.4",
    memoryModel: "gpt-5.4",
    temperature: "0.7",
    newCharacterPolicy: "Director review",
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
  const nextCharacters = (bootstrapDraft.characters ?? []).length
    ? bootstrapDraft.characters.map((name) => ({
      name,
      goal: "",
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
    directorBrief: bootstrapDraft.summary ?? currentDraft.directorBrief,
    characters: nextCharacters.length ? nextCharacters : currentDraft.characters,
  };
}

function parseStoredAgentSettings(value: string | null): AgentSettings | null {
  if (!value) {
    return null;
  }

  try {
    return {
      ...defaultAgentSettings(),
      ...(JSON.parse(value) as Partial<AgentSettings>),
    };
  } catch {
    return null;
  }
}

function toApiAgentSettings(settings: AgentSettings): ApiAgentSettings {
  return {
    mode: settings.mode,
    global_model: settings.globalModel,
    character_model: settings.characterModel,
    director_model: settings.directorModel,
    writer_model: settings.writerModel,
    memory_model: settings.memoryModel,
    temperature: settings.temperature,
    new_character_policy: settings.newCharacterPolicy,
  };
}

function fromApiAgentSettings(settings: ApiAgentSettings | undefined): AgentSettings {
  return {
    mode: settings?.mode ?? "Rule-based",
    globalModel: settings?.global_model ?? "gpt-5.4",
    characterModel: settings?.character_model ?? "gpt-5.4-mini",
    directorModel: settings?.director_model ?? "gpt-5.4",
    writerModel: settings?.writer_model ?? "gpt-5.4",
    memoryModel: settings?.memory_model ?? "gpt-5.4",
    temperature: String(settings?.temperature ?? "0.7"),
    newCharacterPolicy: settings?.new_character_policy ?? "Director review",
  };
}

function defaultRuntimeSettings(): RuntimeSettings {
  return {
    global: {
      api_key: "",
      base_url: "",
    },
    agents: {
      character: {
        api_key: "",
        base_url: "",
      },
      director: {
        api_key: "",
        base_url: "",
      },
      writer: {
        api_key: "",
        base_url: "",
      },
      memory: {
        api_key: "",
        base_url: "",
      },
    },
  };
}

async function onSaveRuntimeSettings(
  runtimeSettings: RuntimeSettings,
  setRuntimeSettingsStatus: (status: "idle" | "loading" | "saving" | "success" | "error") => void,
  isMountedRef: React.MutableRefObject<boolean>,
) {
  setRuntimeSettingsStatus("saving");
  try {
    await saveRuntimeSettings(runtimeSettings);
    if (isMountedRef.current) {
      setRuntimeSettingsStatus("success");
      setTimeout(() => {
        if (isMountedRef.current) {
          setRuntimeSettingsStatus("idle");
        }
      }, 2000);
    }
  } catch {
    if (isMountedRef.current) {
      setRuntimeSettingsStatus("error");
    }
  }
}

async function onTestRuntimeSettings(
  runtimeSettings: RuntimeSettings,
  target: RuntimeConnectionTarget,
  setRuntimeConnectionStatus: React.Dispatch<React.SetStateAction<Record<RuntimeConnectionTarget, { state: "idle" | "testing" | "success" | "error"; message: string }>>>,
  isMountedRef: React.MutableRefObject<boolean>,
) {
  setRuntimeConnectionStatus((prev) => ({
    ...prev,
    [target]: { ...prev[target], state: "testing" },
  }));
  try {
    await testRuntimeSettingsConnection(runtimeSettings, target);
    if (isMountedRef.current) {
      setRuntimeConnectionStatus((prev) => ({
        ...prev,
        [target]: { state: "success", message: "连接测试成功" },
      }));
    }
  } catch (e) {
    if (isMountedRef.current) {
      setRuntimeConnectionStatus((prev) => ({
        ...prev,
        [target]: { state: "error", message: e instanceof Error ? e.message : "连接测试失败" },
      }));
    }
  }
}

function runtimeBadgeTone(state: "idle" | "testing" | "success" | "error"): "info" | "warning" | "success" | "error" {
  switch (state) {
    case "testing":
      return "warning";
    case "success":
      return "success";
    case "error":
      return "error";
    default:
      return "info";
  }
}





function runtimeSourceLabel(source?: string): string {
  if (source === "llm") {
    return "模型";
  }
  if (source === "fallback") {
    return "回退";
  }
  if (source === "rule-based") {
    return "规则";
  }
  return "空闲";
}

function runtimeProbeModel(target: RuntimeConnectionTarget, settings: AgentSettings): string {
  if (target === "character") {
    return settings.characterModel || settings.globalModel;
  }
  if (target === "director") {
    return settings.directorModel || settings.globalModel;
  }
  if (target === "writer") {
    return settings.writerModel || settings.globalModel;
  }
  if (target === "memory") {
    return settings.memoryModel || settings.globalModel;
  }
  return settings.globalModel;
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
    parent_story_id: updatedStory?.parent_story_id ?? baseStory.parent_story_id ?? null,
    branched_from_chapter:
      updatedStory?.branched_from_chapter ?? baseStory.branched_from_chapter ?? null,
    characters: updatedStory?.characters ?? baseStory.characters,
    history: [...baseStory.history, nextBundle],
  };
}

export default function Page() {
  const [activeTab, setActiveTab] = useState<"workbench" | "config" | "api" | "proxy" | "system" | "about">("workbench");
  const [draft, setDraft] = useState<StoryDraft>({
    outline: "一位身为侦探的王子，揭开王宫里的连环罪案。",
    directorBrief: "",
    characters: [
      {
        name: "Lin Yue",
        goal: "find the culprit",
        frozen: false,
        relationshipTarget: "",
        relationshipBond: "",
        trust: "0.0",
        tension: "0.0",
      },
    ],
  });
  const [agentSettings, setAgentSettings] = useState<AgentSettings>(defaultAgentSettings());
  const [story, setStory] = useState<StoryResponse | null>(null);
  const [, setStoryCatalog] = useState<Record<string, StoryResponse>>({});
  const [storySummaries, setStorySummaries] = useState<StorySummary[]>([]);
  const [activeStoryId, setActiveStoryId] = useState<string>(DEFAULT_STORY.story_id);
  const [selectedChapter, setSelectedChapter] = useState<number | null>(null);
  const [storyInitialized, setStoryInitialized] = useState(false);
  const [activeDraftKey, setActiveDraftKey] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSettings>(defaultRuntimeSettings());
  const [runtimeSettingsStatus, setRuntimeSettingsStatus] = useState<"idle" | "loading" | "saving" | "success" | "error">("idle");
  const [runtimeConnectionStatus, setRuntimeConnectionStatus] = useState<Record<RuntimeConnectionTarget, { state: "idle" | "testing" | "success" | "error"; message: string }>>({
    global: { state: "idle", message: "" },
    character: { state: "idle", message: "" },
    director: { state: "idle", message: "" },
    writer: { state: "idle", message: "" },
    memory: { state: "idle", message: "" },
  });
  const [isHydrated, setIsHydrated] = useState(false);
  const draftRef = useRef(draft);
  const agentSettingsHydratedRef = useRef(false);
  const isMountedRef = useRef(true);

  function updateRuntimeSettings(updates: Partial<RuntimeSettings>) {
    setRuntimeSettings((prev) => ({
      ...prev,
      global: { ...prev.global, ...(updates.global ?? {}) },
      agents: {
        ...prev.agents,
        ...Object.entries(updates.agents ?? {}).reduce((acc, [key, value]) => {
          acc[key as keyof typeof prev.agents] = {
            ...prev.agents[key as keyof typeof prev.agents],
            ...value,
          };
          return acc;
        }, {} as typeof prev.agents),
      },
    }));
  }

  function handleTestRuntimeSettings(target: RuntimeConnectionTarget) {
    onTestRuntimeSettings(runtimeSettings, target, setRuntimeConnectionStatus, isMountedRef);
  }

  const currentDraftKey = JSON.stringify(draftRef.current);



  useEffect(() => {
    if (typeof window === "undefined" || agentSettingsHydratedRef.current) {
      return;
    }
    const stored = parseStoredAgentSettings(window.localStorage.getItem(AGENT_SETTINGS_STORAGE_KEY));
    if (stored) {
      setAgentSettings(stored);
    }
    agentSettingsHydratedRef.current = true;
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || !agentSettingsHydratedRef.current) {
      return;
    }
    window.localStorage.setItem(AGENT_SETTINGS_STORAGE_KEY, JSON.stringify(agentSettings));
  }, [agentSettings]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    setIsHydrated(true);
    fetchRuntimeSettings().then((settings) => {
      if (isMountedRef.current) {
        setRuntimeSettings(settings);
      }
    });
  }, []);

  useEffect(() => {
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  function updateDraft(next: StoryDraft) {
    draftRef.current = next;
    setDraft(next);
  }





  function buildCharacters(sourceDraft: StoryDraft = draftRef.current): StoryCharacter[] {
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

  async function refreshStorySummaries() {
    const summaries = await listStories();
    setStorySummaries(summaries);
    const details = await Promise.all(
      summaries.map(async (entry) => {
        try {
          return await fetchStory(entry.story_id);
        } catch {
          return null;
        }
      }),
    );

    setStoryCatalog(
      Object.fromEntries(
        details
          .filter((entry): entry is StoryResponse => entry !== null)
          .map((entry) => [entry.story_id, entry]),
      ),
    );
  }

  async function ensureStoryReady(): Promise<StoryResponse> {
    // 如果故事已经存在，直接返回
    if (story) {
      return story;
    }

    // 如果故事不存在，创建一个新的故事
    const createdStory = await createStory({
      ...DEFAULT_STORY,
      outline: composeOutlineForStory(draftRef.current),
      agent_settings: toApiAgentSettings(agentSettings),
      characters: buildCharacters(),
    });
    setStory(createdStory);
    setAgentSettings(fromApiAgentSettings(createdStory.agent_settings));
    setSelectedChapter(createdStory.history.at(-1)?.chapter_number ?? null);
    setStoryInitialized(true);
    setActiveDraftKey(currentDraftKey);
    setActiveStoryId(createdStory.story_id);
    await refreshStorySummaries();
    return createdStory;
  }

  async function onGenerateNextChapter(sourceDraft?: BookImportBootstrapResponse["draft"]) {
    setError(null);
    setIsGenerating(true);
    try {
      if (sourceDraft) {
        // 更新draft，但不重置故事
        const updatedDraft = applyBootstrappedDraft(draftRef.current, sourceDraft);
        updateDraft(updatedDraft);
      }

      // 确保故事准备就绪
      const readyStory = await ensureStoryReady();

      // 生成下一章
      const nextBundle = await generateNextChapter(activeStoryId);
      const nextStory = buildStoryFromBundle(readyStory, nextBundle, activeStoryId);
      setStory(nextStory);
      setAgentSettings(fromApiAgentSettings(nextStory.agent_settings));
      setSelectedChapter(nextBundle.chapter_number);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成失败");
    } finally {
      setIsGenerating(false);
    }
  }

  async function onRollbackChapter() {
    setError(null);
    setIsGenerating(true);
    try {
      const nextStory = await rollbackStory(activeStoryId);
      setStory(nextStory);
      setAgentSettings(fromApiAgentSettings(nextStory.agent_settings));
      setSelectedChapter(nextStory.history.at(-1)?.chapter_number ?? null);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "回滚失败");
    } finally {
      setIsGenerating(false);
    }
  }

  async function onBranchFromChapter(chapterNumber: number) {
    setError(null);
    setIsGenerating(true);
    try {
      await ensureStoryReady();
      const branchId = `${activeStoryId}-branch-ch${chapterNumber}`;
      const branch = await branchStory(activeStoryId, branchId, chapterNumber);
      setStory(branch);
      setAgentSettings(fromApiAgentSettings(branch.agent_settings));
      setActiveStoryId(branch.story_id);
      setSelectedChapter(branch.history.at(-1)?.chapter_number ?? null);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "分叉失败");
    } finally {
      setIsGenerating(false);
    }
  }

  async function onDeleteActiveStory() {
    if (!story?.parent_story_id) {
      return;
    }

    setError(null);
    setIsGenerating(true);
    try {
      const parentStoryId = story.parent_story_id;
      await deleteStory(activeStoryId);
      const parentStory = await fetchStory(parentStoryId);
      setStory(parentStory);
      setAgentSettings(fromApiAgentSettings(parentStory.agent_settings));
      setActiveStoryId(parentStory.story_id);
      setSelectedChapter(parentStory.history.at(-1)?.chapter_number ?? null);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除故事失败");
    } finally {
      setIsGenerating(false);
    }
  }

  async function onOpenStory(storyId: string) {
    setError(null);
    setIsGenerating(true);
    try {
      const openedStory = await fetchStory(storyId);
      setStory(openedStory);
      setAgentSettings(fromApiAgentSettings(openedStory.agent_settings));
      setActiveStoryId(storyId);
      setSelectedChapter(openedStory.history.at(-1)?.chapter_number ?? null);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "打开故事失败");
    } finally {
      setIsGenerating(false);
    }
  }

  const selectedBundle =
    selectedChapter == null
      ? null
      : story?.history.find((entry) => entry.chapter_number === selectedChapter) ?? null;

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>小说自动演化工作台</h1>
      </header>

      <div className="app-tabs">
        <button
          className={`app-tab ${activeTab === "workbench" ? "app-tab--active" : ""}`}
          onClick={() => setActiveTab("workbench")}
        >
          工作台
        </button>
        <button
          className={`app-tab ${(activeTab === "config" || activeTab === "api" || activeTab === "proxy" || activeTab === "system") ? "app-tab--active" : ""}`}
          onClick={() => setActiveTab("api")}
        >
          配置
        </button>
        <button
          className={`app-tab ${activeTab === "about" ? "app-tab--active" : ""}`}
          onClick={() => setActiveTab("about")}
        >
          关于
        </button>
      </div>

      {activeTab === "workbench" && (
        <div className="app-content">
          <aside className="story-sidebar">
            <section className="panel panel-story" aria-label="故事编辑面板">
              <header className="panel__header">故事大纲与角色</header>
              <div className="panel__body">
                <StorySidebar
                  draft={draft}
                  agentSettings={agentSettings}
                  runtimeSettings={runtimeSettings}
                  onChange={updateDraft}
                  onAgentSettingsChange={setAgentSettings}
                  onRuntimeSettingsChange={updateRuntimeSettings}
                  onSaveRuntimeSettings={() => onSaveRuntimeSettings(runtimeSettings, setRuntimeSettingsStatus, isMountedRef)}
                  onTestRuntimeSettings={(target: RuntimeConnectionTarget) => onTestRuntimeSettings(runtimeSettings, target, setRuntimeConnectionStatus, isMountedRef)}
                  runtimeSettingsStatus={runtimeSettingsStatus}
                  runtimeConnectionStatus={runtimeConnectionStatus}
                  onStartGeneration={onGenerateNextChapter}
                  history={story?.history ?? []}
                  selectedChapter={selectedChapter}
                  onSelectHistoryChapter={setSelectedChapter}
                />
              </div>
            </section>
          </aside>

          <main className="workbench">
            <section className="panel panel-draft" aria-label="章节草稿面板">
              <header className="panel__header">章节草稿</header>
              <div className="panel__body">
                {selectedBundle ? <ChapterBundleView bundle={selectedBundle} /> : <p className="hint">还没有生成章节。</p>}
              </div>
            </section>

            <section className="panel panel-state" aria-label="角色状态面板">
              <header className="panel__header">角色状态</header>
              <div className="panel__body">
                {selectedBundle ? (
                  <div>
                    <p className="hint" style={{ marginBottom: 10 }}>
                      故事：{story?.story_id}
                    </p>
                    <p className="hint" style={{ marginBottom: 10 }}>
                      当前章节：{story?.current_chapter ?? selectedBundle.chapter_number}
                    </p>
                    <p className="hint" style={{ marginBottom: 10 }}>
                      正在查看：第 {selectedBundle.chapter_number} 章
                    </p>
                    {story?.parent_story_id ? (
                      <p className="hint" style={{ marginBottom: 10 }}>
                        父故事：{story.parent_story_id}
                      </p>
                    ) : null}
                    {story?.branched_from_chapter != null ? (
                      <p className="hint" style={{ marginBottom: 10 }}>
                        分叉章节：第 {story.branched_from_chapter} 章
                      </p>
                    ) : null}
                    <p className="hint" style={{ marginBottom: 10 }}>
                      连贯性：{selectedBundle.quality_report?.ok ? "正常" : "需要检查"}
                    </p>
                    <p className="hint" style={{ marginBottom: 10 }}>
                      下一步：{selectedBundle.next_outline ?? "暂无规划"}
                    </p>
                    {story?.agent_runtime ? (
                      <div className="agent-runtime" style={{ marginBottom: 10 }}>
                        <p className="hint" style={{ marginBottom: 8 }}>
                          代理运行状态
                        </p>
                        <p className="hint" style={{ marginBottom: 6 }}>
                          角色代理：{runtimeSourceLabel(story.agent_runtime.character_agent.source)}
                        </p>
                        <p className="hint" style={{ marginBottom: 6 }}>
                          导演代理：{runtimeSourceLabel(story.agent_runtime.director_agent.source)}
                        </p>
                        <p className="hint" style={{ marginBottom: 6 }}>
                          写作代理：{runtimeSourceLabel(story.agent_runtime.writer_agent.source)}
                        </p>
                        <p className="hint" style={{ marginBottom: 6 }}>
                          记忆代理：{runtimeSourceLabel(story.agent_runtime.memory_agent.source)}
                        </p>
                        <p className="hint" style={{ marginBottom: 0 }}>
                          最近事件：{story.agent_runtime.recent_events.at(-1) ?? "暂无"}
                        </p>
                      </div>
                    ) : null}
                    {story?.characters.length ? (
                      <>
                        <p className="hint" style={{ marginBottom: 10 }}>
                          角色表：{story.characters.map((character) => character.name).join(", ")}
                        </p>
                        <p className="hint" style={{ marginBottom: 10 }}>
                          主角：{story.characters[0].name}
                        </p>
                        <p className="hint" style={{ marginBottom: 10 }}>
                          冻结：{story.characters[0].frozen ? "是" : "否"}
                        </p>
                      </>
                    ) : null}
                  </div>
                ) : (
                  <p className="hint">还没有状态，先生成一章开始吧。</p>
                )}
              </div>
            </section>

            <section className="panel panel-controls" aria-label="控制面板">
              <header className="panel__header">控制区</header>
              <div className="panel__body">
                <button className="btn" type="button" onClick={() => void onGenerateNextChapter()} disabled={isGenerating}>
                  生成下一章
                </button>
                <button
                  className="btn btn--ghost"
                  type="button"
                  onClick={onRollbackChapter}
                  disabled={isGenerating || !storyInitialized}
                >
                  回滚章节
                </button>

                {story ? (
                  <div style={{ marginTop: 14 }}>
                    <p className="hint" style={{ marginBottom: 8 }}>
                      当前故事管理
                    </p>
                    {story.parent_story_id ? (
                      <button className="btn btn--ghost" type="button" onClick={onDeleteActiveStory} disabled={isGenerating}>
                        删除当前故事
                      </button>
                    ) : null}
                  </div>
                ) : null}

                {story?.history.length ? (
                  <div style={{ marginTop: 14 }}>
                    <p className="hint" style={{ marginBottom: 8 }}>
                      章节历史
                    </p>
                    {story.history.map((entry) => (
                      <div key={entry.chapter_number} style={{ display: "flex", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                        <button
                          className="btn btn--ghost"
                          type="button"
                          onClick={() => setSelectedChapter(entry.chapter_number)}
                          disabled={isGenerating}
                        >
                          查看第 {entry.chapter_number} 章
                        </button>
                        <button
                          className="btn btn--ghost"
                          type="button"
                          onClick={() => void onBranchFromChapter(entry.chapter_number)}
                          disabled={isGenerating}
                        >
                          从第 {entry.chapter_number} 章分叉
                        </button>
                      </div>
                    ))}
                  </div>
                ) : null}

                {storySummaries.length ? (
                  <div style={{ marginTop: 14 }}>
                    <p className="hint" style={{ marginBottom: 8 }}>
                      故事列表
                    </p>
                    {storySummaries.map((entry) => (
                      <button
                        key={entry.story_id}
                        className="btn btn--ghost"
                        type="button"
                        style={{ marginRight: 8, marginBottom: 8 }}
                        onClick={() => void onOpenStory(entry.story_id)}
                        disabled={isGenerating}
                      >
                        打开 {entry.story_id}
                      </button>
                    ))}
                  </div>
                ) : null}

                {error ? (
                  <p className="hint" style={{ marginTop: 12 }}>
                    错误：{error}
                  </p>
                ) : null}
              </div>
            </section>
          </main>
        </div>
      )}

      {(activeTab === "config" || activeTab === "api" || activeTab === "proxy" || activeTab === "system") && (
        <div className="config-page">
          <div className="config-tabs">
            <button
              className={`config-tab ${(activeTab === "config" || activeTab === "api") ? "config-tab--active" : ""}`}
              onClick={() => setActiveTab("api")}
            >
              API 配置
            </button>
            <button
              className={`config-tab ${activeTab === "proxy" ? "config-tab--active" : ""}`}
              onClick={() => setActiveTab("proxy")}
            >
              代理设置
            </button>
            <button
              className={`config-tab ${activeTab === "system" ? "config-tab--active" : ""}`}
              onClick={() => setActiveTab("system")}
            >
              系统设置
            </button>
          </div>

          <main className="config-content">
            {(activeTab === "config" || activeTab === "api") && (
              <section className="config-section">
                <h2>API 配置</h2>
                <p className="hint" style={{ marginBottom: 10 }}>
                  这里保存的是全局默认 API。下面每个代理都可以单独覆盖，留空则回退到全局默认。
                </p>

                <div className="field">
                  <label htmlFor="runtime-global-api-key">全局 API 密钥</label>
                  <input
                    id="runtime-global-api-key"
                    aria-label="全局 API 密钥"
                    type="password"
                    className="text-input"
                    value={runtimeSettings.global.api_key}
                    onChange={(event) =>
                      updateRuntimeSettings({
                        global: { ...runtimeSettings.global, api_key: event.target.value },
                      })
                    }
                  />
                </div>

                <div className="field">
                  <label htmlFor="runtime-global-base-url">全局接口地址</label>
                  <input
                    id="runtime-global-base-url"
                    aria-label="全局接口地址"
                    className="text-input"
                    value={runtimeSettings.global.base_url}
                    onChange={(event) =>
                      updateRuntimeSettings({
                        global: { ...runtimeSettings.global, base_url: event.target.value },
                      })
                    }
                  />
                </div>

                <button
                  className="btn btn--ghost"
                  type="button"
                  aria-label="测试全局连接"
                  onClick={() => handleTestRuntimeSettings("global")}
                >
                  测试全局连接
                </button>
                <p className="hint runtime-status" style={{ marginTop: 8 }}>
                  <span
                    className={`runtime-status__badge runtime-status__badge--${runtimeBadgeTone(
                      runtimeConnectionStatus.global.state,
                    )}`}
                  >
                    {runtimeConnectionStatus.global.state === "testing"
                      ? "测试中"
                      : runtimeConnectionStatus.global.state === "success"
                        ? "正常"
                        : runtimeConnectionStatus.global.state === "error"
                          ? "失败"
                          : "待测"}
                  </span>
                  <span className="runtime-status__text">
                    {runtimeConnectionStatus.global.state === "testing"
                      ? "正在测试全局连接..."
                      : runtimeConnectionStatus.global.message || "点一下测试，确认全局默认 API 是否可用。"}
                  </span>
                </p>

                <div className="config-section__summary" aria-label="代理运行覆盖配置">
                  <p className="hint">下面这些字段只覆盖对应代理；留空时会自动使用全局默认。</p>
                </div>

                <div className="config-section__grid">
                  {([["character", "角色代理"], ["director", "导演代理"], ["writer", "写作代理"], ["memory", "记忆代理"]] as Array<[AgentRuntimeName, string]>).map(([agentKey, agentLabel]) => (
                    <section className="character-card" key={agentKey}>
                      <p className="character-card__title">{agentLabel} API</p>
                      <p className="hint">留空则回退到全局默认。</p>

                      <div className="field">
                        <label htmlFor={`runtime-${agentKey}-api-key`}>{agentLabel} API 密钥</label>
                        <input
                          id={`runtime-${agentKey}-api-key`}
                          aria-label={`${agentLabel} API 密钥`}
                          type="password"
                          className="text-input"
                          value={runtimeSettings.agents[agentKey].api_key}
                          onChange={(event) =>
                            updateRuntimeSettings({
                              agents: {
                                ...runtimeSettings.agents,
                                [agentKey]: {
                                  ...runtimeSettings.agents[agentKey],
                                  api_key: event.target.value,
                                },
                              },
                            })
                          }
                        />
                      </div>

                      <div className="field">
                        <label htmlFor={`runtime-${agentKey}-base-url`}>{agentLabel} 接口地址</label>
                        <input
                          id={`runtime-${agentKey}-base-url`}
                          aria-label={`${agentLabel} 接口地址`}
                          className="text-input"
                          value={runtimeSettings.agents[agentKey].base_url}
                          onChange={(event) =>
                            updateRuntimeSettings({
                              agents: {
                                ...runtimeSettings.agents,
                                [agentKey]: {
                                  ...runtimeSettings.agents[agentKey],
                                  base_url: event.target.value,
                                },
                              },
                            })
                          }
                        />
                      </div>

                      <button
                        className="btn btn--ghost"
                        type="button"
                        aria-label={`${agentLabel} 测试连接`}
                        onClick={() => handleTestRuntimeSettings(agentKey)}
                      >
                        测试连接
                      </button>
                      <p className="hint runtime-status" style={{ marginTop: 8 }}>
                        <span
                          className={`runtime-status__badge runtime-status__badge--${runtimeBadgeTone(
                            runtimeConnectionStatus[agentKey].state,
                          )}`}
                        >
                          {runtimeConnectionStatus[agentKey].state === "testing"
                            ? "测试中"
                            : runtimeConnectionStatus[agentKey].state === "success"
                              ? "正常"
                              : runtimeConnectionStatus[agentKey].state === "error"
                                ? "失败"
                                : "待测"}
                        </span>
                        <span className="runtime-status__text">
                          {runtimeConnectionStatus[agentKey].state === "testing"
                            ? `正在测试${agentLabel}连接...`
                            : runtimeConnectionStatus[agentKey].message || `点一下测试，确认该代理专用 API 是否可用。`}
                        </span>
                      </p>
                    </section>
                  ))}
                </div>

                <button className="btn btn--ghost" type="button" onClick={() => onSaveRuntimeSettings(runtimeSettings, setRuntimeSettingsStatus, isMountedRef)}>
                  保存 API 配置
                </button>

                <p className="hint">
                  {runtimeSettingsStatus === "saving"
                    ? "正在保存 API 配置..."
                    : runtimeSettingsStatus === "error"
                      ? "API 配置保存失败"
                      : runtimeSettingsStatus === "success"
                        ? "API 配置保存成功"
                        : "保存后会立刻影响后端的 LLM 协助模式。"}
                </p>
              </section>
            )}

            {activeTab === "proxy" && (
              <section className="config-section">
                <h2>代理设置</h2>
                <p className="hint">这里可以配置代理服务器设置，用于连接外部 API。</p>
                <div className="field">
                  <label htmlFor="proxy-url">代理服务器 URL</label>
                  <input
                    id="proxy-url"
                    aria-label="代理服务器 URL"
                    className="text-input"
                    placeholder="例如：http://localhost:7890"
                  />
                </div>
                <button className="btn btn--ghost" type="button">
                  保存代理设置
                </button>
              </section>
            )}

            {activeTab === "system" && (
              <section className="config-section">
                <h2>系统设置</h2>
                <p className="hint">这里可以配置系统级别的设置。</p>
                <div className="field">
                  <label htmlFor="system-language">系统语言</label>
                  <select id="system-language" className="text-input">
                    <option value="zh-CN">简体中文</option>
                    <option value="en-US">English</option>
                  </select>
                </div>
                <button className="btn btn--ghost" type="button">
                  保存系统设置
                </button>
              </section>
            )}
          </main>
        </div>
      )}

      {activeTab === "about" && (
        <div className="about-page">
          <section className="about-section">
            <h2>关于小说自动演化工作台</h2>
            <p className="hint">小说自动演化工作台是一个基于 AI 的小说创作工具，能够自动生成小说章节，帮助作家快速创作故事。</p>
            <p className="hint">版本：1.0.0</p>
            <p className="hint">版权所有 © 2026</p>
          </section>
        </div>
      )}
    </div>
  );
}
