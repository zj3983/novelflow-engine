"use client";

import { useRef, useState } from "react";

import { ChapterBundleView } from "../components/ChapterBundleView";
import { StorySidebar, type StoryDraft } from "../components/StorySidebar";
import {
  branchStory,
  createStory,
  deleteStory,
  fetchStory,
  generateNextChapter,
  listStories,
  rollbackStory,
  type ChapterBundle,
  type StoryCharacter,
  type StoryResponse,
  type StorySummary,
} from "../lib/api";

const DEFAULT_STORY = {
  story_id: "s-001",
  genre: "fantasy",
  style: "noir",
} as const;

export default function Page() {
  const [draft, setDraft] = useState<StoryDraft>({
    outline: "A detective prince uncovers palace crimes.",
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
  const [story, setStory] = useState<StoryResponse | null>(null);
  const [storyCatalog, setStoryCatalog] = useState<Record<string, StoryResponse>>({});
  const [activeStoryId, setActiveStoryId] = useState(DEFAULT_STORY.story_id);
  const [selectedChapter, setSelectedChapter] = useState<number | null>(null);
  const [storySummaries, setStorySummaries] = useState<StorySummary[]>([]);
  const [branchFocus, setBranchFocus] = useState<"all" | "active">("all");
  const [isGenerating, setIsGenerating] = useState(false);
  const [storyInitialized, setStoryInitialized] = useState(false);
  const [activeDraftKey, setActiveDraftKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const draftRef = useRef(draft);

  const currentDraftKey = JSON.stringify(draftRef.current);

  function updateDraft(next: StoryDraft) {
    draftRef.current = next;
    setDraft(next);
  }

  function buildCharacters(): StoryCharacter[] {
    return draftRef.current.characters
      .filter((character) => character.name.trim() && character.goal.trim())
      .map((character, index) => ({
        name: character.name.trim(),
        role: index === 0 ? "protagonist" : "supporting",
        goals: [character.goal.trim()],
        frozen: character.frozen,
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
    let cursor = entry.parent_story_id ? storySummaries.find((item) => item.story_id === entry.parent_story_id) : undefined;
    while (cursor) {
      depth += 1;
      cursor = cursor.parent_story_id ? storySummaries.find((item) => item.story_id === cursor.parent_story_id) : undefined;
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
      return "Opening Move";
    }
    if (chapterNumber === 2) {
      return "Pressure Rises";
    }
    return `Turning Point ${chapterNumber}`;
  }

  function chapterTags(chapterNumber: number): string {
    if (chapterNumber === 1) {
      return "history beat, branch navigation";
    }
    if (chapterNumber === 2) {
      return "escalation beat, continuity";
    }
    return "story beat, continuity";
  }

  function visibleStorySummaries(): StorySummary[] {
    if (branchFocus === "all" || !story) {
      return storySummaries;
    }

    const allowed = new Set<string>([activeStoryId]);
    let cursor = story.parent_story_id
      ? storySummaries.find((item) => item.story_id === story.parent_story_id)
      : undefined;
    while (cursor) {
      allowed.add(cursor.story_id);
      cursor = cursor.parent_story_id
        ? storySummaries.find((item) => item.story_id === cursor.parent_story_id)
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
        outline: draftRef.current.outline,
        characters,
      });
      setStory(createdStory);
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
      setSelectedChapter(nextBundle.chapter_number);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "generate failed");
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
      setSelectedChapter(syncedStory.history.length ? syncedStory.history[syncedStory.history.length - 1].chapter_number : null);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "rollback failed");
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
      setActiveStoryId(branch.story_id);
      setSelectedChapter(branch.history.length ? branch.history[branch.history.length - 1].chapter_number : null);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "branch failed");
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
      setActiveStoryId(storyId);
      setSelectedChapter(openedStory.history.length ? openedStory.history[openedStory.history.length - 1].chapter_number : null);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "open story failed");
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
      setActiveStoryId(storyId);
      setSelectedChapter(chapterNumber);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "open chapter failed");
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
      setActiveStoryId(parentStory.story_id);
      setSelectedChapter(parentStory.history.length ? parentStory.history[parentStory.history.length - 1].chapter_number : null);
      await refreshStorySummaries();
    } catch (e) {
      setError(e instanceof Error ? e.message : "delete story failed");
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
        <header className="panel__header">Outline</header>
        <div className="panel__body">
          <StorySidebar draft={draft} onChange={updateDraft} />
        </div>
      </section>

      <section className="panel panel-draft" aria-label="Chapter Draft Panel">
        <header className="panel__header">Chapter Draft</header>
        <div className="panel__body">
          {selectedBundle ? (
            <ChapterBundleView bundle={selectedBundle} />
          ) : (
            <p className="hint">No chapter generated yet.</p>
          )}
        </div>
      </section>

      <section className="panel panel-state" aria-label="Character State Panel">
        <header className="panel__header">Character State</header>
        <div className="panel__body">
          {selectedBundle ? (
            <div>
              <p className="hint" style={{ marginBottom: 10 }}>
                Story: {story?.story_id}
              </p>
              <p className="hint" style={{ marginBottom: 10 }}>
                Current chapter: {story?.current_chapter ?? selectedBundle.chapter_number}
              </p>
              <p className="hint" style={{ marginBottom: 10 }}>
                Viewing chapter: {selectedBundle.chapter_number}
              </p>
              {story?.story_id !== DEFAULT_STORY.story_id ? (
                <p className="hint" style={{ marginBottom: 10 }}>
                  Branch story: {story?.story_id}
                </p>
              ) : null}
              {story?.parent_story_id ? (
                <p className="hint" style={{ marginBottom: 10 }}>
                  Parent story: {story.parent_story_id}
                </p>
              ) : null}
              {story?.branched_from_chapter != null ? (
                <p className="hint" style={{ marginBottom: 10 }}>
                  Branched from chapter: {story.branched_from_chapter}
                </p>
              ) : null}
              <p className="hint" style={{ marginBottom: 10 }}>
                Continuity: {selectedBundle.quality_report?.ok ? "OK" : "Needs review"}
              </p>
              <p className="hint" style={{ marginBottom: 10 }}>
                Next beat: {selectedBundle.next_outline ?? "Not planned yet."}
              </p>
              {selectedBundle.chapter_summary?.facts?.length ? (
                <p className="hint" style={{ marginBottom: 10 }}>
                  Latest fact: {selectedBundle.chapter_summary.facts[0]}
                </p>
              ) : null}
              {selectedBundle.updated_story &&
              (selectedBundle.updated_story as { characters?: Array<{ name: string; frozen: boolean }> }).characters?.length ? (
                <>
                  <p className="hint" style={{ marginBottom: 10 }}>
                    Cast: {(selectedBundle.updated_story as { characters: Array<{ name: string }> }).characters.map((character) => character.name).join(", ")}
                  </p>
                  <p className="hint" style={{ marginBottom: 10 }}>
                    Lead: {(selectedBundle.updated_story as { characters: Array<{ name: string; frozen: boolean }> }).characters[0].name}
                  </p>
                  <p className="hint" style={{ marginBottom: 10 }}>
                    Frozen: {(selectedBundle.updated_story as { characters: Array<{ name: string; frozen: boolean }> }).characters[0].frozen ? "Yes" : "No"}
                  </p>
                  {(() => {
                    const lead = (selectedBundle.updated_story as { characters: Array<{ relationships?: Record<string, { target: string; trust: number; tension: number; bond: string }> }> }).characters[0];
                    const relations = Object.values(lead.relationships ?? {});
                    if (!relations.length) return null;
                    return (
                      <>
                        <p className="hint" style={{ marginBottom: 10 }}>
                          Relationship: {relations[0].target} ({relations[0].bond || "unlabeled"})
                        </p>
                        <p className="hint" style={{ marginBottom: 10 }}>
                          Trust/Tension: {relations[0].trust} / {relations[0].tension}
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
            <p className="hint">No state yet. Generate a chapter to begin.</p>
          )}
        </div>
      </section>

      <section className="panel panel-controls" aria-label="Controls Panel">
        <header className="panel__header">Controls</header>
        <div className="panel__body">
          <button className="btn" type="button" onClick={onGenerateNextChapter} disabled={isGenerating}>
            Generate Next Chapter
          </button>
          <button className="btn btn--ghost" type="button" onClick={onRollbackChapter} disabled={isGenerating || !storyInitialized}>
            Rollback Chapter
          </button>
          {story ? (
            <div style={{ marginTop: 14 }}>
              <p className="hint" style={{ marginBottom: 8 }}>
                Active Story Admin
              </p>
              <p className="hint" style={{ marginBottom: 8 }}>
                Active branch cleanup stays in the UI; story renaming is available through the API for now.
              </p>
              <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                {story.parent_story_id ? (
                  <button className="btn btn--ghost" type="button" onClick={onDeleteActiveStory} disabled={isGenerating}>
                    Delete Active Story
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}
          {story?.history.length ? (
            <div style={{ marginTop: 14 }}>
              <p className="hint" style={{ marginBottom: 8 }}>
                Chapter History
              </p>
              {story.history.map((entry) => (
                <div key={entry.chapter_number} style={{ display: "flex", gap: 8, marginBottom: 8, flexWrap: "wrap" }}>
                  <button
                    className="btn btn--ghost"
                    type="button"
                    onClick={() => setSelectedChapter(entry.chapter_number)}
                    disabled={isGenerating}
                  >
                    View Chapter {entry.chapter_number}
                  </button>
                  <button
                    className="btn btn--ghost"
                    type="button"
                    onClick={() => onBranchFromChapter(entry.chapter_number)}
                    disabled={isGenerating}
                  >
                    Branch from Chapter {entry.chapter_number}
                  </button>
                </div>
              ))}
            </div>
          ) : null}
          {storySummaries.length ? (
            <div style={{ marginTop: 14 }}>
              <p className="hint" style={{ marginBottom: 8 }}>
                Story Tree
              </p>
              <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
                <button
                  className="btn btn--ghost"
                  type="button"
                  onClick={() => setBranchFocus("active")}
                  disabled={isGenerating || branchFocus === "active"}
                >
                  Focus Active Branch
                </button>
                <button
                  className="btn btn--ghost"
                  type="button"
                  onClick={() => setBranchFocus("all")}
                  disabled={isGenerating || branchFocus === "all"}
                >
                  Show All Branches
                </button>
              </div>
              {visibleStorySummaries().map((entry) => (
                <div
                  key={entry.story_id}
                  className={`story-tree__item${entry.story_id === activeStoryId ? " story-tree__item--active" : ""}`}
                  style={{ paddingLeft: `${storyDepth(entry) * 18}px` }}
                >
                  <p className="hint story-tree__label" style={{ marginBottom: 6 }}>
                    {entry.parent_story_id ? `Story Branch: ${entry.story_id}` : `Story Root: ${entry.story_id}`}
                  </p>
                  <p className="hint" style={{ marginBottom: 6 }}>
                    {entry.parent_story_id
                      ? `From ${entry.parent_story_id} @ Chapter ${entry.branched_from_chapter}`
                      : "Primary timeline"}
                  </p>
                  <p className="hint" style={{ marginBottom: 6 }}>
                    Chapters in {entry.story_id}: {storyCatalog[entry.story_id]?.history.map((chapter) => chapter.chapter_number).join(", ") || "None"}
                  </p>
                  <p className="hint" style={{ marginBottom: 6 }}>
                    Latest summary in {entry.story_id}: {latestSummary(entry.story_id)}
                  </p>
                  <p className="hint" style={{ marginBottom: 6 }}>
                    Latest thread in {entry.story_id}: {latestThread(entry.story_id)}
                  </p>
                  <p className="hint" style={{ marginBottom: 6 }}>
                    Latest foreshadowing in {entry.story_id}: {latestForeshadowing(entry.story_id)}
                  </p>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <button
                      className="btn btn--ghost"
                      type="button"
                      onClick={() => onOpenStory(entry.story_id)}
                      disabled={isGenerating || entry.story_id === activeStoryId}
                    >
                      Open Story: {entry.story_id}
                    </button>
                    {(storyCatalog[entry.story_id]?.history ?? []).map((chapter) => (
                      <div
                        key={`${entry.story_id}-chapter-${chapter.chapter_number}`}
                        className={`story-tree__chapter-card${entry.story_id === activeStoryId && chapter.chapter_number === selectedChapter ? " story-tree__chapter-card--active" : ""}`}
                      >
                        <p className="hint" style={{ marginBottom: 6 }}>
                          Chapter Card in {entry.story_id}: Chapter {chapter.chapter_number} - {chapterTitle(chapter.chapter_number)}
                        </p>
                        <p className="hint" style={{ marginBottom: 6 }}>
                          Tags in {entry.story_id} Chapter {chapter.chapter_number}: {chapterTags(chapter.chapter_number)}
                        </p>
                        <button
                          className={`btn btn--ghost${entry.story_id === activeStoryId && chapter.chapter_number === selectedChapter ? " story-tree__chapter-btn--active" : ""}`}
                          type="button"
                          onClick={() => void onOpenStoryChapter(entry.story_id, chapter.chapter_number)}
                          disabled={isGenerating}
                        >
                          Jump to {entry.story_id} Chapter {chapter.chapter_number}
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
            Note: If the backend is not running, generation uses a local deterministic mock.
          </p>
        </div>
      </section>
    </main>
  );
}
