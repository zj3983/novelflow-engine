"use client";

import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { buildRuleCards } from "../../../../lib/ruleCards";
import { cleanLines } from "../../../../lib/worldDisplay";

function recordLines(value: unknown, limit = 12): string[] {
  if (!value || typeof value !== "object") return [];
  return Object.entries(value as Record<string, unknown>)
    .filter(([, item]) => item !== null && item !== undefined && item !== "" && !(Array.isArray(item) && item.length === 0))
    .slice(0, limit)
    .map(([key, item]) => `${key}：${Array.isArray(item) ? item.join("；") : String(item)}`);
}

export default function WorldPage() {
  const { project, story, error, encodedProjectId } = useProjectWorkspace();
  const worldFacts = cleanLines(story?.world_facts, 20);
  const constraints = cleanLines(project?.author_constraints ?? story?.author_constraints, 12);
  const ruleCards = buildRuleCards(story?.history, story?.world_facts);
  const blueprint = project?.world_blueprint ?? {};
  const worldRules = cleanLines(blueprint.world_rules, 12);
  const economyRules = cleanLines(blueprint.economy_rules, 12);
  const questRules = cleanLines(blueprint.quest_rules, 12);
  const panelRules = cleanLines(blueprint.panel_rules, 12);
  const locationLines = recordLines(blueprint.locations, 12);
  const factionLines = recordLines(blueprint.factions, 12);

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="世界观"
        subtitle={project?.world_summary || "维护世界事实、规则、地点、阵营和作者约束。"}
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : null}

      <div className="ws-editor-layout">
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

        <aside className="ws-sidepanel">
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
            <p className="ws-card__title">世界规则</p>
            {worldRules.length > 0 ? (
              <ul className="ws-plain-list">
                {worldRules.map((rule, index) => (
                  <li key={`${rule}-${index}`}>{rule}</li>
                ))}
              </ul>
            ) : (
              <p className="ws-card__hint">暂无世界规则。</p>
            )}
          </section>

          <section className="ws-card">
            <p className="ws-card__title">系统规则</p>
            {[...economyRules, ...questRules, ...panelRules].length > 0 ? (
              <ul className="ws-plain-list">
                {[...economyRules, ...questRules, ...panelRules].map((rule, index) => (
                  <li key={`${rule}-${index}`}>{rule}</li>
                ))}
              </ul>
            ) : (
              <p className="ws-card__hint">暂无经济、任务或面板规则。</p>
            )}
          </section>

          <section className="ws-card">
            <p className="ws-card__title">地点 / 阵营</p>
            {[...locationLines, ...factionLines].length > 0 ? (
              <ul className="ws-plain-list">
                {[...locationLines, ...factionLines].map((line, index) => (
                  <li key={`${line}-${index}`}>{line}</li>
                ))}
              </ul>
            ) : (
              <p className="ws-card__hint">暂无地点或阵营资料。</p>
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
    </div>
  );
}
