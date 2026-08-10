"use client";

/**
 * Round 8 Task 6: rolling-outline card replaces the legacy "next chapter
 * direction" picker. Three visual states:
 *
 * - "present": an outline exists for the target chapter (either a rolling
 *   chapter or a legacy outline). Show the outline summary.
 * - "missing": no outline for the target chapter. The next body
 *   generation will trigger a rolling fill automatically. Show a brief
 *   status note so the user knows what's about to happen.
 * - "failed": the most recent rolling fill failed. Show the error and
 *   a retry CTA (the user clicks "重试" → POST /outline/rolling-fill).
 * - "legacy": the chapter has a legacy outline but no rolling outline.
 *   Same visual treatment as "present" but the source badge is
 *   "legacy" instead of "rolling".
 *
 * Source badge legend:
 * - "rolling"  → system-generated, refreshable
 * - "legacy"   → pre-rolling-fill data, kept verbatim
 * - "manual"   → user-edited (future enhancement via Task 8)
 */
import type { CSSProperties, ReactNode } from "react";

export type RollingFillStatus = "present" | "missing" | "failed" | "legacy";

export type RollingOutlinePayload = {
  chapter_number?: number;
  title?: string;
  chapter_goal?: string;
  core_conflict?: string;
  cast?: Array<{ name?: string; role?: string }>;
  scenes?: Array<{ location?: string; action?: string; result?: string }>;
  gain?: string;
  cost?: string;
  foreshadowing?: string[];
  hook?: string;
  state_delta?: Record<string, unknown>;
  source?: string;
};

type Props = {
  chapterNumber: number;
  status: RollingFillStatus;
  source: string | null;
  outline: RollingOutlinePayload | null;
  error: string;
  filledChapterNumbers: number[];
};

const CARD_STYLE: CSSProperties = {
  border: "1px solid var(--ws-border, #d6d8df)",
  borderRadius: 12,
  padding: 16,
  background: "var(--ws-card-bg, #fff)",
};

const TITLE_STYLE: CSSProperties = {
  margin: 0,
  fontSize: 15,
  fontWeight: 600,
};

const HINT_STYLE: CSSProperties = {
  margin: "4px 0 0",
  color: "var(--ws-text-dim, #6b6e76)",
  fontSize: 13,
  lineHeight: 1.5,
};

const BADGE_STYLE: CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: 999,
  fontSize: 12,
  background: "var(--ws-accent-soft, #eef2ff)",
  color: "var(--ws-accent, #3b3fa4)",
  marginLeft: 8,
};

const SECTION_STYLE: CSSProperties = {
  marginTop: 8,
  fontSize: 13,
  lineHeight: 1.55,
};

function sourceLabel(source: string | null, status: RollingFillStatus): string {
  if (source === "manual") return "✎ 人工";
  if (source === "legacy") return "legacy";
  if (source === "rolling" || status === "present") return "rolling";
  if (status === "legacy") return "legacy";
  return "";
}

function SceneList({ scenes }: { scenes: RollingOutlinePayload["scenes"] }): ReactNode {
  if (!scenes || scenes.length === 0) return null;
  return (
    <ol style={{ margin: "4px 0 0 18px", padding: 0, fontSize: 13, lineHeight: 1.5 }}>
      {scenes.map((scene, index) => (
        <li key={index}>
          <strong>{scene.location || "未命名场景"}</strong>
          {scene.action ? ` — ${scene.action}` : ""}
          {scene.result ? `，${scene.result}` : ""}
        </li>
      ))}
    </ol>
  );
}

function CastList({ cast }: { cast: RollingOutlinePayload["cast"] }): ReactNode {
  if (!cast || cast.length === 0) return null;
  return (
    <p style={SECTION_STYLE}>
      <strong>出场：</strong>
      {cast
        .map((c) => `${c.name ?? "未命名"}${c.role ? `（${c.role}）` : ""}`)
        .join("、")}
    </p>
  );
}

export function RollingOutlineCard({
  chapterNumber,
  status,
  source,
  outline,
  error,
  filledChapterNumbers,
}: Props) {
  const badgeText = sourceLabel(source, status);
  if (status === "failed") {
    return (
      <section style={CARD_STYLE} aria-label="滚动细纲补全失败">
        <p style={TITLE_STYLE}>
          第{chapterNumber}章细纲补全失败
          {badgeText ? <span style={BADGE_STYLE}>{badgeText}</span> : null}
        </p>
        <p style={HINT_STYLE}>
          滚动细纲生成器本次未写出可用的细纲；请重试或人工填写。
        </p>
        {error ? (
          <pre
            style={{
              margin: "8px 0 0",
              padding: 8,
              fontSize: 12,
              background: "var(--ws-error-bg, #fef2f2)",
              border: "1px solid var(--ws-error-border, #fca5a5)",
              borderRadius: 6,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {error}
          </pre>
        ) : null}
        {filledChapterNumbers.length > 0 ? (
          <p style={HINT_STYLE}>
            最近一次尝试：第{filledChapterNumbers.join("、")}章。
          </p>
        ) : null}
      </section>
    );
  }
  if (status === "missing") {
    return (
      <section style={CARD_STYLE} aria-label="下一章细纲待补全">
        <p style={TITLE_STYLE}>
          第{chapterNumber}章细纲待补全
          {badgeText ? <span style={BADGE_STYLE}>{badgeText}</span> : null}
        </p>
        <p style={HINT_STYLE}>
          目标章节缺少细纲。点击"生成下一章"时系统会自动补全第
          {chapterNumber}至{chapterNumber + 4}章的细纲，无需手动选择。
        </p>
      </section>
    );
  }
  // present or legacy — show the outline summary
  const title = outline?.title ?? `第${chapterNumber}章`;
  return (
    <section style={CARD_STYLE} aria-label="下一章细纲">
      <p style={TITLE_STYLE}>
        本章细纲：{title}
        {badgeText ? <span style={BADGE_STYLE}>{badgeText}</span> : null}
      </p>
      {outline?.chapter_goal ? (
        <p style={SECTION_STYLE}>
          <strong>目标：</strong>
          {outline.chapter_goal}
        </p>
      ) : null}
      {outline?.core_conflict ? (
        <p style={SECTION_STYLE}>
          <strong>核心冲突：</strong>
          {outline.core_conflict}
        </p>
      ) : null}
      <CastList cast={outline?.cast} />
      {outline?.scenes && outline.scenes.length > 0 ? (
        <div style={SECTION_STYLE}>
          <strong>主要场面：</strong>
          <SceneList scenes={outline.scenes} />
        </div>
      ) : null}
      {outline?.gain ? (
        <p style={SECTION_STYLE}>
          <strong>收益：</strong>
          {outline.gain}
        </p>
      ) : null}
      {outline?.cost ? (
        <p style={SECTION_STYLE}>
          <strong>代价：</strong>
          {outline.cost}
        </p>
      ) : null}
      {outline?.hook ? (
        <p style={SECTION_STYLE}>
          <strong>章末钩子：</strong>
          {outline.hook}
        </p>
      ) : null}
    </section>
  );
}
