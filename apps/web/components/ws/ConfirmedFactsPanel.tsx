import { groupWorldFacts } from "../../lib/worldDisplay";

type Props = {
  facts?: string[];
};

export function ConfirmedFactsPanel({ facts = [] }: Props) {
  const grouped = groupWorldFacts(facts);
  const isEmpty = grouped.projectFacts.length === 0 && grouped.chapters.length === 0;

  return (
    <section className="ws-card" aria-labelledby="confirmed-facts-title">
      <div className="ws-section-head">
        <div>
          <h2 className="ws-card__title" id="confirmed-facts-title">已确认事实</h2>
          <p className="ws-card__hint">由章节回写，不在此处直接修改</p>
        </div>
      </div>

      {isEmpty ? <p className="ws-card__hint">暂无已确认事实</p> : null}

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
