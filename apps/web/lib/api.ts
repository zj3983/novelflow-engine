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
};

const mockStore = new Map<string, MockStory>();

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

function mockCreateStory(payload: CreateStoryRequest): StoryResponse {
  const story: MockStory = {
    story_id: payload.story_id,
    outline: payload.outline,
    genre: payload.genre,
    style: payload.style,
    current_chapter: 0,
    characters: payload.characters ?? [],
    history: [],
  };
  mockStore.set(payload.story_id, story);
  return { ...story };
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
    body: `Chapter ${chapterNumber} body.`,
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
  return bundle;
}

function mockRollbackStory(storyId: string): StoryResponse {
  const story = mockStore.get(storyId);
  if (!story) throw new Error("mock: story_not_found");

  if (story.history.length > 0) {
    story.history.pop();
    story.current_chapter = Math.max(0, story.current_chapter - 1);
  }

  return { ...story };
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
    return { ...story };
  }
}
