"use client";

import { useEffect, useRef, useState } from "react";

import { ChapterBundleView } from "../components/ChapterBundleView";
import {
  StorySidebar,
  type AgentSettings,
  type StoryDraft,
  type RuntimeSettings,
} from "../components/StorySidebar";
import {
  branchStory,
  createStory,
  deleteStory,
  fetchRuntimeSettings,
  fetchStory,
  generateNextChapter,
  listStories,
  saveRuntimeSettings,
  testRuntimeSettingsConnection,
  rollbackStory,
  type AgentSettings as ApiAgentSettings,
  type ChapterBundle,
  type RuntimeSettings as ApiRuntimeSettings,
  type RuntimeConnectionTarget,
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

  return `${outline}\n\n【导演预读】\n${directorBrief}`;
}

function parseStoredAgentSettings(value: string | null): AgentSettings | null {
  if (!value) {
    return null;
  }

  try {
    const parsed = JSON.parse(value) as Partial<AgentSettings>;
    return {
      ...defaultAgentSettings(),
      ...parsed,
      globalModel: parsed.globalModel ?? "gpt-5.4",
      characterModel: parsed.characterModel ?? "gpt-5.4-mini",
      directorModel: parsed.directorModel ?? "gpt-5.4",
      writerModel: parsed.writerModel ?? "gpt-5.4",
      memoryModel: parsed.memoryModel ?? "gpt-5.4",
      temperature: parsed.temperature ?? "0.7",
      newCharacterPolicy: parsed.newCharacterPolicy ?? "Director review",
      mode: parsed.mode ?? "Rule-based",
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

function toApiRuntimeSettings(settings: RuntimeSettings): ApiRuntimeSettings {
  return {
    global: {
      api_key: settings.global.apiKey,
      base_url: settings.global.baseUrl,
    },
    agents: {
      character: {
        api_key: settings.agents.character.apiKey,
        base_url: settings.agents.character.baseUrl,
      },
      director: {
        api_key: settings.agents.director.apiKey,
        base_url: settings.agents.director.baseUrl,
      },
      writer: {
        api_key: settings.agents.writer.apiKey,
        base_url: settings.agents.writer.baseUrl,
      },
      memory: {
        api_key: settings.agents.memory.apiKey,
        base_url: settings.agents.memory.baseUrl,
      },
    },
  };
}

function fromApiRuntimeSettings(settings: ApiRuntimeSettings | undefined): RuntimeSettings {
  const defaultEndpoint = {
    apiKey: "",
    baseUrl: "https://api.openai.com/v1",
  };
  const normalize = (value?: { api_key?: string; base_url?: string }) => ({
    apiKey: value?.api_key ?? defaultEndpoint.apiKey,
    baseUrl: value?.base_url ?? defaultEndpoint.baseUrl,
  });
  return {
    global: normalize(settings?.global),
    agents: {
      character: normalize(settings?.agents?.character),
      director: normalize(settings?.agents?.director),
      writer: normalize(settings?.agents?.writer),
      memory: normalize(settings?.agents?.memory),
    },
  };
}

export default function Page() {
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
  const [agentSettings, setAgentSettings] = useState<AgentSettings>({
    mode: "Rule-based",
    globalModel: "gpt-5.4",
    characterModel: "gpt-5.4-mini",
    directorModel: "gpt-5.4",
    writerModel: "gpt-5.4",
    memoryModel: "gpt-5.4",
    temperature: "0.7",
    newCharacterPolicy: "Director review",
  });
  const [runtimeSettings, setRuntimeSettings] = useState<RuntimeSettings>({
    global: {
      apiKey: "",
      baseUrl: "https://api.openai.com/v1",
    },
    agents: {
      character: {
        apiKey: "",
        baseUrl: "",
      },
      director: {
        apiKey: "",
        baseUrl: "",
      },
      writer: {
        apiKey: "",
        baseUrl: "",
      },
      memory: {
        apiKey: "",
        baseUrl: "",
      },
    },
  });
  const [runtimeSettingsStatus, setRuntimeSettingsStatus] = useState<
    "idle" | "saved" | "error"
  >("idle");
  const [runtimeConnectionStatus, setRuntimeConnectionStatus] = useState<
    Record<
      RuntimeConnectionTarget,
      { state: "idle" | "testing" | "success" | "error"; message: string }
    >
  >({
    global: { state: "idle", message: "" },
    character: { state: "idle", message: "" },
    director: { state: "idle", message: "" },
    writer: { state: "idle", message: "" },
    memory: { state: "idle", message: "" },
  });
  const [story, setStory] = useState<StoryResponse | null>(null);
  const [storyCatalog, setStoryCatalog] = useState<Record<string, StoryResponse>>({});
  const [activeStoryId, setActiveStoryId] = useState<string>(DEFAULT_STORY.story_id);
  const [selectedChapter, setSelectedChapter] = useState<number | null>(null);
  const [storySummaries, setStorySummaries] = useState<StorySummary[]>([]);
  const [branchFocus, setBranchFocus] = useState<"all" | "active">("all");
  const [isGenerating, setIsGenerating] = useState(false);
  const [storyInitialized, setStoryInitialized] = useState(false);
  const [activeDraftKey, setActiveDraftKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const draftRef = useRef(draft);
  const agentSettingsHydratedRef = useRef(false);

  const currentDraftKey = JSON.stringify(draftRef.current);

  useEffect(() => {
    void (async () => {
      try {
        const settings = await fetchRuntimeSettings();
        setRuntimeSettings(fromApiRuntimeSettings(settings));
        setRuntimeSettingsStatus("idle");
      } catch {
        setRuntimeSettingsStatus("error");
      }
    })();
  }, []);

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

  function updateDraft(next: StoryDraft) {
    draftRef.current = next;
    setDraft(next);
  }

  function updateRuntimeSettings(next: RuntimeSettings) {
    setRuntimeSettings(next);
    setRuntimeSettingsStatus("idle");
  }

  async function onSaveRuntimeSettings() {
    setError(null);
    try {
      const saved = await saveRuntimeSettings(toApiRuntimeSettings(runtimeSettings));
      setRuntimeSettings(fromApiRuntimeSettings(saved));
      setRuntimeSettingsStatus("saved");
    } catch (e) {
      setRuntimeSettingsStatus("error");
      setError(e instanceof Error ? e.message : "保存 API 配置失败");
    }
  }

  async function onTestRuntimeSettings(target: RuntimeConnectionTarget) {
    setError(null);
    setRuntimeConnectionStatus((current) => ({
      ...current,
      [target]: { state: "testing", message: "正在测试连接..." },
    }));
    try {
      const result = await testRuntimeSettingsConnection(toApiRuntimeSettings(runtimeSettings), target);
      setRuntimeConnectionStatus((current) => ({
        ...current,
        [target]: {
          state: result.ok ? "success" : "error",
          message: result.message,
        },
      }));
    } catch (e) {
      setRuntimeConnectionStatus((current) => ({
        ...current,
        [target]: {
          state: "error",
          message: e instanceof Error ? e.message : "连接测试失败",
        },
      }));
    }
  }

  function buildCharacters(): StoryCharacter[] {
    return draftRef.current.characters
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

  function buildStoryFromBundle(
    baseStory: StoryResponse,
    nextBundle: ChapterBundle,
    storyId: string,
  ): StoryResponse {
    const history = [...baseStory.history, nextBundle];
    const updatedStory = nextBundle.updated_story as StoryResponse | undefined;

    return {
      story_id: storyId,
      outline: updatedStory?.outline ?? baseStory.outline,
      genre: updatedStory?.genre ?? baseStory.genre,
      style: updatedStory?.style ?? baseStory.style,
      current_chapter: updatedStory?.current_chapter ?? nextBundle.chapter_number,
      agent_settings: updatedStory?.agent_settings ?? baseStory.agent_settings,
      agent_runtime: updatedStory?.agent_runtime ?? baseStory.agent_runtime,
      parent_story_id: baseStory.parent_story_id ?? null,
      branched_from_chapter: baseStory.branched_from_chapter ?? null,
      characters: updatedStory?.characters ?? baseStory.characters,
      history,
    };
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

  function storyDepth(entry: StorySummary): number {
    let depth = 0;
    let cursor: StorySummary | undefined = entry.parent_story_id
      ? storySummaries.find((item) => item.story_id === entry.parent_story_id)
      : undefined;
    while (cursor) {
      depth += 1;
      const parentStoryId = cursor.parent_story_id;
      cursor = parentStoryId
        ? storySummaries.find((item) => item.story_id === parentStoryId)
        : undefined;
    }
    return depth;
  }

  function latestSummary(storyId: string): string {
    const latest = storyCatalog[storyId]?.history.at(-1);
    return latest?.chapter_summary?.summary ?? "None";
  }

  function latestThread(storyId: string): string {
    const latest = storyCatalog[storyId]?.history.at(-1);
    return latest?.chapter_summary?.unresolved_threads?.[0] ?? "None";
  }

  function latestForeshadowing(storyId: string): string {
    const latest = storyCatalog[storyId]?.history.at(-1);
    const entry = latest?.foreshadowing?.[0] as { text?: string } | undefined;
    return entry?.text ?? "None";
  }

  function chapterTitle(chapterNumber: number): string {
    if (chapterNumber === 1) {
      return "开局";
    }
    if (chapterNumber === 2) {
      return "压力上升";
    }
    return `转折点 ${chapterNumber}`;
  }

  function chapterTags(chapterNumber: number): string {
    if (chapterNumber === 1) {
      return "历史节点，分支导航";
    }
    if (chapterNumber === 2) {
      return "升级节点，连续性";
    }
    return "故事节点，连续性";
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

  function visibleStorySummaries(): StorySummary[] {
    if (branchFocus === "all" || !story) {
      return storySummaries;
    }

    const allowed = new Set<string>([activeStoryId]);
    let cursor: StorySummary | undefined = story.parent_story_id
      ? storySummaries.find((item) => item.story_id === story.parent_story_id)
      : undefined;
    while (cursor) {
      allowed.add(cursor.story_id);
      const parentStoryId = cursor.parent_story_id;
      cursor = parentStoryId
        ? storySummaries.find((item) => item.story_id === parentStoryId)
        : undefined;
    }

    return storySummaries.filter((entry) => allowed.has(entry.story_id));
  }

  async function ensureStoryReady(): Promise<StoryResponse> {
    const characters = buildCharacters();
    const mustReset = !storyInitialized || activeDraftKey !== currentDraftKey;

    if (mustReset) {
      const createdStory = await createStory({
        ...DEFAULT_STORY,
        outline: composeOutlineForStory(draftRef.current),
        agent_settings: toApiAgentSettings(agentSettings),
        characters,
      });
      setStory(createdStory);
      setAgentSettings(fromApiAgentSettings(createdStory.agent_settings));
      setSelectedChapter(createdStory.history.length ? createdStory.history[createdStory.history.length - 1].chapter_number : null);
      setStoryInitialized(true);
      setActiveDraftKey(currentDraftKey);
      setActiveStoryId(DEFAULT_STORY.story_id);
      await refreshStorySummaries();
      return createdStory;
    }

    if (!story) {
      const syncedStory = await fetchStory(activeStoryId);
      setStory(syncedStory);
      setAgentSettings(fromApiAgentSettings(syncedStory.agent_settings));
      setSelectedChapter(syncedStory.history.length ? syncedStory.history[syncedStory.history.length - 1].chapter_number : null);
      return syncedStory;
    }

    return story;
  }

  async function onGenerateNextChapter() {
    setError(null);
    setIsGenerating(true);
    try {
      const readyStory = await ensureStoryReady();
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
      const syncedStory = await rollbackStory(activeStoryId);
      setStory(syncedStory);
      setAgentSettings(fromApiAgentSettings(syncedStory.agent_settings));
      setSelectedChapter(syncedStory.history.length ? syncedStory.history[syncedStory.history.length - 1].chapter_number : null);
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
      setSelectedChapter(branch.history.length ? branch.history[branch.history.length - 1].chapter_number : null);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "分叉失败");
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
      setSelectedChapter(openedStory.history.length ? openedStory.history[openedStory.history.length - 1].chapter_number : null);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "打开故事失败");
    } finally {
      setIsGenerating(false);
    }
  }

  async function onOpenStoryChapter(storyId: string, chapterNumber: number) {
    setError(null);
    setIsGenerating(true);
    try {
      const openedStory = storyCatalog[storyId] ?? await fetchStory(storyId);
      setStory(openedStory);
      setAgentSettings(fromApiAgentSettings(openedStory.agent_settings));
      setActiveStoryId(storyId);
      setSelectedChapter(chapterNumber);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "打开章节失败");
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
      setSelectedChapter(parentStory.history.length ? parentStory.history[parentStory.history.length - 1].chapter_number : null);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除故事失败");
    } finally {
      setIsGenerating(false);
    }
  }

  const selectedBundle =
    selectedChapter == null
      ? null
      : story?.history.find((entry) => entry.chapter_number === selectedChapter) ?? null;

  return (
    <main className="workbench">
      <section className="panel panel-outline" aria-label="Outline Panel">
        <header className="panel__header">大纲</header>
        <div className="panel__body">
          <StorySidebar
            draft={draft}
            agentSettings={agentSettings}
            runtimeSettings={runtimeSettings}
            runtimeSettingsStatus={runtimeSettingsStatus}
            runtimeConnectionStatus={runtimeConnectionStatus}
            onChange={updateDraft}
            onAgentSettingsChange={setAgentSettings}
          onRuntimeSettingsChange={updateRuntimeSettings}
          onSaveRuntimeSettings={onSaveRuntimeSettings}
          onTestRuntimeSettings={onTestRuntimeSettings}
          onStartGeneration={onGenerateNextChapter}
          history={story?.history ?? []}
          selectedChapter={selectedChapter}
          onSelectHistoryChapter={setSelectedChapter}
          />
        </div>
      </section>

      <section className="panel panel-draft" aria-label="Chapter Draft Panel">
        <header className="panel__header">章节草稿</header>
        <div className="panel__body">
          {selectedBundle ? (
            <ChapterBundleView bundle={selectedBundle} />
          ) : (
            <p className="hint">还没有生成章节。</p>
          )}
        </div>
      </section>

      <section className="panel panel-state" aria-label="Character State Panel">
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
                正在查看：{selectedBundle.chapter_number}
              </p>
              {story?.story_id !== DEFAULT_STORY.story_id ? (
                <p className="hint" style={{ marginBottom: 10 }}>
                  分支故事：{story?.story_id}
                </p>
              ) : null}
              {story?.parent_story_id ? (
                <p className="hint" style={{ marginBottom: 10 }}>
                  父故事：{story.parent_story_id}
                </p>
              ) : null}
              {story?.branched_from_chapter != null ? (
                <p className="hint" style={{ marginBottom: 10 }}>
                  分叉章节：{story.branched_from_chapter}
                </p>
              ) : null}
              <p className="hint" style={{ marginBottom: 10 }}>
                连贯性：{selectedBundle.quality_report?.ok ? "正常" : "需要检查"}
              </p>
              <p className="hint" style={{ marginBottom: 10 }}>
                下一步：{selectedBundle.next_outline ?? "暂未规划"}
              </p>
              {story?.agent_runtime ? (
                <div className="agent-runtime" style={{ marginBottom: 10 }}>
                  <p className="hint" style={{ marginBottom: 8 }}>
                    代理运行状态
                  </p>
                  <p className="hint" style={{ marginBottom: 6 }}>
                    角色代理：{runtimeSourceLabel(story.agent_runtime.character_agent.source)}
                    {story.agent_runtime.character_agent.fallback_reason
                      ? ` - ${story.agent_runtime.character_agent.fallback_reason}`
                      : ""}
                  </p>
                  <p className="hint" style={{ marginBottom: 6 }}>
                    导演代理：{runtimeSourceLabel(story.agent_runtime.director_agent.source)}
                    {story.agent_runtime.director_agent.fallback_reason
                      ? ` - ${story.agent_runtime.director_agent.fallback_reason}`
                      : ""}
                  </p>
                  <p className="hint" style={{ marginBottom: 6 }}>
                    写作代理：{runtimeSourceLabel(story.agent_runtime.writer_agent.source)}
                    {story.agent_runtime.writer_agent.fallback_reason
                      ? ` - ${story.agent_runtime.writer_agent.fallback_reason}`
                      : ""}
                  </p>
                  <p className="hint" style={{ marginBottom: 6 }}>
                    记忆代理：{runtimeSourceLabel(story.agent_runtime.memory_agent.source)}
                    {story.agent_runtime.memory_agent.fallback_reason
                      ? ` - ${story.agent_runtime.memory_agent.fallback_reason}`
                      : ""}
                  </p>
                  <p className="hint" style={{ marginBottom: 0 }}>
                    最近事件：{story.agent_runtime.recent_events.at(-1) ?? "暂无"}
                  </p>
                </div>
              ) : null}
              {selectedBundle.chapter_summary?.facts?.length ? (
                <p className="hint" style={{ marginBottom: 10 }}>
                  最新事实：{selectedBundle.chapter_summary.facts[0]}
                </p>
              ) : null}
              {selectedBundle.updated_story &&
              (selectedBundle.updated_story as { characters?: Array<{ name: string; frozen: boolean }> }).characters?.length ? (
                <>
                  <p className="hint" style={{ marginBottom: 10 }}>
                    角色表：{(selectedBundle.updated_story as { characters: Array<{ name: string }> }).characters.map((character) => character.name).join(", ")}
                  </p>
                  <p className="hint" style={{ marginBottom: 10 }}>
                    主角：{(selectedBundle.updated_story as { characters: Array<{ name: string; frozen: boolean }> }).characters[0].name}
                  </p>
                  <p className="hint" style={{ marginBottom: 10 }}>
                    冻结：{(selectedBundle.updated_story as { characters: Array<{ name: string; frozen: boolean }> }).characters[0].frozen ? "是" : "否"}
                  </p>
                  <p className="hint" style={{ marginBottom: 10 }}>
                    生命周期：{(selectedBundle.updated_story as { characters: Array<{ lifecycle_state: string }> }).characters[0].lifecycle_state}
                  </p>
                  <p className="hint" style={{ marginBottom: 10 }}>
                    最近提议：{(selectedBundle.updated_story as { characters: Array<{ last_proposed_chapter: number }> }).characters[0].last_proposed_chapter}
                  </p>
                  <p className="hint" style={{ marginBottom: 10 }}>
                    最近批准：{(selectedBundle.updated_story as { characters: Array<{ last_approved_chapter: number }> }).characters[0].last_approved_chapter}
                  </p>
                  <p className="hint" style={{ marginBottom: 10 }}>
                    引入来源：{(selectedBundle.updated_story as { characters: Array<{ introduced_by: string }> }).characters[0].introduced_by || "系统"}
                  </p>
                  {(() => {
                    const lead = (selectedBundle.updated_story as { characters: Array<{ relationships?: Record<string, { target: string; trust: number; tension: number; bond: string }> }> }).characters[0];
                    const relations = Object.values(lead.relationships ?? {});
                    if (!relations.length) return null;
                    return (
                      <>
                        <p className="hint" style={{ marginBottom: 10 }}>
                          关系：{relations[0].target}（{relations[0].bond || "未命名"}）
                        </p>
                        <p className="hint" style={{ marginBottom: 10 }}>
                          信任/紧张：{relations[0].trust} / {relations[0].tension}
                        </p>
                      </>
                    );
                  })()}
                </>
              ) : null}
              <pre style={{ margin: 0, overflowX: "auto" }}>
                {JSON.stringify(
                  {
                    character_cards: selectedBundle.character_cards ?? [],
                    foreshadowing: selectedBundle.foreshadowing ?? [],
                    chapter_summary: selectedBundle.chapter_summary ?? null,
                    quality_report: selectedBundle.quality_report ?? null,
                    updated_story: selectedBundle.updated_story ?? null,
                  },
                  null,
                  2,
                )}
              </pre>
            </div>
          ) : (
            <p className="hint">还没有状态。先生成一章开始吧。</p>
          )}
        </div>
      </section>

      <section className="panel panel-controls" aria-label="Controls Panel">
        <header className="panel__header">控制区</header>
        <div className="panel__body">
          <button className="btn" type="button" onClick={onGenerateNextChapter} disabled={isGenerating}>
            生成下一章
          </button>
          <button className="btn btn--ghost" type="button" onClick={onRollbackChapter} disabled={isGenerating || !storyInitialized}>
            回滚章节
          </button>
          {story ? (
            <div style={{ marginTop: 14 }}>
              <p className="hint" style={{ marginBottom: 8 }}>
                当前故事管理
              </p>
              <p className="hint" style={{ marginBottom: 8 }}>
                当前保留的是分支清理；重命名暂时只走 API。
              </p>
              <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                {story.parent_story_id ? (
                  <button className="btn btn--ghost" type="button" onClick={onDeleteActiveStory} disabled={isGenerating}>
                    删除当前故事
                  </button>
                ) : null}
              </div>
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
                    onClick={() => onBranchFromChapter(entry.chapter_number)}
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
                故事树
              </p>
              <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
                <button
                  className="btn btn--ghost"
                  type="button"
                  onClick={() => setBranchFocus("active")}
                  disabled={isGenerating || branchFocus === "active"}
                >
                  聚焦当前分支
                </button>
                <button
                  className="btn btn--ghost"
                  type="button"
                  onClick={() => setBranchFocus("all")}
                  disabled={isGenerating || branchFocus === "all"}
                >
                  显示全部分支
                </button>
              </div>
              {visibleStorySummaries().map((entry) => (
                <div
                  key={entry.story_id}
                  className={`story-tree__item${entry.story_id === activeStoryId ? " story-tree__item--active" : ""}`}
                  style={{ paddingLeft: `${storyDepth(entry) * 18}px` }}
                >
                  <p className="hint story-tree__label" style={{ marginBottom: 6 }}>
                    {entry.parent_story_id ? `分支故事：${entry.story_id}` : `主线故事：${entry.story_id}`}
                  </p>
                  <p className="hint" style={{ marginBottom: 6 }}>
                    {entry.parent_story_id
                      ? `来自 ${entry.parent_story_id}，第 ${entry.branched_from_chapter} 章`
                      : "主时间线"}
                  </p>
                  <p className="hint" style={{ marginBottom: 6 }}>
                    章节列表：{storyCatalog[entry.story_id]?.history.map((chapter) => chapter.chapter_number).join(", ") || "无"}
                  </p>
                  <p className="hint" style={{ marginBottom: 6 }}>
                    最新摘要：{latestSummary(entry.story_id)}
                  </p>
                  <p className="hint" style={{ marginBottom: 6 }}>
                    最新未解线索：{latestThread(entry.story_id)}
                  </p>
                  <p className="hint" style={{ marginBottom: 6 }}>
                    最新伏笔：{latestForeshadowing(entry.story_id)}
                  </p>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <button
                      className="btn btn--ghost"
                      type="button"
                      onClick={() => onOpenStory(entry.story_id)}
                      disabled={isGenerating || entry.story_id === activeStoryId}
                    >
                      打开故事：{entry.story_id}
                    </button>
                    {(storyCatalog[entry.story_id]?.history ?? []).map((chapter) => (
                      <div
                        key={`${entry.story_id}-chapter-${chapter.chapter_number}`}
                        className={`story-tree__chapter-card${entry.story_id === activeStoryId && chapter.chapter_number === selectedChapter ? " story-tree__chapter-card--active" : ""}`}
                      >
                        <p className="hint" style={{ marginBottom: 6 }}>
                          章节卡：{entry.story_id} 第 {chapter.chapter_number} 章 - {chapterTitle(chapter.chapter_number)}
                        </p>
                        <p className="hint" style={{ marginBottom: 6 }}>
                          标签：{entry.story_id} 第 {chapter.chapter_number} 章 - {chapterTags(chapter.chapter_number)}
                        </p>
                        <button
                          className={`btn btn--ghost${entry.story_id === activeStoryId && chapter.chapter_number === selectedChapter ? " story-tree__chapter-btn--active" : ""}`}
                          type="button"
                          onClick={() => void onOpenStoryChapter(entry.story_id, chapter.chapter_number)}
                          disabled={isGenerating}
                        >
                          跳转到 {entry.story_id} 第 {chapter.chapter_number} 章
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : null}
          {error ? <p className="hint" style={{ marginTop: 10 }}>{error}</p> : null}
          <p className="hint" style={{ marginTop: 10 }}>
            注：如果后端没有启动，生成会使用本地确定性模拟。
          </p>
        </div>
      </section>
    </main>
  );
}
