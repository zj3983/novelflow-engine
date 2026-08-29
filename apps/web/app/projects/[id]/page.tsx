"use client";

import Link from "next/link";

import { PageHeader } from "../../../components/ws/PageHeader";
import { PublishingAssetsCards } from "../../../components/ws/PublishingAssetsCards";
import { useProjectWorkspace } from "../../../components/ws/ProjectWorkspaceProvider";
import type { ProjectStatus } from "../../../lib/api";
import { isGameWebnovel, mergeCharacters, shortStatus } from "../../../lib/worldDisplay";
import { userFacingErrorMessage } from "../../../lib/user-facing-error";

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  outlining: "大纲中",
  writing: "写作中",
  reviewing: "审核中",
  simulating: "生成中",
  paused: "已暂停",
  completed: "已完成",
};

function statusLabel(status: ProjectStatus | undefined): string {
  const key = String(status || "draft");
  return STATUS_LABEL[key] ?? key;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function hasFactText(value: unknown): boolean {
  if (typeof value === "string") return Boolean(value.trim());
  if (!value || typeof value !== "object") return false;
  const text = (value as { text?: unknown }).text;
  return typeof text === "string" && Boolean(text.trim());
}

export default function ProjectOverviewPage() {
  const { project, story, chapterIndex, error, encodedProjectId, projectId, refresh } = useProjectWorkspace();
  const currentChapter = story?.current_chapter ?? 0;
  const recentBundles = [...chapterIndex].slice(-5).reverse();
  const latest = chapterIndex.at(-1) ?? null;
  const characters = mergeCharacters(project?.character_profiles, story?.characters);
  const confirmedFactCount = (story?.continuity_facts ?? story?.world_facts ?? []).filter(hasFactText).length;
  const totalWords = story && "total_body_chars" in story
    ? story.total_body_chars
    : chapterIndex.reduce((sum, bundle) => sum + bundle.body_chars, 0);
  const openingNextPath = project?.pipeline_stage === "outlining"
    ? `/projects/${encodedProjectId}/outline`
    : project?.pipeline_stage === "world_ready"
      ? `/projects/${encodedProjectId}/world`
      : project?.pipeline_stage === "environment_ready"
        ? `/projects/${encodedProjectId}/write`
        : project?.pipeline_stage && ["draft", "idea_pending", "direction_ready"].includes(project.pipeline_stage)
          ? `/projects/${encodedProjectId}/setup`
          : null;

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[{ label: "作品", href: "/projects" }]}
        title={project?.title || "加载中"}
        subtitle={project?.current_focus || project?.world_summary?.slice(0, 100)}
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{userFacingErrorMessage(error)}</p>
        </div>
      ) : null}

      {project ? (
        <>
          <section className="ws-card">
            <p className="ws-card__title">状态</p>
            <p className="ws-card__hint">
              第 {currentChapter} 章 · {formatNumber(totalWords)} 字 · {statusLabel(project.status)}
            </p>
            {openingNextPath && currentChapter === 0 ? (
              <Link href={openingNextPath} className="ws-btn ws-btn--primary">
                继续开书
              </Link>
            ) : null}
          </section>

          {project.storage_source === "file" || project.project_id.startsWith("file:") ? (
            <PublishingAssetsCards
              projectId={projectId}
              title={project.title}
              assets={project.publishing_assets}
              onChanged={() => refresh({ invalidateChapter: false })}
            />
          ) : null}

          <section className="ws-card">
            <div className="ws-section-head">
              <h2 className="ws-section-title">章节</h2>
              <Link href={`/projects/${encodedProjectId}/chapters`} className="ws-text-link">
                全部章节
              </Link>
            </div>
            {recentBundles.length > 0 ? (
              <ul className="ws-list">
                {recentBundles.map((bundle) => {
                  const summary = bundle.summary || "";
                  return (
                    <li className="ws-list__item" key={bundle.chapter_number}>
                      <Link
                        href={`/projects/${encodedProjectId}/write?chapter=${bundle.chapter_number}`}
                        className="ws-list__item-title"
                      >
                        第 {bundle.chapter_number} 章 · {bundle.chapter_title || "未命名"}
                      </Link>
                      <span className="ws-list__item-meta">
                        {summary.slice(0, 80)}
                        {summary.length > 80 ? "..." : ""}
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="ws-card__hint">还没有章节。</p>
            )}
          </section>

          <section className="ws-card">
            <div className="ws-section-head">
              <h2 className="ws-section-title">故事状态</h2>
              <Link href={`/projects/${encodedProjectId}/sim`} className="ws-text-link">
                查看
              </Link>
            </div>
            <div className="ws-simple-grid">
              <div className="ws-simple-item">
                <strong>当前局面</strong>
                <span>
                  {chapterIndex.some((chapter) => chapter.has_simulation)
                    ? `${chapterIndex.filter((chapter) => chapter.has_simulation).length} 章有响应记录`
                    : "尚无世界响应记录"}
                </span>
              </div>
              <div className="ws-simple-item">
                <strong>已确认事实</strong>
                <span>{confirmedFactCount > 0 ? `${confirmedFactCount} 条已记录` : "暂无已确认事实"}</span>
              </div>
            </div>
          </section>

          <section className="ws-card">
            <div className="ws-section-head">
              <h2 className="ws-section-title">大纲</h2>
              <Link href={`/projects/${encodedProjectId}/outline`} className="ws-text-link">
                查看
              </Link>
            </div>
            <p className="ws-card__hint">{project.seed_outline || story?.outline || "暂无大纲内容。"}</p>
          </section>

          <section className="ws-card">
            <div className="ws-section-head">
              <h2 className="ws-section-title">角色卡</h2>
              <Link href={`/projects/${encodedProjectId}/characters`} className="ws-text-link">
                查看
              </Link>
            </div>
            {characters.length > 0 ? (
              <div className="ws-simple-grid">
                {characters.slice(0, 6).map((character) => (
                  (() => {
                    const isGameProject = isGameWebnovel(project);
                    const gameCurrent = isGameProject ? character.game_state?.current : undefined;
                    const currentGameId = typeof gameCurrent?.game_id === "string" && gameCurrent.game_id.trim() ? gameCurrent.game_id : undefined;
                    const currentLevel = isGameProject ? gameCurrent?.level ?? character.game_panel?.level : undefined;
                    const gameId = currentGameId ?? (isGameProject ? character.game_id || character.game_panel?.game_id : undefined);
                    const gameSummary = [gameId, currentLevel !== undefined && currentLevel !== null ? `${currentLevel}级` : undefined].filter(Boolean).join(" / ");
                    return <div key={character.name} className="ws-simple-item">
                      <strong>{character.name}</strong>
                      <span>{[character.role, gameSummary].filter(Boolean).join(" / ")}</span>
                      <small>{shortStatus(character)}</small>
                    </div>;
                  })()
                ))}
              </div>
            ) : (
              <p className="ws-card__hint">暂无角色卡。</p>
            )}
          </section>

        </>
      ) : null}
    </div>
  );
}
