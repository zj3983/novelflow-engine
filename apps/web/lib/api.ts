export type CreateStoryRequest = {
  story_id: string;
  outline: string;
  genre: string;
  style: string;
};

function apiBase() {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
}

export async function createStory(payload: CreateStoryRequest) {
  const resp = await fetch(`${apiBase()}/stories`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!resp.ok) throw new Error(`createStory failed: ${resp.status}`);
  return resp.json();
}

export async function generateNextChapter(storyId: string) {
  const resp = await fetch(`${apiBase()}/stories/${encodeURIComponent(storyId)}/generate`, {
    method: "POST",
  });
  if (!resp.ok) throw new Error(`generateNextChapter failed: ${resp.status}`);
  return resp.json();
}

export async function rollbackStory(storyId: string) {
  const resp = await fetch(`${apiBase()}/stories/${encodeURIComponent(storyId)}/rollback`, {
    method: "POST",
  });
  if (!resp.ok) throw new Error(`rollbackStory failed: ${resp.status}`);
  return resp.json();
}

