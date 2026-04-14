export type ChapterBundleLike = {
  chapter_number: number;
  body: string;
  next_outline?: string;
  character_cards?: unknown[];
  foreshadowing?: unknown[];
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

export function ChapterBundleView({ bundle }: { bundle: ChapterBundleLike }) {
  const debug = {
    chapter_number: bundle.chapter_number,
    next_outline: bundle.next_outline ?? "",
    character_cards: bundle.character_cards ?? [],
    foreshadowing: bundle.foreshadowing ?? [],
    chapter_summary: bundle.chapter_summary ?? null,
    quality_report: bundle.quality_report ?? null,
    updated_story: bundle.updated_story ?? null,
  };

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>第 {bundle.chapter_number} 章</h2>
      <article style={{ whiteSpace: "pre-wrap", lineHeight: 1.55 }}>{bundle.body}</article>
      {bundle.chapter_summary ? (
        <section style={{ marginTop: 12 }}>
          <strong>压缩记忆</strong>
          <p style={{ margin: "6px 0 0 0" }}>{bundle.chapter_summary.summary}</p>
        </section>
      ) : null}

      <details style={{ marginTop: 12 }}>
        <summary>详细数据</summary>
        <pre style={{ margin: 0, overflowX: "auto" }}>{JSON.stringify(debug, null, 2)}</pre>
      </details>
    </div>
  );
}
