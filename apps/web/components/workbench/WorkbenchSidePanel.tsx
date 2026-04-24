"use client";

import type { ChapterBundle, ProjectResponse, ProjectSummary, StoryResponse } from "../../lib/api";

type WorkbenchSidePanelProps = {
  project: ProjectResponse | null;
  story: StoryResponse | null;
  bundle: ChapterBundle | null;
  projectSummaries: ProjectSummary[];
  error: string | null;
  onOpenProject: (projectId: string) => Promise<void>;
  isGenerating: boolean;
};

function lifecycleLabel(value: StoryResponse["characters"][number]["lifecycle_state"]): string {
  if (value === "frozen") return "冻结";
  if (value === "proposed") return "待确认";
  if (value === "rejected") return "已拒绝";
  return "活跃";
}

function buildRiskList(story: StoryResponse | null): string[] {
  if (!story) {
    return ["还没有活动故事，进入创作后这里会开始提示当前风险。"];
  }

  const risks: string[] = [];
  const lastSummary = story.history.at(-1)?.chapter_summary;

  if (story.characters.some((character) => character.lifecycle_state === "proposed")) {
    risks.push("有新角色待确认，建议观察是否应该正式纳入主线。");
  }
  if ((lastSummary?.unresolved_threads.length ?? 0) > 0) {
    risks.push("最近一章留下了未收束线索，下一轮推演要注意承接。");
  }
  if (!risks.length) {
    risks.push("当前没有明显风险，可以继续推进下一章。");
  }
  return risks;
}

function relationshipNotes(story: StoryResponse | null): Array<{ name: string; text: string }> {
  if (!story) {
    return [];
  }
  const items: Array<{ name: string; text: string }> = [];
  for (const character of story.characters) {
    const firstRelationship = character.relationships ? Object.values(character.relationships)[0] : undefined;
    if (!firstRelationship) {
      continue;
    }
    items.push({
      name: character.name,
      text: `${firstRelationship.target} · 信任 ${firstRelationship.trust.toFixed(2)} / 紧张 ${firstRelationship.tension.toFixed(2)}`,
    });
    if (items.length >= 4) {
      break;
    }
  }
  return items;
}

function candidateCharacters(story: StoryResponse | null, bundle: ChapterBundle | null): string[] {
  const names = new Set<string>();
  for (const character of story?.characters ?? []) {
    if (character.lifecycle_state === "proposed") {
      names.add(character.name);
    }
  }
  for (const name of bundle?.chapter_intent?.approved_new_characters ?? []) {
    names.add(name);
  }
  for (const name of bundle?.chapter_intent?.deferred_characters ?? []) {
    names.add(name);
  }
  return Array.from(names);
}

function projectLibrary(projectSummaries: ProjectSummary[], currentProjectId: string | null) {
  return projectSummaries.filter((entry) => entry.project_id !== currentProjectId);
}

export function WorkbenchSidePanel({
  project,
  story,
  bundle,
  projectSummaries,
  error,
  onOpenProject,
  isGenerating,
}: WorkbenchSidePanelProps) {
  const recentEvent = story?.agent_runtime?.recent_events.at(-1) ?? "最近还没有运行记录。";
  const risks = error ? [`当前错误：${error}`] : buildRiskList(story);
  const relations = relationshipNotes(story);
  const newCandidates = candidateCharacters(story, bundle);
  const otherProjects = projectLibrary(projectSummaries, project?.project_id ?? null);

  return (
    <div className="workbench-sidepanel">
      <section className="panel">
        <header className="panel__header">角色群像</header>
        <div className="panel__body workbench-sidepanel__stack">
          {story?.characters.length ? (
            story.characters.map((character) => (
              <article key={character.name} className="side-card side-card--character">
                <div className="side-card__head">
                  <strong>{character.name}</strong>
                  <span className="side-card__badge">{lifecycleLabel(character.lifecycle_state)}</span>
                </div>
                <p className="hint">目标：{character.goals[0] ?? "待补全"}</p>
                <div className="side-card__chips">
                  <span className="side-chip">情绪：{character.current_emotion || "未知"}</span>
                  <span className="side-chip">位置：{character.location || "未落位"}</span>
                </div>
                {character.relationships && Object.values(character.relationships)[0] ? (
                  <p className="side-card__micro">牵引关系：{Object.values(character.relationships)[0].target}</p>
                ) : null}
              </article>
            ))
          ) : (
            <p className="hint">还没有角色状态，先生成第一章或导入已有项目。</p>
          )}
        </div>
      </section>

      <section className="panel">
        <header className="panel__header">关系变化</header>
        <div className="panel__body workbench-sidepanel__stack">
          {relations.length ? (
            relations.map((item) => (
              <article key={item.name} className="side-card side-card--soft">
                <strong>{item.name}</strong>
                <p className="hint">{item.text}</p>
              </article>
            ))
          ) : (
            <p className="hint">关系网络还没有形成明显波动。</p>
          )}
        </div>
      </section>

      <section className="panel">
        <header className="panel__header">新角色流</header>
        <div className="panel__body workbench-sidepanel__stack">
          {newCandidates.length ? (
            newCandidates.map((name) => (
              <article key={name} className="side-card side-card--candidate">
                <div className="side-card__head">
                  <strong>{name}</strong>
                  <span className="side-card__badge">候选</span>
                </div>
                <p className="hint">这一轮推演里已经进入导演视野，先观察是否需要正式纳入主线。</p>
              </article>
            ))
          ) : (
            <p className="hint">当前还没有浮出的新角色候选。</p>
          )}
        </div>
      </section>

      <section className="panel">
        <header className="panel__header">运行记录</header>
        <div className="panel__body">
          <article className="side-card side-card--soft">
            <p className="hint">{recentEvent}</p>
          </article>
        </div>
      </section>

      <section className="panel">
        <header className="panel__header">风险提醒</header>
        <div className="panel__body workbench-sidepanel__stack">
          {risks.map((item) => (
            <article key={item} className="side-card side-card--soft">
              <p className="hint">{item}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <header className="panel__header">项目库</header>
        <div className="panel__body workbench-sidepanel__stack">
          {project ? (
            <article className="side-card side-card--soft">
              <strong>{project.title}</strong>
              <p className="hint">
                当前主线项目 · {project.active_story_id ? `正在推进 ${project.active_story_id}` : "尚未进入章节演化"}
              </p>
            </article>
          ) : null}

          {otherProjects.length ? (
            otherProjects.map((entry) => (
              <button
                key={entry.project_id}
                className="btn btn--ghost workbench-sidepanel__story-btn"
                type="button"
                onClick={() => void onOpenProject(entry.project_id)}
                disabled={isGenerating}
              >
                打开 {entry.title}
              </button>
            ))
          ) : (
            <p className="hint">暂时没有其他项目。</p>
          )}
        </div>
      </section>
    </div>
  );
}
