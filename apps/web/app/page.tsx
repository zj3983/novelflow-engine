"use client";

import { useState } from "react";

import { ChapterBundleView } from "../components/ChapterBundleView";
import { StorySidebar, type StoryDraft } from "../components/StorySidebar";
import { createStory, freezeCharacter, generateNextChapter, type ChapterBundle } from "../lib/api";

const DEFAULT_STORY = {
  story_id: "s-001",
  genre: "fantasy",
  style: "noir",
} as const;

export default function Page() {
  const [draft, setDraft] = useState<StoryDraft>({
    outline: "A detective prince uncovers palace crimes.",
    characterName: "Lin Yue",
    characterGoal: "find the culprit",
    freezeCharacter: false,
  });
  const [bundle, setBundle] = useState<ChapterBundle | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onGenerateNextChapter() {
    setError(null);
    setIsGenerating(true);
    try {
      await createStory({
        ...DEFAULT_STORY,
        outline: draft.outline,
        characters: [
          {
            name: draft.characterName,
            role: "protagonist",
            goals: [draft.characterGoal],
            frozen: draft.freezeCharacter,
          },
        ],
      });
      if (draft.freezeCharacter) {
        await freezeCharacter(DEFAULT_STORY.story_id, draft.characterName);
      }
      const nextBundle = await generateNextChapter(DEFAULT_STORY.story_id);
      setBundle(nextBundle);
    } catch (e) {
      setError(e instanceof Error ? e.message : "generate failed");
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
                    Lead: {(bundle.updated_story as { characters: Array<{ name: string; frozen: boolean }> }).characters[0].name}
                  </p>
                  <p className="hint" style={{ marginBottom: 10 }}>
                    Frozen: {(bundle.updated_story as { characters: Array<{ name: string; frozen: boolean }> }).characters[0].frozen ? "Yes" : "No"}
                  </p>
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
          <button className="btn btn--ghost" type="button" disabled>
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
