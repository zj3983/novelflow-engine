export type CreateStoryRequest = {
  story_id: string;
  outline: string;
  genre: string;
  style: string;
  agent_settings?: {
    mode: "Rule-based" | "LLM-assisted";
    global_model: string;
    character_model: string;
    director_model: string;
    writer_model: string;
    memory_model: string;
    temperature: string | number;
    new_character_policy: "Director review" | "Auto-approve named candidates" | "Manual review";
  };
  characters?: Array<{
    name: string;
    role: string;
    goals: string[];
    frozen: boolean;
    lifecycle_state?: "proposed" | "active" | "rejected" | "frozen";
    last_proposed_chapter?: number;
    last_approved_chapter?: number;
    introduced_by?: string;
    relationships?: Record<
      string,
      {
        target: string;
        trust: number;
        tension: number;
        bond: string;
      }
    >;
  }>;
};

export type AgentSettings = NonNullable<CreateStoryRequest["agent_settings"]>;

export type RuntimeEndpoint = {
  api_key: string;
  base_url: string;
};

export type AgentRuntimeName = "character" | "director" | "writer" | "memory";

export type RuntimeSettings = {
  global: RuntimeEndpoint;
  agents: Record<AgentRuntimeName, RuntimeEndpoint>;
};

export type RuntimeConnectionTarget = "global" | AgentRuntimeName;

export type RuntimeConnectionResult = {
  ok: boolean;
  agent_name: RuntimeConnectionTarget;
  message: string;
};

export type AgentRuntimeEntry = {
  mode: "Rule-based" | "LLM-assisted";
  source: "idle" | "rule-based" | "llm" | "fallback";
  fallback_reason: string;
  last_run_chapter: number;
};

export type AgentRuntimeState = {
  character_agent: AgentRuntimeEntry;
  director_agent: AgentRuntimeEntry;
  writer_agent: AgentRuntimeEntry;
  memory_agent: AgentRuntimeEntry;
  outline_agent: AgentRuntimeEntry;
  recent_events: string[];
};

// ── Outline types ────────────────────────────────────────────────

export type ChapterOutline = {
  chapter_number: number;
  chapter_title: string;
  summary: string;
  key_characters: string[];
  primary_conflict: string;
  cadence: "urgent" | "measured" | "breathing";
  word_count_estimate: number;
  arc_phase: string;
};

export type NovelOutlineResponse = {
  story_id: string;
  genre: string;
  style: string;
  total_chapters: number;
  chapters: ChapterOutline[];
  overall_arc: string;
  act_breaks: Array<{ act: number; start: number; end: number; theme: string }>;
  notes: string;
  created_at: string;
  updated_at: string;
  saved: boolean;
};

// ── World Bible types ─────────────────────────────────────────────

export type PowerSystem = {
  name: string;
  description: string;
  levels: string[];
  rules: string[];
  limitations: string[];
};

export type WorldLocation = {
  name: string;
  description: string;
  type: string;
  importance: number;
  connections: string[];
};

export type Faction = {
  name: string;
  description: string;
  type: string;
  goals: string[];
  allies: string[];
  enemies: string[];
  notable_members: string[];
};

export type WorldBibleResponse = {
  story_id: string;
  world_name: string;
  overview: string;
  power_system: PowerSystem;
  locations: WorldLocation[];
  factions: Faction[];
  world_facts: string[];
  timeline_events: Array<{ chapter: number; event: string }>;
  cultural_notes: string[];
  glossary: Record<string, string>;
  updated_at: string;
};

export type WorldBibleRequest = {
  world_name?: string;
  overview?: string;
  power_system?: Partial<PowerSystem>;
  locations?: Partial<WorldLocation>[];
  factions?: Partial<Faction>[];
  world_facts?: string[];
  timeline_events?: Array<{ chapter: number; event: string }>;
  cultural_notes?: string[];
  glossary?: Record<string, string>;
};

// ── Novel Status types ────────────────────────────────────────────

export type NovelStatusType = "draft" | "outlining" | "writing" | "reviewing" | "completed" | "paused";

export type NovelStatusResponse = {
  story_id: string;
  status: NovelStatusType;
  total_chapters_planned: number;
  total_chapters_written: number;
  total_word_count: number;
  last_written_chapter: number;
  last_written_at: string;
  created_at: string;
  updated_at: string;
};

export type ChapterBundle = {
  chapter_number: number;
  body: string;
  character_cards?: unknown[];
  foreshadowing?: unknown[];
  next_outline?: string;
  chapter_summary?: {
    chapter_number: number;
    summary: string;
    facts: string[];
    unresolved_threads: string[];
  };
  quality_report?: {
    ok: boolean;
    issues: string[];
  };
  updated_story?: unknown;
};

export type StoryResponse = {
  story_id: string;
  outline: string;
  genre: string;
  style: string;
  current_chapter: number;
  agent_settings: AgentSettings;
  agent_runtime: AgentRuntimeState;
  parent_story_id?: string | null;
  branched_from_chapter?: number | null;
  characters: Array<{
    name: string;
    role: string;
    goals: string[];
    frozen: boolean;
    lifecycle_state: "proposed" | "active" | "rejected" | "frozen";
    last_proposed_chapter: number;
    last_approved_chapter: number;
    introduced_by: string;
    relationships?: Record<
      string,
      {
        target: string;
        trust: number;
        tension: number;
        bond: string;
      }
    >;
  }>;
  history: ChapterBundle[];
};

export type StorySummary = {
  story_id: string;
  current_chapter: number;
  parent_story_id?: string | null;
  branched_from_chapter?: number | null;
};

export type DeleteStoryResponse = {
  deleted: boolean;
  story_id: string;
};

export type StoryCharacter = StoryResponse["characters"][number];

export type BookImportScanRequest = {
  source_path: string;
};

export type BookImportScanReport = {
  source_path: string;
  exists: boolean;
  missing_required_files: string[];
  missing_optional_files: string[];
  unusable_required_files: string[];
  empty_files: string[];
  present_files: string[];
  warnings: string[];
  can_bootstrap: boolean;
};

export type BookImportBootstrapRequest = {
  source_path: string;
};

export type BookImportBootstrapResponse = {
  report: BookImportScanReport;
  draft: {
    source_path: string;
    outline: string;
    summary?: string;
    characters: string[];
  };
};

export type BookLibraryItem = {
  item_id: string;
  title: string;
  kind: string;
  filename: string;
  path: string;
  preview: string;
  content: string;
  chapter_number?: number | null;
  parsed_characters?: string[];
};

export type BookLibrarySection = {
  section_id: string;
  title: string;
  items: BookLibraryItem[];
};

export type BookLibraryCatalogResponse = {
  source_path: string;
  exists: boolean;
  can_bootstrap: boolean;
  sections: BookLibrarySection[];
};

function apiBase() {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
}

type MockStory = {
  story_id: string;
  outline: string;
  genre: string;
  style: string;
  current_chapter: number;
  agent_settings: AgentSettings;
  agent_runtime: AgentRuntimeState;
  characters: StoryResponse["characters"];
  history: ChapterBundle[];
  initial_story: StoryResponse;
  parent_story_id?: string | null;
  branched_from_chapter?: number | null;
};

const mockStore = new Map<string, MockStory>();
let mockRuntimeSettings: RuntimeSettings = defaultRuntimeSettings();
const runtimeSettingsStorageKey = "novel-autogrowth-engine.runtime-settings";

function runtimeTargetLabel(target: RuntimeConnectionTarget): string {
  return target === "global"
    ? "全局默认"
    : target === "character"
      ? "角色代理"
      : target === "director"
        ? "导演代理"
        : target === "writer"
          ? "写作代理"
          : "记忆代理";
}

function runtimeSourceLabel(source: AgentRuntimeEntry["source"]): string {
  if (source === "llm") {
    return "模型";
  }
  if (source === "rule-based") {
    return "规则";
  }
  if (source === "fallback") {
    return "回退";
  }
  return "空闲";
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function defaultAgentSettings(): AgentSettings {
  return {
    mode: "Rule-based",
    global_model: "gpt-5.4",
    character_model: "gpt-5.4-mini",
    director_model: "gpt-5.4",
    writer_model: "gpt-5.4",
    memory_model: "gpt-5.4",
    temperature: "0.7",
    new_character_policy: "Director review",
  };
}

function defaultRuntimeEndpoint(): RuntimeEndpoint {
  return {
    api_key: "",
    base_url: "https://api.openai.com/v1",
  };
}

function blankRuntimeEndpoint(): RuntimeEndpoint {
  return {
    api_key: "",
    base_url: "",
  };
}

function defaultRuntimeSettings(): RuntimeSettings {
  return {
    global: defaultRuntimeEndpoint(),
    agents: {
      character: blankRuntimeEndpoint(),
      director: blankRuntimeEndpoint(),
      writer: blankRuntimeEndpoint(),
      memory: blankRuntimeEndpoint(),
    },
  };
}

function normalizeAgentSettings(
  settings?: Partial<AgentSettings>,
): AgentSettings {
  return {
    ...defaultAgentSettings(),
    ...(settings ?? {}),
  };
}

function defaultRuntimeEntry(
  mode: AgentSettings["mode"],
  source: AgentRuntimeEntry["source"] = "idle",
  fallbackReason = "",
  lastRunChapter = 0,
): AgentRuntimeEntry {
  return {
    mode,
    source,
    fallback_reason: fallbackReason,
    last_run_chapter: lastRunChapter,
  };
}

function defaultAgentRuntime(mode: AgentSettings["mode"]): AgentRuntimeState {
  return {
    character_agent: defaultRuntimeEntry(mode),
    director_agent: defaultRuntimeEntry(mode),
    writer_agent: defaultRuntimeEntry(mode),
    memory_agent: defaultRuntimeEntry(mode),
    recent_events: [],
  };
}

function updateRuntimeForChapter(
  runtime: AgentRuntimeState,
  mode: AgentSettings["mode"],
  chapterNumber: number,
  source: AgentRuntimeEntry["source"],
  fallbackReason = "",
): AgentRuntimeState {
  const nextRuntime = clone(runtime);
  nextRuntime.character_agent = defaultRuntimeEntry(mode, source, fallbackReason, chapterNumber);
  nextRuntime.director_agent = defaultRuntimeEntry(mode, source, fallbackReason, chapterNumber);
  nextRuntime.writer_agent = defaultRuntimeEntry(mode, source, fallbackReason, chapterNumber);
  nextRuntime.memory_agent = defaultRuntimeEntry(mode, source, fallbackReason, chapterNumber);
  nextRuntime.recent_events = [
    ...nextRuntime.recent_events,
    `角色代理：${runtimeSourceLabel(source)}，第 ${chapterNumber} 章${fallbackReason ? `（${fallbackReason}）` : ""}`,
    `导演代理：${runtimeSourceLabel(source)}，第 ${chapterNumber} 章${fallbackReason ? `（${fallbackReason}）` : ""}`,
    `写作代理：${runtimeSourceLabel(source)}，第 ${chapterNumber} 章${fallbackReason ? `（${fallbackReason}）` : ""}`,
    `记忆代理：${runtimeSourceLabel(source)}，第 ${chapterNumber} 章${fallbackReason ? `（${fallbackReason}）` : ""}`,
  ].slice(-8);
  return nextRuntime;
}

function normalizeRuntimeEndpoint(
  value?: Partial<RuntimeEndpoint>,
  fallbackBaseUrl = "https://api.openai.com/v1",
): RuntimeEndpoint {
  return {
    api_key: value?.api_key ?? "",
    base_url: value?.base_url ?? fallbackBaseUrl,
  };
}

function normalizeRuntimeSettings(value?: Partial<RuntimeSettings> | any): RuntimeSettings {
  const base = defaultRuntimeSettings();
  if (!value) {
    return base;
  }

  if ("api_key" in value || "base_url" in value) {
    const endpoint = normalizeRuntimeEndpoint(value as Partial<RuntimeEndpoint>);
    return {
      global: endpoint,
      agents: base.agents,
    };
  }

  return {
    global: normalizeRuntimeEndpoint(value.global),
    agents: {
      character: normalizeRuntimeEndpoint(value.agents?.character, ""),
      director: normalizeRuntimeEndpoint(value.agents?.director, ""),
      writer: normalizeRuntimeEndpoint(value.agents?.writer, ""),
      memory: normalizeRuntimeEndpoint(value.agents?.memory, ""),
    },
  };
}

function relationshipShift(goals: string[]): { trustDelta: number; tensionDelta: number } {
  const goalText = goals.join(" ").toLowerCase();

  if (/(protect|save|guard|help)/.test(goalText)) {
    return { trustDelta: 0.1, tensionDelta: -0.1 };
  }
  if (/(expose|find|accuse|hunt)/.test(goalText)) {
    return { trustDelta: -0.1, tensionDelta: 0.1 };
  }
  return { trustDelta: 0.05, tensionDelta: 0.05 };
}

function relationshipSentence(story: MockStory): string {
  const lead = story.characters[0];
  const relations = Object.values(lead?.relationships ?? {});
  if (!lead || !relations.length) {
    return "The room offers no certainty, only pressure.";
  }

  const relation = relations[0];
  if (relation.tension >= 0.8) {
    return `Each exchange with ${relation.target} needles the alliance closer to open fracture.`;
  }
  if (relation.trust >= 0.5 && relation.tension <= 0.5) {
    return `${lead.name} works in fragile step with ${relation.target}, trusting the silence between them.`;
  }
  return `${lead.name} studies ${relation.target} carefully, unsure which way the balance will tip.`;
}

function continuitySentence(story: MockStory): string {
  const parts: string[] = [];
  const lastFact = story.history.at(-1)?.chapter_summary?.facts?.[0];
  const foreshadowingText = story.history.at(-1)?.foreshadowing?.[0]
    ? ((story.history.at(-1)?.foreshadowing?.[0] as { text?: string }).text ?? "")
    : "";

  if (lastFact) {
    parts.push(`Carries forward: ${lastFact}`);
  }
  if (foreshadowingText) {
    parts.push(`Foreshadowing lingers: ${foreshadowingText}`);
  }

  return parts.join(" ");
}

function mockCreateStory(payload: CreateStoryRequest): StoryResponse {
  const agentSettings = normalizeAgentSettings(payload.agent_settings);
  const agentRuntime = defaultAgentRuntime(agentSettings.mode);
  const normalizedCharacters = clone(payload.characters ?? []).map((character) => ({
    ...character,
    lifecycle_state: character.lifecycle_state ?? (character.frozen ? "frozen" : "active"),
    last_proposed_chapter: character.last_proposed_chapter ?? 0,
    last_approved_chapter: character.last_approved_chapter ?? 0,
    introduced_by: character.introduced_by ?? "",
  }));

  const initialStory: StoryResponse = {
    story_id: payload.story_id,
    outline: payload.outline,
    genre: payload.genre,
    style: payload.style,
    current_chapter: 0,
    agent_settings: clone(agentSettings),
    agent_runtime: clone(agentRuntime),
    parent_story_id: null,
    branched_from_chapter: null,
    characters: normalizedCharacters,
    history: [],
  };

  const story: MockStory = {
    story_id: payload.story_id,
    outline: payload.outline,
    genre: payload.genre,
    style: payload.style,
    current_chapter: 0,
    agent_settings: clone(agentSettings),
    agent_runtime: clone(agentRuntime),
    characters: clone(normalizedCharacters),
    history: [],
    initial_story: initialStory,
    parent_story_id: null,
    branched_from_chapter: null,
  };
  mockStore.set(payload.story_id, story);
  return clone(initialStory);
}

function mockGenerateNextChapter(storyId: string): ChapterBundle {
  const story = mockStore.get(storyId);
  if (!story) throw new Error("mock: story_not_found");

  const chapterNumber = story.current_chapter + 1;
  story.current_chapter = chapterNumber;
  const source: AgentRuntimeEntry["source"] =
    story.agent_settings.mode === "LLM-assisted" ? "fallback" : "rule-based";
  const fallbackReason =
    story.agent_settings.mode === "LLM-assisted"
      ? "模拟后端使用确定性回退。"
      : "";
  story.agent_runtime = updateRuntimeForChapter(
    story.agent_runtime,
    story.agent_settings.mode,
    chapterNumber,
    source,
    fallbackReason,
  );
  story.characters = story.characters.map((character, index) => {
    if (index !== 0 || character.frozen || !character.relationships) {
      return {
        ...character,
        lifecycle_state: character.frozen ? "frozen" : character.lifecycle_state,
      };
    }

    const nextRelationships = Object.fromEntries(
      Object.entries(character.relationships).map(([key, relationship]) => [
        key,
        {
          ...relationship,
          trust: Math.max(0, Math.min(1, Number((relationship.trust + relationshipShift(character.goals).trustDelta).toFixed(2)))),
          tension: Math.max(0, Math.min(1, Number((relationship.tension + relationshipShift(character.goals).tensionDelta).toFixed(2)))),
        },
      ]),
    );

    return {
      ...character,
      lifecycle_state: character.frozen ? "frozen" : character.lifecycle_state,
      relationships: nextRelationships,
    };
  });

  const bundle: ChapterBundle = {
    chapter_number: chapterNumber,
    body: `Chapter ${chapterNumber} body. ${relationshipSentence(story)} ${continuitySentence(story)} A hidden letter appears.`,
    character_cards: story.characters.map((character) => ({
      name: character.name,
      role: character.role,
      goals: character.goals,
      current_emotion: character.frozen ? "steady" : "alert",
      location: character.frozen ? "held position" : "palace archive",
      relationships: character.relationships ?? {},
    })),
    foreshadowing: [{ text: "A hidden letter appears.", first_chapter: chapterNumber, status: "open" }],
    next_outline: `Chapter ${chapterNumber + 1}: force the lead to act on the newest clue.`,
    chapter_summary: {
      chapter_number: chapterNumber,
      summary: `Chapter ${chapterNumber} body.`,
      facts: [`Chapter ${chapterNumber} confirms the investigation is still unfolding.`],
      unresolved_threads: [`Who will control the truth after chapter ${chapterNumber}?`],
    },
    quality_report: {
      ok: true,
      issues: [],
    },
    updated_story: {
      story_id: story.story_id,
      outline: story.outline,
      genre: story.genre,
      style: story.style,
      current_chapter: story.current_chapter,
      agent_settings: clone(story.agent_settings),
      agent_runtime: clone(story.agent_runtime),
      characters: story.characters,
      timeline: [
        {
          chapter_number: chapterNumber,
          summary: `Chapter ${chapterNumber} pushes the core mystery forward.`,
          impact: "raises pressure on every major player",
        },
      ],
      chapter_summaries: [],
      foreshadowing: [],
    },
  };

  story.history.push(bundle);
  return clone(bundle);
}

function mockRollbackStory(storyId: string): StoryResponse {
  const story = mockStore.get(storyId);
  if (!story) throw new Error("mock: story_not_found");

  if (story.history.length > 0) {
    story.history.pop();
    if (story.history.length > 0) {
      const restored = story.history.at(-1)?.updated_story as StoryResponse;
      story.current_chapter = restored.current_chapter;
      story.characters = clone(restored.characters);
      story.agent_runtime = clone(restored.agent_runtime);
    } else {
      story.current_chapter = story.initial_story.current_chapter;
      story.characters = clone(story.initial_story.characters);
      story.agent_runtime = clone(story.initial_story.agent_runtime);
    }
  }

  return {
    story_id: story.story_id,
    outline: story.outline,
    genre: story.genre,
    style: story.style,
    current_chapter: story.current_chapter,
    agent_settings: clone(story.agent_settings),
    agent_runtime: clone(story.agent_runtime),
    characters: clone(story.characters),
    history: clone(story.history),
    parent_story_id: story.parent_story_id ?? null,
    branched_from_chapter: story.branched_from_chapter ?? null,
  };
}

function mockFetchStory(storyId: string): StoryResponse {
  const story = mockStore.get(storyId);
  if (!story) throw new Error("mock: story_not_found");
  return {
    story_id: story.story_id,
    outline: story.outline,
    genre: story.genre,
    style: story.style,
    current_chapter: story.current_chapter,
    agent_settings: clone(story.agent_settings),
    agent_runtime: clone(story.agent_runtime),
    characters: clone(story.characters),
    history: clone(story.history),
    parent_story_id: story.parent_story_id ?? null,
    branched_from_chapter: story.branched_from_chapter ?? null,
  };
}

function mockBranchStory(storyId: string, newStoryId: string, fromChapter: number): StoryResponse {
  const story = mockStore.get(storyId);
  if (!story) throw new Error("mock: story_not_found");
  if (mockStore.has(newStoryId)) throw new Error("mock: story_exists");
  if (fromChapter < 0 || fromChapter > story.history.length) throw new Error("mock: chapter_not_found");

  const branchHistory = clone(story.history.slice(0, fromChapter));
  const branchState =
    fromChapter === 0
      ? clone(story.initial_story)
      : clone((branchHistory.at(-1)?.updated_story as StoryResponse | undefined) ?? story.initial_story);

  branchState.story_id = newStoryId;
  branchState.history = branchHistory;

  const branchStory: MockStory = {
    story_id: newStoryId,
    outline: story.outline,
    genre: story.genre,
    style: story.style,
    current_chapter: branchState.current_chapter,
    agent_settings: clone(branchState.agent_settings),
    agent_runtime: clone(branchState.agent_runtime),
    characters: clone(branchState.characters),
    history: branchHistory,
    initial_story: {
      ...clone(story.initial_story),
      story_id: newStoryId,
    },
    parent_story_id: storyId,
    branched_from_chapter: fromChapter,
  };

  for (const bundle of branchStory.history) {
    if (bundle.updated_story && typeof bundle.updated_story === "object") {
      (bundle.updated_story as { story_id?: string }).story_id = newStoryId;
    }
  }

  mockStore.set(newStoryId, branchStory);
  return mockFetchStory(newStoryId);
}

function mockRenameStory(storyId: string, newStoryId: string): StoryResponse {
  const story = mockStore.get(storyId);
  if (!story) throw new Error("mock: story_not_found");
  if (mockStore.has(newStoryId)) throw new Error("mock: story_exists");

  mockStore.delete(storyId);
  story.story_id = newStoryId;
  story.initial_story.story_id = newStoryId;
  for (const bundle of story.history) {
    if (bundle.updated_story && typeof bundle.updated_story === "object") {
      (bundle.updated_story as { story_id?: string }).story_id = newStoryId;
    }
  }
  for (const child of mockStore.values()) {
    if (child.parent_story_id === storyId) {
      child.parent_story_id = newStoryId;
    }
  }
  mockStore.set(newStoryId, story);
  return mockFetchStory(newStoryId);
}

function mockDeleteStory(storyId: string): DeleteStoryResponse {
  const story = mockStore.get(storyId);
  if (!story) throw new Error("mock: story_not_found");
  if (!story.parent_story_id) throw new Error("mock: cannot_delete_root");
  if (Array.from(mockStore.values()).some((entry) => entry.parent_story_id === storyId)) {
    throw new Error("mock: story_has_children");
  }
  mockStore.delete(storyId);
  return {
    deleted: true,
    story_id: storyId,
  };
}

function mockFetchRuntimeSettings(): RuntimeSettings {
  if (typeof window !== "undefined") {
    try {
      const stored = window.localStorage.getItem(runtimeSettingsStorageKey);
      if (stored) {
        mockRuntimeSettings = normalizeRuntimeSettings(JSON.parse(stored));
      }
    } catch {
      // Ignore storage errors and fall back to the in-memory copy.
    }
  }

  return clone(mockRuntimeSettings);
}

function mockSaveRuntimeSettings(settings: RuntimeSettings): RuntimeSettings {
  mockRuntimeSettings = normalizeRuntimeSettings(settings);
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(runtimeSettingsStorageKey, JSON.stringify(mockRuntimeSettings));
    } catch {
      // Ignore storage errors and keep the in-memory fallback.
    }
  }
  return clone(mockRuntimeSettings);
}

async function tryFetchJson(url: string, init: RequestInit): Promise<any> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);

  try {
    const resp = await fetch(url, { ...init, signal: controller.signal });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      throw new Error(detail ? `${url} failed: ${resp.status} ${detail}` : `${url} failed: ${resp.status}`);
    }
    return resp.json();
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`${url} failed: request timed out`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export async function fetchRuntimeSettings(): Promise<RuntimeSettings> {
  try {
    const response = await tryFetchJson(`${apiBase()}/runtime-settings`, {
      method: "GET",
    });
    return normalizeRuntimeSettings(response);
  } catch {
    return mockFetchRuntimeSettings();
  }
}

export async function saveRuntimeSettings(settings: RuntimeSettings): Promise<RuntimeSettings> {
  try {
    const response = await tryFetchJson(`${apiBase()}/runtime-settings`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(settings),
    });
    return normalizeRuntimeSettings(response);
  } catch {
    return mockSaveRuntimeSettings(settings);
  }
}

export async function testRuntimeSettingsConnection(
  settings: RuntimeSettings,
  target: RuntimeConnectionTarget,
  modelName?: string,
): Promise<RuntimeConnectionResult> {
  try {
    const response = await tryFetchJson(`${apiBase()}/runtime-settings/test`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        agent_name: target,
        model_name: modelName,
        runtime_settings: settings,
      }),
    });
    return response as RuntimeConnectionResult;
  } catch {
    const endpoint =
      target === "global" ? settings.global : settings.agents[target] ?? defaultRuntimeEndpoint();
    const ok = Boolean(endpoint.api_key && endpoint.base_url);
    return {
      ok,
      agent_name: target,
      message: ok
        ? `${runtimeTargetLabel(target)} 连接正常`
        : `${runtimeTargetLabel(target)} 连接失败：缺少 API 密钥或接口地址`,
    };
  }
}

export async function scanBookImport(sourcePath: string): Promise<BookImportScanReport> {
  return (await tryFetchJson(`${apiBase()}/book-import/scan`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_path: sourcePath } satisfies BookImportScanRequest),
  })) as BookImportScanReport;
}

export async function bootstrapBookImport(sourcePath: string): Promise<BookImportBootstrapResponse> {
  return (await tryFetchJson(`${apiBase()}/book-import/bootstrap`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_path: sourcePath } satisfies BookImportBootstrapRequest),
  })) as BookImportBootstrapResponse;
}

export async function fetchBookLibraryCatalog(sourcePath: string): Promise<BookLibraryCatalogResponse> {
  return (await tryFetchJson(`${apiBase()}/book-import/catalog`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ source_path: sourcePath }),
  })) as BookLibraryCatalogResponse;
}

export async function createStory(payload: CreateStoryRequest): Promise<StoryResponse> {
  try {
    return await tryFetchJson(`${apiBase()}/stories`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    return mockCreateStory(payload);
  }
}

export async function generateNextChapter(storyId: string): Promise<ChapterBundle> {
  try {
    return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/generate`, {
      method: "POST",
    });
  } catch {
    return mockGenerateNextChapter(storyId);
  }
}

export async function rollbackStory(storyId: string): Promise<StoryResponse> {
  try {
    return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/rollback`, {
      method: "POST",
    });
  } catch {
    return mockRollbackStory(storyId);
  }
}

export async function fetchStory(storyId: string): Promise<StoryResponse> {
  try {
    return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}`, {
      method: "GET",
    });
  } catch {
    return mockFetchStory(storyId);
  }
}

function mockListStories(): StorySummary[] {
  return Array.from(mockStore.values()).map((story) => ({
    story_id: story.story_id,
    current_chapter: story.current_chapter,
    parent_story_id: story.parent_story_id ?? null,
    branched_from_chapter: story.branched_from_chapter ?? null,
  }));
}

export async function listStories(): Promise<StorySummary[]> {
  try {
    return await tryFetchJson(`${apiBase()}/stories`, {
      method: "GET",
    });
  } catch {
    return mockListStories();
  }
}

export async function branchStory(storyId: string, newStoryId: string, fromChapter: number): Promise<StoryResponse> {
  try {
    return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/branch`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ new_story_id: newStoryId, from_chapter: fromChapter }),
    });
  } catch {
    return mockBranchStory(storyId, newStoryId, fromChapter);
  }
}

export async function renameStory(storyId: string, newStoryId: string): Promise<StoryResponse> {
  try {
    return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/rename`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ new_story_id: newStoryId }),
    });
  } catch {
    return mockRenameStory(storyId, newStoryId);
  }
}

export async function deleteStory(storyId: string): Promise<DeleteStoryResponse> {
  try {
    return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}`, {
      method: "DELETE",
    });
  } catch {
    return mockDeleteStory(storyId);
  }
}

export async function freezeCharacter(storyId: string, characterName: string): Promise<StoryResponse> {
  try {
    return await tryFetchJson(
      `${apiBase()}/stories/${encodeURIComponent(storyId)}/characters/${encodeURIComponent(characterName)}/freeze`,
      {
        method: "POST",
      },
    );
  } catch {
    const story = mockStore.get(storyId);
    if (!story) throw new Error("mock: story_not_found");
    story.characters = story.characters.map((character) =>
      character.name === characterName
        ? { ...character, frozen: true, lifecycle_state: "frozen" }
        : character,
    );
    return mockFetchStory(storyId);
  }
}

// ── Outline API ────────────────────────────────────────────────

export async function generateOutline(storyId: string, targetChapters: number = 30): Promise<NovelOutlineResponse> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/outline/generate`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ target_chapters: targetChapters }),
  });
}

export async function fetchOutline(storyId: string): Promise<NovelOutlineResponse> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/outline`, {
    method: "GET",
  });
}

export async function updateOutline(storyId: string, payload: {
  chapters: ChapterOutline[];
  overall_arc?: string;
  act_breaks?: Array<{ act: number; start: number; end: number; theme: string }>;
  notes?: string;
}): Promise<NovelOutlineResponse> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/outline`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// ── World Bible API ────────────────────────────────────────────

export async function fetchWorldBible(storyId: string): Promise<WorldBibleResponse> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/world-bible`, {
    method: "GET",
  });
}

export async function updateWorldBible(storyId: string, payload: WorldBibleRequest): Promise<WorldBibleResponse> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/world-bible`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// ── Novel Status API ───────────────────────────────────────────

export async function fetchNovelStatus(storyId: string): Promise<NovelStatusResponse> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/status`, {
    method: "GET",
  });
}

export async function updateNovelStatus(storyId: string, payload: {
  status?: NovelStatusType;
  total_chapters_planned?: number;
}): Promise<NovelStatusResponse> {
  return await tryFetchJson(`${apiBase()}/stories/${encodeURIComponent(storyId)}/status`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}
