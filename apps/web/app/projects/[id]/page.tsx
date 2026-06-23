"use client";

import Link from "next/link";
import { useMemo } from "react";

import { PageHeader } from "../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../components/ws/ProjectWorkspaceProvider";
import type { ProjectResponse } from "../../../lib/api";
import { cleanLines, mergeCharacters, shortStatus } from "../../../lib/worldDisplay";

const STATUS_LABEL: Record<ProjectResponse["status"], string> = {
  draft: "草稿",
  simulating: "推演中",
  paused: "已暂停",
  completed: "已完成",
};

function chapterCharCount(body: string | undefined): number {
  if (!body) return 0;
  return body.replace(/\s+/g, "").length;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}

export default function ProjectOverviewPage() {
  const { project, story, error, encodedProjectId } = useProjectWorkspace();
  const currentChapter = story?.current_chapter ?? 0;
  const recentBundles = story?.history ? [...story.history].slice(-5).reverse() : [];
  const latest = story?.history?.at(-1) ?? null;
  const characters = mergeCharacters(project?.character_profiles, story?.characters);
  const sceneCards = latest?.scene_cards ?? [];
  const worldFacts = cleanLines(story?.world_facts, 5);
  const totalWords = useMemo(
    () => (story?.history ?? []).reduce((sum, bundle) => sum + chapterCharCount(bundle.body), 0),
    [story?.history],
  );

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[{ label: "作品", href: "/projects" }]}
        title={project?.title || "加载中"}
        subtitle={project?.current_focus || project?.world_summary?.slice(0, 100)}
      />

      {error ? (
        <div className="ws-card" style={{ borderColor: "var(--ws-danger)" }}>
          <p style={{ color: "var(--ws-danger)", margin: 0 }}>加载失败：{error}</p>
        </div>
      ) : null}

      {project ? (
        <>
          <section className="ws-card">
            <p className="ws-card__title">状态</p>
            <p className="ws-card__hint">
              第 {currentChapter} 章 · {formatNumber(totalWords)} 字 · {STATUS_LABEL[project.status]}
            </p>
          </section>

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
                  const summary = bundle.chapter_summary?.summary || "";
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
              <h2 className="ws-section-title">剧情推演</h2>
              <Link href={`/projects/${encodedProjectId}/sim`} className="ws-text-link">
                查看
              </Link>
            </div>
            <p className="ws-card__hint">
              {latest?.next_outline || project.current_focus || latest?.chapter_summary?.summary || "暂无剧情焦点。"}
            </p>
            {sceneCards.length > 0 ? (
              <ul className="ws-plain-list">
                {sceneCards.slice(0, 3).map((card, index) => (
                  <li key={card.scene_id || index}>{card.purpose || card.conflict || card.location || "未命名场景"}</li>
                ))}
              </ul>
            ) : null}
          </section>

          <section className="ws-card">
            <div className="ws-section-head">
              <h2 className="ws-section-title">角色卡</h2>
              <Link href={`/projects/${encodedProjectId}/world`} className="ws-text-link">
                查看
              </Link>
            </div>
            {characters.length > 0 ? (
              <div className="ws-simple-grid">
                {characters.slice(0, 6).map((character) => (
                  <div key={character.name} className="ws-simple-item">
                    <strong>{character.name}</strong>
                    <span>{[character.role, character.game_id || character.game_panel?.game_id].filter(Boolean).join(" / ")}</span>
                    <small>{shortStatus(character)}</small>
                  </div>
                ))}
              </div>
            ) : (
              <p className="ws-card__hint">暂无角色卡。</p>
            )}
          </section>

          <section className="ws-card">
            <h2 className="ws-section-title">世界事实</h2>
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
        </>
      ) : null}
    </div>
  );
}
