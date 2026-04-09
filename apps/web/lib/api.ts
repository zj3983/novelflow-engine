export type CreateStoryRequest = {
  story_id: string;
  outline: string;
  genre: string;
  style: string;
};

export type ChapterBundle = {
  chapter_number: number;
  body: string;
  character_cards?: unknown[];
  foreshadowing?: unknown[];
  next_outline?: string;
  updated_story?: unknown;
};

export type StoryResponse = {
  story_id: string;
  outline: string;
  genre: string;
  style: string;
  current_chapter: number;
  history: ChapterBundle[];
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
  history: ChapterBundle[];
};

const mockStore = new Map<string, MockStory>();

function mockCreateStory(payload: CreateStoryRequest): StoryResponse {
  const story: MockStory = {
    story_id: payload.story_id,
    outline: payload.outline,
    genre: payload.genre,
    style: payload.style,
    current_chapter: 0,
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

  const bundle: ChapterBundle = {
    chapter_number: chapterNumber,
    body: `Chapter ${chapterNumber} body.`,
    character_cards: [],
    foreshadowing: [{ text: "A hidden letter appears." }],
    next_outline: `Continue from chapter ${chapterNumber}.`,
    updated_story: {
      story_id: story.story_id,
      outline: story.outline,
      genre: story.genre,
      style: story.style,
      current_chapter: story.current_chapter,
      characters: [],
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
