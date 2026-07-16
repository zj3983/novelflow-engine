"use client";

import type { StoryResponse, StorySummary } from "../lib/api";

export type StoryCharacterDraft = {
  name: string;
  gameId?: string;
  goal: string;
  frozen: boolean;
  relationshipTarget: string;
  relationshipBond: string;
  trust: string;
  tension: string;
};

export type StoryDraft = {
  outline: string;
  directorBrief: string;
  characters: StoryCharacterDraft[];
};

type StorySidebarProps = {
  story: StoryResponse | null;
  storySummaries: StorySummary[];
  selectedChapter: number | null;
  onSelectHistoryChapter: (chapterNumber: number) => void;
  onBranchFromChapter: (chapterNumber: number) => Promise<void>;
  onDeleteActiveStory: () => Promise<void>;
  onOpenStory: (storyId: string) => Promise<void>;
  isGenerating: boolean;
  error: string | null;
};

function runtimeSourceLabel(source?: string): string {
  if (source === "llm") {
    return "模型";
  }
  if (source === "fallback") {
    return "回退";
  }
  return "空闲";
}

export function StorySidebar({
  story,
  storySummaries,
  selectedChapter,
  onSelectHistoryChapter,
  onBranchFromChapter,
  onDeleteActiveStory,
  onOpenStory,
  isGenerating,
  error,
}: StorySidebarProps) {
  return (
    <div className="story-sidebar">
      <section className="panel story-sidebar__section">
        <header className="panel__header">故事状态</header>
        <div className="panel__body">
          {story ? (
            <div className="story-sidebar__stack">
              <div className="story-sidebar__summary">
                <p className="character-card__title">当前故事</p>
                <p className="story-sidebar__headline">{story.story_id}</p>
                <p className="hint">当前章节：第 {story.current_chapter} 章</p>
                {story.parent_story_id ? <p className="hint">父故事：{story.parent_story_id}</p> : null}
                {story.branched_from_chapter != null ? (
                  <p className="hint">分支章节：第 {story.branched_from_chapter} 章</p>
                ) : null}
              </div>

              {story.agent_runtime ? (
                <div className="story-sidebar__summary">
                  <p className="character-card__title">运行状态</p>
                  <p className="hint">规划阶段：{runtimeSourceLabel(story.agent_runtime.planner.source)}</p>
                  <p className="hint">写作阶段：{runtimeSourceLabel(story.agent_runtime.writer.source)}</p>
                  <p className="hint">记忆阶段：{runtimeSourceLabel(story.agent_runtime.memory.source)}</p>
                  <p className="hint">最近事件：{story.agent_runtime.recent_events.at(-1) ?? "暂无"}</p>
                </div>
              ) : null}

              {story.characters.length ? (
                <div className="story-sidebar__summary">
                  <p className="character-card__title">角色一览</p>
                  <p className="hint">
                    角色表：
                    {story.characters
                      .map((character) => character.game_id ? `${character.name}（${character.game_id}）` : character.name)
                      .join("、")}
                  </p>
                  <p className="hint">
                    主角：{story.characters[0].name}
                    {story.characters[0].game_id ? `（游戏ID：${story.characters[0].game_id}）` : ""}
                  </p>
                  <p className="hint">冻结：{story.characters[0].frozen ? "是" : "否"}</p>
                </div>
              ) : null}
            </div>
          ) : (
            <div className="story-sidebar__summary">
              <p className="character-card__title">还没有故事</p>
              <p className="hint">先在左侧导入书籍，或者在中央直接开始第一章。</p>
            </div>
          )}

          {error ? <p className="hint story-sidebar__error">错误：{error}</p> : null}

          {story?.parent_story_id ? (
            <button className="btn btn--ghost" type="button" onClick={() => void onDeleteActiveStory()} disabled={isGenerating}>
              删除当前故事
            </button>
          ) : null}
        </div>
      </section>

      <section className="panel story-sidebar__section">
        <header className="panel__header">章节历史</header>
        <div className="panel__body">
          {story?.history.length ? (
            <div className="story-sidebar__history">
              {story.history.map((entry) => (
                <div key={entry.chapter_number} className="story-sidebar__history-row">
                  <button
                    className={`btn btn--ghost story-sidebar__history-btn${
                      entry.chapter_number === selectedChapter ? " story-sidebar__history-btn--active" : ""
                    }`}
                    type="button"
                    onClick={() => onSelectHistoryChapter(entry.chapter_number)}
                    disabled={isGenerating}
                  >
                    查看第 {entry.chapter_number} 章
                  </button>
                  <button
                    className="btn btn--ghost"
                    type="button"
                    onClick={() => void onBranchFromChapter(entry.chapter_number)}
                    disabled={isGenerating}
                  >
                    从第 {entry.chapter_number} 章分支
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <p className="hint">生成第一章后，这里会显示章节历史。</p>
          )}
        </div>
      </section>

      <section className="panel story-sidebar__section">
        <header className="panel__header">故事库</header>
        <div className="panel__body">
          {storySummaries.length ? (
            <div className="story-sidebar__library">
              {storySummaries.map((entry) => (
                <button
                  key={entry.story_id}
                  className="btn btn--ghost story-sidebar__library-btn"
                  type="button"
                  onClick={() => void onOpenStory(entry.story_id)}
                  disabled={isGenerating}
                >
                  打开 {entry.story_id}
                </button>
              ))}
            </div>
          ) : (
            <p className="hint">暂时没有其他故事。</p>
          )}
        </div>
      </section>
    </div>
  );
}
