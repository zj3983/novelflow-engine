"use client";

import { useState } from "react";

import { ChapterBundleView } from "../components/ChapterBundleView";
import { StorySidebar, type StoryDraft } from "../components/StorySidebar";
import {
  createStory,
  freezeCharacter,
  generateNextChapter,
  rollbackStory,
  type ChapterBundle,
  type StoryCharacter,
  type StoryResponse,
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
  const [bundle, setBundle] = useState<ChapterBundle | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [storyInitialized, setStoryInitialized] = useState(false);
  const [activeDraftKey, setActiveDraftKey] = useState("");
  const [error, setError] = useState<string | null>(null);

  const currentDraftKey = JSON.stringify(draft);

  function buildCharacters(): StoryCharacter[] {
    return draft.characters
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

  async function ensureStoryReady() {
    const characters = buildCharacters();
    const mustReset = !storyInitialized || activeDraftKey !== currentDraftKey;

    if (mustReset) {
      await createStory({
        ...DEFAULT_STORY,
        outline: draft.outline,
        characters,
      });
      for (const character of characters) {
        if (character.frozen) {
          await freezeCharacter(DEFAULT_STORY.story_id, character.name);
        }
      }
      setStoryInitialized(true);
      setActiveDraftKey(currentDraftKey);
    }
  }

  function syncBundleFromStory(story: StoryResponse) {
    const history = story.history ?? [];
    setBundle(history.length ? history[history.length - 1] : null);
  }

  async function onGenerateNextChapter() {
    setError(null);
    setIsGenerating(true);
    try {
      await ensureStoryReady();
      const nextBundle = await generateNextChapter(DEFAULT_STORY.story_id);
      setBundle(nextBundle);
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
      const story = await rollbackStory(DEFAULT_STORY.story_id);
      syncBundleFromStory(story);
    } catch (e) {
      setError(e instanceof Error ? e.message : "rollback failed");
    } finally {
      setIsGenerating(false);
    }
  }

  return (
    <main className="workbench">
      <section className="panel panel-outline" aria-label="Outline Panel">
        <header className="panel__header">Outline</header>
        <div className="panel__body">
          <StorySidebar draft={draft} onChange={setDraft} />
        </div>
      </section>

      <section className="panel panel-draft" aria-label="Chapter Draft Panel">
        <header className="panel__header">Chapter Draft</header>
        <div className="panel__body">
          {bundle ? (
            <ChapterBundleView bundle={bundle} />
          ) : (
            <p className="hint">No chapter generated yet.</p>
          )}
        </div>
      </section>

      <section className="panel panel-state" aria-label="Character State Panel">
        <header className="panel__header">Character State</header>
        <div className="panel__body">
          {bundle ? (
            <div>
              <p className="hint" style={{ marginBottom: 10 }}>
                Current chapter: {bundle.chapter_number}
              </p>
              <p className="hint" style={{ marginBottom: 10 }}>
                Continuity: {bundle.quality_report?.ok ? "OK" : "Needs review"}
              </p>
              <p className="hint" style={{ marginBottom: 10 }}>
                Next beat: {bundle.next_outline ?? "Not planned yet."}
              </p>
              {bundle.chapter_summary?.facts?.length ? (
                <p className="hint" style={{ marginBottom: 10 }}>
                  Latest fact: {bundle.chapter_summary.facts[0]}
                </p>
              ) : null}
              {bundle.updated_story && (bundle.updated_story as { characters?: Array<{ name: string; frozen: boolean }> }).characters?.length ? (
                <>
                  <p className="hint" style={{ marginBottom: 10 }}>
                    Cast: {(bundle.updated_story as { characters: Array<{ name: string }> }).characters.map((character) => character.name).join(", ")}
                  </p>
                  <p className="hint" style={{ marginBottom: 10 }}>
                    Lead: {(bundle.updated_story as { characters: Array<{ name: string; frozen: boolean }> }).characters[0].name}
                  </p>
                  <p className="hint" style={{ marginBottom: 10 }}>
                    Frozen: {(bundle.updated_story as { characters: Array<{ name: string; frozen: boolean }> }).characters[0].frozen ? "Yes" : "No"}
                  </p>
                  {(() => {
                    const lead = (bundle.updated_story as { characters: Array<{ relationships?: Record<string, { target: string; trust: number; tension: number; bond: string }> }> }).characters[0];
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
                    character_cards: bundle.character_cards ?? [],
                    foreshadowing: bundle.foreshadowing ?? [],
                    chapter_summary: bundle.chapter_summary ?? null,
                    quality_report: bundle.quality_report ?? null,
                    updated_story: bundle.updated_story ?? null,
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
          {error ? <p className="hint" style={{ marginTop: 10 }}>{error}</p> : null}
          <p className="hint" style={{ marginTop: 10 }}>
            Note: If the backend is not running, generation uses a local deterministic mock.
          </p>
        </div>
      </section>
    </main>
  );
}
