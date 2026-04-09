"use client";

import { useState } from "react";

import { ChapterBundleView } from "../components/ChapterBundleView";
import { StorySidebar } from "../components/StorySidebar";
import { createStory, generateNextChapter, type ChapterBundle } from "../lib/api";

const DEFAULT_STORY = {
  story_id: "s-001",
  outline: "A detective prince uncovers palace crimes.",
  genre: "fantasy",
  style: "noir",
} as const;

export default function Page() {
  const [bundle, setBundle] = useState<ChapterBundle | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onGenerateNextChapter() {
    setError(null);
    setIsGenerating(true);
    try {
      // Ensure the story exists before generating. If the real backend is unreachable
      // (CORS/offline), `createStory` falls back to a deterministic in-browser mock.
      await createStory(DEFAULT_STORY);
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
          <StorySidebar />
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
              <pre style={{ margin: 0, overflowX: "auto" }}>
                {JSON.stringify(
                  {
                    character_cards: bundle.character_cards ?? [],
                    foreshadowing: bundle.foreshadowing ?? [],
                    next_outline: bundle.next_outline ?? "",
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
