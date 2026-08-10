"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { ConfirmedFactsPanel } from "../../../../components/ws/ConfirmedFactsPanel";
import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { useChapterDetail } from "../../../../components/ws/useChapterDetail";
import type { ChapterBundle } from "../../../../lib/api";

type WorldPulse = {
  pulse_index?: number;
  chapter_number?: number;
  visible_at_chapter?: number;
  summary?: string;
  public_traces?: unknown[];
  pressure_points?: unknown[];
  background_events?: unknown[];
  visibility_inbox?: unknown[];
  hidden_state?: Record<string, unknown>;
  market_order_book?: Record<string, unknown>;
};

function compactText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (!value || typeof value !== "object") return "";
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => {
      if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
        return `${key}: ${item}`;
      }
      if (Array.isArray(item)) return `${key}: ${item.map(compactText).filter(Boolean).join("、")}`;
      return "";
    })
    .filter(Boolean)
    .join("；");
}

function textList(value: unknown, limit = 8): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(compactText).filter(Boolean).slice(0, limit);
}

function pulseFor(bundle: ChapterBundle): WorldPulse | null {
  const latest = bundle.simulation_status?.world_pulse?.latest;
  return latest && typeof latest === "object" ? (latest as WorldPulse) : null;
}

function inboxFor(bundle: ChapterBundle, pulse: WorldPulse | null): string[] {
  const direct = bundle.simulation_status?.visibility_inbox;
  const source = Array.isArray(direct) && direct.length > 0 ? direct : pulse?.visibility_inbox;
  return textList(source);
}

function recordLines(value: Record<string, unknown> | undefined): string[] {
  if (!value) return [];
  return Object.entries(value)
    .map(([key, item]) => {
      const text = compactText(item);
      return text ? `${key}: ${text}` : "";
    })
    .filter(Boolean)
    .slice(0, 10);
}

function StateBlock({ title, lines }: { title: string; lines: string[] }) {
  if (!lines.length) return null;
  return (
    <div className="ws-character-block">
      <strong>{title}</strong>
      <ul>
        {lines.map((line, index) => (
          <li key={`${title}-${index}`}>{line}</li>
        ))}
      </ul>
    </div>
  );
}

export default function WorldStatePage() {
  const { project, story, chapterIndex, error, encodedProjectId, projectId, refreshVersion } = useProjectWorkspace();
  const stateIndex = useMemo(() => chapterIndex.filter((entry) => entry.has_simulation).reverse(), [chapterIndex]);
  const [selectedChapter, setSelectedChapter] = useState(0);

  useEffect(() => {
    if (!stateIndex.length) {
      setSelectedChapter(0);
      return;
    }
    if (!stateIndex.some((entry) => entry.chapter_number === selectedChapter)) {
      setSelectedChapter(stateIndex[0].chapter_number);
    }
  }, [selectedChapter, stateIndex]);

  const { chapter, loading, error: chapterError } = useChapterDetail({
    projectId,
    story: story ?? null,
    chapterNumber: selectedChapter,
    refreshVersion,
  });

  return (
    <div className="ws-page">
      <PageHeader
        crumbs={[
          { label: "我的作品", href: "/projects" },
          { label: project?.title || "作品", href: `/projects/${encodedProjectId}` },
        ]}
        title="世界状态"
        subtitle={project?.world_summary || "当前世界状态"}
      />

      {error ? <p className="ws-inline-error">加载失败：{error}</p> : null}

      {story?.world_snapshot && Object.keys(story.world_snapshot).length > 0 ? (
        <section className="ws-card">
          <div className="ws-section-head">
            <div>
              <h2 className="ws-card__title">当前世界快照</h2>
              <p className="ws-card__hint">当前章结束后的局面，会随章节推进更新。</p>
            </div>
          </div>
          <StateBlock title="当前状态" lines={recordLines(story.world_snapshot)} />
        </section>
      ) : null}

      <ConfirmedFactsPanel facts={story?.continuity_facts ?? story?.world_facts ?? []} />

      {stateIndex.length > 1 ? (
        <label className="ws-search">
          <span>响应章节</span>
          <select aria-label="响应章节" className="ws-input" value={selectedChapter} onChange={(event) => setSelectedChapter(Number(event.target.value))}>
            {stateIndex.map((entry) => (
              <option key={entry.chapter_number} value={entry.chapter_number}>
                第 {entry.chapter_number} 章：{entry.chapter_title || "未命名"}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {chapterError ? <p className="ws-inline-error">章节加载失败：{chapterError}</p> : null}
      {loading && chapter?.chapter_number !== selectedChapter ? <p className="ws-card__hint">正在加载章节...</p> : null}

      {chapter && chapter.chapter_number === selectedChapter ? (
        <WorldStateRecord bundle={chapter} encodedProjectId={encodedProjectId} />
      ) : !loading && !chapterError ? (
        <section className="ws-card">
          <p className="ws-card__title">世界状态</p>
          <p className="ws-card__hint">尚无已确认的世界状态。</p>
        </section>
      ) : null}
    </div>
  );
}

function WorldStateRecord({ bundle, encodedProjectId }: { bundle: ChapterBundle; encodedProjectId: string }) {
  const pulse = pulseFor(bundle);
  const publicTraces = textList(pulse?.public_traces);
  const pressures = textList(pulse?.pressure_points);
  const backgroundEvents = textList(pulse?.background_events);
  const inbox = inboxFor(bundle, pulse);
  const hiddenState = recordLines(pulse?.hidden_state);
  const marketState = recordLines(pulse?.market_order_book);
  const summary = pulse?.summary || bundle.chapter_summary?.summary || "本章没有产生新的世界状态。";

  return (
    <section className="ws-card ws-sim-chapter">
      <div className="ws-section-head">
        <div>
          <p className="ws-card__title">第 {bundle.chapter_number} 章响应记录</p>
          <h2 className="ws-sim-chapter__title">{bundle.chapter_title || "未命名"}</h2>
        </div>
        <Link href={`/projects/${encodedProjectId}/write?chapter=${bundle.chapter_number}`} className="ws-text-link">
          看正文
        </Link>
      </div>

      <p className="ws-card__hint">{summary}</p>
      <StateBlock title="公开痕迹" lines={publicTraces} />
      <StateBlock title="后续压力" lines={pressures} />
      <StateBlock title="下一章可见信息" lines={inbox} />
      <StateBlock title="后台变化" lines={backgroundEvents} />
      <StateBlock title="隐藏状态" lines={hiddenState} />
      <StateBlock title="市场状态" lines={marketState} />
    </section>
  );
}
