import { useState } from "react";

import type { BookImportBootstrapResponse } from "../lib/api";
import type { BookLibraryCatalogResponse, BookLibraryItem, ChapterBundle } from "../lib/api";
import type { RuntimeConnectionTarget, RuntimeSettings } from "../lib/api";
import { BookImportPanel } from "./BookImportPanel";
import { BookLibraryBrowser } from "./BookLibraryBrowser";

export type StoryCharacterDraft = {
  name: string;
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



export type AgentMode = "Rule-based" | "LLM-assisted";

export type NewCharacterPolicy = "Director review" | "Auto-approve named candidates" | "Manual review";

export type AgentSettings = {
  mode: AgentMode;
  globalModel: string;
  characterModel: string;
  directorModel: string;
  writerModel: string;
  memoryModel: string;
  temperature: string;
  newCharacterPolicy: NewCharacterPolicy;
};



type StorySidebarProps = {
  draft: StoryDraft;
  agentSettings: AgentSettings;
  runtimeSettings: RuntimeSettings;
  onChange: (next: StoryDraft) => void;
  onAgentSettingsChange: (next: AgentSettings) => void;
  onRuntimeSettingsChange: (next: RuntimeSettings) => void;
  onSaveRuntimeSettings: () => void;
  onTestRuntimeSettings: (target: RuntimeConnectionTarget) => void;
  runtimeSettingsStatus: "idle" | "loading" | "saving" | "success" | "error";
  runtimeConnectionStatus: Record<RuntimeConnectionTarget, { state: "idle" | "testing" | "success" | "error"; message: string }>;
  onStartGeneration: (draft?: BookImportBootstrapResponse["draft"]) => Promise<void>;
  history: ChapterBundle[];
  selectedChapter: number | null;
  onSelectHistoryChapter: (chapterNumber: number) => void;
};

export function StorySidebar({
  draft,
  agentSettings,
  runtimeSettings,
  onChange,
  onAgentSettingsChange,
  onRuntimeSettingsChange,
  onSaveRuntimeSettings,
  onTestRuntimeSettings,
  runtimeSettingsStatus,
  runtimeConnectionStatus,
  onStartGeneration,
  history,
  selectedChapter,
  onSelectHistoryChapter,
}: StorySidebarProps) {
  const [isAgentSettingsOpen, setIsAgentSettingsOpen] = useState(true);
  const [isApiSettingsOpen, setIsApiSettingsOpen] = useState(true);
  const [bookCatalog, setBookCatalog] = useState<BookLibraryCatalogResponse | null>(null);
  const [selectedSourceItem, setSelectedSourceItem] = useState<BookLibraryItem | null>(null);

  function updateRuntimeSettings(next: Partial<RuntimeSettings>) {
    onRuntimeSettingsChange({ ...runtimeSettings, ...next });
  }

  function updateModelSettings(agent: keyof RuntimeSettings["agents"], next: Partial<RuntimeSettings["agents"][keyof RuntimeSettings["agents"]]>) {
    onRuntimeSettingsChange({
      ...runtimeSettings,
      agents: {
        ...runtimeSettings.agents,
        [agent]: {
          ...runtimeSettings.agents[agent],
          ...next,
        },
      },
    });
  }

  const runtimeMode =
    agentSettings.mode === "LLM-assisted" ? "LLM 协助模式，失败时自动回退到规则流程" : "纯规则模式";
  const agentRuntimeLabel = agentSettings.mode === "LLM-assisted" ? "LLM 协助模式" : "纯规则模式";

  function updateCharacter(index: number, next: StoryCharacterDraft) {
    const characters = draft.characters.map((character, currentIndex) =>
      currentIndex === index ? next : character,
    );
    onChange({ ...draft, characters });
  }

  function updateAgentSettings(next: Partial<AgentSettings>) {
    onAgentSettingsChange({ ...agentSettings, ...next });
  }

  function modeLabel(mode: AgentMode): string {
    return mode === "LLM-assisted" ? "LLM 协助模式" : "纯规则模式";
  }

  function policyLabel(policy: NewCharacterPolicy): string {
    if (policy === "Auto-approve named candidates") {
      return "自动通过命名候选";
    }
    if (policy === "Manual review") {
      return "手动审核";
    }
    return "导演审核";
  }

  function runtimeBadgeTone(state: "idle" | "loading" | "saving" | "testing" | "success" | "error"): string {
    if (state === "testing" || state === "loading" || state === "saving") {
      return "warning";
    }
    if (state === "success") {
      return "success";
    }
    if (state === "error") {
      return "error";
    }
    return "idle";
  }

  function addCharacter() {
    onChange({
      ...draft,
      characters: [
        ...draft.characters,
        {
          name: "",
          goal: "",
          frozen: false,
          relationshipTarget: "",
          relationshipBond: "",
          trust: "0.0",
          tension: "0.0",
        },
      ],
    });
  }

  function handleCatalogLoaded(nextCatalog: BookLibraryCatalogResponse | null) {
    setBookCatalog(nextCatalog);
    if (!nextCatalog) {
      setSelectedSourceItem(null);
    }
  }

  function loadSourceItem(item: BookLibraryItem) {
    setSelectedSourceItem(item);

    if (item.filename === "character_matrix.md" && item.parsed_characters?.length) {
      onChange({
        ...draft,
        characters: item.parsed_characters.map((name) => ({
          name,
          goal: "",
          frozen: false,
          relationshipTarget: "",
          relationshipBond: "",
          trust: "0.0",
          tension: "0.0",
        })),
      });
      return;
    }

    if (
      item.filename === "volume_outline.md" ||
      item.filename === "current_focus.md" ||
      item.filename === "author_intent.md" ||
      item.filename === "book_rules.md" ||
      item.filename === "story_bible.md"
    ) {
      onChange({
        ...draft,
        outline: item.content.trim() || item.preview,
      });
      return;
    }

    if (item.chapter_number != null) {
      onSelectHistoryChapter(item.chapter_number);
    }
  }



  function onBootstrapDraft(payload: BookImportBootstrapResponse["draft"]) {
    const nextCharacters = (payload.characters ?? []).length
      ? payload.characters.map((name) => ({
        name,
        goal: "",
        frozen: false,
        relationshipTarget: "",
        relationshipBond: "",
        trust: "0.0",
        tension: "0.0",
      }))
      : draft.characters;

    onChange({
      ...draft,
      outline: payload.outline ?? draft.outline,
      directorBrief: payload.summary ?? draft.directorBrief,
      characters: nextCharacters.length ? nextCharacters : draft.characters,
    });
  }

  return (
    <div className="sidebar-fields">
      <BookImportPanel
        onBootstrapDraft={onBootstrapDraft}
        onCatalogLoaded={handleCatalogLoaded}
        onStartGeneration={onStartGeneration}
      />

      {draft.directorBrief ? (
        <section className="book-import__report" aria-label="导演预读">
          <p className="book-import__title">导演预读</p>
          <pre className="book-library-browser__preview-text">{draft.directorBrief}</pre>
        </section>
      ) : null}

      <BookLibraryBrowser
        catalog={bookCatalog}
        history={history}
        selectedSourceItemId={selectedSourceItem?.item_id ?? null}
        selectedHistoryChapter={selectedChapter}
        onSelectSourceItem={loadSourceItem}
        onSelectHistoryChapter={onSelectHistoryChapter}
      />

      <section className="agent-settings">
        <button
          className="agent-settings__toggle"
          type="button"
          onClick={() => setIsApiSettingsOpen((value) => !value)}
          aria-expanded={isApiSettingsOpen}
        >
          API 配置
        </button>
        {isApiSettingsOpen ? (
          <div className="agent-settings__body">
            <p className="hint" style={{ marginBottom: 10 }}>
              API 配置：这里可以设置全局 API 地址和密钥，以及各个代理的独立 API 设置。
            </p>

            <div className="field">
              <label htmlFor="global-api-base-url">全局 API 基础地址</label>
              <input
                id="global-api-base-url"
                aria-label="全局 API 基础地址"
                className="text-input"
                value={runtimeSettings.global.base_url}
                onChange={(event) => updateRuntimeSettings({ global: { ...runtimeSettings.global, base_url: event.target.value } })}
              />
            </div>

            <div className="field">
              <label htmlFor="global-api-key">全局 API 密钥</label>
              <input
                id="global-api-key"
                aria-label="全局 API 密钥"
                className="text-input"
                value={runtimeSettings.global.api_key}
                onChange={(event) => updateRuntimeSettings({ global: { ...runtimeSettings.global, api_key: event.target.value } })}
              />
            </div>

            <h3>代理 API 设置</h3>

            {Object.entries(runtimeSettings.agents).map(([agentKey, agentSettings]) => (
              <div key={agentKey} className="model-settings">
                <h4>{agentKey}</h4>

                <div className="field">
                  <label htmlFor={`${agentKey}-api-base-url`}>{agentKey} API 基础地址</label>
                  <input
                    id={`${agentKey}-api-base-url`}
                    aria-label={`${agentKey} API 基础地址`}
                    className="text-input"
                    value={agentSettings.base_url}
                    onChange={(event) => updateModelSettings(agentKey as keyof RuntimeSettings["agents"], { base_url: event.target.value })}
                  />
                </div>

                <div className="field">
                  <label htmlFor={`${agentKey}-api-key`}>{agentKey} API 密钥</label>
                  <input
                    id={`${agentKey}-api-key`}
                    aria-label={`${agentKey} API 密钥`}
                    className="text-input"
                    value={agentSettings.api_key}
                    onChange={(event) => updateModelSettings(agentKey as keyof RuntimeSettings["agents"], { api_key: event.target.value })}
                  />
                </div>

                <div className="field">
                  <button
                    className="btn"
                    type="button"
                    onClick={() => onTestRuntimeSettings(agentKey as keyof RuntimeSettings["agents"])}
                    disabled={runtimeConnectionStatus[agentKey as keyof RuntimeSettings["agents"]].state === "testing"}
                  >
                    {runtimeConnectionStatus[agentKey as keyof RuntimeSettings["agents"]].state === "testing" ? "测试中..." : `测试 ${agentKey} 连接`}
                  </button>
                  <span className={`status-badge status-badge--${runtimeBadgeTone(runtimeConnectionStatus[agentKey as keyof RuntimeSettings["agents"]].state)}`}>
                    {runtimeConnectionStatus[agentKey as keyof RuntimeSettings["agents"]].state === "idle" && "未测试"}
                    {runtimeConnectionStatus[agentKey as keyof RuntimeSettings["agents"]].state === "testing" && "测试中"}
                    {runtimeConnectionStatus[agentKey as keyof RuntimeSettings["agents"]].state === "success" && "连接成功"}
                    {runtimeConnectionStatus[agentKey as keyof RuntimeSettings["agents"]].state === "error" && "连接失败"}
                  </span>
                </div>
              </div>
            ))}

            <div className="field">
              <button
                className="btn"
                type="button"
                onClick={onSaveRuntimeSettings}
                disabled={runtimeSettingsStatus === "saving"}
              >
                {runtimeSettingsStatus === "saving" ? "保存中..." : "保存配置"}
              </button>
              <span className={`status-badge status-badge--${runtimeBadgeTone(runtimeSettingsStatus)}`}>
                {runtimeSettingsStatus === "idle" && "未保存"}
                {runtimeSettingsStatus === "saving" && "保存中"}
                {runtimeSettingsStatus === "success" && "保存成功"}
                {runtimeSettingsStatus === "error" && "保存失败"}
              </span>
            </div>
          </div>
        ) : null}
      </section>

      <section className="agent-settings">
        <button
          className="agent-settings__toggle"
          type="button"
          onClick={() => setIsAgentSettingsOpen((value) => !value)}
          aria-expanded={isAgentSettingsOpen}
        >
          代理设置
        </button>
        {isAgentSettingsOpen ? (
          <div className="agent-settings__body">
            <p className="hint" style={{ marginBottom: 10 }}>
              模型配置：这里可以直接填写角色、导演、写作、记忆所用的模型名。
            </p>

            <div className="agent-settings__grid">
              <div className="field">
                <label htmlFor="agent-mode">代理模式</label>
                <select
                  id="agent-mode"
                  aria-label="代理模式"
                  className="text-input"
                  value={agentSettings.mode}
                  onChange={(event) =>
                    updateAgentSettings({
                      mode: event.target.value as AgentMode,
                    })
                  }
                >
                  <option value="Rule-based">纯规则模式</option>
                  <option value="LLM-assisted">LLM 协助模式</option>
                </select>
              </div>

              <div className="field">
                <label htmlFor="new-character-policy">新角色策略</label>
                <select
                  id="new-character-policy"
                  aria-label="新角色策略"
                  className="text-input"
                  value={agentSettings.newCharacterPolicy}
                  onChange={(event) =>
                    updateAgentSettings({
                      newCharacterPolicy: event.target.value as NewCharacterPolicy,
                    })
                  }
                >
                  <option value="Director review">导演审核</option>
                  <option value="Auto-approve named candidates">自动通过命名候选</option>
                  <option value="Manual review">手动审核</option>
                </select>
              </div>
            </div>

            <div className="field">
              <label htmlFor="global-model">全局默认模型</label>
              <input
                id="global-model"
                aria-label="全局默认模型"
                className="text-input"
                value={agentSettings.globalModel}
                onChange={(event) => updateAgentSettings({ globalModel: event.target.value })}
              />
            </div>

            <div className="field">
              <label htmlFor="character-model">角色模型</label>
              <input
                id="character-model"
                aria-label="角色模型"
                className="text-input"
                value={agentSettings.characterModel}
                onChange={(event) => updateAgentSettings({ characterModel: event.target.value })}
              />
            </div>

            <div className="field">
              <label htmlFor="director-model">导演模型</label>
              <input
                id="director-model"
                aria-label="导演模型"
                className="text-input"
                value={agentSettings.directorModel}
                onChange={(event) => updateAgentSettings({ directorModel: event.target.value })}
              />
            </div>

            <div className="field">
              <label htmlFor="writer-model">写作模型</label>
              <input
                id="writer-model"
                aria-label="写作模型"
                className="text-input"
                value={agentSettings.writerModel}
                onChange={(event) => updateAgentSettings({ writerModel: event.target.value })}
              />
            </div>

            <div className="field">
              <label htmlFor="memory-model">记忆代理模型</label>
              <input
                id="memory-model"
                aria-label="记忆代理模型"
                className="text-input"
                value={agentSettings.memoryModel}
                onChange={(event) => updateAgentSettings({ memoryModel: event.target.value })}
              />
            </div>

            <div className="field">
              <label htmlFor="agent-temperature">温度</label>
              <input
                id="agent-temperature"
                aria-label="温度"
                className="text-input"
                inputMode="decimal"
                value={agentSettings.temperature}
                onChange={(event) => updateAgentSettings({ temperature: event.target.value })}
              />
            </div>

            <div className="agent-settings__summary" aria-label="代理设置摘要">
              <p className="hint">模式：{modeLabel(agentSettings.mode)}</p>
              <p className="hint">角色模型：{agentSettings.characterModel}</p>
              <p className="hint">导演模型：{agentSettings.directorModel}</p>
              <p className="hint">写作模型：{agentSettings.writerModel}</p>
              <p className="hint">记忆模型：{agentSettings.memoryModel}</p>
              <p className="hint">温度：{agentSettings.temperature}</p>
              <p className="hint">新角色策略：{policyLabel(agentSettings.newCharacterPolicy)}</p>
            </div>

            <div className="agent-settings__summary" aria-label="代理运行状态">
              <p className="hint">运行状态</p>
              <p className="hint">运行模式：{runtimeMode}</p>
              <p className="hint">角色代理：{agentRuntimeLabel}</p>
              <p className="hint">导演代理：{agentRuntimeLabel}</p>
              <p className="hint">写作代理：{agentRuntimeLabel}</p>
              <p className="hint">记忆代理：{agentRuntimeLabel}</p>
            </div>
          </div>
        ) : null}
      </section>

      <div className="field">
        <label htmlFor="outline-input">大纲输入</label>
        <textarea
          id="outline-input"
          aria-label="大纲输入"
          placeholder="把你的小说大纲贴在这里。"
          value={draft.outline}
          onChange={(event) => onChange({ ...draft, outline: event.target.value })}
        />
      </div>

      {draft.characters.map((character, index) => (
        <section className="character-card" key={index}>
          <p className="character-card__title">角色 {index + 1}</p>

          <div className="field">
            <label htmlFor={`character-name-${index}`}>角色名称 {index + 1}</label>
            <input
              id={`character-name-${index}`}
              aria-label={`角色名称 ${index + 1}`}
              className="text-input"
              value={character.name}
              onChange={(event) => updateCharacter(index, { ...character, name: event.target.value })}
            />
          </div>

          <div className="field">
            <label htmlFor={`character-goal-${index}`}>角色目标 {index + 1}</label>
            <input
              id={`character-goal-${index}`}
              aria-label={`角色目标 ${index + 1}`}
              className="text-input"
              value={character.goal}
              onChange={(event) => updateCharacter(index, { ...character, goal: event.target.value })}
            />
          </div>

          <label className="checkbox-row" htmlFor={`freeze-character-${index}`}>
            <input
              id={`freeze-character-${index}`}
              aria-label={index === 0 ? "冻结角色" : `冻结角色 ${index + 1}`}
              type="checkbox"
              checked={character.frozen}
              onChange={(event) => updateCharacter(index, { ...character, frozen: event.target.checked })}
            />
            <span>冻结角色</span>
          </label>

          <div className="field">
            <label htmlFor={`relationship-target-${index}`}>关系对象 {index + 1}</label>
            <input
              id={`relationship-target-${index}`}
              aria-label={`关系对象 ${index + 1}`}
              className="text-input"
              value={character.relationshipTarget}
              onChange={(event) =>
                updateCharacter(index, { ...character, relationshipTarget: event.target.value })
              }
            />
          </div>

          <div className="field">
            <label htmlFor={`relationship-bond-${index}`}>关系类型 {index + 1}</label>
            <input
              id={`relationship-bond-${index}`}
              aria-label={`关系类型 ${index + 1}`}
              className="text-input"
              value={character.relationshipBond}
              onChange={(event) => updateCharacter(index, { ...character, relationshipBond: event.target.value })}
            />
          </div>

          <div className="field-row">
            <div className="field">
              <label htmlFor={`trust-level-${index}`}>信任值 {index + 1}</label>
              <input
                id={`trust-level-${index}`}
                aria-label={`信任值 ${index + 1}`}
                className="text-input"
                value={character.trust}
                onChange={(event) => updateCharacter(index, { ...character, trust: event.target.value })}
              />
            </div>

            <div className="field">
              <label htmlFor={`tension-level-${index}`}>紧张值 {index + 1}</label>
              <input
                id={`tension-level-${index}`}
                aria-label={`紧张值 ${index + 1}`}
                className="text-input"
                value={character.tension}
                onChange={(event) => updateCharacter(index, { ...character, tension: event.target.value })}
              />
            </div>
          </div>
        </section>
      ))}

      <button className="btn btn--ghost" type="button" onClick={addCharacter}>
        添加角色
      </button>

      <p className="hint">冻结角色会保留当前情绪、位置和记忆不变，但剧情仍会继续围绕他们推进。</p>
    </div>
  );
}
