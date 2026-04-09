export type ChapterBundleLike = {
  chapter_number: number;
  body: string;
  next_outline?: string;
  character_cards?: unknown[];
  foreshadowing?: unknown[];
  updated_story?: unknown;
};

export function ChapterBundleView({ bundle }: { bundle: ChapterBundleLike }) {
  const debug = {
    chapter_number: bundle.chapter_number,
    next_outline: bundle.next_outline ?? "",
    character_cards: bundle.character_cards ?? [],
    foreshadowing: bundle.foreshadowing ?? [],
    updated_story: bundle.updated_story ?? null,
  };

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Chapter {bundle.chapter_number}</h2>
      <article style={{ whiteSpace: "pre-wrap", lineHeight: 1.55 }}>
        {bundle.body}
      </article>

      <details style={{ marginTop: 12 }}>
        <summary>Bundle</summary>
        <pre style={{ margin: 0, overflowX: "auto" }}>
          {JSON.stringify(debug, null, 2)}
        </pre>
      </details>
    </div>
  );
}
