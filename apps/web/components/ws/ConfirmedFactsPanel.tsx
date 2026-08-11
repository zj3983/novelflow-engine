import { groupWorldFacts } from "../../lib/worldDisplay";

type Props = {
  facts?: Array<string | {
    text: string;
    source_chapter?: number;
    status?: string;
    updated_chapter?: number;
  }>;
};

export function ConfirmedFactsPanel({ facts = [] }: Props) {
  const structured = facts.filter((fact): fact is Exclude<(typeof facts)[number], string> => (
    typeof fact === "object" && fact !== null && typeof fact.text === "string" && Boolean(fact.text.trim())
  ));
  const grouped = groupWorldFacts(facts.filter((fact): fact is string => typeof fact === "string"));
  const isEmpty = structured.length === 0 && grouped.projectFacts.length === 0 && grouped.chapters.length === 0;
  const statusLabel = (status?: string) => ({
    active: "有效",
    resolved: "已解决",
    superseded: "已替代",
    retired: "已失效",
  }[status || "active"] || status || "有效");

  return (
    <section id="confirmed-facts" className="ws-card" aria-labelledby="confirmed-facts-title">
      <div className="ws-section-head">
        <div>
          <h2 className="ws-card__title" id="confirmed-facts-title">已确认事实</h2>
          <p className="ws-card__hint">由章节回写，不在此处直接修改</p>
        </div>
      </div>

      {isEmpty ? <p className="ws-card__hint">暂无已确认事实</p> : null}

      {structured.length > 0 ? (
        <ul className="ws-fact-list">
          {structured.map((fact, index) => (
            <li key={`${fact.source_chapter ?? 0}-${index}`}>
              <span>{fact.text}</span>
              <small className="ws-card__hint">
                {fact.source_chapter ? `来源：第 ${fact.source_chapter} 章 · ` : ""}{statusLabel(fact.status)}
              </small>
            </li>
          ))}
        </ul>
      ) : null}

      {grouped.projectFacts.length > 0 ? (
        <section aria-labelledby="project-facts-title">
          <h3 id="project-facts-title">项目事实</h3>
          <ul>
            {grouped.projectFacts.map((fact, index) => <li key={`project-${index}`}>{fact}</li>)}
          </ul>
        </section>
      ) : null}

      {grouped.chapters.map((chapter) => (
        <section aria-labelledby={`chapter-${chapter.chapterNumber}-facts-title`} key={chapter.chapterNumber}>
          <h3 id={`chapter-${chapter.chapterNumber}-facts-title`}>第 {chapter.chapterNumber} 章</h3>
          <ul>
            {chapter.facts.map((fact, index) => <li key={`${chapter.chapterNumber}-${index}`}>{fact}</li>)}
          </ul>
        </section>
      ))}
    </section>
  );
}
