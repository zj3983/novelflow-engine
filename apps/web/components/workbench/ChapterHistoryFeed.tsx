"use client";

import type { ChapterBundle } from "../../lib/api";

type ChapterHistoryFeedProps = {
  history: ChapterBundle[];
  selectedChapter: number | null;
  onOpenChapter: (chapterNumber: number) => void;
  isGenerating: boolean;
};

function historySummary(entry: ChapterBundle): string {
  return entry.chapter_summary?.summary || entry.next_outline || "本章已经生成，等待继续推进。";
}

function chapterTitle(entry: ChapterBundle): string {
  return entry.chapter_title || entry.chapter_intent?.chapter_title || `第 ${entry.chapter_number} 章`;
}

function timelineBeats(entry: ChapterBundle): Array<{ label: string; text: string }> {
  const beats: Array<{ label: string; text: string }> = [];

  const intent =
    (entry.chapter_intent?.primary_conflict?.collision as string | undefined) ||
    entry.conflict_summary?.summary;
  if (intent) {
    beats.push({ label: "本章意图", text: intent });
  }

  if (entry.event_plan?.pivot) {
    beats.push({ label: "事件拐点", text: entry.event_plan.pivot });
  }

  if (entry.memory_constraints?.unresolved_threads?.[0]) {
    beats.push({ label: "记忆护栏", text: entry.memory_constraints.unresolved_threads[0] });
  }

  if (entry.event_plan?.next_focus || entry.next_outline) {
    beats.push({ label: "下一粒种子", text: entry.event_plan?.next_focus || entry.next_outline || "" });
  }

  return beats.slice(0, 4);
}

function chapterSignals(entry: ChapterBundle): string[] {
  const signals: string[] = [];
  if (entry.character_moves?.length) {
    signals.push(`角色动作 ${entry.character_moves.length}`);
  }
  if (entry.foreshadowing?.length) {
    signals.push("伏笔已更新");
  }
  signals.push(entry.simulation_status?.mode === "degraded" ? "降级推演" : "完整推演");
  return signals;
}

export function ChapterHistoryFeed({
  history,
  selectedChapter,
  onOpenChapter,
  isGenerating,
}: ChapterHistoryFeedProps) {
  return (
    <div className="panel">
      <header className="panel__header">事件时间线</header>
      <div className="panel__body">
        {history.length ? (
          <div className="chapter-history-feed">
            {[...history].reverse().map((entry) => {
              const isActive = entry.chapter_number === selectedChapter;
              const beats = timelineBeats(entry);
              const signals = chapterSignals(entry);

              return (
                <article
                  key={entry.chapter_number}
                  className={`chapter-history-card${isActive ? " chapter-history-card--active" : ""}`}
                >
                  <div className="chapter-history-card__rail" aria-hidden="true">
                    <span className="chapter-history-card__node" />
                  </div>

                  <div className="chapter-history-card__content">
                    <div className="chapter-history-card__head">
                      <div>
                        <p className="chapter-history-card__eyebrow">第 {entry.chapter_number} 章</p>
                        <h3 className="chapter-history-card__title">{chapterTitle(entry)}</h3>
                      </div>
                      {isActive ? <span className="chapter-history-card__badge">当前查看</span> : null}
                    </div>

                    <p className="chapter-history-card__summary">{historySummary(entry)}</p>

                    <div className="chapter-history-card__signals">
                      {signals.map((signal) => (
                        <span key={signal} className="chapter-history-card__signal">
                          {signal}
                        </span>
                      ))}
                    </div>

                    {beats.length ? (
                      <div className="chapter-history-card__timeline">
                        {beats.map((beat) => (
                          <div key={`${entry.chapter_number}-${beat.label}`} className="chapter-history-card__beat">
                            <span className="chapter-history-card__beat-label">{beat.label}</span>
                            <p className="chapter-history-card__beat-text">{beat.text}</p>
                          </div>
                        ))}
                      </div>
                    ) : null}

                    <div className="chapter-history-card__actions">
                      <button
                        className="btn btn--ghost"
                        type="button"
                        onClick={() => onOpenChapter(entry.chapter_number)}
                        disabled={isGenerating}
                      >
                        打开章节详情
                      </button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <p className="hint">生成第一章后，这里会按时间顺序展示关键事件、状态变化和下一轮种子。</p>
        )}
      </div>
    </div>
  );
}
