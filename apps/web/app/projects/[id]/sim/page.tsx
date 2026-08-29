"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { ConfirmedFactsPanel } from "../../../../components/ws/ConfirmedFactsPanel";
import { PageHeader } from "../../../../components/ws/PageHeader";
import { useProjectWorkspace } from "../../../../components/ws/ProjectWorkspaceProvider";
import { useChapterDetail } from "../../../../components/ws/useChapterDetail";
import type { ChapterBundle } from "../../../../lib/api";
import { userFacingErrorMessage } from "../../../../lib/user-facing-error";

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

const STATE_FIELD_LABELS: Record<string, string> = {
  current_arc: "当前阶段",
  current_focus: "当前焦点",
  time_state: "时间状态",
  current_scene_time: "当前场景时间",
  server_day: "开服天数",
  server_phase: "开服阶段",
  game_clock: "游戏时间",
  real_clock: "现实时间",
  elapsed_since_launch: "开服时长",
  elapsed_minutes_since_launch: "开服分钟数",
  chapter_time_spans: "章节时间记录",
  chapter_number: "章节",
  chapter_title: "章节标题",
  start: "开始时间",
  end: "结束时间",
  duration_minutes: "持续分钟数",
  scene_time: "场景时间",
  cooldowns: "冷却事项",
  scheduled_events: "预定事件",
  time_rules: "时间规则",
  chaos_seed_anomaly_score: "混沌之种异常值",
  guild_knowledge_state: "公会掌握程度",
  buy_orders: "收购单",
  sell_orders: "寄售单",
  spread_copper: "买卖价差",
  sell_pressure: "出售压力",
  buyer: "买方",
  seller: "卖方",
  quantity: "数量",
  quantity_hint: "预计数量",
  price_copper: "铜币价格",
  bid: "买价",
  ask: "卖价",
  visibility: "可见范围",
  visible_at_chapter: "可见章节",
  actor: "行动方",
  action: "行动",
  visible_to: "可见对象",
  channel: "获知渠道",
  text: "内容",
  source_event: "来源事件",
};

function stateFieldLabel(key: string): string {
  return STATE_FIELD_LABELS[key] ?? key;
}

function compactText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (!value || typeof value !== "object") return "";
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => {
      if (typeof item === "string" || typeof item === "number" || typeof item === "boolean") {
        return `${stateFieldLabel(key)}: ${item}`;
      }
      if (Array.isArray(item)) return `${stateFieldLabel(key)}: ${item.map(compactText).filter(Boolean).join("、")}`;
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
      return text ? `${stateFieldLabel(key)}: ${text}` : "";
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

      {error ? <p className="ws-inline-error">加载失败：{userFacingErrorMessage(error)}</p> : null}

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
                第 {entry.chapter_number} 章：{userFacingErrorMessage(entry.chapter_title || "未命名")}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {chapterError ? <p className="ws-inline-error">章节加载失败：{userFacingErrorMessage(chapterError)}</p> : null}
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
