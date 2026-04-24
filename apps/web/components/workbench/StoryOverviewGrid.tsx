"use client";

type StoryOverviewCard = {
  title: string;
  value: string;
  detail: string;
};

type StoryOverviewGridProps = {
  cards: StoryOverviewCard[];
};

export function StoryOverviewGrid({ cards }: StoryOverviewGridProps) {
  return (
    <div className="panel">
      <header className="panel__header">故事总览</header>
      <div className="panel__body">
        <div className="story-overview-grid">
          {cards.map((card) => (
            <article key={card.title} className="story-overview-card">
              <p className="story-overview-card__title">{card.title}</p>
              <h3 className="story-overview-card__value">{card.value}</h3>
              <p className="story-overview-card__detail">{card.detail}</p>
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}
