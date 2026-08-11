"use client";

import Link from "next/link";
import type { CSSProperties, ReactNode } from "react";

export type RollingFillStatus = "present" | "missing" | "failed" | "legacy";

export type RollingOutlinePayload = {
  chapter_number?: number;
  title?: string;
  chapter_goal?: string;
  core_conflict?: string;
  cast?: Array<string | { name?: string; role?: string }>;
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
  outlineHref: string;
};

const CARD_STYLE: CSSProperties = {
  border: "1px solid var(--ws-border, #d6d8df)",
  borderRadius: 8,
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
  if (source === "manual") return "人工修改";
  if (source === "legacy" || status === "legacy") return "已有大纲";
  if (source === "rolling" || status === "present") return "滚动细纲";
  return "";
}

function SceneList({ scenes }: { scenes: RollingOutlinePayload["scenes"] }): ReactNode {
  if (!scenes || scenes.length === 0) return null;
  return (
    <ol style={{ margin: "4px 0 0 18px", padding: 0, fontSize: 13, lineHeight: 1.5 }}>
      {scenes.map((scene, index) => (
        <li key={index}>
          <strong>{scene.location || "未命名场景"}</strong>
          {scene.action ? `：${scene.action}` : ""}
          {scene.result ? `；结果：${scene.result}` : ""}
        </li>
      ))}
    </ol>
  );
}

function CastList({ cast }: { cast: RollingOutlinePayload["cast"] }): ReactNode {
  if (!cast || cast.length === 0) return null;
  const names = cast
    .map((character) => {
      if (typeof character === "string") return character.trim();
      const name = character.name?.trim() ?? "";
      if (!name) return "";
      return character.role ? `${name}（${character.role}）` : name;
    })
    .filter(Boolean);
  if (names.length === 0) return null;
  return (
    <p style={SECTION_STYLE}>
      <strong>出场人物：</strong>
      {names.join("、")}
    </p>
  );
}

function OutlineRequired({
  chapterNumber,
  status,
  error,
  filledChapterNumbers,
  outlineHref,
}: Pick<Props, "chapterNumber" | "status" | "error" | "filledChapterNumbers" | "outlineHref">) {
  const failed = status === "failed";
  return (
    <section style={CARD_STYLE} aria-label={`第${chapterNumber}章细纲${failed ? "生成失败" : "待补充"}`}>
      <p style={TITLE_STYLE}>第{chapterNumber}章还没有可用细纲</p>
      <p style={HINT_STYLE}>
        {failed ? "上次补全没有生成可用结果。" : "正文生成尚未开始。"}
        请先在大纲页补充并确认章节细纲，再回来生成正文。
      </p>
      {error ? <p className="ws-error" style={{ marginTop: 8 }}>{error}</p> : null}
      {filledChapterNumbers.length > 0 ? (
        <p style={HINT_STYLE}>上次已补充：第{filledChapterNumbers.join("、")}章。</p>
      ) : null}
      <div style={{ marginTop: 12 }}>
        <Link className="ws-btn ws-btn--sm ws-btn--primary" href={outlineHref}>
          去补章节细纲
        </Link>
      </div>
    </section>
  );
}

export function RollingOutlineCard({
  chapterNumber,
  status,
  source,
  outline,
  error,
  filledChapterNumbers,
  outlineHref,
}: Props) {
  if (status === "missing" || status === "failed") {
    return (
      <OutlineRequired
        chapterNumber={chapterNumber}
        status={status}
        error={error}
        filledChapterNumbers={filledChapterNumbers}
        outlineHref={outlineHref}
      />
    );
  }

  const badgeText = sourceLabel(source, status);
  const title = outline?.title ?? `第${chapterNumber}章`;
  return (
    <section style={CARD_STYLE} aria-label={`第${chapterNumber}章细纲`}>
      <p style={TITLE_STYLE}>
        第{chapterNumber}章细纲：{title}
        {badgeText ? <span style={BADGE_STYLE}>{badgeText}</span> : null}
      </p>
      {outline?.chapter_goal ? <p style={SECTION_STYLE}><strong>目标：</strong>{outline.chapter_goal}</p> : null}
      {outline?.core_conflict ? <p style={SECTION_STYLE}><strong>核心冲突：</strong>{outline.core_conflict}</p> : null}
      <CastList cast={outline?.cast} />
      {outline?.scenes?.length ? (
        <div style={SECTION_STYLE}>
          <strong>主要场面：</strong>
          <SceneList scenes={outline.scenes} />
        </div>
      ) : null}
      {outline?.gain ? <p style={SECTION_STYLE}><strong>收获：</strong>{outline.gain}</p> : null}
      {outline?.cost ? <p style={SECTION_STYLE}><strong>代价：</strong>{outline.cost}</p> : null}
      {outline?.hook ? <p style={SECTION_STYLE}><strong>章末钩子：</strong>{outline.hook}</p> : null}
    </section>
  );
}
