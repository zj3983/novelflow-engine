"use client";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { buildRuleCards } from "../../../../lib/ruleCards";
import { cleanLines, compactRecord, mergeCharacters, panelRows, shortStatus } from "../../../../lib/worldDisplay";

export default function WorldPage() {
  const { project, story, error, encodedProjectId } = useProjectWorkspace();
  const characters = mergeCharacters(project?.character_profiles, story?.characters);
  const worldFacts = cleanLines(story?.world_facts, 14);
  const constraints = cleanLines(project?.author_constraints ?? story?.author_constraints, 10);
  const ruleCards = buildRuleCards(story?.history, story?.world_facts);

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="人物 / 世界"
        subtitle={project?.world_summary || "维护角色卡、世界事实和作者约束。"}
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : (
        <div className="ws-editor-layout">
          <section className="ws-card">
            <p className="ws-card__title">角色卡</p>
            {characters.length > 0 ? (
              <div className="ws-character-list">
                {characters.map((character) => {
                  const panel = character.game_panel;
                  const rows = panelRows(panel);
                  const attributes = compactRecord(panel?.attributes);
                  const equipment = compactRecord(panel?.equipment);
                  const inventory = compactRecord(panel?.inventory);

                  return (
                    <article className="ws-character-card" key={character.name}>
                      <div className="ws-character-card__head">
                        <div>
                          <h2>{character.name}</h2>
                          <p>
                            {[character.role, character.game_id || panel?.game_id, character.lifecycle_state]
                              .filter(Boolean)
                              .join(" / ") || "角色"}
                          </p>
                        </div>
                        <span>
                          {character.lifecycle_state === "active" ? "大模型驱动" : "记录卡"}
                          {panel?.updated_chapter ? ` · 第 ${panel.updated_chapter} 章更新` : ""}
                        </span>
                      </div>

                      <p className="ws-character-card__status">{shortStatus(character)}</p>

                      {rows.length > 0 ? (
                        <dl className="ws-panel-grid">
                          {rows.map(([label, value]) => (
                            <div key={label}>
                              <dt>{label}</dt>
                              <dd>{value}</dd>
                            </div>
                          ))}
                        </dl>
                      ) : null}

                      {character.goals?.length ? (
                        <div className="ws-character-block">
                          <strong>目标</strong>
                          <ul>
                            {character.goals.slice(0, 4).map((goal, index) => (
                              <li key={`${goal}-${index}`}>{goal}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}

                      {character.memory?.length ? (
                        <div className="ws-character-block">
                          <strong>记忆</strong>
                          <ul>
                            {cleanLines(character.memory, 3).map((memory, index) => (
                              <li key={`${memory}-${index}`}>{memory}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}

                      {[...attributes, ...equipment, ...inventory].length > 0 ? (
                        <div className="ws-character-block">
                          <strong>面板细节</strong>
                          <ul>
                            {[...attributes, ...equipment, ...inventory].slice(0, 8).map((item, index) => (
                              <li key={`${item}-${index}`}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            ) : (
              <p className="ws-card__hint">暂无角色档案。</p>
            )}
          </section>

          <aside className="ws-sidepanel">
            <section className="ws-card">
              <div className="ws-section-head">
                <p className="ws-card__title">规则卡</p>
                <span className="ws-toolbar__meta">{ruleCards.length} 条</span>
              </div>
              {ruleCards.length > 0 ? (
                <div className="ws-rule-list">
                  {ruleCards.map((card) => (
                    <article className="ws-rule-item" key={card.id}>
                      <div>
                        <strong>{card.title}</strong>
                        <span>
                          {card.category} · 第 {card.firstChapter} 章
                        </span>
                      </div>
                      <p>{card.rule}</p>
                    </article>
                  ))}
                </div>
              ) : (
                <p className="ws-card__hint">暂无规则卡。</p>
              )}
            </section>
            <section className="ws-card">
              <p className="ws-card__title">世界事实</p>
              {worldFacts.length > 0 ? (
                <ul className="ws-plain-list">
                  {worldFacts.map((fact, index) => (
                    <li key={`${fact}-${index}`}>{fact}</li>
                  ))}
                </ul>
              ) : (
                <p className="ws-card__hint">暂无可读世界事实。</p>
              )}
            </section>
            <section className="ws-card">
              <p className="ws-card__title">作者约束</p>
              {constraints.length > 0 ? (
                <ul className="ws-plain-list">
                  {constraints.map((constraint, index) => (
                    <li key={`${constraint}-${index}`}>{constraint}</li>
                  ))}
                </ul>
              ) : (
                <p className="ws-card__hint">暂无作者约束。</p>
              )}
            </section>
          </aside>
        </div>
      )}
    </div>
  );
}
