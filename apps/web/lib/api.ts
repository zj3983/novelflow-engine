export type CreateStoryRequest = {
  story_id: string;
  outline: string;
  genre: string;
  style: string;
  characters?: Array<{
    name: string;
    role: string;
    goals: string[];
    frozen: boolean;
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
  parent_story_id?: string | null;
  branched_from_chapter?: number | null;
  characters: Array<{
    name: string;
    role: string;
    goals: string[];
    frozen: boolean;
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

function apiBase() {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
}

type MockStory = {
  story_id: string;
  outline: string;
  genre: string;
  style: string;
  current_chapter: number;
  characters: StoryResponse["characters"];
  history: ChapterBundle[];
  initial_story: StoryResponse;
  parent_story_id?: string | null;
  branched_from_chapter?: number | null;
};

const mockStore = new Map<string, MockStory>();

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
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
  const initialStory: StoryResponse = {
    story_id: payload.story_id,
    outline: payload.outline,
    genre: payload.genre,
    style: payload.style,
    current_chapter: 0,
    parent_story_id: null,
    branched_from_chapter: null,
    characters: clone(payload.characters ?? []),
    history: [],
  };

  const story: MockStory = {
    story_id: payload.story_id,
    outline: payload.outline,
    genre: payload.genre,
    style: payload.style,
    current_chapter: 0,
    characters: clone(payload.characters ?? []),
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
  story.characters = story.characters.map((character, index) => {
    if (index !== 0 || character.frozen || !character.relationships) {
      return character;
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
    } else {
      story.current_chapter = story.initial_story.current_chapter;
      story.characters = clone(story.initial_story.characters);
    }
  }

  return {
    story_id: story.story_id,
    outline: story.outline,
    genre: story.genre,
    style: story.style,
    current_chapter: story.current_chapter,
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

async function tryFetchJson(url: string, init: RequestInit): Promise<any> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 1500);

  try {
    const resp = await fetch(url, { ...init, signal: controller.signal });
    if (!resp.ok) {
      throw new Error(`${url} failed: ${resp.status}`);
    }
    return resp.json();
  } finally {
    clearTimeout(timeout);
  }
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
      character.name === characterName ? { ...character, frozen: true } : character,
    );
    return mockFetchStory(storyId);
  }
}
