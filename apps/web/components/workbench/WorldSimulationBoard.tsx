"use client";

import type { ReactNode } from "react";
import type {
  ChapterBundle,
  ImportedCharacterProfile,
  ImportedRelationshipEdge,
  ImportedWorldBlueprint,
  ProjectResponse,
  StoryResponse,
} from "../../lib/api";

type WorldSimulationBoardProps = {
  project: ProjectResponse | null;
  story: StoryResponse | null;
  bundle: ChapterBundle | null;
};

function compactLines(text: string | undefined, limit: number): string[] {
  return (text ?? "")
    .split(/\r?\n/)
    .map((line) => line.trim().replace(/^[-*#\d.\s、]+/, "").replace(/\*\*/g, ""))
    .filter(Boolean)
    .slice(0, limit);
}

function firstNonEmpty(...values: Array<string | undefined | null>): string {
  return values.find((value) => value?.trim())?.trim() ?? "";
}

function importedWorld(project: ProjectResponse | null): ImportedWorldBlueprint {
  return project?.world_blueprint ?? {};
}

function importedProfiles(project: ProjectResponse | null): ImportedCharacterProfile[] {
  return project?.character_profiles ?? [];
}

function importedRelationships(project: ProjectResponse | null): ImportedRelationshipEdge[] {
  return project?.relationship_graph ?? project?.world_blueprint?.relationship_graph ?? [];
}

function relationSnapshot(story: StoryResponse | null): Array<{ name: string; text: string }> {
  if (!story?.characters.length) {
    return [];
  }

  const snapshots: Array<{ name: string; text: string }> = [];
  for (const character of story.characters) {
    const firstRelation = character.relationships ? Object.values(character.relationships)[0] : undefined;
    if (!firstRelation) {
      continue;
    }
    snapshots.push({
      name: character.name,
      text: `对 ${firstRelation.target} 的信任 ${firstRelation.trust.toFixed(2)}，紧张 ${firstRelation.tension.toFixed(2)}。`,
    });
    if (snapshots.length >= 3) {
      break;
    }
  }
  return snapshots;
}

function fallbackSummary(bundle: ChapterBundle | null): string {
  if (!bundle?.simulation_status) {
    return "当前还没有章节推演记录。";
  }
  if (bundle.simulation_status.ok) {
    return "本轮为完整推演，各代理都按正常链路参与了生成。";
  }
  const agents = (bundle.simulation_status.fallback_agents ?? []).join("、") || "未知代理";
  return `本轮触发降级推演：${agents} 使用了回退策略。`;
}

function CardList({
  empty,
  items,
  render,
}: {
  empty: string;
  items: unknown[];
  render: (item: any, index: number) => ReactNode;
}) {
  if (!items.length) {
    return <p className="simulation-card__detail">{empty}</p>;
  }
  return <div className="simulation-list">{items.map(render)}</div>;
}

export function WorldSimulationBoard({ project, story, bundle }: WorldSimulationBoardProps) {
  const hasGeneratedChapter = Boolean(story?.history.length || bundle);
  const world = importedWorld(project);
  const profiles = importedProfiles(project);
  const relationships = importedRelationships(project);
  const relationCards = relationSnapshot(story);
  const importedFocusLines = compactLines(project?.current_focus, 4);
  const importedOutlineLines = compactLines(project?.seed_outline, 4);
  const memoryFacts = bundle?.memory_constraints?.must_keep_facts ?? [];
  const unresolvedThreads = bundle?.memory_constraints?.unresolved_threads ?? [];
  const authorConstraints =
    bundle?.memory_constraints?.author_constraints ??
    world.constraints ??
    project?.author_constraints ??
    story?.author_constraints ??
    [];

  const worldSituation = firstNonEmpty(
    bundle?.event_plan?.pivot,
    bundle?.chapter_summary?.summary,
    world.current_arc,
    project?.world_summary,
    world.premise,
  ) || "导入材料已载入，等待确认世界档案后再开始第一章。";

  const chapterIntent = hasGeneratedChapter
    ? firstNonEmpty(
        bundle?.chapter_intent?.primary_conflict?.collision as string | undefined,
        bundle?.conflict_summary?.summary,
      ) || "当前章节还没有形成明确主冲突。"
    : "导入后先生成世界档案和角色档案，确认设定后再开始第一章。";

  const nextFocus = firstNonEmpty(
    bundle?.chapter_intent?.next_focus,
    bundle?.event_plan?.next_focus,
    project?.current_focus,
    bundle?.next_outline,
  ) || "等待下一轮推演种子。";

  const eventActions = bundle?.event_plan?.ordered_actions ?? [];

  return (
    <div className="panel simulation-board">
      <header className="panel__header">世界演化台</header>
      <div className="panel__body simulation-board__body">
        <section className="simulation-hero">
          <div className="simulation-hero__main">
            <p className="simulation-hero__eyebrow">{hasGeneratedChapter ? "当前世界局势" : "导入世界档案"}</p>
            <h3 className="simulation-hero__title">{project?.title ?? "未命名小说项目"}</h3>
            <p className="simulation-hero__summary">{worldSituation}</p>
          </div>
          <div className="simulation-hero__meta">
            <span className="simulation-pill">主线：{project?.active_story_id || story?.story_id || "尚未创建"}</span>
            <span className="simulation-pill">推进到：第 {story?.current_chapter ?? 0} 章</span>
            <span className="simulation-pill">
              推演模式：{hasGeneratedChapter ? (bundle?.simulation_status?.mode === "degraded" ? "降级推演" : "完整推演") : "世界观准备"}
            </span>
          </div>
        </section>

        <div className="simulation-grid">
          <article className="simulation-card simulation-card--focus">
            <p className="simulation-card__label">{hasGeneratedChapter ? "本章意图" : "导入意图"}</p>
            <h4 className="simulation-card__title">{chapterIntent}</h4>
            <p className="simulation-card__detail">下一焦点：{nextFocus}</p>
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">{hasGeneratedChapter ? "事件链" : "世界规则"}</p>
            {hasGeneratedChapter && eventActions.length ? (
              <CardList
                empty="还没有整理出明确的事件链。"
                items={eventActions.slice(0, 3)}
                render={(action, index) => (
                  <div key={`${action.name}-${index}`} className="simulation-list__item">
                    <span className="simulation-list__index">0{index + 1}</span>
                    <div>
                      <strong>{action.name || "未知角色"}</strong>
                      <p>{action.action || action.goal || "暂时没有动作说明"}</p>
                    </div>
                  </div>
                )}
              />
            ) : (
              <CardList
                empty="导入材料里还没有可识别的世界规则。"
                items={world.world_rules?.length ? world.world_rules.slice(0, 4) : importedFocusLines}
                render={(item, index) => (
                  <div key={`${item}-${index}`} className="simulation-list__item">
                    <span className="simulation-list__index">0{index + 1}</span>
                    <div>
                      <strong>规则 {index + 1}</strong>
                      <p>{String(item)}</p>
                    </div>
                  </div>
                )}
              />
            )}
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">{hasGeneratedChapter ? "关系变化" : "角色画像"}</p>
            {relationCards.length ? (
              <CardList
                empty="角色关系还没有形成可追踪变化。"
                items={relationCards}
                render={(item) => (
                  <div key={item.name} className="simulation-list__item simulation-list__item--soft">
                    <div>
                      <strong>{item.name}</strong>
                      <p>{item.text}</p>
                    </div>
                  </div>
                )}
              />
            ) : (
              <CardList
                empty="导入材料里还没有可识别的角色画像。"
                items={profiles.slice(0, 4)}
                render={(profile, index) => (
                  <div key={`${profile.name}-${index}`} className="simulation-list__item simulation-list__item--soft">
                    <div>
                      <strong>{profile.name}</strong>
                      <p>{firstNonEmpty(profile.current_state, profile.motivation, profile.role) || "等待补充角色动机。"}</p>
                    </div>
                  </div>
                )}
              />
            )}
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">世界结构</p>
            <CardList
              empty="还没有可展示的地点、阵营或力量体系。"
              items={[
                ...(world.power_system ?? []).slice(0, 2).map((text) => ({ title: "力量体系", text })),
                ...(world.locations ?? []).slice(0, 2).map((entry) => ({ title: `地点：${entry.name}`, text: entry.description || entry.name })),
                ...(world.factions ?? []).slice(0, 2).map((entry) => ({ title: `阵营：${entry.name}`, text: entry.description || entry.name })),
                ...(!world.power_system?.length && !world.locations?.length && !world.factions?.length
                  ? importedOutlineLines.map((text, index) => ({ title: `设定 ${index + 1}`, text }))
                  : []),
              ].slice(0, 4)}
              render={(item, index) => (
                <div key={`${item.title}-${index}`} className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.text}</p>
                  </div>
                </div>
              )}
            />
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">关系网</p>
            <CardList
              empty="暂未识别出角色之间的明确关系，生成第一章前可继续补充角色档案。"
              items={relationships.slice(0, 4)}
              render={(edge, index) => (
                <div key={`${edge.source}-${edge.target}-${index}`} className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>
                      {edge.source} → {edge.target}
                    </strong>
                    <p>{edge.bond || "关系待确认"}</p>
                  </div>
                </div>
              )}
            />
          </article>

          <article className="simulation-card">
            <p className="simulation-card__label">记忆护栏</p>
            <div className="simulation-list">
              {memoryFacts.length ? (
                memoryFacts.slice(0, 2).map((fact) => (
                  <div key={fact} className="simulation-list__item simulation-list__item--soft">
                    <div>
                      <strong>必须保留</strong>
                      <p>{fact}</p>
                    </div>
                  </div>
                ))
              ) : (
                <p className="simulation-card__detail">当前还没有章节事实，先使用导入约束作为护栏。</p>
              )}
              {unresolvedThreads.length ? (
                <div className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>未收束线索</strong>
                    <p>{unresolvedThreads[0]}</p>
                  </div>
                </div>
              ) : null}
              {authorConstraints.length ? (
                <div className="simulation-list__item simulation-list__item--soft">
                  <div>
                    <strong>作者约束</strong>
                    <p>{authorConstraints.slice(0, 3).join(" / ")}</p>
                  </div>
                </div>
              ) : null}
            </div>
          </article>
        </div>

        <section className="simulation-footer">
          <div>
            <p className="simulation-card__label">运行说明</p>
            <p className="simulation-card__detail">
              {hasGeneratedChapter ? fallbackSummary(bundle) : "当前是导入后的世界观准备态，尚未运行章节生成。确认世界档案和角色画像后，再点击“开始生成第一章”。"}
            </p>
          </div>
          <div>
            <p className="simulation-card__label">项目背景</p>
            <p className="simulation-card__detail">
              {project?.seed_outline || project?.world_summary || project?.current_focus || "当前项目还没有完整的背景摘要。"}
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
